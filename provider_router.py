#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roteador de provedores de IA (rodízio automático entre planos gratuitos/pagos).

- Chaves no ~/.env (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY,
  OPENAI_API_KEY, CLAUDE_API_KEY, XAI_API_KEY, POLLINATIONS_API_KEY...). Chaves extras do
  mesmo provedor usam sufixo: GROQ_API_KEY_2, GROQ_API_KEY_3... (viram instâncias "groq#2").
  Entre o uso de uma chave e outra do mesmo provedor há uma pausa (ROUTER_KEY_DELAY, padrão 5 s).
- Tenta os provedores em ordem; se um devolver limite (429), falta de saldo (402),
  chave inválida (401/403) ou ficar fora do ar, ele entra "em espera" e o próximo é usado.
- Guarda contadores de uso do dia, último erro e limites informados pelos provedores em
  ~/.gemini/antigravity/router_state.json (compartilhado entre proxy, MCP e CLI).
- Só usa a biblioteca padrão do Python.
"""

import os
import re
import json
import time
import io
import base64
import datetime
import threading
import urllib.error
import urllib.request

USER_AGENT = "BiazziTech-AI-Studio-Router/1.0"
DISCOVERY_TTL = 24 * 3600

# Modelos do gateway Pollinations (mantidos da versão anterior do kit)
POLLINATIONS_TEXT_MAP = {
    "deepseek-chat": "openai/gpt-5.3-codex",
    "deepseek-reasoner": "openai/gpt-5.3-codex",
    "codex": "openai/gpt-5.3-codex",
    "auto": "openai/gpt-5.3-codex",
}
POLLINATIONS_FALLBACK_CHAIN = [
    "openai/gpt-5.3-codex",
    "openai/gpt-5.4-mini",
    "deepseek/deepseek-v4.1-flash",
]

# Modelos que nunca devem ser escolhidos na descoberta automática
DISCOVERY_EXCLUDE = ("tts", "whisper", "embed", "guard", "image", "audio", "transcribe",
                     "moderation", "imagen", "veo", "live", "native-audio", "aqa", "learnlm",
                     "orpheus", "allam", "nano", "-mini-")
# Modelos minúsculos (1B-4B) costumam ser fracos demais para código
TINY_MODEL_RE = re.compile(r"(^|[-/_])(0\.\d|1|1\.\d|2|3|4)b([-_:.]|$)", re.I)

PROVIDERS = {
    "gemini": {
        "label": "Google Gemini",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "default_model": "gemini-flash-latest",
        "prefer": ["gemini-flash-latest", "gemini-2.5-flash", "flash"],
        "free": True,
    },
    "groq": {
        "label": "Groq",
        "no_images": True,
        "base": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "default_model": "llama-3.3-70b-versatile",
        "prefer": ["openai/gpt-oss-120b", "llama-3.3-70b", "qwen", "llama"],
        "free": True,
    },
    "openrouter": {
        "label": "OpenRouter (modelos :free)",
        "base": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/settings/keys",
        "default_model": None,  # descoberto automaticamente entre os modelos ":free"
        "prefer": ["deepseek", "qwen3-coder", "nemotron-3-ultra", "gemma-4-31b", "qwen", "gemma",
                   "nemotron-3.5-super", "ernie", "ling", "llama", "mistral"],
        "only_free": True,
        "free": True,
    },
    "ollama_cloud": {
        "label": "Ollama Cloud",
        "no_images": True,
        "base": "https://ollama.com/v1",
        "key_env": "OLLAMA_API_KEY",
        "key_url": "https://ollama.com/settings/keys",
        "default_model": "gpt-oss:120b",
        "prefer": ["kimi-k2.7-code", "qwen3-coder", "deepseek-v4.1-flash", "deepseek", "glm-5.3",
                   "gpt-oss:120b", "kimi", "glm"],
        "free": False,  # a API pede créditos ou assinatura (ollama.com/plans)
    },
    "deepseek": {
        "label": "DeepSeek",
        "no_images": True,
        "base": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "default_model": "deepseek-chat",
        "reason_model": "deepseek-reasoner",
        "no_discovery": True,
        "free": False,
    },
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "base": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-5.4-mini",
        "prefer": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5.4", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
        "exclude": ("realtime", "search", "codex", "instruct", "transcribe", "tts", "audio", "image",
                    "embedding", "moderation", "dall-e", "whisper", "computer-use", "deep-research", "-pro"),
        "free": False,
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "base": "https://api.anthropic.com/v1",
        # CLAUDE_API_KEY (e não ANTHROPIC_API_KEY) para não interferir em outras ferramentas
        "key_env": "CLAUDE_API_KEY",
        "key_url": "https://platform.claude.com/settings/keys",
        "default_model": "claude-opus-5-5",
        "no_discovery": True,
        "api": "anthropic",
        "free": False,
    },
    "xai": {
        "label": "xAI Grok",
        "base": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
        "key_url": "https://console.x.ai",
        "default_model": "grok-3-mini",
        "prefer": ["grok-4-fast", "grok-3-mini", "grok"],
        "free": False,
    },
    "ollama": {
        "label": "Ollama (local)",
        "no_images": True,
        "base": "http://127.0.0.1:11434/v1",
        "key_env": "OLLAMA_ENABLED",
        "key_url": "https://ollama.com/download",
        "default_model": "qwen2.5-coder:7b",
        "prefer": ["coder", "qwen", "llama", "gemma", "mistral"],
        "local": True,
        "free": True,
    },
    "pollinations": {
        "label": "Pollinations",
        "no_images": True,
        "base": "https://gen.pollinations.ai/v1",
        "key_env": "POLLINATIONS_API_KEY",
        "key_url": "https://enter.pollinations.ai",
        "default_model": POLLINATIONS_FALLBACK_CHAIN[0],
        "no_discovery": True,
        "free": True,
    },
}

# Provedores de imagem (pixel art / assets de jogo) — usam o gerenciamento de chaves daqui
PROVIDERS.update({
    "pixellab": {
        "label": "PixelLab (pixel art)",
        "base": "https://api.pixellab.ai/v2",
        "key_env": "PIXELLAB_API_KEY",
        "key_url": "https://pixellab.ai/account",
        "validate_path": "/balance",
        "kind": "image",
        "free": False,
    },
    "retrodiffusion": {
        "label": "Retro Diffusion (pixel art)",
        "base": "https://api.retrodiffusion.ai/v2",
        "key_env": "RETRODIFFUSION_API_KEY",
        "key_url": "https://www.retrodiffusion.ai/app/devtools",
        "validate_path": "/inferences/credits",
        "auth": "rd",
        "kind": "image",
        "free": False,
    },
    "scenario": {
        "label": "Scenario (assets de jogo)",
        "base": "https://api.cloud.scenario.com/v1",
        "key_env": "SCENARIO_API_KEY",  # formato CHAVE:SEGREDO
        "key_url": "https://app.scenario.com",
        "key_hint": "Cole no formato CHAVE:SEGREDO (Scenario > Organization settings > API Keys)",
        "validate_path": "/models?pageSize=1",
        "auth": "basic",
        "kind": "image",
        "free": False,
    },
    "sdlocal": {
        "label": "Stable Diffusion local (offline, LoRAs)",
        "base": "http://127.0.0.1:7861",
        "key_env": "SDLOCAL_ENABLED",  # 1 = ligado (o instalar_sd_local.ps1 grava)
        "key_url": "",
        "kind": "image",
        "local": True,
        "free": True,
    },
})

DEFAULT_ORDER = ["gemini", "groq", "openrouter", "ollama_cloud", "deepseek", "openai", "anthropic", "xai",
                 "ollama", "pollinations"]
IMAGE_PROVIDERS = ["pixellab", "retrodiffusion", "scenario", "sdlocal"]
MAX_INSTANCES = 9
ANTHROPIC_VERSION = "2026-10-21"
# Modelos Claude que aceitam o fallback automático do servidor quando um pedido é recusado
ANTHROPIC_FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                             "claude-sonnet-5-5")

_lock = threading.RLock()


class RouterError(Exception):
    def __init__(self, message, attempts=None, status=502):
        super().__init__(message)
        self.attempts = attempts or []
        self.status = status


# ---------------------------------------------------------------- ambiente

def _home():
    return os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~")


# Variáveis que já existiam no sistema antes de ler o .env (essas nunca são sobrescritas)
_OS_ENV_KEYS = set(os.environ.keys())
_FILE_KEYS = set()


def env_file_path():
    return os.path.join(_home(), ".env")


def load_env():
    """Lê os .env e atualiza os valores (permite trocar chaves sem reiniciar o proxy/MCP)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        env_file_path(),
        os.path.join(_home(), ".gemini", ".env"),
        os.path.join(script_dir, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    seen = {}
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if v.startswith("#"):
                            v = ""
                        if k not in seen:  # o primeiro arquivo (~/.env) tem prioridade
                            seen[k] = v
        except Exception:
            pass
    for k, v in seen.items():
        if k not in _OS_ENV_KEYS:
            os.environ[k] = v
            _FILE_KEYS.add(k)
    for k in list(_FILE_KEYS - set(seen)):
        os.environ.pop(k, None)
        _FILE_KEYS.discard(k)
    _load_custom_providers()
    _register_instances()
    _apply_overrides()


# ---------------------------------------------------------------- ajustes do usuário nos provedores padrão
# Nome exibido, modelo fixo, ligado/desligado e "removido" (chave apagada + cartão escondido, dá para restaurar).
# Guardados em <pasta de dados>/providers_override.json.

def _override_file():
    return os.path.join(data_dir(), "providers_override.json")


def list_overrides():
    try:
        with open(_override_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_overrides(data):
    path = _override_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _apply_overrides():
    ov = list_overrides()
    for pid, cfg in PROVIDERS.items():
        if cfg.get("custom"):
            continue
        cfg.setdefault("orig_label", cfg["label"])
        o = ov.get(pid) or {}
        cfg["label"] = (o.get("label") or "").strip() or cfg["orig_label"]
        cfg["user_model"] = (o.get("model") or "").strip()
        cfg["user_disabled"] = bool(o.get("disabled") or o.get("hidden"))
        cfg["user_hidden"] = bool(o.get("hidden"))


def edit_provider(pid, data):
    """Ajusta um provedor padrão (ou uma chave extra): nome exibido, modelo fixo, ligado/desligado."""
    if pid not in PROVIDERS or PROVIDERS[pid].get("custom"):
        return False, "Provedor inválido (os personalizados se editam no formulário deles)."
    ov = list_overrides()
    o = ov.get(pid) or {}
    if "label" in data:
        label = (data.get("label") or "").strip()[:40]
        o["label"] = "" if label == PROVIDERS[pid].get("orig_label") else label
    if "model" in data:
        o["model"] = (data.get("model") or "").strip()[:120]
    if "disabled" in data:
        o["disabled"] = bool(data.get("disabled"))
    ov[pid] = {k: v for k, v in o.items() if v}
    if not ov[pid]:
        ov.pop(pid)
    _save_overrides(ov)
    _apply_overrides()
    return True, "Provedor atualizado."


def remove_provider(pid):
    """'Remover' um provedor padrão: apaga a chave (se houver) e esconde o cartão. Dá para restaurar."""
    if pid not in PROVIDERS or PROVIDERS[pid].get("custom"):
        return False, "Provedor inválido."
    cfg = PROVIDERS[pid]
    if cfg.get("instance_of"):  # chave extra ("Groq #2"): some junto com a chave
        _write_env_key(cfg["key_env"], "")
        PROVIDERS.pop(pid, None)
        load_env()
        return True, "Chave extra removida."
    if not cfg.get("local") and provider_key(pid):
        _write_env_key(cfg["key_env"], "")
    ov = list_overrides()
    ov.setdefault(pid, {})["hidden"] = True
    _save_overrides(ov)
    load_env()
    return True, f"{cfg['label']} removido do painel e do rodízio (dá para restaurar em 'Mostrar removidos')."


def restore_provider(pid):
    ov = list_overrides()
    o = ov.get(pid) or {}
    o.pop("hidden", None)
    o.pop("disabled", None)
    if o:
        ov[pid] = o
    else:
        ov.pop(pid, None)
    _save_overrides(ov)
    _apply_overrides()
    return True, "Provedor restaurado" + ("" if provider_key(pid) else " (cadastre a chave de novo para usar)") + "."


# ---------------------------------------------------------------- provedores personalizados
# Qualquer servidor compatível com a API da OpenAI (Ollama de outro PC, LM Studio, vLLM, SGLang,
# llama.cpp server, um Grok aberto hospedado...). Guardados em <pasta de dados>/custom_providers.json.

CUSTOM_POSITIONS = {
    "inicio": "Antes de todos",
    "depois_gratis": "Depois dos gratuitos (Gemini, Groq, OpenRouter)",
    "antes_locais": "Antes do Ollama local e da Pollinations",
    "fim": "No fim do rodízio",
}


def _custom_file():
    return os.path.join(data_dir(), "custom_providers.json")


def _slug(name):
    s_ = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:24]
    return s_ or "servidor"


def list_custom_providers():
    try:
        with open(_custom_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [c for c in data.get("providers", []) if isinstance(c, dict) and c.get("id")]
    except Exception:
        return []


def _save_custom_list(items):
    path = _custom_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"providers": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def normalize_base_url(url):
    """Aceita 'host:porta', '.../v1', '.../v1/chat/completions' e devolve a base '.../v1'."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    u = re.sub(r"/(chat/)?completions$", "", u, flags=re.I)
    u = re.sub(r"/models$", "", u, flags=re.I)
    if not re.search(r"/v\d+[a-z]*$", u, re.I) and not re.search(r"/openai$", u, re.I):
        u += "/v1"
    return u


def _load_custom_providers():
    items = list_custom_providers()
    ids = set()
    for c in items:
        pid = c["id"]
        ids.add(pid)
        PROVIDERS[pid] = {
            "label": c.get("label") or pid,
            "base": c.get("base", ""),
            "key_env": f"{pid.upper()}_API_KEY",
            "key_url": c.get("base", ""),
            "default_model": c.get("model") or None,
            "prefer": [c["model"]] if c.get("model") else [],
            "custom": True,
            "no_key": not c.get("has_key"),
            "vision": bool(c.get("vision")),
            "position": c.get("position") or "antes_locais",
            "timeout": int(c.get("timeout") or 300),
            "free": not c.get("paid"),
            "uses": _uses(c.get("uses")),
        }
        if PROVIDERS[pid]["uses"] == ["imagens"]:
            PROVIDERS[pid]["kind"] = "image"
    for pid in [p for p, cfg in PROVIDERS.items() if cfg.get("custom") and p not in ids]:
        PROVIDERS.pop(pid, None)


CUSTOM_USES = {
    "texto": "Texto (chat, código, auxiliar) — servidor compatível com a OpenAI",
    "imagens": "Imagens (Stable Diffusion com LoRAs: stable-diffusion.cpp, AUTOMATIC1111, Forge, SD.Next)",
    "ambos": "Os dois (servidor que faz texto e imagens)",
}


def _uses(value):
    """['texto'], ['imagens'] ou ['texto', 'imagens'] (cadastros antigos = só texto)."""
    if value in ("imagens",):
        return ["imagens"]
    if value in ("ambos",) or (isinstance(value, list) and set(value) >= {"texto", "imagens"}):
        return ["texto", "imagens"]
    if isinstance(value, list) and value == ["imagens"]:
        return ["imagens"]
    return ["texto"]


def custom_ids(kind="texto"):
    """Personalizados que servem para 'texto' (entram no rodízio de chat) ou 'imagens' (lista de geradores)."""
    return [p for p, cfg in PROVIDERS.items() if cfg.get("custom") and kind in cfg.get("uses", ["texto"])]


def _test_text(base, key):
    headers = {"User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        data = _http_json(base + "/models", headers=headers, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"O servidor recusou a chave ({e.code}).", []
        return False, f"O servidor respondeu {e.code} em {base}/models. Confira a URL (geralmente termina em /v1).", []
    except Exception as e:
        return False, f"Não consegui conectar em {base}: {e}", []
    models = sorted({(m.get("id") or "").replace("models/", "") for m in data.get("data", []) if m.get("id")})
    return True, f"Texto: {len(models)} modelo(s).", models


def _test_images(base, key):
    import sd_local
    headers = {}
    if key:
        headers["Authorization"] = ("Basic " + base64.b64encode(key.encode("utf-8")).decode("ascii")) if ":" in key \
            else f"Bearer {key}"
    target = {"url": sd_local.image_root(base), "headers": headers, "label": "O servidor de imagens"}
    try:
        info = sd_local.remote_info(target)
    except sd_local.SDError as e:
        return False, f"{e} (a API de imagens precisa estar ligada: sd-server, ou --api no AUTOMATIC1111/Forge).", []
    tipo = "stable-diffusion.cpp" if info["style"] == "sdcpp" else "WebUI (AUTOMATIC1111/Forge)"
    return True, (f"Imagens: {tipo}, {len(info['models'])} modelo(s) e {len(info['loras'])} LoRA(s)."), \
        [m["file"] for m in info["models"]]


def test_custom(base, key="", uses="texto"):
    """Testa a conexão (texto e/ou imagens) e lista os modelos. Retorna (ok, mensagem, modelos)."""
    base = normalize_base_url(base)
    if not base:
        return False, "Informe a URL do servidor.", []
    kinds = _uses(uses)
    msgs, models = [], []
    for k in kinds:
        ok, msg, found = (_test_text if k == "texto" else _test_images)(base, key)
        if not ok:
            return False, msg, []
        msgs.append(msg)
        models += [m for m in found if m not in models]
    return True, "Conectado. " + " ".join(msgs), models


def save_custom(data):
    """Cria/atualiza um provedor personalizado. Retorna (ok, mensagem, id)."""
    label = (data.get("label") or "").strip()
    base = normalize_base_url(data.get("base"))
    if not label or not base:
        return False, "Informe nome e URL.", None
    key = (data.get("key") or "").strip()
    items = list_custom_providers()
    pid = data.get("id") or ("custom_" + _slug(label))
    existing = next((c for c in items if c["id"] == pid), None)
    if not data.get("id"):
        n, base_pid = 2, pid
        while any(c["id"] == pid for c in items):
            pid, n = f"{base_pid}_{n}", n + 1
    if not data.get("skip_test"):
        ok, msg, _ = test_custom(base, key or (provider_key(pid) if existing and existing.get("has_key") else ""),
                                 data.get("uses") or "texto")
        if not ok:
            return False, msg + " (marque 'salvar mesmo assim' se o servidor estiver desligado agora)", None
    position = data.get("position") if data.get("position") in CUSTOM_POSITIONS else "antes_locais"
    entry = {
        "id": pid, "label": label[:40], "base": base, "model": (data.get("model") or "").strip(),
        "vision": bool(data.get("vision")), "paid": bool(data.get("paid")), "position": position,
        "timeout": int(data.get("timeout") or 300),
        "uses": {("texto",): "texto", ("imagens",): "imagens"}.get(tuple(_uses(data.get("uses"))), "ambos"),
        "has_key": bool(key) or bool(existing and existing.get("has_key") and not data.get("remove_key")),
    }
    if key:
        _write_env_key(f"{pid.upper()}_API_KEY", key)
    elif data.get("remove_key"):
        _write_env_key(f"{pid.upper()}_API_KEY", "")
    items = [c for c in items if c["id"] != pid] + [entry]
    _save_custom_list(items)
    load_env()
    reset(pid)
    return True, f"Provedor '{label}' salvo.", pid


def delete_custom(pid):
    items = list_custom_providers()
    if not any(c["id"] == pid for c in items):
        return False, "Provedor não encontrado."
    _save_custom_list([c for c in items if c["id"] != pid])
    _write_env_key(f"{pid.upper()}_API_KEY", "")
    load_env()
    return True, "Provedor removido."


def base_id(pid):
    """'groq#2' -> 'groq' (instância extra de um provedor)."""
    return PROVIDERS.get(pid, {}).get("instance_of", pid.split("#")[0])


def _new_instance(base, n):
    cfg = PROVIDERS[base]
    inst = dict(cfg)
    for k in ("orig_label", "user_model", "user_disabled", "user_hidden"):  # ajustes do provedor base não passam
        inst.pop(k, None)
    inst.update({"key_env": f"{cfg['key_env']}_{n}", "label": f"{cfg.get('orig_label') or cfg['label']} #{n}",
                 "instance_of": base})
    PROVIDERS[f"{base}#{n}"] = inst


def _register_instances():
    """Cria as instâncias extras (CHAVE_2, CHAVE_3...) a partir do ambiente."""
    for pid in [p for p in list(PROVIDERS) if "#" not in p]:
        cfg = PROVIDERS[pid]
        if cfg.get("local") or cfg.get("custom"):
            continue
        for n in range(2, MAX_INSTANCES + 1):
            if (os.environ.get(f"{cfg['key_env']}_{n}") or "").strip() and f"{pid}#{n}" not in PROVIDERS:
                _new_instance(pid, n)


def instances_of(pid):
    """Provedor base + instâncias extras, na ordem."""
    base = base_id(pid)
    extra = sorted((p for p in PROVIDERS if PROVIDERS[p].get("instance_of") == base),
                   key=lambda x: int(x.split("#")[1]))
    return [base] + extra


def auth_headers(pid, key):
    """Cabeçalhos de autenticação de cada provedor."""
    cfg = PROVIDERS[pid]
    auth = cfg.get("auth") or ("anthropic" if cfg.get("api") == "anthropic" else "bearer")
    h = {"User-Agent": USER_AGENT}
    if auth == "anthropic":
        h.update({"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION})
    elif auth == "rd":
        h["X-RD-Token"] = key
    elif auth == "basic":
        h["Authorization"] = "Basic " + base64.b64encode(key.encode("utf-8")).decode("ascii")
    elif key and key != "none":
        h["Authorization"] = f"Bearer {key}"
    return h


def key_switch_delay():
    try:
        return max(0.0, float(os.environ.get("ROUTER_KEY_DELAY", "5")))
    except ValueError:
        return 5.0


def wait_key_switch(pid):
    """Antes de usar uma chave diferente do mesmo provedor, espera ROUTER_KEY_DELAY segundos
    desde o último uso de qualquer chave dele (evita pedidos colados entre contas)."""
    base = base_id(pid)
    if len(instances_of(base)) < 2:
        return 0.0
    with _lock:
        last = (_load_state().get("key_switch") or {}).get(base) or {}
    if not last or last.get("pid") == pid:
        return 0.0
    wait = key_switch_delay() - (time.time() - last.get("at", 0))
    if wait > 0:
        time.sleep(wait)
        return wait
    return 0.0


def mark_key_use(pid):
    with _lock:
        state = _load_state()
        state.setdefault("key_switch", {})[base_id(pid)] = {"pid": pid, "at": time.time()}
        _save_state(state)


def _write_env_key(key, value):
    """Grava/atualiza (ou remove, se value for vazio) uma linha KEY=valor no ~/.env, sem BOM."""
    path = env_file_path()
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = [l.rstrip("\r\n") for l in f]
    out, found = [], False
    for l in lines:
        if l.split("=", 1)[0].strip() == key and not l.lstrip().startswith("#"):
            if value and not found:
                out.append(f"{key}={value}")
            found = True
            continue
        if l.strip():
            out.append(l)
    if value and not found:
        out.append(f"{key}={value}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def mask_key(val):
    return ("••••" + val[-4:]) if val and len(val) > 8 else ("••••" if val else "")


def validate_key(pid, key, timeout=15):
    """Testa a chave listando os modelos do provedor. Retorna (ok, mensagem)."""
    cfg = PROVIDERS[pid]
    req = urllib.request.Request(cfg["base"] + cfg.get("validate_path", "/models"), headers=auth_headers(pid, key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True, "Chave válida."
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore").lower()
        except Exception:
            body = ""
        # Gemini responde 400 "API key not valid" para chave errada
        invalid = any(x in body for x in ("api key not valid", "valid api key", "invalid api key", "invalid_api_key",
                                          "incorrect api key", "api_key_invalid"))
        if e.code in (401, 403) or (e.code == 400 and invalid):
            return False, f"O provedor recusou a chave ({e.code}). Confira se copiou inteira."
        return True, f"Chave salva (o teste devolveu {e.code}, será confirmada no primeiro uso)."
    except Exception as e:
        return True, f"Chave salva (não deu para testar agora: {e})."


def set_key(pid, key, validate=True):
    """Salva a chave do provedor no ~/.env. Retorna (ok, mensagem)."""
    if pid not in PROVIDERS or PROVIDERS[pid].get("local"):
        return False, "Provedor inválido."
    key = (key or "").strip().strip("'\"")
    if not key:
        return False, "Chave vazia."
    if any(c.isspace() for c in key) or len(key) < 10:
        return False, "Isso não parece uma chave de API."
    if PROVIDERS[pid].get("auth") == "basic" and ":" not in key:
        return False, PROVIDERS[pid].get("key_hint") or "Formato esperado: CHAVE:SEGREDO"
    msg = "Chave salva."
    if validate:
        ok, msg = validate_key(pid, key)
        if not ok:
            return False, msg
    _write_env_key(PROVIDERS[pid]["key_env"], key)
    load_env()
    reset(pid)
    return True, msg


def add_key(pid, key, validate=True):
    """Adiciona mais uma chave (instância extra) ao provedor base. Retorna (ok, mensagem)."""
    load_env()
    base = base_id(pid)
    if base not in PROVIDERS or PROVIDERS[base].get("local"):
        return False, "Provedor inválido."
    if not provider_key(base):
        return set_key(base, key, validate)
    key = (key or "").strip().strip("'\"")
    if key in {provider_key(p) for p in instances_of(base)}:
        return False, "Essa chave já está cadastrada."
    env_base = PROVIDERS[base]["key_env"]
    for n in range(2, MAX_INSTANCES + 1):
        if not (os.environ.get(f"{env_base}_{n}") or "").strip():
            if f"{base}#{n}" not in PROVIDERS:
                _new_instance(base, n)
            ok, msg = set_key(f"{base}#{n}", key, validate)
            return ok, (f"Chave #{n} adicionada. " + msg) if ok else msg
    return False, f"Limite de {MAX_INSTANCES} chaves para este provedor."


def remove_key(pid):
    if pid not in PROVIDERS or PROVIDERS[pid].get("local"):
        return False, "Provedor inválido."
    _write_env_key(PROVIDERS[pid]["key_env"], "")
    load_env()
    return True, "Chave removida."


def provider_key(pid):
    val = (os.environ.get(PROVIDERS[pid]["key_env"]) or "").strip()
    if PROVIDERS[pid].get("local"):
        # Ollama não usa chave: OLLAMA_ENABLED=1 liga o provedor
        return "ollama" if val.lower() in ("1", "true", "sim", "yes", "on") else ""
    if PROVIDERS[pid].get("no_key"):
        return "none"  # servidor personalizado sem chave
    return val


def _local_server_up(base, timeout=0.6):
    import socket
    from urllib.parse import urlparse
    u = urlparse(base)
    try:
        with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout=timeout):
            return True
    except OSError:
        return False


def provider_order(with_instances=True):
    """Ordem do rodízio de texto.
    As chaves extras do mesmo serviço ("Groq #2"...) ficam no FIM da fila, depois de todos os outros
    provedores: só são usadas se nenhum outro responder. (Se o pedido for de um modelo daquele serviço,
    _candidate_plan coloca o serviço e as extras dele na frente.)"""
    raw = os.environ.get("ROUTER_ORDER", "")
    order = [p.strip().lower() for p in raw.split(",") if p.strip().lower() in DEFAULT_ORDER] if raw else []
    for p in DEFAULT_ORDER:
        if p not in order:
            order.append(p)
    # provedores personalizados entram na posição escolhida
    anchors = {"inicio": 0,
               "depois_gratis": (order.index("openrouter") + 1) if "openrouter" in order else 0,
               "antes_locais": order.index("ollama") if "ollama" in order else len(order)}
    customs = custom_ids()
    for pos in ("fim", "antes_locais", "depois_gratis", "inicio"):
        group = [c for c in customs if PROVIDERS[c].get("position", "antes_locais") == pos]
        if not group:
            continue
        if pos == "fim":
            order = order + group
        else:
            i = anchors[pos]
            order = order[:i] + group + order[i:]
    if not with_instances:
        return order
    extras = []
    for p in order:
        extras += instances_of(p)[1:]
    return order + extras


def daily_limit(pid):
    raw = os.environ.get(f"{base_id(pid).upper()}_DAILY_LIMIT", "").strip()
    return int(raw) if raw.isdigit() else None


# ---------------------------------------------------------------- estado

def data_dir():
    """Pasta de dados do kit (estado do rodízio, imagens geradas).
    BIAZZITECH_HOME > ~/.gemini/antigravity só se já tiver dados de uma instalação antiga > ~/.biazzitech."""
    custom = (os.environ.get("BIAZZITECH_HOME") or "").strip()
    if custom:
        d = custom
    elif (os.path.isfile(os.path.join(_home(), ".gemini", "antigravity", "router_state.json"))
          and not os.path.isdir(os.path.join(_home(), ".biazzitech"))):
        d = os.path.join(_home(), ".gemini", "antigravity")  # instalação antiga: continua onde estava
    else:
        d = os.path.join(_home(), ".biazzitech")  # padrão (PC novo, .exe, Termux)
    os.makedirs(d, exist_ok=True)
    return d


def _state_path():
    return os.path.join(data_dir(), "router_state.json")


def _today():
    return datetime.date.today().isoformat()


def _load_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"providers": {}}


def _save_state(state):
    path = _state_path()
    tmp = path + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _pstate(state, pid):
    ps = state.setdefault("providers", {}).setdefault(pid, {})
    if ps.get("day") != _today():
        ps["day"] = _today()
        ps["today"] = {"requests": 0, "ok": 0, "errors": 0}
    ps.setdefault("today", {"requests": 0, "ok": 0, "errors": 0})
    ps.setdefault("total_ok", 0)
    return ps


def _update(pid, fn):
    """Lê o estado do disco, aplica fn(provider_state) e salva (merge entre processos)."""
    with _lock:
        state = _load_state()
        ps = _pstate(state, pid)
        fn(ps)
        _save_state(state)
        return dict(ps)


def _get(pid):
    with _lock:
        return dict(_pstate(_load_state(), pid))


# ---------------------------------------------------------------- descoberta de modelos

def _http_json(url, key=None, timeout=20, headers=None):
    if headers is None:
        headers = {"User-Agent": USER_AGENT}
        if key:
            headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _discover_models(pid):
    """Lista ordenada de modelos candidatos do provedor (cache de 24h)."""
    cfg = PROVIDERS[pid]
    cached = _get(pid).get("discovered") or {}
    if cached.get("models") and time.time() - cached.get("at", 0) < DISCOVERY_TTL:
        return list(cached["models"])
    try:
        key = provider_key(pid)
        data = _http_json(cfg["base"] + "/models",
                          headers=auth_headers(pid, key) if key and not cfg.get("local") else None)
        ids = []
        for m in data.get("data", []):
            mid = (m.get("id") or "").replace("models/", "")
            if not mid or any(x in mid.lower() for x in DISCOVERY_EXCLUDE + tuple(cfg.get("exclude", ()))):
                continue
            if not cfg.get("local") and not cfg.get("custom") and TINY_MODEL_RE.search(mid):
                continue
            if cfg.get("only_free") and not mid.endswith(":free"):
                continue
            ids.append(mid)
        ranked = []
        for pattern in cfg.get("prefer", []):
            ranked += [i for i in ids if pattern in i and i not in ranked]
        ranked += [i for i in ids if i not in ranked]
        ranked = ranked[:6]
        if ranked:
            _update(pid, lambda s: s.__setitem__("discovered", {"models": ranked, "model": ranked[0], "at": time.time()}))
            return ranked
    except Exception:
        pass
    return []


def resolve_models(pid, requested):
    """Modelos a tentar no provedor pid (em ordem) para o modelo pedido pelo cliente."""
    cfg = PROVIDERS[pid]
    base = base_id(pid)
    if requested and native_provider(requested) == base:
        name = strip_prefix(base, requested)
        if name.lower() not in ("auto", "auto-free", "free"):
            return [name]
    if requested == "deepseek-reasoner":
        reason = os.environ.get(f"{base.upper()}_REASON_MODEL", "").strip() or cfg.get("reason_model")
        if reason:
            return [reason]
    override = os.environ.get(f"{base.upper()}_MODEL", "").strip() or cfg.get("user_model") or ""
    if override:
        return [override]
    if base == "pollinations":
        first = POLLINATIONS_TEXT_MAP.get(requested, cfg["default_model"])
        return [first] + [m for m in POLLINATIONS_FALLBACK_CHAIN if m != first]
    models = [] if cfg.get("no_discovery") else _discover_models(pid)
    if not models and cfg.get("default_model"):
        models = [cfg["default_model"]]
    cool = _get(pid).get("model_cooldown") or {}
    now = time.time()
    fresh = [m for m in models if cool.get(m, 0) <= now]
    return fresh


VISION_HINT = re.compile(r"(vl|vision|llama-4|gemma-3|gemma3|pixtral|qwen2\.5-vl|qwen3-vl|gpt-4o|gemini|claude|grok)", re.I)


def payload_has_images(payload):
    for m in payload.get("messages") or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "image") for p in c):
            return True
    return False


def accepts_images(pid):
    cfg = PROVIDERS[pid]
    if cfg.get("custom"):
        return bool(cfg.get("vision"))
    return not cfg.get("no_images")


def resolve_model(pid, requested):
    models = resolve_models(pid, requested)
    return models[0] if models else None


# Formato "provedor:modelo" (usado pela versão v2.0 do kit) -> formato deste roteador
_COLON_PREFIX = {
    "groq": "groq/", "openrouter": "openrouter/", "ollama": "ollama_cloud/", "ollama-cloud": "ollama_cloud/",
    "ollama_cloud": "ollama_cloud/", "ollama-local": "ollama/", "local": "ollama/", "gemini": "gemini/",
    "claude": "claude/", "anthropic": "claude/", "chatgpt": "chatgpt/", "xai": "xai/",
    "deepseek": "", "pollinations": "",
}


def normalize_model(model):
    """'groq:openai/gpt-oss-120b' -> 'groq/openai/gpt-oss-120b'; 'deepseek:deepseek-chat' -> 'deepseek-chat'.
    Nomes de modelo do Ollama com ':' (ex.: 'gemma4:26b') ficam como estão."""
    m = (model or "").strip()
    prefix, sep, rest = m.partition(":")
    if sep and rest and prefix.lower() in _COLON_PREFIX:
        return _COLON_PREFIX[prefix.lower()] + rest
    return m


def native_provider(model):
    """Qual provedor 'é dono' do nome de modelo pedido (None = qualquer um / auto)."""
    m = (model or "").strip()
    low = m.lower()
    head = low.split("/", 1)[0]
    if head in PROVIDERS and PROVIDERS[head].get("custom"):
        return head
    if not m or low in ("auto", "default"):
        return None
    if low in ("deepseek-chat", "deepseek-reasoner"):
        return "deepseek"
    if low.startswith("gemini/") or low.startswith("gemini-"):
        return "gemini"
    if low.startswith("groq/"):
        return "groq"
    if low.startswith("openrouter/") or low.endswith(":free"):
        return "openrouter"
    if low.startswith("xai/") or low.startswith("grok-"):
        return "xai"
    if low.startswith("claude/") or low.startswith("anthropic/") or low.startswith("claude-"):
        return "anthropic"
    if low.startswith("chatgpt/") or low.startswith("gpt-") or re.match(r"^o\d", low):
        return "openai"
    if low.startswith("ollama_cloud/"):
        return "ollama_cloud"
    if low.startswith("ollama/"):
        return "ollama"
    return "pollinations"


def strip_prefix(pid, model):
    extra = {"anthropic": ("claude/",), "openai": ("chatgpt/",)}.get(pid, ())
    for prefix in (pid + "/",) + extra:
        if model.lower().startswith(prefix):
            return model[len(prefix):]
    return model


# ---------------------------------------------------------------- cooldown

def _parse_duration(text):
    """Converte '2m59.5s', '1h', '30s', '850ms' ou '12' em segundos."""
    if not text:
        return None
    text = str(text).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", text):
        found = True
        n = float(num)
        total += {"ms": n / 1000, "s": n, "m": n * 60, "h": n * 3600}[unit]
    return total if found else None


def _seconds_until_utc_hour(hour):
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def _cooldown_for(code, headers, body_text):
    body_low = (body_text or "").lower()
    if code == 429:
        if any(k in body_low for k in ("perday", "per day", "daily", "per_day", "requests per day")):
            # cotas diárias do Gemini/OpenRouter zeram ~meia-noite do Pacífico (08:00 UTC)
            return _seconds_until_utc_hour(8), "limite diário atingido"
        ra = None
        if headers is not None:
            ra = _parse_duration(headers.get("Retry-After")) or \
                 _parse_duration(headers.get("x-ratelimit-reset-requests")) or \
                 _parse_duration(headers.get("x-ratelimit-reset-tokens"))
        return max(ra or 60, 10), "limite de pedidos (429)"
    if code == 402:
        return 6 * 3600, "sem saldo/créditos (402)"
    if code in (401, 403):
        return 6 * 3600, f"chave recusada ({code})"
    if code is None or code >= 500:
        return 30, "provedor indisponível"
    return 0, None


def _capture_ratelimit(headers):
    out = {}
    if headers is None:
        return out
    for k, v in headers.items():
        kl = k.lower()
        if kl.startswith("x-ratelimit") or kl.startswith("anthropic-ratelimit") or kl == "retry-after":
            out[kl] = v
    return out


def _record_ok(pid, model, headers):
    rl = _capture_ratelimit(headers)

    def fn(ps):
        ps["today"]["requests"] += 1
        ps["today"]["ok"] += 1
        ps["total_ok"] = ps.get("total_ok", 0) + 1
        ps["last_ok"] = time.time()
        ps["last_used"] = time.time()
        ps["last_model"] = model
        ps["cooldown_until"] = 0
        ps["cooldown_reason"] = None
        if rl:
            ps["ratelimit"] = rl
            ps["ratelimit_at"] = time.time()
    _update(pid, fn)


def _record_error(pid, model, code, message, headers=None, body_text=""):
    secs, reason = _cooldown_for(code, headers, body_text)
    rl = _capture_ratelimit(headers)

    def fn(ps):
        ps["today"]["requests"] += 1
        ps["today"]["errors"] += 1
        ps["last_used"] = time.time()
        ps["last_error"] = {"at": time.time(), "code": code, "model": model, "message": (message or "")[:300]}
        if secs:
            ps["cooldown_until"] = time.time() + secs
            ps["cooldown_reason"] = reason
        if code == 404:
            ps.pop("discovered", None)  # modelo sumiu: redescobrir na próxima
        if rl:
            ps["ratelimit"] = rl
            ps["ratelimit_at"] = time.time()
    _update(pid, fn)


def _record_model_issue(pid, model, code, message, seconds):
    def fn(ps):
        ps["today"]["requests"] += 1
        ps["today"]["errors"] += 1
        ps["last_used"] = time.time()
        ps["last_error"] = {"at": time.time(), "code": code, "model": model, "message": (message or "")[:300]}
        mc = ps.setdefault("model_cooldown", {})
        now = time.time()
        for k in [k for k, v in mc.items() if v <= now]:
            mc.pop(k, None)
        mc[model] = now + seconds
    _update(pid, fn)


def unavailable_reason(pid, ps=None):
    if PROVIDERS[pid].get("user_hidden"):
        return "removido por você"
    if PROVIDERS[pid].get("user_disabled"):
        return "desligado por você"
    if pid == "sdlocal":  # o painel liga o motor sozinho na hora de gerar
        import sd_local
        if not provider_key(pid):
            return "desativado (rode bat\\Instalar_SD_Local_IA.bat)"
        return None if sd_local.installed() else "não instalado (rode bat\\Instalar_SD_Local_IA.bat)"
    if not provider_key(pid):
        return "desativado (rode o instalador do Ollama)" if PROVIDERS[pid].get("local") else "sem chave"
    if PROVIDERS[pid].get("local") and not _local_server_up(PROVIDERS[pid]["base"]):
        return "Ollama não está rodando (abra o app Ollama)"
    if PROVIDERS[pid].get("custom") and not _local_server_up(PROVIDERS[pid]["base"]):
        return "servidor não responde"
    ps = ps or _get(pid)
    if ps.get("cooldown_until", 0) > time.time():
        return ps.get("cooldown_reason") or "em espera"
    lim = daily_limit(pid)
    if lim is not None and ps.get("today", {}).get("requests", 0) >= lim:
        return f"limite diário local ({lim})"
    return None


LONG_WAIT = 3600  # esperas de 1 h ou mais = chave recusada, sem saldo ou limite do dia


def usable(pid):
    """(aparece nas listas?, em espera curta?, motivo). Some: sem chave, desligado/removido, motor local
    parado/não instalado, chave recusada/sem saldo/limite do dia. Fica (marcado): espera curta de limite por minuto."""
    insts = instances_of(pid) if pid in PROVIDERS else []
    if not insts:
        return False, False, "desconhecido"
    reasons = []
    for i in insts:
        reason = unavailable_reason(i)
        if reason is None:
            return True, False, None
        reasons.append(reason)
        cfg = PROVIDERS[i]
        if cfg.get("user_hidden") or cfg.get("user_disabled") or (not provider_key(i) and i != "pollinations"):
            continue
        wait = _get(i).get("cooldown_until", 0) - time.time()
        if 0 < wait < LONG_WAIT:
            return True, True, reason
    return False, False, reasons[0]


DEMO_TEXT_KEYS = ("gemini", "groq", "openrouter")  # chaves grátis sugeridas, na ordem


def demo_status():
    """Modo demo = nenhum provedor de texto utilizável (instalação sem chaves). Imagens continuam funcionando:
    o Flux/Pollinations gera sem chave (com marca d'água e limite menor)."""
    load_env()
    text_ok = any(usable(b)[0] for b in provider_order(with_instances=False))
    return {
        "demo": not text_ok,
        "text_ok": text_ok,
        "image_key": bool(provider_key("pollinations")),
        "free_keys": [{"id": p, "label": PROVIDERS[p]["label"], "url": PROVIDERS[p].get("key_url")}
                      for p in DEMO_TEXT_KEYS if p in PROVIDERS],
        "pollinations_url": PROVIDERS.get("pollinations", {}).get("key_url"),
        "ollama_url": PROVIDERS.get("ollama", {}).get("key_url"),
    }


def model_availability(models):
    """Para cada nome de modelo das listas do painel: o provedor dono e se ele deve aparecer.
    'auto' e outros sem dono aparecem se houver pelo menos um provedor de texto utilizável."""
    load_env()
    text_ok = any(usable(b)[0] for b in provider_order(with_instances=False))
    out = {}
    for m in models:
        m = str(m or "")
        if m in IMAGE_PROVIDERS or (m in PROVIDERS and PROVIDERS[m].get("kind") == "image"):
            pid = m
        elif m.startswith("auto"):
            pid = None
        else:
            pid = native_provider(m)
        if pid is None:
            out[m] = {"provider": None, "show": text_ok, "waiting": False, "reason": None if text_ok else "nenhum provedor ativo"}
            continue
        show, waiting, reason = usable(pid)
        out[m] = {"provider": pid, "show": show, "waiting": waiting, "reason": reason}
    return out


def reset(pid=None):
    with _lock:
        state = _load_state()
        for p in ([pid] if pid else list(PROVIDERS)):
            if p not in PROVIDERS:
                continue
            ps = _pstate(state, p)
            ps["cooldown_until"] = 0
            ps["cooldown_reason"] = None
            ps.pop("discovered", None)
            ps.pop("model_cooldown", None)
        _save_state(state)


# ---------------------------------------------------------------- chamadas

def _candidate_plan(requested, only=None):
    order = provider_order()
    if only:
        return instances_of(only) if base_id(only) in provider_order(False) else []
    native = native_provider(requested)
    if native and native in order:
        first = instances_of(native)
        order = first + [p for p in order if p not in first]
    return order


def _build_body(pid, model, payload):
    body = dict(payload)
    body["model"] = model
    if base_id(pid) == "pollinations":
        body.pop("max_tokens", None)
        body.pop("reasoning_effort", None)
    return json.dumps(body).encode("utf-8")


# ---------------------------------------------------------------- Claude (API Messages nativa)

class _ConvertedResponse:
    """Imita a resposta HTTP de /chat/completions (JSON ou SSE) a partir de outro formato."""

    def __init__(self, openai_json, stream, source_headers=None):
        self.headers = {}
        if source_headers is not None:
            for k, v in source_headers.items():
                if k.lower().startswith("anthropic-ratelimit") or k.lower() == "retry-after":
                    self.headers[k] = v
        if stream:
            self.headers["Content-Type"] = "text/event-stream"
            msg = openai_json["choices"][0]["message"]
            head = {k: openai_json[k] for k in ("id", "created", "model") if k in openai_json}
            head["object"] = "chat.completion.chunk"
            c1 = dict(head, choices=[{"index": 0, "delta": {"role": "assistant", "content": msg.get("content") or ""},
                                      "finish_reason": None}])
            c2 = dict(head, choices=[{"index": 0, "delta": {},
                                      "finish_reason": openai_json["choices"][0]["finish_reason"]}],
                      usage=openai_json.get("usage"))
            raw = ("data: " + json.dumps(c1, ensure_ascii=False) + "\n\n" +
                   "data: " + json.dumps(c2, ensure_ascii=False) + "\n\n" + "data: [DONE]\n\n").encode("utf-8")
        else:
            self.headers["Content-Type"] = "application/json"
            raw = json.dumps(openai_json, ensure_ascii=False).encode("utf-8")
        self._buf = io.BytesIO(raw)
        self.status = 200

    def read(self, *a):
        return self._buf.read(*a)

    def readline(self, *a):
        return self._buf.readline(*a)

    def close(self):
        pass


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "" if content is None else str(content)


def _anthropic_images(content):
    """Partes image_url (data:image/...;base64,...) no formato de bloco de imagem da API Messages."""
    out = []
    if not isinstance(content, list):
        return out
    for p in content:
        if not isinstance(p, dict) or p.get("type") != "image_url":
            continue
        url = (p.get("image_url") or {}).get("url", "") if isinstance(p.get("image_url"), dict) else p.get("image_url", "")
        m = re.match(r"^data:(image/(?:png|jpeg|gif|webp));base64,(.+)$", url or "", re.S)
        if m:
            out.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}})
        elif (url or "").startswith("http"):
            out.append({"type": "image", "source": {"type": "url", "url": url}})
    return out


