#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera o pacote .deb do BiazziTech AI Studio (Debian, Ubuntu, Mint, Pop!_OS...) só com a biblioteca padrão:
roda no Windows, no Linux ou no Mac, sem dpkg-deb.

    python build_deb.py                 # versão padrão
    python build_deb.py --versao 1.3.0  # saída: dist/biazzitech-ai-studio_1.3.0_all.deb

No Linux:  sudo apt install ./biazzitech-ai-studio_1.3.0_all.deb   (o apt resolve o python3)
Abrir:     menu de aplicativos → BiazziTech AI Studio, ou no terminal:  biazzitech-studio
Remover:   sudo apt remove biazzitech-ai-studio   (seus dados em ~/.biazzitech e ~/.env ficam)

Um .deb é um arquivo 'ar' com três membros: debian-binary, control.tar.gz e data.tar.gz.
"""

import argparse
import gzip
import hashlib
import io
import os
import tarfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = "biazzitech-ai-studio"
APP_DIR = "usr/lib/" + PKG
# só o que roda no Linux: os instaladores .ps1/.bat, o gerador do .exe e os testes ficam de fora
SKIP_PY = {"build_deb.py"}

LAUNCHER = """#!/bin/sh
# BiazziTech AI Studio: sobe o servidor do painel (se ainda não estiver rodando) e abre o navegador.
# Opções: --port 9191  --no-browser
exec python3 /usr/lib/biazzitech-ai-studio/biazzitech_studio.py "$@"
"""

MCP = """#!/bin/sh
# Servidor MCP do BiazziTech AI Studio (para editores/agentes que falam MCP por stdio)
exec python3 /usr/lib/biazzitech-ai-studio/studio_mcp.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=BiazziTech AI Studio
GenericName=Estúdio de IA
Comment=Chat com memória, busca na web, imagens, quadrinhos e Godot com vários provedores de IA
Exec=biazzitech-studio
Icon=biazzitech-ai-studio
Terminal=false
Categories=Development;Graphics;Utility;
Keywords=IA;AI;chat;Godot;pixel art;quadrinhos;
StartupNotify=false
"""

COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: BiazziTech AI Studio
Source: https://github.com/faustobiazzi/biazzitech-ai-studio

Files: *
Copyright: BiazziTech
License: AGPL-3.0-or-later
 Veja /usr/share/doc/biazzitech-ai-studio/LICENSE (licença completa) e o README do projeto.
 Licença comercial disponível: veja CONTRIBUTING.md no repositório.
"""

POSTINST = """#!/bin/sh
set -e
# atualiza o menu e o cache de ícones, se as ferramentas existirem
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
"""


def _files():
    """(caminho no pacote, caminho de origem, executável?) de tudo que vai instalado."""
    out = []
    for name in sorted(os.listdir(ROOT)):
        if name.endswith(".py") and name not in SKIP_PY:
            out.append((f"{APP_DIR}/{name}", os.path.join(ROOT, name), False))
    out.append((f"{APP_DIR}/studio_ui.html", os.path.join(ROOT, "studio_ui.html"), False))
    for name in sorted(os.listdir(os.path.join(ROOT, "ui"))):
        p = os.path.join(ROOT, "ui", name)
        if os.path.isfile(p):
            out.append((f"{APP_DIR}/ui/{name}", p, False))
    for size in ("192", "512"):
        out.append((f"usr/share/icons/hicolor/{size}x{size}/apps/{PKG}.png", os.path.join(ROOT, "ui", f"icon-{size}.png"), False))
    out.append((f"usr/share/doc/{PKG}/LICENSE", os.path.join(ROOT, "LICENSE"), False))
    out.append((f"usr/share/doc/{PKG}/README.md", os.path.join(ROOT, "README.md"), False))
    return out


