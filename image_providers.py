#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geração de pixel art / assets de jogo via PixelLab, Retro Diffusion e Scenario, e Stable Diffusion local
(offline, com LoRAs) pelo sd_local.py.

- As chaves e o rodízio entre várias chaves do mesmo provedor vêm do provider_router
  (PIXELLAB_API_KEY, RETRODIFFUSION_API_KEY, SCENARIO_API_KEY=CHAVE:SEGREDO, e _2, _3...).
- Aceita 1 imagem de referência (PixelLab e Retro Diffusion).
- Só usa a biblioteca padrão do Python.
"""

import json
import time
import uuid
import base64
import urllib.error
import urllib.request

import provider_router as router

POLL_TIMEOUT = 420  # segundos máximos esperando um trabalho assíncrono

# Estilos da Retro Diffusion úteis para jogos: (id, rótulo, tamanho fixo ou None, é animação, usa input_image)
RETRO_STYLES = [
    ("rd_lite__default", "Pixel art geral (Lite)", None, False, False),
    ("rd_lite__platformer", "Plataforma 2D (Lite)", None, False, False),
    ("rd_lite__topdown", "Top-down (Lite)", None, False, False),
    ("rd_lite__isometric", "Isométrico (Lite)", None, False, False),
    ("rd_lite__fantasy", "Fantasia (Lite)", None, False, False),
    ("rd_lite__spritesheet", "Spritesheet de itens (Lite)", None, False, False),
    ("rd_core__default", "Pixel art geral (Core, melhor)", None, False, False),
    ("rd_tile__tileset", "Tileset (tiles 16-32 px)", None, False, False),
    ("rd_tile__single_tile", "Tile único", None, False, False),
    ("rd_tile__scene_object", "Objeto de cenário", None, False, False),
    ("rd_animation__four_angle_walking", "Animação: andar 4 direções (48x48)", (48, 48), True, False),
    ("rd_animation__four_angle_walking_idle", "Animação: andar + parado 4 dir. (48x48)", (48, 48), True, False),
    ("rd_animation__small_sprites", "Animação: sprites pequenos (32x32)", (32, 32), True, False),
    ("rd_animation__battle_sprites", "Animação: sprites de batalha (64x64)", (64, 64), True, False),
    ("rd_animation__any_animation", "Animação livre (64x64)", (64, 64), True, False),
    ("rd_animation__vfx", "Efeito visual / VFX", None, True, False),
    ("rd_animation__8_dir_rotation", "Rotação 8 direções (80x80)", (80, 80), True, False),
    ("rd_advanced_animation__walking", "Animar referência: andar", None, True, True),
    ("rd_advanced_animation__idle", "Animar referência: parado", None, True, True),
    ("rd_advanced_animation__attack", "Animar referência: ataque", None, True, True),
    ("rd_advanced_animation__jump", "Animar referência: pulo", None, True, True),
    ("rd_advanced_animation__rotate", "Animar referência: girar 8 direções", None, True, True),
]

PIXELLAB_MODES = [
    ("imagem", "Imagem / sprite"),
    ("personagem4", "Personagem 4 direções"),
    ("personagem8", "Personagem 8 direções"),
    ("tileset", "Tileset top-down (prompt: chão | topo)"),
    ("animar", "Animar a referência (prompt = ação)"),
]


class ImageError(Exception):
    pass


class _Retryable(Exception):
    """Erro da chave/conta (limite, saldo, chave recusada): tenta a próxima chave."""

    def __init__(self, code, body, headers=None):
        super().__init__(f"{code}: {body[:200]}")
        self.code, self.body, self.headers = code, body, headers


# ---------------------------------------------------------------- utilidades

def _http(method, url, headers, body=None, timeout=120):
    h = dict(headers)
    data = None
    if body is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode("utf-8")) if raw else {})
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="ignore")
        if e.code in (401, 402, 403, 429):
            raise _Retryable(e.code, text, e.headers)
        if e.code == 423:  # PixelLab: recurso ainda sendo gerado
            return 423, {}
        raise ImageError(f"Erro {e.code} do provedor: {_short(text)}")


def _short(text):
    try:
        d = json.loads(text)
        err = d.get("detail") or d.get("error") or d.get("message") or d
        if isinstance(err, dict):
            err = err.get("message") or err
        return str(err)[:300]
    except Exception:
        return (text or "")[:300]


def _download(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": router.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ext_of(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _decode_b64(value):
    if not isinstance(value, str) or len(value) < 64:
        return None
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    try:
        data = base64.b64decode(value, validate=False)
    except Exception:
        return None
    return data if _ext_of(data) else None


def _extract_images(obj, label="", out=None):
    """Procura imagens em qualquer lugar da resposta (base64, data URL, lista de base64)."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{label}_{k}" if label else str(k)
            if isinstance(v, str):
                data = _decode_b64(v)
                if data:
                    out.append((data, label or "img"))
            else:
                _extract_images(v, sub if k not in ("image", "images", "base64", "last_response", "result") else label, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                data = _decode_b64(v)
                if data:
                    out.append((data, f"{label}{i + 1}" if label else f"img{i + 1}"))
            else:
                _extract_images(v, label, out)
    return out


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _size(opts, default=64, multiple=1, lo=16, hi=512):
    def fix(v):
        v = int(v or default)
        v = max(lo, min(hi, v))
        return v - (v % multiple) if multiple > 1 else v
    return fix(opts.get("width")), fix(opts.get("height"))


def _with_keys(base, fn):
    """Roda fn(pid, headers) em cada chave do provedor até uma funcionar (com pausa entre chaves)."""
    router.load_env()
    tried = []
    for pid in router.instances_of(base):
        key = router.provider_key(pid)
        if not key:
            continue
        reason = router.unavailable_reason(pid)
        if reason:
            tried.append(f"{router.PROVIDERS[pid]['label']}: {reason}")
            continue
        router.wait_key_switch(pid)
        router.mark_key_use(pid)
        try:
            result = fn(pid, router.auth_headers(pid, key))
            router._record_ok(pid, base, None)
            return result
        except _Retryable as e:
            router._record_error(pid, base, e.code, e.body, e.headers, e.body)
            tried.append(f"{router.PROVIDERS[pid]['label']}: erro {e.code} ({_short(e.body)})")
        except ImageError as e:
            router._record_error(pid, base, 0, str(e))
            raise
    if not tried:
        raise ImageError(f"Nenhuma chave de {router.PROVIDERS[base]['label']} configurada. "
                         "Adicione na aba Provedores.")
    raise ImageError("Nenhuma chave conseguiu gerar: " + "; ".join(tried))


# ---------------------------------------------------------------- PixelLab

def _pixellab_job(base_url, headers, job_id):
    end = time.time() + POLL_TIMEOUT
    while time.time() < end:
        time.sleep(5)
        _, job = _http("GET", f"{base_url}/background-jobs/{job_id}", headers)
        st = job.get("status")
        if st == "completed":
            return job.get("last_response") or {}
        if st == "failed":
            raise ImageError("A PixelLab não conseguiu gerar: " + _short(json.dumps(job.get("last_response") or job)))
    raise ImageError("Tempo esgotado esperando a PixelLab.")


def _pixellab_resource(base_url, headers, path):
    """GET em recurso que devolve 423 enquanto está sendo gerado (tilesets, personagens)."""
    end = time.time() + POLL_TIMEOUT
    while time.time() < end:
        code, data = _http("GET", base_url + path, headers)
        if code != 423 and data:
            return data
        time.sleep(5)
    raise ImageError("Tempo esgotado esperando a PixelLab.")


def _pixellab(opts):
    mode = opts.get("mode") or "imagem"
    prompt = (opts.get("prompt") or "").strip()
    ref = opts.get("reference")
    transparent = bool(opts.get("transparent", True))
    base_url = router.PROVIDERS["pixellab"]["base"]

    def run(pid, headers):
        if mode == "animar":
            if not ref:
                raise ImageError("Para animar, envie uma imagem de referência (ou use o botão Animar de uma imagem).")
            body = {"first_frame": {"base64": _b64(ref), "format": "png"}, "action": prompt or "walking",
                    "frame_count": int(opts.get("frames") or 8), "no_background": transparent}
            _, r = _http("POST", base_url + "/animate-with-text-v3", headers, body)
            data = _pixellab_job(base_url, headers, r["background_job_id"]) if r.get("background_job_id") else r
            return _extract_images(data, "quadro")

        if mode == "tileset":
            low, _, up = prompt.partition("|")
            ts = int(opts.get("tile") or 16)
            body = {"lower_description": low.strip() or "grass", "upper_description": up.strip() or "dirt path",
                    "tile_size": {"width": ts, "height": ts}}
            _, r = _http("POST", base_url + "/create-tileset", headers, body)
            data = _pixellab_resource(base_url, headers, f"/tilesets/{r['tileset_id']}?layout=godot")
            return _extract_images(data, "tile")

        if mode in ("personagem4", "personagem8"):
            n = 4 if mode == "personagem4" else 8
            if ref:
                w, h = _size(opts, 64, 1, 32, 256)
                body = {"description": prompt or "character", "reference_image": {"base64": _b64(ref), "format": "png"},
                        "n_directions": n, "image_size": {"width": w, "height": h}, "no_background": transparent}
                _, r = _http("POST", base_url + "/create-character-v3", headers, body)
                if r.get("background_job_id"):
                    _pixellab_job(base_url, headers, r["background_job_id"])
                data = _pixellab_resource(base_url, headers, f"/characters/{r['character_id']}")
                return _extract_images(data, "dir")
            w, h = _size(opts, 64, 1, 16, 128)
            body = {"description": prompt or "character", "image_size": {"width": w, "height": h}}
            path = "/create-character-with-4-directions" if n == 4 else "/create-character-with-8-directions"
            _, r = _http("POST", base_url + path, headers, body, timeout=300)
            if r.get("background_job_id"):
                r = _pixellab_job(base_url, headers, r["background_job_id"])
            return _extract_images(r, "dir")

        # imagem simples
        if ref:  # pixflux aceita imagem inicial (até 400x400)
            w, h = _size(opts, 64, 1, 16, 400)
            body = {"description": prompt, "image_size": {"width": w, "height": h}, "no_background": transparent,
                    "init_image": {"type": "base64", "base64": _b64(ref), "format": "png"},
                    "init_image_strength": int(opts.get("strength") or 300)}
            _, r = _http("POST", base_url + "/create-image-pixflux", headers, body, timeout=300)
        else:
            w, h = _size(opts, 64, 4, 16, 512)
            if min(w, h) < 32:
                w = h = max(w, h)
            body = {"description": prompt, "image_size": {"width": w, "height": h}, "no_background": transparent}
            _, r = _http("POST", base_url + "/create-image-pixen", headers, body, timeout=300)
        return _extract_images(r, "sprite")

    return _with_keys("pixellab", run)


# ---------------------------------------------------------------- Retro Diffusion

def _retro(opts):
    style = opts.get("mode") or "rd_lite__default"
    info = next((s for s in RETRO_STYLES if s[0] == style), (style, style, None, False, False))
    _, _, fixed, is_anim, needs_input = info
    ref = opts.get("reference")
    base_url = router.PROVIDERS["retrodiffusion"]["base"]
    if fixed:
        w, h = fixed
    else:
        w, h = _size(opts, 64, 1, 16 if not needs_input else 32, 512 if not needs_input else 256)
    body = {"prompt": (opts.get("prompt") or "").strip(), "prompt_style": style, "width": w, "height": h,
            "num_images": 1}
    if is_anim:
        body["return_spritesheet"] = True
        body["frames_duration"] = int(opts.get("frames") or 8)
    elif opts.get("transparent"):
        body["remove_bg"] = True
    if ref:
        if needs_input or style == "rd_tile__tile_variation":
            body["input_image"] = _b64(ref)
        else:
            body["reference_images"] = [_b64(ref)]
    elif needs_input:
        raise ImageError("Esse estilo anima uma imagem: envie uma referência do mesmo tamanho (32-256 px).")

    def run(pid, headers):
        h = dict(headers)
        h["Idempotency-Key"] = str(uuid.uuid4())
        _, r = _http("POST", base_url + "/inferences", h, body)
        task = r.get("task_id")
        if not task:
            return _extract_images(r, "retro")
        end = time.time() + POLL_TIMEOUT
        while time.time() < end:
            time.sleep(2)
            _, t = _http("GET", f"{base_url}/inferences/tasks/{task}", headers)
            st = t.get("status")
            if st == "succeeded":
                res = t.get("result") or {}
                imgs = []
                for i, b in enumerate(res.get("base64_images") or []):
                    data = _decode_b64(b)
                    if data:
                        imgs.append((data, f"retro{i + 1}"))
                for i, url in enumerate(res.get("output_urls") or []):
                    imgs.append((_download(url), f"retro_url{i + 1}"))
                return imgs
            if st == "failed":
                err = t.get("error") or {}
                raise ImageError("A Retro Diffusion não conseguiu gerar: " + str(err.get("message") or err))
        raise ImageError("Tempo esgotado esperando a Retro Diffusion.")

    return _with_keys("retrodiffusion", run)


# ---------------------------------------------------------------- Scenario

def _scenario(opts):
    model_id = (opts.get("model_id") or "").strip()
    if not model_id:
        raise ImageError("Informe o modelId da Scenario (ex.: um modelo de pixel art público ou um treinado por você).")
    if opts.get("reference"):
        raise ImageError("Imagem de referência na Scenario ainda não é suportada aqui (exige upload do asset). "
                         "Gere sem referência ou use PixelLab/Retro Diffusion.")
    base_url = router.PROVIDERS["scenario"]["base"]
    w, h = _size(opts, 512, 16, 256, 1536)
    body = {"prompt": (opts.get("prompt") or "").strip(), "width": w, "height": h}

    def run(pid, headers):
        _, r = _http("POST", f"{base_url}/generate/custom/{model_id}", headers, body)
        job_id = (r.get("job") or {}).get("jobId")
        if not job_id:
            raise ImageError("A Scenario não devolveu um job: " + _short(json.dumps(r)))
        end = time.time() + POLL_TIMEOUT
        while time.time() < end:
            time.sleep(3)
            _, j = _http("GET", f"{base_url}/jobs/{job_id}", headers)
            job = j.get("job") or {}
            st = job.get("status")
            if st == "success":
                imgs = []
                for i, aid in enumerate((job.get("metadata") or {}).get("assetIds") or []):
                    _, a = _http("GET", f"{base_url}/assets/{aid}", headers)
                    url = (a.get("asset") or {}).get("url")
                    if url:
                        imgs.append((_download(url), f"scenario{i + 1}"))
                return imgs
            if st in ("failure", "canceled"):
                raise ImageError(f"A Scenario terminou com status '{st}'.")
        raise ImageError("Tempo esgotado esperando a Scenario.")

    return _with_keys("scenario", run)


# ---------------------------------------------------------------- novos provedores gerais (Gemini, HF, OpenAI, Together, Fal, Stability)

_ASPECT_DIMS = {
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
}


def _aspect_dims(opts):
    aspect = (opts.get("aspect") or "1:1").strip()
    if aspect in _ASPECT_DIMS:
        return _ASPECT_DIMS[aspect]
    return int(opts.get("width") or 1024), int(opts.get("height") or 1024)


def _http_raw(method, url, headers, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="ignore")
        if e.code in (401, 402, 403, 429):
            raise _Retryable(e.code, text, e.headers)
        raise ImageError(f"Erro {e.code} do provedor: {_short(text)}")
    except Exception as e:
        raise ImageError(f"Falha de rede: {e}")


def _ref_mime(data):
    ext = _ext_of(data)
    return {".jpg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")


def _gemini_image(opts):
    models = [opts.get("model")] if opts.get("model") else [
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-3-pro-image-preview",
    ]
    aspect = (opts.get("aspect") or "1:1").strip()

    def run(pid, _headers):
        key = router.provider_key(pid)
        parts = []
        if opts.get("reference"):
            parts.append({"inlineData": {"mimeType": _ref_mime(opts["reference"]), "data": _b64(opts["reference"])}})
        parts.append({"text": opts["prompt"]})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        if aspect in _ASPECT_DIMS:
            body["generationConfig"]["imageConfig"] = {"aspectRatio": aspect}
        last_err = None
        for m in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
            try:
                _, res = _http("POST", url, {"User-Agent": router.USER_AGENT, "x-goog-api-key": key}, body, timeout=120)
                imgs = []
                for cand in res.get("candidates") or []:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        inline = part.get("inlineData") or part.get("inline_data") or {}
                        raw = _decode_b64(inline.get("data") or "")
                        if raw:
                            imgs.append((raw, m))
                if imgs:
                    return imgs
                last_err = "Gemini não devolveu imagem na resposta."
            except _Retryable:
                raise
            except ImageError as e:
                last_err = str(e)
        raise ImageError(last_err or "Falha ao gerar imagem no Gemini.")

    return _with_keys("gemini", run)


def _huggingface(opts):
    model = (opts.get("model") or "black-forest-labs/FLUX.1-schnell").strip()
    w, h = _aspect_dims(opts)

    def run(pid, headers):
        base = router.PROVIDERS[pid]["base"].rstrip("/")
        h_req = dict(headers)
        h_req["Content-Type"] = "application/json"
        h_req["Accept"] = "image/png"
        payload = json.dumps({"inputs": opts["prompt"], "parameters": {"width": w, "height": h}}).encode("utf-8")
        _, raw = _http_raw("POST", f"{base}/{model}", h_req, payload, timeout=120)
        if not _ext_of(raw):
            raise ImageError("Hugging Face respondeu, mas sem imagem reconhecível.")
        return [(raw, model.split("/")[-1])]

    return _with_keys("huggingface", run)


def _openai_image(opts):
    model = (opts.get("model") or "gpt-image-1").strip()
    aspect = (opts.get("aspect") or "1:1").strip()
    size = {"16:9": "1536x1024", "4:3": "1536x1024", "9:16": "1024x1536", "3:4": "1024x1536"}.get(aspect, "1024x1024")

    def run(pid, headers):
        base = router.PROVIDERS[pid]["base"].rstrip("/")
        _, res = _http("POST", f"{base}/images/generations", headers, {
            "model": model,
            "prompt": opts["prompt"],
            "size": size,
        }, timeout=120)
        imgs = []
        for item in res.get("data") or []:
            if item.get("b64_json"):
                raw = _decode_b64(item["b64_json"])
                if raw:
                    imgs.append((raw, model))
            elif item.get("url"):
                imgs.append((_download(item["url"]), model))
        if not imgs:
            raise ImageError("OpenAI não devolveu imagem.")
        return imgs

    return _with_keys("openai", run)


def _together(opts):
    model = (opts.get("model") or "black-forest-labs/FLUX.1-schnell-Free").strip()
    w, h = _aspect_dims(opts)

    def run(pid, headers):
        base = router.PROVIDERS[pid]["base"].rstrip("/")
        _, res = _http("POST", f"{base}/images/generations", headers, {
            "model": model,
            "prompt": opts["prompt"],
            "width": w,
            "height": h,
            "response_format": "b64_json",
        }, timeout=120)
        imgs = []
        for item in res.get("data") or []:
            if item.get("b64_json"):
                raw = _decode_b64(item["b64_json"])
                if raw:
                    imgs.append((raw, model.split("/")[-1]))
            elif item.get("url"):
                imgs.append((_download(item["url"]), model.split("/")[-1]))
        if not imgs:
            raise ImageError("Together não devolveu imagem.")
        return imgs

    return _with_keys("together", run)


def _fal(opts):
    model = (opts.get("model") or "fal-ai/flux/schnell").strip()
    w, h = _aspect_dims(opts)

    def run(pid, headers):
        base = router.PROVIDERS[pid]["base"].rstrip("/")
        _, res = _http("POST", f"{base}/{model}", headers, {
            "prompt": opts["prompt"],
            "image_size": {"width": w, "height": h},
        }, timeout=120)
        imgs = []
        for item in res.get("images") or []:
            if item.get("url"):
                imgs.append((_download(item["url"]), model.split("/")[-1]))
        if not imgs:
            raise ImageError("Fal.ai não devolveu imagem.")
        return imgs

    return _with_keys("fal", run)


def _stability(opts):
    endpoint = (opts.get("model") or "core").strip()
    aspect = (opts.get("aspect") or "1:1").strip()
    if aspect not in _ASPECT_DIMS:
        aspect = "1:1"

    def run(pid, headers):
        base = router.PROVIDERS[pid]["base"].rstrip("/")
        boundary = f"----BiazziTech{uuid.uuid4().hex}"
        fields = [("prompt", opts["prompt"]), ("aspect_ratio", aspect), ("output_format", "png")]
        if opts.get("negative"):
            fields.append(("negative_prompt", opts["negative"]))
        chunks = []
        for k, v in fields:
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        h_req = dict(headers)
        h_req["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        h_req["Accept"] = "image/*"
        _, raw = _http_raw("POST", f"{base}/stable-image/generate/{endpoint}", h_req, body, timeout=120)
        if not _ext_of(raw):
            raise ImageError("Stability AI respondeu, mas sem imagem reconhecível.")
        return [(raw, f"stability_{endpoint}")]

    return _with_keys("stability", run)


# ---------------------------------------------------------------- entrada

def _sdlocal(opts):
    import sd_local
    try:
        return sd_local.generate(opts)
    except sd_local.SDError as e:
        raise ImageError(str(e))


GENERATORS = {
    "pixellab": _pixellab,
    "retrodiffusion": _retro,
    "scenario": _scenario,
    "sdlocal": _sdlocal,
    "gemini_image": _gemini_image,
    "huggingface": _huggingface,
    "openai_image": _openai_image,
    "together": _together,
    "fal": _fal,
    "stability": _stability,
}


def options():
    """Opções para o painel montar os menus."""
    import sd_local
    return {
        "pixellab": [{"id": m, "label": l} for m, l in PIXELLAB_MODES],
        "retrodiffusion": [{"id": s[0], "label": s[1], "fixed": s[2], "animation": s[3], "needs_reference": s[4]}
                           for s in RETRO_STYLES],
        "scenario": [{"id": "custom", "label": "Modelo pelo modelId"}],
        "sdlocal_status": sd_local.status(),
        "sd_remote": [{"id": p, "label": router.PROVIDERS[p]["label"]} for p in router.custom_ids("imagens")],
    }


def is_custom_image(provider):
    """Provedor personalizado cadastrado para imagens (servidor Stable Diffusion de outro PC)."""
    router.load_env()
    return provider in router.custom_ids("imagens")


def is_image_provider(provider):
    return provider in GENERATORS or is_custom_image(provider)


def _sd_remote(provider, opts):
    import sd_local
    if router.unavailable_reason(provider):
        raise ImageError(f"{router.PROVIDERS[provider]['label']}: {router.unavailable_reason(provider)}.")
    try:
        result = sd_local.generate(opts, target=sd_local.remote_target(provider))
        router._record_ok(provider, "sd", None)
        return result
    except sd_local.SDError as e:
        router._record_error(provider, "sd", 0, str(e))
        raise ImageError(str(e))


def sd_info(provider):
    """Modelos e LoRAs do SD deste PC ('sdlocal') ou de um servidor personalizado de imagens."""
    import sd_local
    if provider == "sdlocal":
        return sd_local.status()
    if not is_custom_image(provider):
        raise ImageError("Gerador desconhecido.")
    try:
        info = sd_local.remote_info(sd_local.remote_target(provider))
    except sd_local.SDError as e:
        raise ImageError(str(e))
    info.update({"installed": True, "enabled": True, "remote": True, "running": True,
                 "label": router.PROVIDERS[provider]["label"]})
    return info


def generate(provider, opts):
    """Gera e devolve lista de (bytes, extensão, rótulo)."""
    fn = GENERATORS.get(provider)
    if fn:
        imgs = fn(opts)
    elif is_custom_image(provider):
        imgs = _sd_remote(provider, opts)
    else:
        raise ImageError(f"Gerador desconhecido: {provider}")
    out = []
    for data, label in imgs:
        ext = _ext_of(data)
        if ext:
            out.append((data, ext, label))
    if not out:
        raise ImageError("O provedor respondeu, mas sem imagem reconhecível.")
    return out
