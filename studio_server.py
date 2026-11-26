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

UI_FILES = {"studio.css": "text/css; charset=utf-8", "studio.js": "application/javascript; charset=utf-8"}


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


def resolve_output_image(name) -> str:
    """Caminho de uma imagem gerada, aceitando SÓ nomes simples dentro da pasta output/imagens."""
    if not isinstance(name, str) or not IMAGE_NAME_RE.match(name):
        return None
    base = os.path.realpath(get_output_images_dir())
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


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
        if not path:
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
            self._send_json(200, {"ok": True, "message": f"Porta {port} salva. Vale na próxima vez que o servidor iniciar "
                                                         "(feche e abra o atalho, ou reinicie o Antigravity)."})
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

        if parsed_path.startswith("/ui/"):
            name = parsed_path[len("/ui/"):]
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
            img_path = resolve_output_image(urllib.parse.unquote(parsed_path[len("/imagens/"):]))
            if not img_path:
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

        if parsed_path == "/api/prompt-assist":
            if not self._guard("imagens", check_origin=True):
                return
            req = self._read_json(body)
            if not (req.get("instruction") or "").strip():
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
                ids += characters.detect(req["instruction"], req.get("text") or "")
            chars = []
            for cid in dict.fromkeys(ids):
                c = characters.get(cid)
                if c:
                    c = dict(c)
                    c["image_data"] = [u for u in (characters.image_data_url(n) for n in c.get("images", [])[:2]) if u]
                    chars.append(c)
            try:
                plan = prompt_assist.plan(req["instruction"], req.get("text") or "", images[:6],
                                          req.get("model"), req.get("generator") or "pollinations",
                                          characters=chars[:6], layout=req.get("layout") or "",
                                          layout_text=req.get("layout_text") or "", sfx_text=req.get("sfx_text") or "",
                                          sfx_mode=req.get("sfx_mode") or "overlay")
            except prompt_assist.AssistError as e:
                self._send_json(502, {"ok": False, "message": str(e)})
                return
            self._send_json(200, {"ok": True, **plan})
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
            out_path = os.path.join(get_output_images_dir(), f"{label}_{int(time.time())}{ext}")
            with open(out_path, "wb") as f:
                f.write(data)
            self._send_json(200, {"ok": True, "model": req.get("label") or "página montada", "width": "", "height": "",
                                  "saved_path": out_path, "file_name": os.path.basename(out_path),
                                  "url": "/imagens/" + urllib.parse.quote(os.path.basename(out_path)),
                                  "data_url": req["data_url"], "prompt": req.get("prompt") or ""})
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
            img_path = resolve_output_image(name)
            if not img_path:
                self._send_json(404, {"ok": False, "message": "Imagem não encontrada (já foi excluída?)"})
                return
            try:
                if parsed_path.endswith("/open"):
                    os.startfile(img_path)  # abre no visualizador padrão do Windows
                    self._send_json(200, {"ok": True, "message": "Imagem aberta."})
                else:
                    os.remove(img_path)
                    self._send_json(200, {"ok": True, "message": "Imagem excluída."})
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
        out_path = os.path.join(get_output_images_dir(), f"studio_{safe_tag}_{int(time.time())}{ext}")
        with open(out_path, "wb") as f:
            f.write(img_bytes)

        b64 = base64.b64encode(img_bytes).decode("ascii")
        self._send_json(200, {
            "model": used_model,
            "prompt": prompt,
            "provider": "pollinations",
            "settings": {"model": model, "aspect": aspect},
            "width": w,
            "height": h,
            "saved_path": out_path,
            "file_name": os.path.basename(out_path),
            "url": "/imagens/" + urllib.parse.quote(os.path.basename(out_path)),
            "data_url": f"data:{content_type};base64,{b64}",
        })

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
        out_dir = get_output_images_dir()
        remote = provider not in image_providers.GENERATORS
        label_model = ("SD local" if provider == "sdlocal" else
                       (router.PROVIDERS.get(provider, {}).get("label", provider) if remote else f"{provider}/{mode or 'padrao'}"))
        mode = mode or ("local" if provider == "sdlocal" else ("sd" if remote else ""))
        images = []
        for i, (data, ext, label) in enumerate(results):
            safe = re.sub(r"[^\w-]", "_", f"{provider}_{mode}_{label}")[:60]
            out_path = os.path.join(out_dir, f"{safe}_{stamp}_{i + 1}{ext}")
            with open(out_path, "wb") as f:
                f.write(data)
            ctype = IMAGE_TYPES.get(ext, "image/gif" if ext == ".gif" else "image/png")
            images.append({
                "model": f"{label_model} · {label}",
                "prompt": prompt,
                "provider": provider,
                "settings": {k: payload.get(k) for k in ("mode", "width", "height", "transparent", "model_id",
                                                          "model", "aspect", "loras", "fast", "strength")},
                "width": opts.get("width") or "",
                "height": opts.get("height") or "",
                "saved_path": out_path,
                "file_name": os.path.basename(out_path),
                "url": "/imagens/" + urllib.parse.quote(os.path.basename(out_path)),
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
