#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fichas de personagem reutilizáveis entre sessões.

Cada ficha guarda nome, apelidos, a descrição visual (em inglês, pronta para prompt), notas e até
4 imagens de referência. O auxiliar de prompt usa as fichas automaticamente quando o nome (ou um
apelido) aparece no pedido ou no texto de referência, repetindo a mesma descrição em todos os
quadros — é o que mantém o personagem igual de um quadro para o outro.

Arquivos: <pasta de dados>/personagens.json e <pasta de dados>/personagens/<id>_<n>.png
"""

import base64
import json
import os
import re
import threading
import time
import unicodedata

import provider_router as router

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMG_RE = re.compile(r"^[a-z0-9_]+_\d+\.(png|jpg|webp)$")
_lock = threading.RLock()


class CharacterError(Exception):
    pass


def _file():
    return os.path.join(router.data_dir(), "personagens.json")


def image_dir():
    d = os.path.join(router.data_dir(), "personagens")
    os.makedirs(d, exist_ok=True)
    return d


def _plain(text):
    """minúsculas e sem acento (para achar 'Jose' em 'José')."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", _plain(name)).strip("_")[:30]
    return s or "personagem"


def list_characters():
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [c for c in data.get("characters", []) if isinstance(c, dict) and c.get("id")]
    except Exception:
        return []


def _save_all(items):
    path = _file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"characters": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def get(cid):
    return next((c for c in list_characters() if c["id"] == cid), None)


def _aliases(value):
    if isinstance(value, str):
        value = value.split(",")
    return [a.strip()[:40] for a in (value or []) if a and a.strip()][:8]


def _store_image(cid, data_url, n):
    m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise CharacterError("Imagem inválida (use PNG, JPG ou WEBP).")
    raw = base64.b64decode(m.group(2))
    if len(raw) > MAX_IMAGE_BYTES:
        raise CharacterError("Imagem muito grande (máx. 8 MB).")
    ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
    name = f"{cid}_{n}.{ext}"
    with open(os.path.join(image_dir(), name), "wb") as f:
        f.write(raw)
    return name


def image_path(name):
    if not name or not IMG_RE.match(name):
        return None
    p = os.path.join(image_dir(), name)
    return p if os.path.isfile(p) else None


def image_data_url(name):
    p = image_path(name)
    if not p:
        return None
    ext = os.path.splitext(p)[1].lower()
    ctype = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[ext]
    with open(p, "rb") as f:
        return f"data:{ctype};base64," + base64.b64encode(f.read()).decode("ascii")


def save_character(data):
    """Cria/atualiza uma ficha. data: id?, name, aliases, look, notes, new_images [data_url], remove_images [nome].
    Retorna a ficha salva."""
    name = (data.get("name") or "").strip()[:60]
    if not name:
        raise CharacterError("Dê um nome ao personagem.")
    look = (data.get("look") or "").strip()[:2000]
    with _lock:
        items = list_characters()
        cid = data.get("id")
        existing = next((c for c in items if c["id"] == cid), None) if cid else None
        if cid and not existing:
            raise CharacterError("Ficha não encontrada.")
        if not existing:
            base = cid = _slug(name)
            n = 2
            while any(c["id"] == cid for c in items):
                cid, n = f"{base}_{n}", n + 1
        images = list(existing.get("images", [])) if existing else []
        for rm in data.get("remove_images") or []:
            if rm in images:
                images.remove(rm)
                p = image_path(rm)
                if p:
                    os.remove(p)
        new = [u for u in (data.get("new_images") or []) if u]
        if len(images) + len(new) > MAX_IMAGES:
            raise CharacterError(f"Cada ficha guarda até {MAX_IMAGES} imagens.")
        used = {int(re.search(r"_(\d+)\.", i).group(1)) for i in images}
        for u in new:
            k = 1
            while k in used:
                k += 1
            used.add(k)
            images.append(_store_image(cid, u, k))
        entry = {
            "id": cid, "name": name, "aliases": _aliases(data.get("aliases")), "look": look,
            "notes": (data.get("notes") or "").strip()[:2000], "images": images,
            "created": existing.get("created") if existing else time.time(), "updated": time.time(),
        }
        items = [c for c in items if c["id"] != cid] + [entry]
        items.sort(key=lambda c: _plain(c["name"]))
        _save_all(items)
        return entry


def delete_character(cid):
    with _lock:
        items = list_characters()
        c = next((x for x in items if x["id"] == cid), None)
        if not c:
            raise CharacterError("Ficha não encontrada.")
        for name in c.get("images", []):
            p = image_path(name)
            if p:
                os.remove(p)
        _save_all([x for x in items if x["id"] != cid])


def detect(*texts):
    """IDs das fichas cujo nome ou apelido aparece nos textos (palavra inteira, sem ligar para acento)."""
    hay = " " + _plain(" ".join(t or "" for t in texts)) + " "
    found = []
    for c in list_characters():
        for label in [c["name"]] + c.get("aliases", []):
            lab = _plain(label).strip()
            if lab and re.search(r"(?<![a-z0-9])" + re.escape(lab) + r"(?![a-z0-9])", hay):
                found.append(c["id"])
                break
    return found


def prompt_block(chars):
    """Trecho do pedido ao auxiliar com as fichas (descrição a ser repetida palavra por palavra)."""
    if not chars:
        return ""
    lines = ["KNOWN CHARACTERS (saved character sheets). When one of them appears in a panel, use exactly this "
             "name and copy this look word for word into that panel's prompt; their reference images are attached "
             "after the user's images:"]
    for c in chars:
        alias = f" (also called: {', '.join(c['aliases'])})" if c.get("aliases") else ""
        look = c.get("look") or "(no written description: describe from the attached images)"
        lines.append(f"- {c['name']}{alias}: {look}")
        if c.get("notes"):
            lines.append(f"  notes: {c['notes']}")
    return "\n".join(lines)


def public(c):
    """Ficha para o painel (com URLs das imagens)."""
    out = dict(c)
    out["image_urls"] = [f"/api/characters/img/{n}" for n in c.get("images", [])]
    return out
