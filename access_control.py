#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controle de acesso do BiazziTech AI Studio: porta, acesso pela rede, usuários e senhas.

- Configuração em <pasta de dados>/config.json  -> {"port": 9090, "lan": false, "auth_local": false}
- Usuários em     <pasta de dados>/users.json   -> senhas com PBKDF2-SHA256 + salt (nunca em texto)
- Permissões: "chat", "imagens", "admin" (admin = chaves, usuários, rede, excluir arquivos)
- Sem nenhum usuário cadastrado o acesso é livre, mas SÓ neste PC: a rede exige pelo menos um usuário.
- Rede com HTTPS: coloque cert.pem e key.pem na pasta de dados (ex.: gerados com o mkcert); a rede passa
  a usar https://IP:porta+1 e a porta HTTP fica só neste PC.

Uso pela linha de comando (o instalador usa isto):
  python access_control.py show
  python access_control.py set port 9091
  python access_control.py set lan true
  python access_control.py add-user NOME [--perms chat,imagens,admin]   (senha lida do stdin)
  python access_control.py del-user NOME
  python access_control.py check-port 9091
"""

import os
import sys
import json
import time
import socket
import secrets
import hashlib
import threading

import provider_router as router

PERMISSIONS = ("chat", "imagens", "admin")
DEFAULT_PORT = 9090
RESERVED_PORTS = {8080}  # Tomcat e afins
PBKDF2_ITER = 200_000
SESSION_TTL = 7 * 24 * 3600
MAX_FAILS, FAIL_WINDOW = 5, 300  # 5 senhas erradas em 5 min bloqueiam o IP por 5 min

_lock = threading.RLock()
_sessions = {}       # token -> {"user": nome, "exp": ts}
_fails = {}          # ip -> [timestamps]


# ---------------------------------------------------------------- arquivos

def _path(name):
    return os.path.join(router.data_dir(), name)


def _read(name, default):
    try:
        with open(_path(name), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else default
    except Exception:
        return default


def _write(name, data):
    p = _path(name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------- configuração

def get_config():
    cfg = {"port": DEFAULT_PORT, "lan": False, "auth_local": False}
    cfg.update(_read("config.json", {}))
    env_port = (os.environ.get("BIAZZITECH_PORT") or "").strip()
    if env_port.isdigit():
        cfg["port"] = int(env_port)
    return cfg


def set_config(**changes):
    with _lock:
        cfg = _read("config.json", {})
        cfg.update(changes)
        _write("config.json", cfg)
        return get_config()


LAN_RISK_TEXT = (
    "Ao liberar o acesso pela rede, outras máquinas da mesma rede poderão abrir o painel e usar as chaves "
    "configuradas neste PC (com o usuário e senha que você criou). Sem HTTPS, senha e conversas trafegam sem "
    "criptografia e podem ser vistas por alguém na mesma rede. Use só em redes de confiança, nunca abra esta "
    "porta no roteador para a internet (para acesso de fora, use uma VPN como o Tailscale) e lembre que cada "
    "provedor tem termos de uso próprios. O software é fornecido sem garantias (licença AGPL-3.0)."
)


def lan_effective():
    """A rede só fica aberta de fato com a opção ligada E pelo menos um usuário com senha."""
    return bool(get_config().get("lan")) and has_users()


def https_status():
    """HTTPS da rede local: <dados>/cert.pem + key.pem (ex.: gerados com o mkcert). Porta = config ou porta+1."""
    cfg = get_config()
    d = router.data_dir()
    cert = cfg.get("https_cert") or os.path.join(d, "cert.pem")
    key = cfg.get("https_key") or os.path.join(d, "key.pem")
    port = int(cfg.get("https_port") or (int(cfg.get("port") or DEFAULT_PORT) + 1))
    return {"ready": os.path.isfile(cert) and os.path.isfile(key), "cert": cert, "key": key, "port": port,
            "folder": d}


def log_event(kind, ip, user="", detail=""):
    """Registro simples de acessos (<dados>/acessos.log), útil para ver tentativas de login."""
    try:
        p = _path("acessos.log")
        if os.path.isfile(p) and os.path.getsize(p) > 2 * 1024 * 1024:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{kind}\t{ip}\t{user}\t{detail}\n")
    except Exception:
        pass


def validate_port(port, allow_in_use=False):
    """Retorna None se a porta serve, senão a mensagem de erro."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return "Porta inválida."
    if not 1024 <= port <= 65535:
        return "Use uma porta entre 1024 e 65535."
    if port in RESERVED_PORTS:
        return f"A porta {port} costuma ser usada pelo Tomcat/outros servidores. Escolha outra."
    if not allow_in_use:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return f"A porta {port} já está em uso por outro programa."
    return None


