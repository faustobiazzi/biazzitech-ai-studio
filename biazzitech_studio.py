#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BiazziTech AI Studio — lançador stand-alone (não precisa do Antigravity).

- Sobe o servidor local (painel + proxy OpenAI) em http://localhost:9090 e abre o navegador.
- Se o servidor já estiver rodando (ex.: Sidecar do Antigravity), só abre o navegador.
- Funciona como script (python biazzitech_studio.py) ou empacotado em .exe (PyInstaller).

Opções:
  --port N        porta (padrão 9090)
  --no-browser    não abre o navegador (útil para iniciar junto com o Windows)
"""

import os
import sys
import json
import time
import argparse
import threading
import webbrowser
import urllib.request

APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)


def server_ok(port, timeout=1.5):
    """True se já há um BiazziTech AI Studio respondendo nessa porta."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:
        return False


def port_busy(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_when_ready(port, url):
    for _ in range(40):
        if server_ok(port, 0.5):
            webbrowser.open(url)
            return
        time.sleep(0.25)


def main():
    ap = argparse.ArgumentParser(description="BiazziTech AI Studio (stand-alone)")
    ap.add_argument("--port", type=int, default=None, help="padrão: a porta escolhida na instalação (config.json)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if not args.port:
        import access_control
        args.port = int(access_control.get_config().get("port") or 9090)
    url = f"http://localhost:{args.port}"

    if server_ok(args.port):
        print(f"[BiazziTech] Já está rodando em {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if port_busy(args.port):
        print(f"[BiazziTech] A porta {args.port} está ocupada por outro programa. Use --port OUTRA_PORTA.")
        return 1

    # Em modo stand-alone não há Sidecar: garante que o servidor use a porta pedida
    os.environ.pop("ANTIGRAVITY_SIDECAR_WEB_PORT", None)
    import studio_server

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(args.port, url), daemon=True).start()
    print(f"[BiazziTech] Painel em {url}  (feche esta janela para desligar)")
    studio_server.run_proxy(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