def _anthropic_request(model, payload):
    """Converte um pedido estilo OpenAI (chat/completions) para a API Messages da Anthropic."""
    system, messages = [], []
    for m in payload.get("messages") or []:
        role, text = m.get("role"), _text_of(m.get("content"))
        if not text:
            continue
        if role in ("system", "developer"):
            if messages:  # instrução no meio da conversa vira texto do usuário
                messages.append({"role": "user", "content": f"[Instrução do sistema] {text}"})
            else:
                system.append(text)
        elif role == "assistant":
            messages.append({"role": "assistant", "content": text})
        else:  # user, tool, function...
            images = _anthropic_images(m.get("content"))
            if images:  # texto + imagens (data URLs) viram blocos da API Messages
                messages.append({"role": "user", "content": images + [{"type": "text", "text": text}]})
            else:
                messages.append({"role": "user", "content": text})
    if not messages or messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "(continuação da conversa)"})
    body = {
        "model": model,
        "max_tokens": int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 16000),
        "messages": messages,
    }
    # Na versão atual da API, temperature/top_p/top_k dão erro 400: não são enviados.
    if system:
        body["system"] = "\n\n".join(system)
    stop = payload.get("stop")
    if stop:
        body["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    extra = {}
    if model.startswith(ANTHROPIC_FALLBACK_MODELS):
        # se os filtros de segurança recusarem o pedido, o servidor tenta outro modelo sozinho
        body["fallbacks"] = "default"
        extra["anthropic-beta"] = "server-side-fallback-2026-07-01"
    return body, extra


def _anthropic_to_openai(data, model):
    text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
    stop = data.get("stop_reason")
    if stop == "refusal":
        det = data.get("stop_details") or {}
        cat = det.get("category")
        text = text or ("(O Claude recusou este pedido" + (f": {cat}" if cat else "") + ".)")
    finish = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
              "refusal": "content_filter", "tool_use": "tool_calls"}.get(stop, "stop")
    usage = data.get("usage") or {}
    return {
        "id": data.get("id", "msg"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("model", model),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0),
                  "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)},
    }


