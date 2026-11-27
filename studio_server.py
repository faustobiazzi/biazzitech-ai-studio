#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BiazziTech AI Studio & OpenAI-Compatible Local Proxy (Porta padrão: 9090)
- Serve o painel visual BiazziTech AI Studio em / e /ui.html (0% consumo de tokens do Antigravity)
- Expõe endpoint compatível com OpenAI em /v1/chat/completions e /v1/models
- Expõe geração privada de imagens sem marca d'água em /api/image
- Compatível nativamente com o protocolo Sidecar Web UI do Antigravity (ANTIGRAVITY_SIDECAR_WEB_PORT)
"""

import os
import re
import sys
import json
import time
import base64
import struct
import hashlib
import socket
import threading
import urllib.parse
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
sys.path.append(os.path.join(_HOME, ".biazzitech", "app"))
sys.path.append(os.path.join(_HOME, ".gemini", "antigravity", "scripts"))
import provider_router as router
import image_providers
import access_control as access
import doc_extract
import prompt_assist
import characters
import comic_layouts
import godot_export
import conversations
import web_search

DEFAULT_PORT = 9090
MAX_BODY = 60 * 1024 * 1024  # imagens de referência em base64 cabem com folga

POLLINATIONS_IMAGE_MAP = {
    "flux": "black-forest-labs/flux.1-schnell",
    "flux-pro": "black-forest-labs/flux.1.1-pro",
    "flux-flex": "black-forest-labs/flux.2-flex",
    "turbo": "tongyi-mai/z-image-turbo",
    "anime": "community/vendouple/animagine",
}

load_env = router.load_env  # um só leitor de ~/.env

UI_FILES = {"studio.css": "text/css; charset=utf-8", "studio.js": "application/javascript; charset=utf-8",
            # app instalável (PWA): manifesto, service worker e ícones
            "manifest.webmanifest": "application/manifest+json; charset=utf-8",
            "sw.js": "application/javascript; charset=utf-8", "icon-192.png": "image/png", "icon-512.png": "image/png",
            "icon-maskable-512.png": "image/png", "apple-touch-icon.png": "image/png"}
ROOT_UI_FILES = {"/manifest.webmanifest": "manifest.webmanifest", "/sw.js": "sw.js",
                 "/apple-touch-icon.png": "apple-touch-icon.png", "/favicon.ico": "icon-192.png"}


def _ui_candidates(rel):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~")
    return [
        os.path.join(script_dir, rel),
        os.path.join(getattr(sys, "_MEIPASS", script_dir), rel),  # dentro do .exe
        os.path.join(home, ".biazzitech", "app", rel),
        os.path.join(home, ".gemini", "antigravity", "scripts", rel),
    ]


def get_ui_file(rel):
    """Lê um arquivo do painel (studio_ui.html ou ui/<arquivo>); None se não achar."""
    for p in _ui_candidates(rel):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    return None


def get_ui_html() -> bytes:
    return get_ui_file("studio_ui.html") or b"<h1>studio_ui.html nao encontrado</h1>"


def get_output_images_dir() -> str:
    # Uma pasta só para todas as cópias do servidor (Sidecar, atalho, .exe): <pasta de dados>/imagens
    out_dir = os.environ.get("BIAZZITECH_IMAGES") or os.path.join(router.data_dir(), "imagens")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


IMAGE_NAME_RE = re.compile(r"^[\w.-]+\.(png|jpe?g|webp|gif)$", re.IGNORECASE)
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif"}
_gallery_lock = threading.RLock()


def resolve_output_image(name) -> str:
    """Caminho de uma imagem gerada, aceitando SÓ nomes simples dentro da pasta output/imagens."""
    if not isinstance(name, str) or not IMAGE_NAME_RE.match(name):
        return None
    base = os.path.realpath(get_output_images_dir())
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


def sidecar_json_path(img_path: str) -> str:
    """Caminho do .json anexo de uma imagem (mesmo nome-base na mesma pasta)."""
    return os.path.splitext(img_path)[0] + ".json"


def _image_dimensions(data: bytes):
    """Extrai (largura, altura) de PNG, JPEG, GIF ou WEBP usando só a biblioteca padrão."""
    if not data or len(data) < 16:
        return 0, 0
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            chunk = data[12:16]
            if chunk == b"VP8 " and len(data) >= 30:
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L" and len(data) >= 25:
                b0, b1, b2, b3 = data[21:25]
                return 1 + (((b1 & 0x3F) << 8) | b0), 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
            if chunk == b"VP8X" and len(data) >= 30:
                w = 1 + int.from_bytes(data[24:27], "little")
                h = 1 + int.from_bytes(data[27:30], "little")
                return w, h
        if data[:2] == b"\xff\xd8":
            i, n = 2, len(data)
            sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
            while i + 1 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                while i < n and data[i] == 0xFF:
                    i += 1
                if i >= n:
                    break
                marker = data[i]
                i += 1
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                if i + 2 > n:
                    break
                seg_len = struct.unpack(">H", data[i:i + 2])[0]
                if seg_len < 2 or i + seg_len > n:
                    break
                if marker in sof_markers and seg_len >= 7:
                    h, w = struct.unpack(">HH", data[i + 3:i + 7])
                    return w, h
                i += seg_len
    except Exception:
        pass
    return 0, 0


def _infer_legacy_meta(fname: str) -> dict:
    """Infere metadados básicos para imagens antigas que já estavam em imagens/ antes do .json anexo."""
    stem = os.path.splitext(fname)[0]
    low = stem.lower()
    if low.startswith("studio_"):
        core = re.sub(r"_\d{9,}(?:_\d+)?$", "", stem[len("studio_"):])
        known = {
            "animagine": ("pollinations", "community/vendouple/animagine", {"model": "anime"}),
            "flux_1-schnell": ("pollinations", "black-forest-labs/flux.1-schnell", {"model": "flux"}),
            "flux_1_1-pro": ("pollinations", "black-forest-labs/flux.1.1-pro", {"model": "flux-pro"}),
            "flux_2-flex": ("pollinations", "black-forest-labs/flux.2-flex", {"model": "flux-flex"}),
            "z-image-turbo": ("pollinations", "tongyi-mai/z-image-turbo", {"model": "turbo"}),
        }
        if core.lower() in known:
            prov, mod, st = known[core.lower()]
            return {"provider": prov, "model": mod, "settings": st}
        return {"provider": "pollinations", "model": core or "studio", "settings": {}}
    if low.startswith("pagina"):
        return {"provider": "montagem", "model": "página montada", "settings": {}}
    if low.startswith("pixai_"):
        return {"provider": "pixai", "model": "PixAI", "settings": {}}
    for p in ("sdlocal", "pixellab", "retrodiffusion", "scenario"):
        if low.startswith(p + "_"):
            return {"provider": p, "model": "SD local" if p == "sdlocal" else p, "settings": {}}
    return {"provider": "", "model": stem, "settings": {}}


def _write_json_atomic(path: str, payload: dict):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _unique_output_image_path(stem: str, ext: str) -> str:
    """Garante nome-base único em imagens/ (uma imagem <-> um .json de mesmo nome-base, sem colisão)."""
    out_dir = get_output_images_dir()
    clean_stem = re.sub(r"[^\w.-]", "_", stem).strip("._")[:80] or "imagem"
    existing_stems = set()
    try:
        for entry in os.listdir(out_dir):
            if IMAGE_NAME_RE.match(entry) or (entry.lower().endswith(".json") and not entry.endswith(".tmp")):
                existing_stems.add(os.path.splitext(entry)[0].lower())
    except OSError:
        pass
    candidate = clean_stem
    n = 2
    while candidate.lower() in existing_stems:
        candidate = f"{clean_stem}_{n}"
        n += 1
    return os.path.join(out_dir, candidate + ext)


def _public_gallery_item(img_path: str, meta: dict) -> dict:
    fname = os.path.basename(img_path)
    mtime_ns = meta.get("file_mtime_ns") or 0
    return {
        "file_name": fname,
        "saved_path": img_path,
        "json_path": sidecar_json_path(img_path),
        "url": f"/imagens/{urllib.parse.quote(fname)}" + (f"?v={mtime_ns}" if mtime_ns else ""),
        "model": meta.get("model") or os.path.splitext(fname)[0],
        "provider": meta.get("provider") or "",
        "prompt": meta.get("prompt") or "",
        "negative": meta.get("negative") or "",
        "settings": meta.get("settings") if isinstance(meta.get("settings"), dict) else {},
        "width": meta.get("width") or "",
        "height": meta.get("height") or "",
        "created_at": meta.get("created_at") or 0,
        "updated_at": meta.get("updated_at") or 0,
        "modified": bool(meta.get("modified", False)),
        "owner": meta.get("owner") or "",
    }


def save_output_image(img_bytes: bytes, stem: str, ext: str, meta: dict = None) -> dict:
    """Salva uma imagem nova em imagens/ e grava seu .json anexo com os dados de criação."""
    meta = dict(meta or {})
    with _gallery_lock:
        out_path = _unique_output_image_path(stem, ext)
        tmp_img = f"{out_path}.{os.getpid()}.tmp"
        with open(tmp_img, "wb") as f:
            f.write(img_bytes)
        os.replace(tmp_img, out_path)
        st = os.stat(out_path)
        w, h = _image_dimensions(img_bytes)
        width = int(meta.get("width") or w or 0) or ""
        height = int(meta.get("height") or h or 0) or ""
        now = time.time()
        fname = os.path.basename(out_path)
        record = {
            "file_name": fname,
            "model": meta.get("model") or os.path.splitext(fname)[0],
            "provider": meta.get("provider") or "",
            "prompt": meta.get("prompt") or "",
            "negative": meta.get("negative") or "",
            "settings": meta.get("settings") if isinstance(meta.get("settings"), dict) else {},
            "width": width,
            "height": height,
            "created_at": float(meta.get("created_at") or now),
            "updated_at": now,
            "modified": False,
            "owner": meta.get("owner") or "",
            "file_size": st.st_size,
            "file_mtime_ns": st.st_mtime_ns,
            "sha256": hashlib.sha256(img_bytes).hexdigest(),
        }
        _write_json_atomic(sidecar_json_path(out_path), record)
        return _public_gallery_item(out_path, record)


def image_owner(name: str) -> str:
    """Dono gravado no .json anexo ('' = imagem antiga/sem dono: só administradores veem)."""
    path = resolve_output_image(name)
    if not path:
        return ""
    try:
        with open(sidecar_json_path(path), "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("owner") or ""
    except (OSError, ValueError):
        return ""


def delete_output_image(name: str) -> bool:
    """Remove a imagem e o seu .json anexo juntos (também limpa .json órfão se a imagem já saiu do disco)."""
    if not isinstance(name, str) or not IMAGE_NAME_RE.match(name):
        return False
    with _gallery_lock:
        base = os.path.realpath(get_output_images_dir())
        img_path = os.path.realpath(os.path.join(base, name))
        if os.path.dirname(img_path) != base:
            return False
        jpath = sidecar_json_path(img_path)
        existed = os.path.isfile(img_path)
        if existed:
            os.remove(img_path)
        if os.path.isfile(jpath):
            try:
                os.remove(jpath)
            except OSError:
                pass
        return existed


def sync_output_images() -> list:
    """Sincroniza imagens/ e seus .json anexos:
    - remove qualquer .json órfão cuja imagem não exista mais;
    - cria o .json para imagens que ainda não tinham anexo (ex.: geradas antes ou via CLI);
    - atualiza o .json se a imagem foi alterada/editada no disco;
    - devolve a lista ordenada (mais recentes primeiro) para o painel."""
    with _gallery_lock:
        out_dir = get_output_images_dir()
        try:
            entries = os.listdir(out_dir)
        except OSError:
            return []

        images_by_stem = {}
        json_by_stem = {}
        for name in entries:
            full = os.path.join(out_dir, name)
            if not os.path.isfile(full) or name.endswith(".tmp"):
                continue
            if IMAGE_NAME_RE.match(name):
                key = os.path.splitext(name)[0].lower()
                images_by_stem.setdefault(key, []).append(name)
            elif re.match(r"^[\w.-]+\.json$", name, re.IGNORECASE):
                key = os.path.splitext(name)[0].lower()
                json_by_stem[key] = name

        # 1) Remove qualquer .json órfão (sem imagem correspondente de mesmo nome-base)
        for key, jname in list(json_by_stem.items()):
            if key not in images_by_stem:
                try:
                    os.remove(os.path.join(out_dir, jname))
                except OSError:
                    pass
                json_by_stem.pop(key, None)

        # 2) Garante e atualiza o .json de cada imagem presente
        items = []
        for key, img_names in images_by_stem.items():
            jname = json_by_stem.get(key)
            existing = None
            if jname:
                try:
                    with open(os.path.join(out_dir, jname), "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        existing = loaded
                except Exception:
                    existing = None

            # Se houver mais de uma extensão com o mesmo stem manual, prioriza a do .json ou a mais nova
            chosen = img_names[0]
            if len(img_names) > 1:
                pref = existing.get("file_name") if existing else None
                if pref in img_names:
                    chosen = pref
                else:
                    chosen = max(img_names, key=lambda fn: os.path.getmtime(os.path.join(out_dir, fn)))

            img_path = os.path.join(out_dir, chosen)
            target_jpath = sidecar_json_path(img_path)
            try:
                st = os.stat(img_path)
            except OSError:
                continue

            if existing is None:
                try:
                    with open(img_path, "rb") as f:
                        raw = f.read()
                except OSError:
                    continue
                w, h = _image_dimensions(raw)
                inferred = _infer_legacy_meta(chosen)
                record = {
                    "file_name": chosen,
                    "model": inferred.get("model") or os.path.splitext(chosen)[0],
                    "provider": inferred.get("provider") or "",
                    "prompt": "",
                    "negative": "",
                    "settings": inferred.get("settings") or {},
                    "width": w or "",
                    "height": h or "",
                    "created_at": st.st_mtime,
                    "updated_at": st.st_mtime,
                    "modified": False,
                    "file_size": st.st_size,
                    "file_mtime_ns": st.st_mtime_ns,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                _write_json_atomic(target_jpath, record)
                if jname and os.path.normcase(os.path.join(out_dir, jname)) != os.path.normcase(target_jpath):
                    try:
                        os.remove(os.path.join(out_dir, jname))
                    except OSError:
                        pass
            else:
                record = dict(existing)
                changed_stat = (
                    record.get("file_size") != st.st_size
                    or record.get("file_mtime_ns") != st.st_mtime_ns
                    or record.get("file_name") != chosen
                )
                if changed_stat:
                    try:
                        with open(img_path, "rb") as f:
                            raw = f.read()
                    except OSError:
                        continue
                    new_hash = hashlib.sha256(raw).hexdigest()
                    content_changed = (new_hash != record.get("sha256")) or (record.get("file_name") != chosen)
                    w, h = _image_dimensions(raw)
                    record["file_name"] = chosen
                    record["file_size"] = st.st_size
                    record["file_mtime_ns"] = st.st_mtime_ns
                    record["sha256"] = new_hash
                    if w and h:
                        record["width"], record["height"] = w, h
                    elif content_changed:
                        record["width"], record["height"] = "", ""
                    if content_changed:
                        record["updated_at"] = st.st_mtime
                        record["modified"] = True
                    _write_json_atomic(target_jpath, record)
                    if jname and os.path.normcase(os.path.join(out_dir, jname)) != os.path.normcase(target_jpath):
                        try:
                            os.remove(os.path.join(out_dir, jname))
                        except OSError:
                            pass

            items.append(_public_gallery_item(img_path, record))

        items.sort(key=lambda x: (float(x.get("created_at") or 0), x.get("file_name") or ""), reverse=True)
        return items


class StudioHandler(BaseHTTPRequestHandler):
    def _origin_ok(self) -> bool:
        """Bloqueia pedidos vindos de outros sites (CSRF). Aceita o próprio painel (mesma origem),
        localhost e webviews do Antigravity."""
        raw = (self.headers.get("Origin") or "").strip()
        if raw.lower() == "null":  # iframes isolados / arquivos locais: origem desconhecida
            return False
        origin = urllib.parse.urlparse(raw)
        if origin.scheme not in ("http", "https"):
            return True  # sem Origin (Continue, Cline, curl) ou webview do editor
        if origin.hostname in ("localhost", "127.0.0.1"):
            return True
        return origin.netloc == (self.headers.get("Host") or "")

    def _is_local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _user(self):
        return access.user_from_request(self.headers.get("Cookie"), self.headers.get("Authorization"))

    def _owner(self) -> str:
        """Nome de quem está usando: o usuário logado ou 'local' (este PC sem login)."""
        user = self._user()
        return user["name"] if user else "local"

    def _owner_keys(self):
        """Donos que esta pessoa representa: ela mesma e, se for administrador, também 'local' (este PC sem login)."""
        me = self._owner()
        return (me, "local") if me != "local" and self._is_admin() else (me,)

    def _is_admin(self) -> bool:
        return access.decide("admin", self._is_local(), self._user())[0]

    def _can_see_image(self, name) -> bool:
        return self._is_admin() or image_owner(name) == self._owner()

    def _handle_conversation_chat(self, req):
        """Pergunta numa conversa guardada: grava, monta o contexto com a memória, responde e grava a resposta."""
        me, content = self._owner(), (req.get("content") or "").strip()
        keys = self._owner_keys()
        if not content:
            self._send_json(400, {"ok": False, "message": "Mensagem vazia."})
            return
        model = req.get("model") or "auto"
        said = req.get("display") or content
        prefs = conversations.get_prefs(me)
        extra_calls, removed = 0, []
        try:
            cid = req.get("conversation_id") or ""
            if not cid:
                cid = conversations.create(me, preset=req.get("preset") or "", model=model)["id"]
            conv = conversations.get(cid, keys, False)
            if not conversations.can_edit(conv, keys):
                raise conversations.ConversationError("Só o dono pode escrever nesta conversa.")
            # resposta à pergunta das opções com IA ("sim", "faça", "do it", "não"...): resolve aqui, sem gastar consulta
            if conv.get("pending_question") == "ai_options":
                answer = conversations.parse_answer(said)
                conversations.set_pending_question(cid, keys, None)
                if answer is not None:
                    prefs = conversations.set_prefs(me, ai_confirm=answer, partial_reset=answer, asked=True)
                    conversations.append(cid, keys, "user", content, display=req.get("display"), intent="skip")
                    reply = ("✅ Ativado: vou confirmar com a IA as reclamações e mudanças de contexto e, na mudança, "
                             "tirar só o que conflita. Cada uso gasta uma consulta extra. Dá para desligar na 🧠 Memória."
                             if answer else
                             "👍 Fica desligado: sigo pela detecção de frases, sem gastar consultas extras. "
                             "Dá para ligar depois na 🧠 Memória.")
                    conv = conversations.append(cid, keys, "assistant", reply, meta={"provider": "painel", "model": "local"})
                    self._send_json(200, {"ok": True, "reply": reply, "provider": "painel", "model": "local",
                                          "conversation_id": cid, "title": conv["title"], "prefs": prefs,
                                          "user_index": len(conv["messages"]) - 2,
                                          "reply_index": len(conv["messages"]) - 1, "intent": None})
                    return
            # busca na internet / lugares perto: responde sem passar pela IA de conversa
            web_calls = []

            def ai_route(text):
                web_calls.append(1)
                return web_search.ai_classifier(text)
            route = web_search.classify(said, req.get("web") or "auto", req.get("preset") or "free",
                                        ask=ai_route if prefs.get("ai_confirm") else None)
            if route in ("web", "places") and self._answer_from_web(route, cid, keys, conv, content, said, req, len(web_calls)):
                return
            intent = conversations.detect_intent(said)
            if intent and prefs.get("ai_confirm"):
                intent = conversations.confirm_intent(conv, said, intent)
                extra_calls += 1
            keep = None
            if intent == "reset" and prefs.get("partial_reset") and conv.get("anchors"):
                keep, removed = conversations.partial_keep(conv, said)
                extra_calls += 1
            conv = conversations.append(cid, keys, "user", content, display=req.get("display"), intent=intent, keep=keep)
            if intent == "reset" and keep is None:
                removed = [a["text"] for a in (conv.get("undo") or {}).get("anchors", [])]
        except conversations.ConversationError as e:
            self._send_json(403, {"ok": False, "message": str(e)})
            return
        messages = conversations.build_context(conv, req.get("system") or "", intent=intent,
                                               query=req.get("display") or content)
        rescue = conv.pop("_last_rescue", {})
        try:
            data, info = router.chat_completion({"model": model, "messages": messages,
                                                 "temperature": req.get("temperature", 0.7)}, timeout=180)
        except router.RouterError as e:
            conversations.pop_last_user(cid, keys)
            self._send_json(502, {"ok": False, "message": str(e), "conversation_id": cid})
            return
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        reply = msg.get("content") or "(Sem conteúdo)"
        conv = conversations.append(cid, keys, "assistant", reply,
                                    meta={"provider": info.get("provider"), "model": data.get("model") or info.get("model")})
        user_index = len(conv["messages"]) - 2
        question = None
        if intent and not prefs.get("asked"):  # 1ª vez que faz sentido: pergunta no chat se quer as opções com IA
            conversations.set_prefs(me, asked=True)
            conv = conversations.append(cid, keys, "assistant", conversations.AI_OPTIONS_QUESTION,
                                        meta={"provider": "painel", "model": "local"})
            conversations.set_pending_question(cid, keys, "ai_options")
            question = conversations.AI_OPTIONS_QUESTION
        if intent == "reset" and conv.get("memory"):  # memória sem o que ficou do contexto antigo
            def rebase():
                try:
                    conversations.rebase_memory(cid, keys)
                except Exception as e:
                    sys.stderr.write(f"[Studio] memória não reescrita: {e}\n")
            threading.Thread(target=rebase, daemon=True).start()
        compacting = conversations.needs_compaction(conv)
        if compacting:  # resume em segundo plano para a próxima pergunta já sair mais leve
            def bg():
                try:
                    conversations.compact(cid, keys)
                except Exception as e:
                    sys.stderr.write(f"[Studio] compactação automática falhou: {e}\n")
            threading.Thread(target=bg, daemon=True).start()
        self._send_json(200, {"ok": True, "reply": reply, "provider": info.get("provider"),
                              "model": data.get("model") or info.get("model"), "conversation_id": cid,
                              "title": conv["title"], "compacting": compacting, "intent": intent,
                              "rescue": rescue, "question": question, "removed_anchors": removed,
                              "extra_calls": extra_calls, "user_index": user_index, "reply_index": user_index + 1,
                              "can_undo": intent == "reset",
                              "context_chars": conversations.summary(conv)["context_chars"]})

    def _answer_from_web(self, route, cid, keys, conv, content, said, req, extra_calls):
        """Responde com a busca na internet ou com lugares perto. Devolve False para cair na IA de conversa."""
        secure = bool(req.get("secure"))
        note = ""
        try:
            if route == "places":
                loc = req.get("location") if isinstance(req.get("location"), dict) else {}
                try:
                    lat, lon = float(loc["lat"]), float(loc["lon"])
                    acc = float(loc.get("accuracy") or 0) or None
                except (KeyError, TypeError, ValueError):
                    lat = lon = acc = None
                res = web_search.places(said, lat, lon, acc)
                if res.get("need_location"):
                    reply = (f"📍 Para achar {res['label'].lower()} perto de você eu preciso da sua localização. " +
                             ("Permita a localização quando o navegador perguntar (ou libere no cadeado da barra de endereço) e mande de novo. "
                              if secure else
                              "O navegador só libera a localização com HTTPS (ou usando o painel no próprio PC, em localhost): "
                              "peça ao administrador para habilitar o HTTPS na aba Acesso. ") +
                             "Ou escreva o bairro e a cidade, por exemplo: \"padaria perto de Barão Geraldo, Campinas\".")
                    provider = "painel"
                else:
                    reply, provider = web_search.format_places(res), "OpenStreetMap"
            else:
                history = conv["messages"][-4:]  # contexto para perguntas de seguimento ("e amanhã?")
                res = web_search.search(said, history)
                reply, provider = web_search.format_search(res), res["provider"]
        except web_search.WebError as e:
            if route == "web":
                return False  # sem buscador: a IA de conversa responde (e o status avisa)
            reply, provider, note = f"⚠ {e}", "painel", str(e)
        conversations.append(cid, keys, "user", content, display=req.get("display"), intent="skip")
        conv = conversations.append(cid, keys, "assistant", reply, meta={"provider": provider, "model": route})
        self._send_json(200, {"ok": True, "reply": reply, "provider": provider, "model": route, "kind": route,
                              "conversation_id": cid, "title": conv["title"], "intent": None, "note": note,
                              "need_location": route == "places" and provider == "painel" and not note,
                              "extra_calls": extra_calls, "user_index": len(conv["messages"]) - 2,
                              "reply_index": len(conv["messages"]) - 1})
        return True

    def _handle_conversation_action(self, req):
        me, admin, action, cid = self._owner(), self._is_admin(), req.get("action"), req.get("id") or ""
        keys = self._owner_keys()
        try:
            if action == "new":
                out = conversations.create(me, req.get("title") or "", req.get("preset") or "", req.get("model") or "")
            elif action == "rename":
                out = conversations.rename(cid, keys, req.get("title"))
            elif action == "memory":
                out = conversations.set_memory(cid, keys, req.get("memory"))
            elif action == "undo_reset":
                out = conversations.undo_reset(cid, keys)
            elif action == "pin":
                out = conversations.toggle_pin(cid, keys, int(req.get("index")))
            elif action == "prefs":
                out = {"prefs": conversations.set_prefs(me, ai_confirm=req.get("ai_confirm"),
                                                         partial_reset=req.get("partial_reset"), asked=True)}
            elif action == "anchor_remove":
                out = conversations.remove_anchor(cid, keys, int(req.get("index")))
            elif action == "clear":
                out = conversations.clear(cid, keys)
            elif action == "compact":
                out = conversations.compact(cid, keys, req.get("model"))
            elif action == "delete":
                conversations.delete(cid, keys, admin)
                out = {}
            elif action == "cleanup":
                days = max(1, int(req.get("days") or 90))
                everyone = admin and req.get("everyone")
                out = {"removed": conversations.cleanup(days, None if everyone else keys)}
            else:
                self._send_json(400, {"ok": False, "message": "Ação desconhecida."})
                return
        except conversations.ConversationError as e:
            self._send_json(400, {"ok": False, "message": str(e)})
            return
        except (TypeError, ValueError):
            self._send_json(400, {"ok": False, "message": "Pedido inválido."})
            return
        info = conversations.summary(out) if isinstance(out, dict) and "messages" in out else out
        self._send_json(200, {"ok": True, "result": info})

    def _guard(self, perm, check_origin=False) -> bool:
        """Confere permissão da rota. Responde 401/403 e devolve False se negado."""
        if check_origin and not self._origin_ok():
            self._send_json(403, {"ok": False, "error": "Origem não permitida", "message": "Origem não permitida"})
            return False
        ok, reason, need_login = access.decide(perm, self._is_local(), self._user())
        if not ok:
            self._send_json(401 if need_login else 403,
                            {"ok": False, "login": need_login, "error": reason, "message": reason})
        return ok

    def _guard_any(self, perms, check_origin=False) -> bool:
        """Permite se o usuário tiver QUALQUER uma das permissões."""
        user, local = self._user(), self._is_local()
        if any(access.decide(p, local, user)[0] for p in perms):
            if check_origin and not self._origin_ok():
                self._send_json(403, {"ok": False, "error": "Origem não permitida", "message": "Origem não permitida"})
                return False
            return True
        return self._guard(perms[0], check_origin)

    def _read_json(self, body):
        try:
            return json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return {}

    def _gallery_data_url(self, name):
        path = resolve_output_image(name)
        if not path or not self._can_see_image(name):
            return None
        with open(path, "rb") as f:
            data = f.read()
        ctype = IMAGE_TYPES.get(os.path.splitext(path)[1].lower(), "image/png")
        return f"data:{ctype};base64," + base64.b64encode(data).decode("ascii")

    def _effective_perms(self):
        user = self._user()
        return [p for p in access.PERMISSIONS if access.decide(p, self._is_local(), user)[0]]

    def log_message(self, fmt, *args):
        # Mantém log limpo sem poluir excessivamente
        sys.stderr.write(f"[Studio {self.server.server_port}] {fmt % args}\n")

    def _set_cors(self):
        """CORS só para a própria origem/localhost/editor: um site qualquer aberto no navegador
        NÃO consegue ler respostas nem usar suas chaves pelo painel."""
        origin = (self.headers.get("Origin") or "").strip()
        if origin and self._origin_ok():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Vary", "Origin")
        self._security_headers()

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _is_https(self) -> bool:
        return bool(getattr(self.server, "is_https", False))

    def _session_cookie(self, value: str, max_age: int) -> str:
        return (f"bt_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
                + ("; Secure" if self._is_https() else ""))

    def _send_json(self, code: int, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._set_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_json_cookie(self, code: int, obj: dict, cookie: str):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _handle_access(self, path: str, body: bytes):
        """Administração: rede, porta, usuários."""
        try:
            req = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            req = {}
        if path == "/api/access/network":
            lan = bool(req.get("lan"))
            if lan and not access.has_users():
                self._send_json(400, {"ok": False, "need_user": True,
                                      "message": "Para liberar na rede, crie antes um usuário administrador com senha "
                                                 "(senão qualquer pessoa da rede usaria suas chaves)."})
                return
            if lan and not req.get("accept_risk"):
                self._send_json(400, {"ok": False, "need_risk": True, "message": access.LAN_RISK_TEXT})
                return
            changes = {"lan": lan}
            if lan:
                changes["lan_risk_accepted"] = time.strftime("%Y-%m-%d %H:%M:%S")
            access.set_config(**changes)
            request_rebind()
            if lan:
                https = access.https_status()
                msg = ("Acesso pela rede LIGADO" + (f", com HTTPS na porta {https['port']}." if https["ready"]
                       else " SEM HTTPS (senha e conversa trafegam sem criptografia; veja como ativar o HTTPS).")
                       + " Se o Windows perguntar sobre o firewall, permita em 'Redes privadas'.")
            else:
                msg = "Acesso pela rede DESLIGADO: só este PC acessa."
            self._send_json(200, {"ok": True, "message": msg})
        elif path == "/api/access/auth_local":
            access.set_config(auth_local=bool(req.get("value")))
            self._send_json(200, {"ok": True, "message": "Configuração salva."})
        elif path == "/api/access/port":
            port = req.get("port")
            err = access.validate_port(port, allow_in_use=str(port) == str(self.server.server_port))
            if err:
                self._send_json(400, {"ok": False, "message": err})
                return
            access.set_config(port=int(port))
            self._send_json(200, {"ok": True, "message": f"Porta {port} salva. Clique em 'Reiniciar servidor' abaixo "
                                                         "para aplicar agora (ou feche e abra o atalho)."})
        elif path == "/api/access/restart":
            next_port = int(access.get_config().get("port") or self.server.server_port)
            sidecar_port = os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT")
            target_port = int(sidecar_port) if (sidecar_port and sidecar_port.isdigit()) else next_port
            schedule_restart()
            self._send_json(200, {"ok": True, "restarting": True, "port": target_port,
                                  "message": f"Reiniciando o servidor (porta {target_port})..."})
        elif path == "/api/access/users":
            action, name = req.get("action"), (req.get("name") or "").strip()
            if action == "add":
                ok, msg, token = access.add_user(name, req.get("password") or "", req.get("perms") or ["chat", "imagens"])
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg, "token": token})
            elif action == "update":
                ok, msg, _ = access.update_user(name, perms=req.get("perms"),
                                                password=req.get("password") or None)
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg})
            elif action == "token":
                ok, msg, token = access.update_user(name, new_token=True)
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg, "token": token})
            elif action == "delete":
                ok, msg = access.delete_user(name)
                if ok and not access.has_users() and access.get_config().get("lan"):
                    msg += " Sem usuários, a rede foi fechada: só este PC acessa até você criar um usuário."
                request_rebind()
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg})
            else:
                self._send_json(400, {"ok": False, "message": "Ação inválida."})
        else:
            self._send_json(404, {"ok": False, "message": "Rota inválida."})

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path in ("/", "/index.html", "/ui.html"):
            html = get_ui_html()
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed_path.startswith("/ui/") or parsed_path in ROOT_UI_FILES:
            # o service worker precisa ser servido na raiz para controlar o painel inteiro
            name = ROOT_UI_FILES.get(parsed_path) or parsed_path[len("/ui/"):]
            data = get_ui_file(os.path.join("ui", name)) if name in UI_FILES else None
            if data is None:
                self._send_json(404, {"error": "Arquivo nao encontrado"})
                return
            self.send_response(200)
            self._security_headers()
            self.send_header("Content-Type", UI_FILES[name])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed_path == "/healthz":
            self._send_json(200, {"status": "ok", "port": self.server.server_port, "app": "biazzitech"})
            return

        if parsed_path == "/api/auth/me":
            user = self._user()
            cfg = access.get_config()
            self._send_json(200, {
                "auth_enabled": access.has_users(),
                "user": user["name"] if user else None,
                "perms": self._effective_perms(),
                "is_local": self._is_local(),
                "lan": cfg.get("lan"),
            })
            return

        if parsed_path == "/api/access":
            if not self._guard("admin"):
                return
            cfg = access.get_config()
            self._send_json(200, {"config": cfg, "users": access.list_users(), "lan_ips": access.lan_addresses(),
                                  "running_port": self.server.server_port, "bound_host": self.server.server_address[0],
                                  "is_local": self._is_local(), "https": access.https_status(),
                                  "lan_active": access.lan_effective(), "risk_text": access.LAN_RISK_TEXT})
            return

        if parsed_path == "/api/status":
            if not self._guard("chat"):
                return
            load_env()
            self._send_json(200, {
                "status": "ok",
                "port": self.server.server_port,
                "providers": {p: bool(router.provider_key(p)) for p in router.PROVIDERS},
            })
            return

        if parsed_path == "/api/custom-providers":
            if not self._guard("admin"):
                return
            router.load_env()
            self._send_json(200, {"providers": router.list_custom_providers(), "positions": router.CUSTOM_POSITIONS,
                                  "uses": router.CUSTOM_USES})
            return

        if parsed_path == "/api/characters":
            if not self._guard("imagens"):
                return
            self._send_json(200, {"characters": [characters.public(c) for c in characters.list_characters()]})
            return

        if parsed_path.startswith("/api/characters/img/"):
            if not self._guard("imagens"):
                return
            p = characters.image_path(urllib.parse.unquote(parsed_path.rsplit("/", 1)[-1]))
            if not p:
                self._send_json(404, {"error": "Imagem não encontrada"})
                return
            with open(p, "rb") as f:
                data = f.read()
            self.send_response(200)
            self._security_headers()
            self.send_header("Content-Type", IMAGE_TYPES.get(os.path.splitext(p)[1].lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed_path == "/api/image/sd-info":
            # modelos e LoRAs do SD deste PC ou de um servidor SD de outro PC (provedor personalizado de imagens)
            if not self._guard("imagens"):
                return
            pid = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("id") or ["sdlocal"])[0]
            try:
                self._send_json(200, {"ok": True, **image_providers.sd_info(pid)})
            except image_providers.ImageError as e:
                self._send_json(502, {"ok": False, "message": str(e)})
            return

        if parsed_path == "/api/comic/layouts":
            if not self._guard("imagens"):
                return
            self._send_json(200, comic_layouts.layouts())
            return

        if parsed_path == "/api/images":
            if not self._guard("imagens"):
                return
            items = sync_output_images()
            admin, me = self._is_admin(), self._owner()
            if not admin:
                items = [i for i in items if i.get("owner") == me]
            self._send_json(200, {"ok": True, "images": items, "is_admin": admin, "me": me})
            return

        if parsed_path == "/api/conversations":
            if not self._guard("chat"):
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            admin = self._is_admin()
            everyone = admin and query.get("all", ["0"])[0] == "1"
            self._send_json(200, {"ok": True, "me": self._owner(), "mine": list(self._owner_keys()), "is_admin": admin,
                                  "prefs": conversations.get_prefs(self._owner()),
                                  "conversations": conversations.list_for(self._owner_keys(), admin, everyone)})
            return

        if parsed_path.startswith("/api/conversations/"):
            if not self._guard("chat"):
                return
            try:
                conv = conversations.get(parsed_path.rsplit("/", 1)[1], self._owner_keys(), self._is_admin())
            except conversations.ConversationError as e:
                self._send_json(404, {"ok": False, "message": str(e)})
                return
            self._send_json(200, {"ok": True, "conversation": {**conv, "can_edit": conversations.can_edit(conv, self._owner_keys()),
                                                                "info": conversations.summary(conv)}})
            return

        if parsed_path == "/api/image/options":
            if not self._guard("imagens"):
                return
            opts = image_providers.options()
            opts["_pdf"] = doc_extract.pdf_support()
            self._send_json(200, opts)
            return

        if parsed_path == "/api/providers":
            if not self._guard("chat"):
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send_json(200, router.status(refresh=query.get("refresh", ["0"])[0] == "1"))
            return

        if parsed_path == "/api/demo":
            if not self._guard_any(["chat", "imagens"]):
                return
            self._send_json(200, {"ok": True, **router.demo_status()})
            return

        if parsed_path == "/api/models/availability":
            if not self._guard("chat"):
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send_json(200, {"ok": True, "models": router.model_availability(query.get("m", [])[:200])})
            return

        if parsed_path in ("/v1/models", "/models"):
            if not self._guard("chat"):
                return
            self._send_json(200, {
                "object": "list",
                "data": [
                    {"id": "auto", "object": "model", "owned_by": "router"},
                    {"id": "gemini-flash-latest", "object": "model", "owned_by": "gemini"},
                    {"id": "groq/openai/gpt-oss-120b", "object": "model", "owned_by": "groq"},
                    {"id": "groq/llama-3.3-70b-versatile", "object": "model", "owned_by": "groq"},
                    {"id": "openrouter/auto-free", "object": "model", "owned_by": "openrouter"},
                    {"id": "claude/auto", "object": "model", "owned_by": "anthropic"},
                    {"id": "chatgpt/auto", "object": "model", "owned_by": "openai"},
                    {"id": "ollama/auto", "object": "model", "owned_by": "ollama"},
                    {"id": "openai/gpt-5.3-codex", "object": "model", "owned_by": "pollinations"},
                    {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
                    {"id": "deepseek-reasoner", "object": "model", "owned_by": "deepseek"},
                    {"id": "deepseek/deepseek-v4.1-flash", "object": "model", "owned_by": "pollinations"},
                    {"id": "openai/gpt-5.4-mini", "object": "model", "owned_by": "pollinations"},
                    {"id": "moonshotai/kimi-k3.1-pro", "object": "model", "owned_by": "pollinations"},
                    {"id": "x-ai/grok-4.6", "object": "model", "owned_by": "pollinations"},
                ] + [{"id": f"{c}/auto", "object": "model", "owned_by": c} for c in router.custom_ids()]
            })
            return

        if parsed_path.startswith("/imagens/"):
            if not self._guard("imagens"):
                return
            img_name = urllib.parse.unquote(parsed_path[len("/imagens/"):])
            img_path = resolve_output_image(img_name)
            if img_path and not self._can_see_image(img_name):
                img_path = None
            if not img_path:
                sync_output_images()
                self._send_json(404, {"error": "Imagem nao encontrada"})
                return
            with open(img_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", IMAGE_TYPES.get(os.path.splitext(img_path)[1].lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        self._send_json(404, {"error": "Rota nao encontrada"})

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path).path
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0
        if content_length > MAX_BODY:
            self._send_json(413, {"ok": False, "message": "Pedido grande demais (máx. 60 MB)."})
            self.close_connection = True
            return
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        # Nenhum POST aceito de outros sites (protege suas chaves e configurações de páginas maliciosas)
        if not self._origin_ok():
            self._send_json(403, {"ok": False, "error": "Origem não permitida", "message": "Origem não permitida"})
            return

        if parsed_path in ("/api/auth/login", "/api/auth/logout"):
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                req = {}
            if parsed_path.endswith("/logout"):
                tok = None
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "bt_session":
                        tok = v
                if tok:
                    access.logout(tok)
                self._send_json_cookie(200, {"ok": True}, self._session_cookie("", 0))
                return
            token, msg = access.login(req.get("user"), req.get("password"), self.client_address[0])
            if not token:
                self._send_json(401, {"ok": False, "message": msg})
                return
            self._send_json_cookie(200, {"ok": True, "user": req.get("user")},
                                   self._session_cookie(token, access.SESSION_TTL))
            return

        if parsed_path.startswith("/api/access/"):
            if not self._guard("admin", check_origin=True):
                return
            self._handle_access(parsed_path, body)
            return

        if parsed_path == "/api/image":
            if not self._guard("imagens"):
                return
            self._handle_image(body)
            return

        if parsed_path == "/api/extract":
            # Texto de anexos (.docx/.md/.txt/.pdf) para usar como referência
            if not self._guard_any(["chat", "imagens"], check_origin=True):
                return
            req = self._read_json(body)
            try:
                raw = base64.b64decode((req.get("data") or "").split(",", 1)[-1])
            except Exception:
                self._send_json(400, {"ok": False, "message": "Arquivo inválido."})
                return
            if len(raw) > 20 * 1024 * 1024:
                self._send_json(400, {"ok": False, "message": "Arquivo muito grande (máx. 20 MB)."})
                return
            try:
                text, warn = doc_extract.extract(req.get("name") or "", raw)
            except doc_extract.ExtractError as e:
                self._send_json(400, {"ok": False, "message": str(e)})
                return
            except Exception as e:
                self._send_json(400, {"ok": False, "message": f"Não consegui ler o arquivo: {e}"})
                return
            self._send_json(200, {"ok": True, "text": text, "chars": len(text), "warning": warn})
            return

        if parsed_path == "/api/image/cancel":
            if not self._guard("imagens", check_origin=True):
                return
            stopped = False
            try:
                import sd_local
                if sd_local._proc.get("p") and sd_local._proc["p"].poll() is None:
                    sd_local.stop_server()
                    stopped = True
            except Exception:
                pass
            self._send_json(200, {"ok": True, "stopped_sd": stopped, "message": "Geração cancelada."})
            return

        if parsed_path == "/api/prompt-assist":
            if not self._guard("imagens", check_origin=True):
                return
            req = self._read_json(body)
            mode = (req.get("mode") or "plan").strip().lower()
            instr = req.get("instruction") or ""
            ref_text = req.get("text") or ""
            lay_id = req.get("layout") or ""
            lay_text = req.get("layout_text") or ""
            sfx_text = req.get("sfx_text") or ""
            if mode == "auto":
                use_single = not prompt_assist.is_multi_panel(instr, ref_text, lay_id, lay_text, sfx_text)
            else:
                use_single = (mode == "single")
            if not instr.strip() and not (use_single and ref_text.strip()):
                self._send_json(400, {"ok": False, "message": "Escreva o que você quer (ex.: página de 5 quadros...)."})
                return
            images = [u for u in (req.get("images") or []) if isinstance(u, str) and u.startswith("data:image/")][:6]
            for name in (req.get("image_names") or [])[:6]:
                u = self._gallery_data_url(name)
                if u:
                    images.append(u)
            # fichas: as marcadas no painel + (opcional) as citadas pelo nome no pedido/texto
            ids = [i for i in (req.get("characters") or []) if isinstance(i, str)]
            if req.get("auto_characters", True):
                ids += characters.detect(instr, ref_text)
            chars = []
            for cid in dict.fromkeys(ids):
                c = characters.get(cid)
                if c:
                    c = dict(c)
                    c["image_data"] = [u for u in (characters.image_data_url(n) for n in c.get("images", [])[:2]) if u]
                    chars.append(c)
            try:
                if use_single:
                    out = prompt_assist.single(instr, ref_text, images[:6],
                                               req.get("model"), req.get("generator") or "pollinations", characters=chars[:6])
                    self._send_json(200, {"ok": True, "kind": "single", **out})
                    return
                plan = prompt_assist.plan(instr or ref_text[:400], ref_text, images[:6],
                                          req.get("model"), req.get("generator") or "pollinations",
                                          characters=chars[:6], layout=lay_id,
                                          layout_text=lay_text, sfx_text=sfx_text,
                                          sfx_mode=req.get("sfx_mode") or "overlay")
            except prompt_assist.AssistError as e:
                self._send_json(502, {"ok": False, "message": str(e)})
                return
            self._send_json(200, {"ok": True, "kind": "panels", **plan})
            return

        if parsed_path == "/api/comic/layouts":
            if not self._guard("imagens"):
                return
            req = self._read_json(body)
            action = req.get("action")
            try:
                if action == "import":
                    lay = comic_layouts.import_bw_layout(req.get("name") or "", req.get("data_url") or "")
                    self._send_json(200, {"ok": True, "layout": lay,
                                          "message": f"Modelo '{lay['name']}' criado com {lay['count']} quadro(s)."})
                elif action == "delete":
                    comic_layouts.delete_custom(req.get("id") or "")
                    self._send_json(200, {"ok": True, "message": "Modelo personalizado removido."})
                else:
                    self._send_json(400, {"ok": False, "message": "Ação inválida."})
            except comic_layouts.LayoutError as e:
                self._send_json(400, {"ok": False, "message": str(e)})
            return

        if parsed_path == "/api/characters":
            if not self._guard("imagens"):
                return
            req = self._read_json(body)
            action = req.get("action")
            try:
                if action == "save":
                    c = characters.save_character(req)
                    self._send_json(200, {"ok": True, "message": f"Ficha de {c['name']} salva.",
                                          "character": characters.public(c)})
                elif action == "delete":
                    characters.delete_character(req.get("id"))
                    self._send_json(200, {"ok": True, "message": "Ficha apagada."})
                elif action == "describe":
                    imgs = [u for u in (req.get("images") or []) if isinstance(u, str) and u.startswith("data:image/")]
                    c = characters.get(req.get("id")) if req.get("id") else None
                    if c:
                        imgs += [u for u in (characters.image_data_url(n) for n in c.get("images", [])) if u]
                    d = prompt_assist.describe_character(imgs[:4], req.get("name") or (c or {}).get("name", ""),
                                                         req.get("hint") or "", req.get("model"))
                    self._send_json(200, {"ok": True, **d})
                elif action == "detect":
                    self._send_json(200, {"ok": True, "ids": characters.detect(req.get("text") or "")})
                elif action == "dataset":
                    p = characters.dataset_zip(req.get("id"))
                    with open(p, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self._security_headers()
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(p)}"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._send_json(400, {"ok": False, "message": "Ação inválida."})
            except characters.CharacterError as e:
                self._send_json(400, {"ok": False, "message": str(e)})
            except prompt_assist.AssistError as e:
                self._send_json(502, {"ok": False, "message": str(e)})
            return

        if parsed_path == "/api/godot/export":
            if not self._guard("imagens"):
                return
            req = self._read_json(body)
            try:
                out = godot_export.export(req, get_output_images_dir(), resolve_output_image)
            except godot_export.ExportError as e:
                self._send_json(400, {"ok": False, "message": str(e)})
                return
            self._send_json(200, {"ok": True, **out})
            return

        if parsed_path == "/api/godot/download":
            if not self._guard("imagens"):
                return
            req = self._read_json(body)
            p = godot_export.zip_path(req.get("name") or "", get_output_images_dir())
            if not p:
                self._send_json(404, {"ok": False, "message": "Pacote não encontrado."})
                return
            with open(p, "rb") as f:
                data = f.read()
            self.send_response(200)
            self._security_headers()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(p)}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed_path == "/api/prompt-fix":
            if not self._guard("imagens", check_origin=True):
                return
            req = self._read_json(body)
            if not (req.get("prompt") or "").strip() or not (req.get("problem") or "").strip():
                self._send_json(400, {"ok": False, "message": "Informe o prompt e o que saiu errado."})
                return
            image = None
            if req.get("image_name"):
                image = self._gallery_data_url(req["image_name"])
            try:
                fixed = prompt_assist.fix(req["prompt"], req["problem"], image, req.get("model"),
                                          req.get("generator") or "pollinations", req.get("negative") or "")
            except prompt_assist.AssistError as e:
                self._send_json(502, {"ok": False, "message": str(e)})
                return
            self._send_json(200, {"ok": True, **fixed})
            return

        if parsed_path == "/api/image/upload":
            # Salva na galeria uma imagem montada no painel (ex.: página de quadrinhos)
            if not self._guard("imagens", check_origin=True):
                return
            req = self._read_json(body)
            m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", req.get("data_url") or "", re.S)
            if not m:
                self._send_json(400, {"ok": False, "message": "Imagem inválida."})
                return
            data = base64.b64decode(m.group(2))
            if len(data) > 40 * 1024 * 1024:
                self._send_json(400, {"ok": False, "message": "Imagem muito grande."})
                return
            ext = ".jpg" if m.group(1) == "jpeg" else "." + m.group(1)
            label = re.sub(r"[^\w-]", "_", req.get("label") or "pagina")[:40]
            saved = save_output_image(data, f"{label}_{int(time.time())}", ext, {
                "model": req.get("label") or "página montada",
                "provider": "montagem",
                "owner": self._owner(),
                "prompt": req.get("prompt") or "",
                "settings": req.get("settings") if isinstance(req.get("settings"), dict) else {},
            })
            self._send_json(200, {"ok": True, **saved, "data_url": req["data_url"]})
            return

        if parsed_path == "/api/chat":
            if not self._guard("chat", check_origin=True):
                return
            self._handle_conversation_chat(self._read_json(body))
            return

        if parsed_path == "/api/conversations":
            if not self._guard("chat", check_origin=True):
                return
            self._handle_conversation_action(self._read_json(body))
            return

        if parsed_path in ("/api/image/open", "/api/image/delete"):
            if not self._guard("imagens", check_origin=True):
                return
            if parsed_path.endswith("/open") and not self._is_local():
                self._send_json(403, {"ok": False, "message": "Abrir no visualizador só funciona no PC do servidor."})
                return
            try:
                name = json.loads(body.decode("utf-8") or "{}").get("name")
            except Exception:
                name = None
            if resolve_output_image(name) and not self._can_see_image(name):
                self._send_json(404, {"ok": False, "message": "Imagem não encontrada (já foi excluída?)"})
                return
            if parsed_path.endswith("/delete"):
                try:
                    removed = delete_output_image(name)
                except Exception as e:
                    self._send_json(500, {"ok": False, "message": f"Falhou: {e}"})
                    return
                if not removed:
                    sync_output_images()
                    self._send_json(404, {"ok": False, "message": "Imagem não encontrada (já foi excluída?)"})
                    return
                self._send_json(200, {"ok": True, "message": "Imagem e metadados excluídos."})
                return
            img_path = resolve_output_image(name)
            if not img_path:
                sync_output_images()
                self._send_json(404, {"ok": False, "message": "Imagem não encontrada (já foi excluída?)"})
                return
            try:
                if not hasattr(os, "startfile"):
                    self._send_json(400, {"ok": False, "message": "Abrir no visualizador só funciona no Windows. "
                                                                   "Use Compartilhar ou abra a imagem no navegador."})
                    return
                os.startfile(img_path)  # abre no visualizador padrão do Windows
                self._send_json(200, {"ok": True, "message": "Imagem aberta."})
            except Exception as e:
                self._send_json(500, {"ok": False, "message": f"Falhou: {e}"})
            return

        if parsed_path == "/api/providers/key":
            # Chaves: só administradores (ou este PC, quando não há usuários cadastrados)
            if not self._guard("admin", check_origin=True):
                return
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                req = {}
            pid = req.get("provider")
            router.load_env()
            if req.get("action") != "add" and pid not in router.PROVIDERS:
                self._send_json(400, {"ok": False, "message": "Provedor inválido."})
                return
            if req.get("action") == "remove":
                ok, msg = router.remove_key(pid)
            elif req.get("action") == "add":
                ok, msg = router.add_key(pid, req.get("key", ""))
            else:
                ok, msg = router.set_key(pid, req.get("key", ""))
            self._send_json(200 if ok else 400, {"ok": ok, "message": msg, "status": router.status()})
            return

        if parsed_path == "/api/custom-providers":
            # Provedores personalizados (qualquer servidor compatível com a OpenAI): só administradores
            if not self._guard("admin", check_origin=True):
                return
            req = self._read_json(body)
            action = req.get("action")
            if action == "test":
                pid = req.get("id")
                key = (req.get("key") or "").strip()
                if not key and pid and pid in router.PROVIDERS and not router.PROVIDERS[pid].get("no_key"):
                    key = router.provider_key(pid)
                ok, msg, models = router.test_custom(req.get("base"), key, req.get("uses") or "texto")
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg, "models": models,
                                                     "base": router.normalize_base_url(req.get("base"))})
            elif action == "save":
                ok, msg, pid = router.save_custom(req)
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg, "id": pid})
            elif action == "delete":
                ok, msg = router.delete_custom(req.get("id"))
                self._send_json(200 if ok else 400, {"ok": ok, "message": msg})
            else:
                self._send_json(400, {"ok": False, "message": "Ação inválida."})
            return

        if parsed_path == "/api/providers/edit":
            # editar / remover / restaurar provedores padrão (nome, modelo fixo, ligado/desligado)
            if not self._guard("admin", check_origin=True):
                return
            req = self._read_json(body)
            pid, action = req.get("id"), req.get("action") or "edit"
            router.load_env()
            if action == "remove":
                ok, msg = router.remove_provider(pid)
            elif action == "restore":
                ok, msg = router.restore_provider(pid) if pid in router.PROVIDERS else (False, "Provedor inválido.")
            else:
                ok, msg = router.edit_provider(pid, {k: req[k] for k in ("label", "model", "disabled") if k in req})
            self._send_json(200 if ok else 400, {"ok": ok, "message": msg})
            return

        if parsed_path == "/api/providers/reset":
            if not self._guard("admin", check_origin=True):
                return
            try:
                pid = json.loads(body.decode("utf-8") or "{}").get("provider")
            except Exception:
                pid = None
            router.reset(pid if pid in router.PROVIDERS else None)
            self._send_json(200, router.status())
            return

        if parsed_path.endswith("/chat/completions") or parsed_path.endswith("/completions"):
            if not self._guard("chat"):
                return
            self._handle_chat(body)
            return

        self._send_json(404, {"error": "Endpoint POST nao encontrado"})

    def _handle_image(self, body: bytes):
        load_env()
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "JSON invalido"})
            return

        prompt = (payload.get("prompt") or "").strip()
        provider = payload.get("provider") or "pollinations"

        if image_providers.is_image_provider(provider):
            self._handle_pixel_image(provider, payload, prompt)
            return

        if not prompt:
            self._send_json(400, {"error": "Prompt vazio"})
            return

        model = payload.get("model") or "flux"
        aspect = payload.get("aspect") or "1:1"
        dim_map = {
            "1:1": (1024, 1024),
            "16:9": (1280, 720),
            "9:16": (720, 1280),
            "3:4": (768, 1024),
            "4:3": (1024, 768),
        }
        w, h = dim_map.get(aspect, (1024, 1024))
        api_key = os.environ.get("POLLINATIONS_API_KEY")
        resolved_primary = POLLINATIONS_IMAGE_MAP.get(model, model)

        if api_key:
            candidates = [resolved_primary, "black-forest-labs/flux.1-schnell", "tongyi-mai/z-image-turbo"]
        else:
            candidates = [model if model in ("flux", "turbo") else "flux", "turbo"]

        models_to_try = []
        for m in candidates:
            if m not in models_to_try:
                models_to_try.append(m)

        headers = {"User-Agent": "Mozilla/5.0 Antigravity-Studio/2.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        encoded_prompt = urllib.parse.quote(prompt)
        img_bytes = None
        content_type = "image/jpeg"
        used_model = resolved_primary
        last_err = None

        for current_model in models_to_try:
            encoded_model = urllib.parse.quote(current_model, safe="/-._")
            if api_key:
                url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width={w}&height={h}&model={encoded_model}&nologo=true&private=true"
            else:
                url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={w}&height={h}&model={encoded_model}&nologo=true&private=true"

            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = resp.read()
                    if data and len(data) > 1000:
                        img_bytes = data
                        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                        used_model = current_model
                        break
            except Exception as e:
                last_err = e

        if not img_bytes:
            self._send_json(502, {"error": f"Falha ao gerar imagem: {last_err}"})
            return

        ext = ".png" if "png" in content_type else ".jpg"
        safe_tag = used_model.split("/")[-1].replace(".", "_")
        saved = save_output_image(img_bytes, f"studio_{safe_tag}_{int(time.time())}", ext, {
            "model": used_model,
            "prompt": prompt,
            "negative": payload.get("negative") or "",
            "provider": "pollinations",
            "owner": self._owner(),
            "settings": {"model": model, "aspect": aspect},
            "width": w,
            "height": h,
        })
        b64 = base64.b64encode(img_bytes).decode("ascii")
        self._send_json(200, {**saved, "data_url": f"data:{content_type};base64,{b64}"})

    def _handle_pixel_image(self, provider: str, payload: dict, prompt: str):
        """PixelLab / Retro Diffusion / Scenario: pode devolver várias imagens (direções, quadros, tiles)."""
        if not self._origin_ok():
            self._send_json(403, {"error": "Origem não permitida"})
            return
        mode = payload.get("mode") or ""
        if not prompt and mode != "animar":
            self._send_json(400, {"error": "Prompt vazio"})
            return

        # Imagem de referência: enviada pelo painel (data URL) ou uma imagem já gerada (pelo nome)
        reference = None
        ref_data = payload.get("reference_data")
        ref_name = payload.get("reference_name")
        try:
            if ref_data:
                reference = base64.b64decode(ref_data.split(",", 1)[-1])
            elif ref_name:
                ref_path = resolve_output_image(ref_name)
                if not ref_path:
                    self._send_json(404, {"error": "Imagem de referência não encontrada"})
                    return
                with open(ref_path, "rb") as f:
                    reference = f.read()
        except Exception:
            self._send_json(400, {"error": "Imagem de referência inválida"})
            return
        if reference and len(reference) > 8 * 1024 * 1024:
            self._send_json(400, {"error": "Imagem de referência muito grande (máx. 8 MB)"})
            return

        opts = {k: payload.get(k) for k in ("mode", "width", "height", "transparent", "model_id", "frames", "tile",
                                            "strength", "model", "aspect", "loras", "negative", "steps")}
        if "fast" in payload:
            opts["fast"] = payload.get("fast")
        opts["prompt"] = prompt
        opts["reference"] = reference
        try:
            results = image_providers.generate(provider, opts)
        except image_providers.ImageError as e:
            self._send_json(502, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(502, {"error": f"Falha inesperada: {e}"})
            return

        stamp = int(time.time())
        remote = provider not in image_providers.GENERATORS
        label_model = ("SD local" if provider == "sdlocal" else
                       (router.PROVIDERS.get(provider, {}).get("label", provider) if remote else f"{provider}/{mode or 'padrao'}"))
        mode = mode or ("local" if provider == "sdlocal" else ("sd" if remote else ""))
        images = []
        for i, (data, ext, label) in enumerate(results):
            safe = re.sub(r"[^\w-]", "_", f"{provider}_{mode}_{label}")[:60]
            saved = save_output_image(data, f"{safe}_{stamp}_{i + 1}", ext, {
                "model": f"{label_model} · {label}",
                "prompt": prompt,
                "negative": payload.get("negative") or "",
                "provider": provider,
                "owner": self._owner(),
                "settings": {k: payload.get(k) for k in ("mode", "width", "height", "transparent", "model_id",
                                                          "model", "aspect", "loras", "fast", "strength")},
                "width": opts.get("width") or "",
                "height": opts.get("height") or "",
            })
            ctype = IMAGE_TYPES.get(ext, "image/gif" if ext == ".gif" else "image/png")
            images.append({
                **saved,
                "data_url": f"data:{ctype};base64," + base64.b64encode(data).decode("ascii"),
            })
        self._send_json(200, {"images": images, **images[0]})

    def _handle_chat(self, body: bytes):
        load_env()
        auth_header = self.headers.get("Authorization", "")
        explicit_key = None
        if auth_header.startswith("Bearer "):
            candidate = auth_header[7:].strip()
            if candidate and candidate.lower() not in ("dummy", "local", "none", "ollama") and not candidate.startswith("btk_"):
                explicit_key = candidate

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": {"message": "JSON invalido"}})
            return
        payload.setdefault("model", "auto")

        # Roteamento automático entre provedores (Gemini, Groq, OpenRouter, DeepSeek, xAI, Pollinations)
        try:
            resp, info = router.open_chat(payload, explicit_deepseek_key=explicit_key)
        except router.RouterError as e:
            self._send_json(e.status, {"error": {"message": str(e), "attempts": e.attempts}})
            return

        try:
            if payload.get("stream"):
                # Repassa o streaming SSE linha a linha
                self.send_response(200)
                self._set_cors()
                self.send_header("Content-Type", resp.headers.get("Content-Type", "text/event-stream"))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Provider", info["provider"])
                self.send_header("X-Provider-Model", info["model"])
                self.end_headers()
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    self.wfile.write(line)
                    self.wfile.flush()
            else:
                data = json.loads(resp.read().decode("utf-8"))
                data["provider"] = info["provider"]
                data.setdefault("model", info["model"])
                raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self._set_cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("X-Provider", info["provider"])
                self.end_headers()
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send_json(502, {"error": {"message": f"Falha lendo resposta de {info['provider']}: {e}"}})
            except Exception:
                pass
        finally:
            resp.close()

def write_sidecar_info(port: int):
    data_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if data_dir:
        try:
            os.makedirs(data_dir, exist_ok=True)
            info_path = os.path.join(data_dir, "server_info.json")
            info = {
                "host": "127.0.0.1",
                "port": port,
                "token": os.environ.get("ANTIGRAVITY_SIDECAR_UI_TOKEN"),
                "pid": os.getpid(),
            }
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info, f)
        except Exception:
            pass

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

_servers = {}          # porta -> servidor ativo
_serve_lock = threading.Lock()
_stopping = False


def _bind_host(lan_capable: bool) -> str:
    """Porta principal (HTTP). Com HTTPS configurado, a rede usa a porta HTTPS e esta fica só neste PC."""
    if lan_capable and access.lan_effective() and not access.https_status()["ready"]:
        return "0.0.0.0"
    return "127.0.0.1"


def _https_wanted() -> bool:
    return access.lan_effective() and access.https_status()["ready"]


def make_https_server(host, port, cert, key):
    """Servidor do painel com TLS 1.2+ (certificado PEM)."""
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    httpd = ThreadingHTTPServer((host, port), StudioHandler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.daemon_threads = True
    httpd.is_https = True
    httpd.lan_capable = True
    return httpd


def _https_loop():
    """Servidor HTTPS para a rede local (só existe com a rede ligada e certificado em <dados>/cert.pem + key.pem)."""
    while not _stopping:
        if not _https_wanted():
            time.sleep(1.5)
            continue
        st = access.https_status()
        try:
            httpd = make_https_server("0.0.0.0", st["port"], st["cert"], st["key"])
        except Exception as e:
            print(f"[BiazziTech Studio] HTTPS não iniciou ({e}). Confira cert.pem/key.pem e a porta {st['port']}.")
            sys.stdout.flush()
            time.sleep(15)
            continue
        with _serve_lock:
            _servers["https"] = httpd
        print("[BiazziTech Studio] Rede local com HTTPS: "
              + ", ".join(f"https://{ip}:{st['port']}" for ip in access.lan_addresses()))
        sys.stdout.flush()
        httpd.serve_forever()
        httpd.server_close()
        with _serve_lock:
            if _servers.get("https") is httpd:
                _servers.pop("https", None)


def _serve_loop(port: int, lan_capable: bool, on_ready=None):
    """Serve na porta; quando o modo rede muda, fecha e reabre no novo endereço (sem reiniciar o processo)."""
    while not _stopping:
        host = _bind_host(lan_capable)
        try:
            httpd = ThreadingHTTPServer((host, port), StudioHandler)
        except OSError as e:
            if host != "127.0.0.1":
                print(f"[BiazziTech Studio] Não deu para abrir na rede ({e}); ficando só neste PC.")
                httpd = ThreadingHTTPServer(("127.0.0.1", port), StudioHandler)
                host = "127.0.0.1"
            else:
                raise
        httpd.daemon_threads = True
        httpd.lan_capable = lan_capable
        with _serve_lock:
            _servers[port] = httpd
        where = "rede local (" + ", ".join(f"http://{ip}:{port}" for ip in access.lan_addresses()) + ")" \
            if host == "0.0.0.0" else "somente este PC"
        print(f"[BiazziTech Studio] Painel em http://localhost:{port}  [{where}]")
        sys.stdout.flush()
        if on_ready:
            on_ready()
            on_ready = None
        httpd.serve_forever()
        httpd.server_close()
        with _serve_lock:
            if _servers.get(port) is httpd:
                _servers.pop(port, None)


def _restart_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--no-browser"]
    return [sys.executable, os.path.abspath(__file__)]


def schedule_restart(delay=0.35):
    """Reinicia o servidor: para o SD local, libera as portas atuais e sobe um processo limpo."""
    def worker():
        global _stopping
        time.sleep(delay)
        _stopping = True
        try:
            import sd_local
            sd_local.stop_server()
        except Exception:
            pass
        with _serve_lock:
            current = list(_servers.values())
            _servers.clear()
        for httpd in current:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass
        # Como Sidecar do Antigravity (restart_policy=always), o próprio supervisor relança o processo
        if not os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT"):
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(_restart_command(), cwd=os.path.dirname(os.path.abspath(__file__)),
                             close_fds=True, creationflags=flags)
        os._exit(0)
    threading.Thread(target=worker, daemon=True).start()


def request_rebind():
    """Chamado ao ligar/desligar o acesso pela rede: reabre os servidores no novo endereço."""
    def worker():
        time.sleep(0.4)  # deixa a resposta HTTP sair antes
        with _serve_lock:
            current = list(_servers.values())
        for httpd in current:
            if getattr(httpd, "is_https", False):
                if not _https_wanted():
                    httpd.shutdown()
                continue
            desired = _bind_host(getattr(httpd, "lan_capable", True))
            if httpd.server_address[0] != desired:
                httpd.shutdown()
    threading.Thread(target=worker, daemon=True).start()


def run_proxy(port: int = None):
    port = int(port or access.get_config().get("port") or DEFAULT_PORT)
    sidecar_env_port = os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT")
    primary_port = int(sidecar_env_port) if (sidecar_env_port and sidecar_env_port.isdigit()) else port

    # Como Sidecar do Antigravity (porta dinâmica, só local), sobe também a porta fixa em paralelo
    if primary_port != port and not is_port_in_use(port):
        threading.Thread(target=_serve_loop, args=(port, True), daemon=True).start()

    threading.Thread(target=_https_loop, daemon=True).start()
    write_sidecar_info(primary_port)
    print(f"[BiazziTech Studio] Endpoint OpenAI:    http://localhost:{primary_port}/v1/chat/completions")
    try:
        _serve_loop(primary_port, primary_port == port)
    except KeyboardInterrupt:
        print("\n[BiazziTech Studio] Encerrado.")


if __name__ == "__main__":
    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    run_proxy(cli_port)
