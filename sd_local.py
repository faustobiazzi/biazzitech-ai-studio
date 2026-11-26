#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stable Diffusion local (offline) com LoRAs, pelo stable-diffusion.cpp (sd-server).

Feito para máquinas simples: o motor é um executável pequeno (Vulkan: funciona em placas NVIDIA, AMD e
Intel, inclusive integradas; ou só CPU), sem Python/PyTorch. O painel liga o servidor sozinho na primeira
geração e ele libera a memória depois de 10 minutos parado.

Pastas (criadas pelo instalar_sd_local.ps1):
  <dados>/sdlocal/bin/sd-server.exe
  <dados>/sdlocal/models/checkpoints/   modelos (SD 1.5 leve em GGUF, SDXL pesado...)
  <dados>/sdlocal/models/loras/         LoRAs (.safetensors) — inclusive as LCM, que deixam tudo 4x mais rápido
  <dados>/sdlocal/models/vae/           VAE do SDXL

Configuração no ~/.env:
  SDLOCAL_ENABLED=1        liga o gerador
  SDLOCAL_MODEL=arquivo    modelo padrão (nome do arquivo em checkpoints/)
  SDLOCAL_ARGS=...         opções extras do sd-server para todos os modelos
  SDLOCAL_ARGS_SDXL=...    opções só para o SDXL (o instalador põe --offload-to-cpu em placas de menos de 8 GB)
  SDLOCAL_PORT=7861        porta interna do motor
  SDLOCAL_URL=http://...   usar um sd-server que já está rodando (outro PC, testes); aí o painel não liga nada