def _open_anthropic(pid, key, model, payload, timeout):
    body, extra = _anthropic_request(model, payload)
    headers = auth_headers(pid, key)
    headers["Content-Type"] = "application/json"
    headers.update(extra)
    req = urllib.request.Request(PROVIDERS[pid]["base"] + "/messages", data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=max(timeout, 300)) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return _ConvertedResponse(_anthropic_to_openai(data, model), bool(payload.get("stream")), resp.headers)


def open_chat(payload, explicit_deepseek_key=None, only=None, timeout=90):
    """
    Abre uma requisição /chat/completions no primeiro provedor disponível.
    Retorna (resposta_http_aberta, info). Quem chama deve ler e fechar a resposta.
    Levanta RouterError se nenhum provedor responder.
    """
    load_env()
    requested = normalize_model(payload.get("model") or "auto")
    if requested != payload.get("model"):
        payload = dict(payload, model=requested)
    attempts = []
    with_images = payload_has_images(payload)

    for pid in _candidate_plan(requested, only):
        key = provider_key(pid)
        use_explicit = pid == "deepseek" and explicit_deepseek_key
        if use_explicit:
            key = explicit_deepseek_key
        reason = None if use_explicit else unavailable_reason(pid)
        if reason:
            attempts.append({"provider": pid, "skipped": reason})
            continue

        if with_images and not accepts_images(pid):
            attempts.append({"provider": pid, "skipped": "não aceita imagens"})
            continue
        models = resolve_models(pid, requested)
        if with_images and len(models) > 1:
            # com imagens, modelos que enxergam vêm primeiro (ex.: os ':free' com 'vl' no OpenRouter)
            models = sorted(models, key=lambda m: 0 if VISION_HINT.search(m) else 1)
        if not models:
            attempts.append({"provider": pid, "skipped": "nenhum modelo disponível"})
            continue

        waited = wait_key_switch(pid)
        if waited:
            attempts.append({"provider": pid, "waited": round(waited, 1)})
        mark_key_use(pid)
        for model in models:
            headers = auth_headers(pid, key)
            headers["Content-Type"] = "application/json"
            if base_id(pid) == "openrouter":
                headers["X-Title"] = "BiazziTech AI Studio"
            req = urllib.request.Request(PROVIDERS[pid]["base"] + "/chat/completions",
                                         data=_build_body(pid, model, payload), headers=headers, method="POST")
            try:
                if PROVIDERS[pid].get("api") == "anthropic":
                    resp = _open_anthropic(pid, key, model, payload, timeout)
                else:
                    # modelos locais em CPU podem levar minutos para responder
                    cfg_t = 600 if PROVIDERS[pid].get("local") else PROVIDERS[pid].get("timeout", 0)
                    resp = urllib.request.urlopen(req, timeout=max(timeout, cfg_t))
                _record_ok(pid, model, resp.headers)
                info = {"provider": pid, "provider_label": PROVIDERS[pid]["label"], "model": model,
                        "requested": requested, "attempts": attempts}
                return resp, info
            except urllib.error.HTTPError as e:
                try:
                    body_text = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    body_text = ""
                attempts.append({"provider": pid, "model": model, "error": e.code, "message": body_text[:200]})
                low = body_text.lower()
                if (e.code == 429 and "upstream" in low) or e.code == 404:
                    # problema só deste modelo (ex.: modelo grátis congestionado): tenta o próximo modelo
                    _record_model_issue(pid, model, e.code, body_text, 600 if e.code == 429 else 86400)
                    continue
                _record_error(pid, model, e.code, body_text or str(e), e.headers, body_text)
                if base_id(pid) != "pollinations" or e.code in (401, 402, 403):
                    break  # passa para o próximo provedor
            except Exception as e:
                _record_error(pid, model, None, str(e))
                attempts.append({"provider": pid, "model": model, "error": "rede", "message": str(e)[:200]})
                break

    if not attempts:
        raise RouterError("Nenhum provedor configurado. Coloque ao menos uma chave no ~/.env.", attempts, 401)
    resumo = "; ".join(
        f"{a['provider']}: {a.get('skipped') or a.get('error')}" for a in attempts if not a.get("waited")
    )
    raise RouterError(f"Todos os provedores falharam ou estão em espera ({resumo})", attempts)