def _tar_gz(entries, mtime):
    """entries: [(nome, bytes, modo)] — diretórios são criados a partir dos caminhos."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        dirs = set()
        for name, _, _ in entries:
            parts = name.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        for d in sorted(dirs):
            ti = tarfile.TarInfo("./" + d)
            ti.type, ti.mode, ti.mtime, ti.uname, ti.gname = tarfile.DIRTYPE, 0o755, mtime, "root", "root"
            tar.addfile(ti)
        for name, data, mode in entries:
            ti = tarfile.TarInfo("./" + name)
            ti.size, ti.mode, ti.mtime, ti.uname, ti.gname = len(data), mode, mtime, "root", "root"
            tar.addfile(ti, io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=mtime) as g:
        g.write(raw.getvalue())
    return gz.getvalue()


def _ar(members, mtime):
    """Formato ar do Unix (o que o dpkg lê): cabeçalho fixo de 60 bytes por membro, alinhado em 2 bytes."""
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        header = (f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n").encode("ascii")
        assert len(header) == 60
        out.write(header)
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def build(version, out_dir):
    mtime = int(time.time())
    data_entries = []
    for dest, src, _ in _files():
        with open(src, "rb") as f:
            content = f.read()
        if dest.endswith(".py"):
            content = content.replace(b"\r\n", b"\n")  # finais de linha do Linux
        data_entries.append((dest, content, 0o644))
    data_entries += [
        ("usr/bin/biazzitech-studio", LAUNCHER.encode(), 0o755),
        ("usr/bin/biazzitech-studio-mcp", MCP.encode(), 0o755),
        (f"usr/share/applications/{PKG}.desktop", DESKTOP.encode(), 0o644),
        (f"usr/share/doc/{PKG}/copyright", COPYRIGHT.encode(), 0o644),
    ]
    installed_kb = sum(len(d) for _, d, _ in data_entries) // 1024 + 1
    md5sums = "".join(f"{hashlib.md5(d).hexdigest()}  {n}\n" for n, d, _ in data_entries)
    control = (
        f"Package: {PKG}\n"
        f"Version: {version}\n"
        "Section: devel\n"
        "Priority: optional\n"
        "Architecture: all\n"
        "Depends: python3 (>= 3.8)\n"
        "Recommends: python3-pypdf\n"
        "Suggests: ollama\n"
        f"Installed-Size: {installed_kb}\n"
        "Maintainer: BiazziTech <noreply@users.noreply.github.com>\n"
        "Homepage: https://github.com/faustobiazzi/biazzitech-ai-studio\n"
        "Description: estúdio de IA para jogos e histórias, com rodízio de provedores\n"
        " Chat com memória (Godot/GDScript, Lua, Python, C#, lore), busca na web com\n"
        " fontes, lugares perto, imagens e pixel art, páginas de quadrinho, fichas de\n"
        " personagem e exportação para o Godot 4, alternando entre provedores de IA\n"
        " gratuitos primeiro. Painel no navegador, proxy compatível com OpenAI e\n"
        " servidor MCP. Só usa a biblioteca padrão do Python.\n"
    )
    control_tar = _tar_gz([("control", control.encode(), 0o644), ("md5sums", md5sums.encode(), 0o644),
                           ("postinst", POSTINST.encode(), 0o755)], mtime)
    data_tar = _tar_gz(data_entries, mtime)
    deb = _ar([("debian-binary", b"2.0\n"), ("control.tar.gz", control_tar), ("data.tar.gz", data_tar)], mtime)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{PKG}_{version}_all.deb")
    with open(path, "wb") as f:
        f.write(deb)
    return path, len(data_entries)


def main():
    ap = argparse.ArgumentParser(description="Gera o .deb do BiazziTech AI Studio")
    ap.add_argument("--versao", default="1.3.0")
    ap.add_argument("--saida", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()
    path, n = build(args.versao, args.saida)
    print(f"Pronto: {path} ({os.path.getsize(path) // 1024} KB, {n} arquivos)")
    print(f"No Linux: sudo apt install ./{os.path.basename(path)}  -  depois: menu de aplicativos ou 'biazzitech-studio'")


if __name__ == "__main__":
    main()
