#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exporta spritesheets e tilesets da galeria direto para o formato do Godot 4.

- Animação: gera <nome>.png + <nome>.tres (SpriteFrames, com uma AtlasTexture por quadro) já com as
  animações nomeadas (idle, andar, atacar...), velocidade (fps) e repetição (loop).
- Tileset: gera <nome>.png + <nome>_tileset.tres (TileSet com TileSetAtlasSource), criando um tile por
  célula que tenha algum pixel visível.
- Tudo vai para <imagens>/godot/<nome>_<hora>/ e num .zip para baixar. No Godot, basta copiar a pasta
  para o caminho escolhido (ex.: res://assets/heroi/) — os .tres já apontam para esse caminho.

Só biblioteca padrão: o PNG é lido aqui mesmo (para saber o tamanho e achar quadros vazios).
"""

import os
import re
import shutil
import struct
import time
import unicodedata
import zipfile
import zlib


class ExportError(Exception):
    pass


# ---------------------------------------------------------------- PNG

def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ExportError("Use uma imagem PNG (spritesheets precisam de PNG para manter a transparência).")
    return struct.unpack(">II", head[16:24])


def _png_alpha(path):
    """Matriz de 'pixel visível?' (lista de bytearrays, 1 = visível). None se o formato não for suportado."""
    with open(path, "rb") as f:
        data = f.read()
    pos, idat, ihdr, trns = 8, [], None, None
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"tRNS":
            trns = chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    w, h, depth, ctype, _, _, interlace = ihdr
    if depth != 8 or interlace or ctype not in (0, 2, 3, 4, 6):
        return None
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + b) & 255
            elif ft == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif ft == 4:
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    vis = []
    for line in rows:
        if ctype == 6:
            vis.append(bytearray(1 if line[k * 4 + 3] > 8 else 0 for k in range(w)))
        elif ctype == 4:
            vis.append(bytearray(1 if line[k * 2 + 1] > 8 else 0 for k in range(w)))
        elif ctype == 3 and trns:
            vis.append(bytearray(0 if (line[k] < len(trns) and trns[line[k]] <= 8) else 1 for k in range(w)))
        else:
            vis.append(bytearray(b"\x01" * w))  # sem canal alfa: tudo visível
    return vis


def _cell_visible(vis, x0, y0, w, h):
    if vis is None:
        return True
    for y in range(y0, min(y0 + h, len(vis))):
        if any(vis[y][x0:x0 + w]):
            return True
    return False


# ---------------------------------------------------------------- .tres

def _safe_name(name, default="sprite"):
    plain = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9_]+", "_", plain.lower()).strip("_")[:40]
    return s or default


def _res_path(prefix, filename):
    prefix = (prefix or "res://").strip().replace("\\", "/")
    if not prefix.startswith("res://"):
        prefix = "res://" + prefix.lstrip("/")
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix + filename


def spriteframes_tres(tex_path, frame_w, frame_h, cols, animations):
    """animations: [{"name", "frames": [índices], "fps", "loop"}]"""
    used = sorted({i for a in animations for i in a["frames"]})
    sub = {i: f"AtlasTexture_{i}" for i in used}
    out = [f'[gd_resource type="SpriteFrames" load_steps={len(used) + 2} format=3]', "",
           f'[ext_resource type="Texture2D" path="{tex_path}" id="1_tex"]', ""]
    for i in used:
        x, y = (i % cols) * frame_w, (i // cols) * frame_h
        out += [f'[sub_resource type="AtlasTexture" id="{sub[i]}"]', 'atlas = ExtResource("1_tex")',
                f"region = Rect2({x}, {y}, {frame_w}, {frame_h})", ""]
    anims = []
    for a in animations:
        frames = ",\n".join('{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % sub[i] for i in a["frames"])
        anims.append('{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
                     % (frames, "true" if a["loop"] else "false", a["name"], float(a["fps"])))
    out += ["[resource]", "animations = [" + ", ".join(anims) + "]", ""]
    return "\n".join(out)


def tileset_tres(tex_path, tile_w, tile_h, cells, margin=0, separation=0):
    out = ['[gd_resource type="TileSet" load_steps=3 format=3]', "",
           f'[ext_resource type="Texture2D" path="{tex_path}" id="1_tex"]', "",
           '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]', 'texture = ExtResource("1_tex")']
    if margin:
        out.append(f"margins = Vector2i({margin}, {margin})")
    if separation:
        out.append(f"separation = Vector2i({separation}, {separation})")
    out.append(f"texture_region_size = Vector2i({tile_w}, {tile_h})")
    out += [f"{cx}:{cy}/0 = 0" for cx, cy in cells]
    out += ["", "[resource]", f"tile_size = Vector2i({tile_w}, {tile_h})",
            'sources/0 = SubResource("TileSetAtlasSource_1")', ""]
    return "\n".join(out)


# ---------------------------------------------------------------- exportação

def _int(v, name, lo=1, hi=4096):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ExportError(f"{name} inválido.")
    if not lo <= v <= hi:
        raise ExportError(f"{name} fora do limite ({lo} a {hi}).")
    return v


def _parse_animations(items, cols, rows, visible):
    total = cols * rows
    anims = []
    for a in items or []:
        name = _safe_name(a.get("name"), "default")
        if a.get("frames"):
            frames = [int(i) for i in a["frames"] if 0 <= int(i) < total]
        else:
            row = int(a.get("row") or 0)
            start = int(a.get("start") or 0)
            count = int(a.get("count") or 0) or cols
            if not 0 <= row < rows:
                raise ExportError(f"Animação '{name}': a linha {row + 1} não existe (a folha tem {rows}).")
            frames = [row * cols + c for c in range(start, min(start + count, cols))]
        frames = [i for i in frames if i in visible] or frames
        if not frames:
            raise ExportError(f"Animação '{name}' sem quadros.")
        try:
            fps = max(0.1, min(120.0, float(a.get("fps") or 8)))
        except (TypeError, ValueError):
            fps = 8.0
        anims.append({"name": name, "frames": frames, "fps": fps, "loop": a.get("loop", True) is not False})
    if not anims:  # padrão: uma animação por linha que tenha quadros
        for r in range(rows):
            frames = [i for i in range(r * cols, (r + 1) * cols) if i in visible]
            if frames:
                anims.append({"name": "default" if rows == 1 else f"linha_{r + 1}", "frames": frames, "fps": 8.0,
                              "loop": True})
    names = [a["name"] for a in anims]
    if len(set(names)) != len(names):
        raise ExportError("Há animações com o mesmo nome.")
    return anims


def export(req, images_dir, resolver):
    """req: image, kind ('spriteframes' | 'tileset'), frame_w, frame_h, name, res_path, animations, margin, separation."""
    src = resolver(req.get("image") or "")
    if not src:
        raise ExportError("Imagem não encontrada na galeria.")
    w, h = png_size(src)
    kind = req.get("kind") or "spriteframes"
    fw = _int(req.get("frame_w"), "Largura do quadro")
    fh = _int(req.get("frame_h"), "Altura do quadro")
    margin = _int(req.get("margin") or 0, "Margem", 0, 512) if kind == "tileset" else 0
    sep = _int(req.get("separation") or 0, "Espaçamento", 0, 512) if kind == "tileset" else 0
    cols = (w - 2 * margin + sep) // (fw + sep)
    rows = (h - 2 * margin + sep) // (fh + sep)
    if cols < 1 or rows < 1:
        raise ExportError(f"O quadro ({fw}x{fh}) é maior que a imagem ({w}x{h}).")
    name = _safe_name(req.get("name") or os.path.splitext(os.path.basename(src))[0])
    folder_res = req.get("res_path") or f"res://assets/{name}/"
    tex_res = _res_path(folder_res, name + ".png")

    vis = None
    try:
        vis = _png_alpha(src)
    except Exception:
        vis = None
    cells = []
    for cy in range(rows):
        for cx in range(cols):
            x0, y0 = margin + cx * (fw + sep), margin + cy * (fh + sep)
            if _cell_visible(vis, x0, y0, fw, fh):
                cells.append((cx, cy))
    visible = {cy * cols + cx for cx, cy in cells}

    out_dir = os.path.join(images_dir, "godot", f"{name}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    shutil.copyfile(src, os.path.join(out_dir, name + ".png"))
    files = [name + ".png"]
    info = {"columns": cols, "rows": rows, "image_size": [w, h]}
    if kind == "tileset":
        tres = name + "_tileset.tres"
        with open(os.path.join(out_dir, tres), "w", encoding="utf-8", newline="\n") as f:
            f.write(tileset_tres(tex_res, fw, fh, cells, margin, sep))
        info["tiles"] = len(cells)
        how = (f"No Godot: copie esta pasta para {folder_res}. Num TileMapLayer, em Tile Set escolha Carregar e "
               f"selecione {tres}. Os {len(cells)} tiles ({fw}x{fh}) já estão criados.")
    else:
        anims = _parse_animations(req.get("animations"), cols, rows, visible)
        tres = name + ".tres"
        with open(os.path.join(out_dir, tres), "w", encoding="utf-8", newline="\n") as f:
            f.write(spriteframes_tres(tex_res, fw, fh, cols, anims))
        info["animations"] = [{"name": a["name"], "frames": len(a["frames"]), "fps": a["fps"], "loop": a["loop"]}
                              for a in anims]
        how = (f"No Godot: copie esta pasta para {folder_res}. Num AnimatedSprite2D, em Sprite Frames escolha "
               f"Carregar e selecione {tres}. Animações: " + ", ".join(a["name"] for a in anims) + ".")
    files.append(tres)
    with open(os.path.join(out_dir, "LEIA-ME.txt"), "w", encoding="utf-8") as f:
        f.write(how + "\n\nSe colocar a pasta em outro caminho, abra o .tres num editor de texto e troque o "
                f"caminho {tex_res} pelo novo (ou exporte de novo com o caminho certo).\n")
    files.append("LEIA-ME.txt")
    zip_name = os.path.basename(out_dir) + ".zip"
    with zipfile.ZipFile(os.path.join(images_dir, "godot", zip_name), "w", zipfile.ZIP_DEFLATED) as z:
        for fn in files:
            z.write(os.path.join(out_dir, fn), f"{name}/{fn}")
    return {"folder": out_dir, "zip": zip_name, "files": files, "how": how, "texture_path": tex_res, **info}


def zip_path(name, images_dir):
    if not re.match(r"^[a-z0-9_]+_\d{8}_\d{6}\.zip$", name or ""):
        return None
    p = os.path.join(images_dir, "godot", name)
    return p if os.path.isfile(p) else None