def lan_addresses():
    """IPs desta máquina na rede local (para mostrar o endereço de acesso)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:  # IP da rota padrão (não envia nada)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


# ---------------------------------------------------------------- usuários

def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER).hex()


def _users():
    return _read("users.json", {}).get("users", {})


def _save_users(users):
    _write("users.json", {"users": users})


def has_users():
    return bool(_users())


def list_users():
    return [{"name": n, "perms": u.get("perms", []), "created": u.get("created"), "has_token": bool(u.get("token_hash"))}
            for n, u in sorted(_users().items())]


def _valid_name(name):
    return bool(name) and len(name) <= 40 and all(c.isalnum() or c in "._-" for c in name)


def add_user(name, password, perms=PERMISSIONS):
    """Cria (ou recria) um usuário. Retorna (ok, mensagem, token_api)."""
    name = (name or "").strip()
    if not _valid_name(name):
        return False, "Nome inválido (use letras, números, ponto, traço ou _; até 40).", None
    if not password or len(password) < 6:
        return False, "A senha precisa ter pelo menos 6 caracteres.", None
    perms = [p for p in perms if p in PERMISSIONS]
    if not perms:
        return False, "Escolha pelo menos uma permissão.", None
    with _lock:
        users = _users()
        if not users and "admin" not in perms:
            perms.append("admin")  # o primeiro usuário sempre pode administrar
        salt = secrets.token_bytes(16)
        token = "btk_" + secrets.token_urlsafe(24)
        users[name] = {"salt": salt.hex(), "hash": _hash(password, salt), "perms": perms, "created": time.time(),
                       "token_hash": hashlib.sha256(token.encode()).hexdigest()}
        _save_users(users)
    return True, f"Usuário '{name}' salvo.", token


def update_user(name, perms=None, password=None, new_token=False):
    with _lock:
        users = _users()
        u = users.get(name)
        if not u:
            return False, "Usuário não encontrado.", None
        if perms is not None:
            perms = [p for p in perms if p in PERMISSIONS]
            if not perms:
                return False, "Escolha pelo menos uma permissão.", None
            if "admin" not in perms and _admins(users) == [name]:
                return False, "Ele é o único administrador; crie outro admin antes.", None
            u["perms"] = perms
        if password is not None:
            if len(password) < 6:
                return False, "A senha precisa ter pelo menos 6 caracteres.", None
            salt = secrets.token_bytes(16)
            u["salt"], u["hash"] = salt.hex(), _hash(password, salt)
            _drop_sessions(name)
        token = None
        if new_token:
            token = "btk_" + secrets.token_urlsafe(24)
            u["token_hash"] = hashlib.sha256(token.encode()).hexdigest()
        _save_users(users)
    return True, "Usuário atualizado.", token


def _admins(users):
    return [n for n, u in users.items() if "admin" in u.get("perms", [])]


def delete_user(name):
    with _lock:
        users = _users()
        if name not in users:
            return False, "Usuário não encontrado."
        if _admins(users) == [name] and len(users) > 1:
            return False, "Ele é o único administrador; crie outro admin antes (ou apague os outros usuários)."
        users.pop(name)
        _save_users(users)
        _drop_sessions(name)
    return True, f"Usuário '{name}' removido." + ("" if users else " Sem usuários: o acesso voltou a ser livre.")


def _drop_sessions(name):
    for t in [t for t, s in _sessions.items() if s["user"] == name]:
        _sessions.pop(t, None)


# ---------------------------------------------------------------- login / sessão

def _blocked(ip):
    now = time.time()
    lst = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    _fails[ip] = lst
    return len(lst) >= MAX_FAILS


def login(name, password, ip):
    """Retorna (token_sessao, mensagem)."""
    with _lock:
        who = (name or "").strip()[:40]
        if _blocked(ip):
            log_event("login_bloqueado", ip, who)
            return None, "Muitas tentativas erradas. Espere alguns minutos."
        u = _users().get(who)
        if u and secrets.compare_digest(_hash(password or "", bytes.fromhex(u["salt"])), u["hash"]):
            token = secrets.token_urlsafe(32)
            _sessions[token] = {"user": who, "exp": time.time() + SESSION_TTL}
            _fails.pop(ip, None)
            log_event("login_ok", ip, who)
            return token, "ok"
        _fails.setdefault(ip, []).append(time.time())
        log_event("login_falhou", ip, who)
        return None, "Usuário ou senha incorretos."


def logout(token):
    with _lock:
        _sessions.pop(token, None)


def user_from_request(cookie_header, auth_header):
    """Usuário (dict com name/perms) pela sessão do navegador ou pelo token de API (Bearer btk_...)."""
    users = _users()
    if not users:
        return None
    token = None
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "bt_session":
            token = v
    with _lock:
        s = _sessions.get(token) if token else None
        if s and s["exp"] > time.time() and s["user"] in users:
            return {"name": s["user"], "perms": users[s["user"]].get("perms", [])}
    if auth_header and auth_header.startswith("Bearer btk_"):
        h = hashlib.sha256(auth_header[7:].strip().encode()).hexdigest()
        for n, u in users.items():
            if u.get("token_hash") and secrets.compare_digest(u["token_hash"], h):
                return {"name": n, "perms": u.get("perms", [])}
    return None


def decide(perm, is_local, user):
    """
    perm: None (público), "chat", "imagens", "admin", "local_admin" (só admin E só neste PC).
    Retorna (permitido, motivo_ou_None, precisa_login).
    """
    if perm is None:
        return True, None, False
    cfg = get_config()
    users_exist = has_users()
    local_free = is_local and not cfg.get("auth_local")
    if not users_exist:
        if not is_local:
            return False, "Acesso pela rede exige usuário e senha: cadastre um usuário no PC do servidor.", False
        return True, None, False
    if local_free:
        return True, None, False
    if not user:
        return False, "Faça login.", True
    if perm == "local_admin":
        if not is_local:
            return False, "Só pode ser feito no próprio PC do servidor.", False
        perm = "admin"
    if perm in user["perms"] or "admin" in user["perms"]:
        return True, None, False
    return False, f"Seu usuário não tem permissão de '{perm}'.", False


# ---------------------------------------------------------------- linha de comando

def _cli(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "show":
        cfg = get_config()
        print(json.dumps({"config": cfg, "users": list_users(), "lan_ips": lan_addresses(), "https": https_status(),
                          "lan_active": lan_effective()}, ensure_ascii=False, indent=1))
    elif cmd == "set" and len(argv) >= 3:
        key, val = argv[1], argv[2]
        if key == "port":
            err = validate_port(val, allow_in_use="--allow-in-use" in argv)
            if err:
                print("ERRO: " + err)
                return 2
            set_config(port=int(val))
        elif key in ("lan", "auth_local"):
            on = val.lower() in ("1", "true", "sim", "yes", "on")
            if key == "lan" and on and not has_users():
                print("ERRO: crie um usuário administrador antes de liberar o acesso pela rede.")
                return 2
            changes = {key: on}
            if key == "lan" and on:
                changes["lan_risk_accepted"] = time.strftime("%Y-%m-%d %H:%M:%S")
            set_config(**changes)
        else:
            print("Chave desconhecida.")
            return 2
        print("ok")
    elif cmd == "check-port" and len(argv) >= 2:
        err = validate_port(argv[1], allow_in_use="--allow-in-use" in argv)
        print("ok" if not err else "ERRO: " + err)
        return 0 if not err else 2
    elif cmd == "add-user" and len(argv) >= 2:
        perms = list(PERMISSIONS)
        if "--perms" in argv:
            perms = argv[argv.index("--perms") + 1].split(",")
        password = sys.stdin.readline().rstrip("\r\n")
        ok, msg, token = add_user(argv[1], password, perms)
        print(msg if ok else "ERRO: " + msg)
        if ok:
            print("TOKEN_API=" + token)
        return 0 if ok else 2
    elif cmd == "del-user" and len(argv) >= 2:
        ok, msg = delete_user(argv[1])
        print(msg if ok else "ERRO: " + msg)
        return 0 if ok else 2
    else:
        print("Comando inválido. Use: python access_control.py help")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