def chat_completion(payload, explicit_deepseek_key=None, only=None, timeout=90):
    """Versão sem streaming: devolve (json_da_resposta, info) com campo 'provider' incluído."""
    body = dict(payload)
    body["stream"] = False
    resp, info = open_chat(body, explicit_deepseek_key, only, timeout)
    try:
        data = json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()
    data["provider"] = info["provider"]
    data.setdefault("model", info["model"])
    return data, info


def simple_chat(prompt, system="", model="auto", temperature=0.7, only=None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if model == "deepseek-reasoner":
        payload["temperature"] = 1.0
    data, info = chat_completion(payload, only=only)
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    return {
        "content": msg.get("content", "") or "",
        "reasoning_content": msg.get("reasoning_content", "") or "",
        "model": data.get("model", info["model"]),
        "provider": info["provider"],
        "usage": data.get("usage", {}),
    }


# ---------------------------------------------------------------- painel de uso

def _refresh_openrouter_usage():
    key = provider_key("openrouter")
    if not key:
        return
    ps = _get("openrouter")
    if time.time() - ps.get("account_at", 0) < 300:
        return
    try:
        data = _http_json("https://openrouter.ai/api/v1/key", key=key, timeout=10).get("data", {})
        info = {k: data.get(k) for k in ("usage", "usage_daily", "limit", "limit_remaining", "is_free_tier") if k in data}
        _update("openrouter", lambda s: (s.__setitem__("account", info), s.__setitem__("account_at", time.time())))
    except Exception:
        pass


def _provider_note(pid):
    if PROVIDERS[pid].get("instance_of"):
        return "Chave extra. Usar várias contas do mesmo serviço pode violar os termos de uso dele."
    if pid != "ollama" or not provider_key(pid):
        return None
    tier = os.environ.get("OLLAMA_HW_TIER", "")
    if tier == "abaixo_minimo":
        return "Máquina abaixo do mínimo recomendado: o desempenho pode ser muito prejudicado."
    if tier == "minimo":
        return "Máquina no mínimo: respostas locais podem ser lentas."
    return None


def status(refresh=False):
    load_env()
    if refresh:
        _refresh_openrouter_usage()
    state = _load_state()
    out = []
    image_ids = []
    for b in IMAGE_PROVIDERS:
        image_ids += instances_of(b)
    text_ids = provider_order()
    image_ids += [c for c in custom_ids("imagens") if c not in text_ids]  # personalizados só de imagens
    for pid in text_ids + image_ids:
        cfg = PROVIDERS[pid]
        if cfg.get("instance_of") and not provider_key(pid):
            continue  # instância extra sem chave: não mostra
        ps = _pstate(state, pid)
        reason = unavailable_reason(pid, ps)
        cd = ps.get("cooldown_until", 0)
        out.append({
            "id": pid,
            "base": base_id(pid),
            "instance": bool(cfg.get("instance_of")),
            "kind": cfg.get("kind", "chat"),
            "key_hint": cfg.get("key_hint"),
            "label": cfg["label"],
            "free_tier": cfg["free"],
            "configured": bool(provider_key(pid)),
            "key_url": cfg.get("key_url"),
            "key_env": cfg["key_env"],
            "key_mask": "" if cfg.get("local") else mask_key(provider_key(pid)),
            "local": bool(cfg.get("local")),
            "custom": bool(cfg.get("custom")),
            "base_url": cfg.get("base") if cfg.get("custom") else None,
            "vision": bool(cfg.get("vision")),
            "position": cfg.get("position"),
            "uses": cfg.get("uses") if cfg.get("custom") else None,
            "hidden": bool(cfg.get("user_hidden")),
            "disabled": bool(cfg.get("user_disabled")) and not cfg.get("user_hidden"),
            "orig_label": cfg.get("orig_label"),
            "user_model": cfg.get("user_model") or "",
            "custom_model": cfg.get("default_model") if cfg.get("custom") else None,
            "has_key": (not cfg.get("no_key")) if cfg.get("custom") else None,
            "available": reason is None,
            "reason": reason,
            "cooldown_until": cd if cd > time.time() else 0,
            "cooldown_seconds": max(0, int(cd - time.time())),
            "today": ps.get("today", {}),
            "daily_limit": daily_limit(pid),
            "total_ok": ps.get("total_ok", 0),
            "last_ok": ps.get("last_ok"),
            "last_model": ps.get("last_model") or (ps.get("discovered") or {}).get("model"),
            "models": (ps.get("discovered") or {}).get("models"),
            "last_error": ps.get("last_error"),
            "ratelimit": ps.get("ratelimit"),
            "account": ps.get("account"),
            "note": _provider_note(pid),
        })
    return {"order": provider_order(), "providers": out, "now": time.time(),
            "max_instances": MAX_INSTANCES, "key_delay": key_switch_delay(),
            "custom_positions": CUSTOM_POSITIONS}


if __name__ == "__main__":
    # Diagnóstico rápido: python provider_router.py [status|reset|teste]
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "reset":
        reset(sys.argv[2] if len(sys.argv) > 2 else None)
        print("Esperas zeradas.")
    elif cmd == "teste":
        r = simple_chat("Responda apenas: OK", model=sys.argv[2] if len(sys.argv) > 2 else "auto")
        print(f"[{r['provider']} / {r['model']}] {r['content']}")
    else:
        for p in status(refresh=True)["providers"]:
            st = "ATIVO" if p["available"] else f"OFF ({p['reason']})"
            print(f"{p['id']:<13} {st:<40} hoje: {p['today'].get('ok', 0)} ok / {p['today'].get('errors', 0)} erros")