"""

import atexit
import base64
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

import provider_router as router

MODEL_EXT = (".gguf", ".safetensors", ".ckpt")
LORA_EXT = (".safetensors", ".ckpt", ".pt")
LCM_LORAS = {"sd15": "lcm-lora-sdv1-5", "sdxl": "lcm-lora-sdxl"}
SIZES = {
    "sd15": {"1:1": (512, 512), "4:3": (640, 480), "3:4": (480, 640), "16:9": (704, 384), "9:16": (384, 704)},
    "sdxl": {"1:1": (1024, 1024), "4:3": (1152, 896), "3:4": (896, 1152), "16:9": (1344, 768), "9:16": (768, 1344)},
}
GEN_TIMEOUT = 1800  # em CPU uma imagem pode levar minutos

_lock = threading.RLock()
_proc = {"p": None, "model": None, "log": None}


class SDError(Exception):
    pass


# ---------------------------------------------------------------- pastas e configuração

def home():
    return (os.environ.get("SDLOCAL_DIR") or "").strip() or os.path.join(router.data_dir(), "sdlocal")


def models_dir(kind=""):
    return os.path.join(home(), "models", kind) if kind else os.path.join(home(), "models")


def exe_path():
    for name in ("sd-server.exe", "sd-server"):
        p = os.path.join(home(), "bin", name)
        if os.path.isfile(p):
            return p
    return None


def external_url():
    return (os.environ.get("SDLOCAL_URL") or "").strip().rstrip("/")


def port():
    raw = (os.environ.get("SDLOCAL_PORT") or "7861").strip()
    return int(raw) if raw.isdigit() else 7861


def base_url():
    return external_url() or f"http://127.0.0.1:{port()}"


def enabled():
    return (os.environ.get("SDLOCAL_ENABLED") or "").strip().lower() in ("1", "true", "sim", "yes", "on")


def installed():
    return bool(external_url()) or bool(exe_path() and list_models())


def _files(folder, exts):
    out = []
    if not os.path.isdir(folder):
        return out
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(exts):
                out.append(os.path.relpath(os.path.join(root, f), folder).replace("\\", "/"))
    return sorted(out, key=str.lower)


def list_models():
    return _files(models_dir("checkpoints"), MODEL_EXT)


def list_loras():
    return _files(models_dir("loras"), LORA_EXT)


def family(model_file):
    low = (model_file or "").lower()
    return "sdxl" if ("xl" in low or "sdxl" in low) else "sd15"


def _stem(path):
    return os.path.splitext(os.path.basename(path or ""))[0]


def default_model():
    models = list_models()
    wanted = (os.environ.get("SDLOCAL_MODEL") or "").strip()
    if wanted in models:
        return wanted
    return models[0] if models else None


def status():
    router.load_env()
    loras = list_loras()
    return {
        "installed": installed(), "enabled": enabled(), "external": bool(external_url()),
        "models": [{"file": m, "family": family(m), "label": _stem(m)} for m in list_models()],
        "default_model": default_model(),
        "loras": [{"file": l, "name": _stem(l), "lcm": _stem(l).lower().startswith("lcm-lora")} for l in loras],
        "folder_loras": models_dir("loras"), "running": _server_up(),
        "sizes": SIZES,
    }


# ---------------------------------------------------------------- servidor (sd-server)

def _http(method, path, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": router.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")[:300]
        raise SDError(f"O motor local respondeu {e.code}: {msg}")
    except (urllib.error.URLError, OSError) as e:
        raise SDError(f"Não consegui falar com o motor local ({base_url()}): {e}")
    try:
        return json.loads(raw.decode("utf-8") or "null")
    except ValueError:
        raise SDError("Resposta inválida do motor local.")


def _server_up():
    try:
        _http("GET", "/sdapi/v1/options", timeout=2)
        return True
    except SDError:
        return False


def _log_tail(n=12):
    path = _proc.get("log")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return "".join(f.readlines()[-n:]).strip()
    except Exception:
        return ""


def stop_server():
    with _lock:
        p = _proc.get("p")
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        _proc.update({"p": None, "model": None})


atexit.register(stop_server)


def ensure_server(model):
    """Garante o sd-server rodando com o modelo pedido (liga ou troca de modelo). Devolve a URL."""
    if external_url():
        return base_url()
    with _lock:
        p = _proc.get("p")
        if p and p.poll() is None and _proc.get("model") == model and _server_up():
            return base_url()
        exe = exe_path()
        if not exe:
            raise SDError("O Stable Diffusion local não está instalado. Rode bat\\Instalar_SD_Local_IA.bat "
                          "(analisa a máquina antes de instalar).")
        stop_server()
        if _server_up():
            raise SDError(f"A porta {port()} já está em uso por outro programa (mude SDLOCAL_PORT no ~/.env).")
        args = [exe, "--model-dir", models_dir(), "--listen-ip", "127.0.0.1", "--listen-port", str(port()),
                "--model", os.path.join(models_dir("checkpoints"), model), "--weight-residency-ttl", "600"]
        if family(model) == "sdxl":
            vae = next((v for v in _files(models_dir("vae"), MODEL_EXT) if "xl" in v.lower()), None)
            if vae:
                args += ["--vae", os.path.join(models_dir("vae"), vae)]
        args += (os.environ.get("SDLOCAL_ARGS") or "").split()
        if family(model) == "sdxl":  # ex.: --offload-to-cpu em placas de menos de 8 GB (o instalador grava)
            args += (os.environ.get("SDLOCAL_ARGS_SDXL") or "").split()
        log = os.path.join(home(), "sd-server.log")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(log, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(args, cwd=home(), stdout=lf, stderr=subprocess.STDOUT, creationflags=flags)
        _proc.update({"p": proc, "model": model, "log": log})
        end = time.time() + 180
        while time.time() < end:
            if proc.poll() is not None:
                raise SDError("O motor local fechou ao iniciar. Últimas linhas do registro:\n" + _log_tail())
            if _server_up():
                return base_url()
            time.sleep(1)
        stop_server()
        raise SDError("O motor local demorou demais para iniciar. Registro:\n" + _log_tail())


# ---------------------------------------------------------------- geração

def _pick(names, *wanted):
    low = {n.lower().replace(" ", "_"): n for n in names}
    for w in wanted:
        for k, n in low.items():
            if w in k:
                return n
    return None


def _lora_entries(requested, fast, fam, available):
    """[{path, multiplier}] para o sd-server; aceita nome ('pixel-art-xl') ou arquivo ('estilos/pixel.safetensors')."""
    by_key = {}
    for a in available:
        path = a.get("path") or a.get("name")
        for k in (path, a.get("name"), _stem(path)):
            if k:
                by_key[str(k).lower()] = path
    out, missing = [], []
    for item in requested or []:
        name = str(item.get("name") or item.get("file") or "").strip()
        if not name:
            continue
        path = by_key.get(name.lower()) or by_key.get(_stem(name).lower())
        if not path:
            missing.append(name)
            continue
        try:
            w = max(-2.0, min(2.0, float(item.get("weight", 0.8))))
        except (TypeError, ValueError):
            w = 0.8
        out.append({"path": path, "multiplier": w})
    if fast:
        lcm = by_key.get(LCM_LORAS[fam])
        if lcm and not any(e["path"] == lcm for e in out):
            out.append({"path": lcm, "multiplier": 1.0})
    if missing:
        raise SDError("LoRA não encontrada na pasta do motor: " + ", ".join(missing))
    return out


def _round64(v, lo=256, hi=1536):
    v = int(v)
    return max(lo, min(hi, v - v % 64 or 64))


def generate(opts):
    """opts: prompt, negative, model, aspect | width/height, fast (LCM), loras [{name, weight}], reference (bytes),
    strength, steps, seed. Devolve [(bytes, rótulo)]."""
    router.load_env()
    prompt = (opts.get("prompt") or "").strip()
    if not prompt:
        raise SDError("Prompt vazio.")
    model = opts.get("model") or default_model()
    if not external_url():
        if not model or model not in list_models():
            raise SDError("Nenhum modelo local encontrado. Rode bat\\Instalar_SD_Local_IA.bat.")
    ensure_server(model)
    fam = family(model)
    fast = opts.get("fast", True) is not False
    if opts.get("aspect") in SIZES[fam]:
        w, h = SIZES[fam][opts["aspect"]]
    else:
        w, h = _round64(opts.get("width") or SIZES[fam]["1:1"][0]), _round64(opts.get("height") or SIZES[fam]["1:1"][1])
    try:
        available = _http("GET", "/sdapi/v1/loras") or []
    except SDError:
        available = []
    loras = _lora_entries(opts.get("loras"), fast, fam, available)
    has_lcm = any(_stem(e["path"]).lower().startswith("lcm-lora") for e in loras)
    try:
        samplers = [s.get("name") for s in (_http("GET", "/sdapi/v1/samplers") or []) if s.get("name")]
    except SDError:
        samplers = []
    if has_lcm:
        sampler, steps, cfg = _pick(samplers, "lcm") or "LCM", 6, 1.5
    else:
        sampler, steps, cfg = _pick(samplers, "euler_a", "euler_ancestral", "euler") or "Euler a", 22, 7.0
    if opts.get("steps"):
        steps = max(1, min(60, int(opts["steps"])))
    neg = (opts.get("negative") or "lowres, blurry, worst quality, watermark, text, signature, deformed").strip()
    body = {"prompt": prompt, "negative_prompt": neg, "width": w, "height": h, "steps": steps, "cfg_scale": cfg,
            "seed": int(opts.get("seed", -1)), "batch_size": 1, "sampler_name": sampler, "lora": loras}
    path = "/sdapi/v1/txt2img"
    if opts.get("reference"):
        try:
            strength = max(0.05, min(1.0, float(opts.get("strength") or 0.6)))
        except (TypeError, ValueError):
            strength = 0.6
        body.update({"init_images": [base64.b64encode(opts["reference"]).decode("ascii")],
                     "denoising_strength": strength})
        path = "/sdapi/v1/img2img"
    data = _http("POST", path, body, timeout=GEN_TIMEOUT) or {}
    out = []
    for i, b64 in enumerate(data.get("images") or []):
        try:
            out.append((base64.b64decode(b64.split(",", 1)[-1]), f"{_stem(model)}_{i + 1}"))
        except Exception:
            continue
    if not out:
        raise SDError("O motor local não devolveu imagem.")
    return out
