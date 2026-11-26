#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelos de página de quadrinho (prontos + personalizados a partir de desenho P&B).

Cada modelo é descrito por polígonos em pixels numa página retrato de 1600 x 2400 (2:3).
Além dos 20 modelos prontos (grades, faixas, dinâmicos e mistos), o usuário pode importar uma
imagem em preto e branco (ex.: desenhada no Paint com linhas pretas no fundo branco, ou blocos
pretos) — o módulo fecha pequenas frestas, acha os quadros, simplifica os polígonos e salva em
<pasta de dados>/custom_layouts.json.
"""

import base64
import json
import math
import os
import re
import struct
import threading
import unicodedata
import zlib
from collections import deque

import provider_router as router

PAGE_W, PAGE_H = 1600, 2400
MARGIN, GUTTER = 48, 28
ASPECTS = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}
MAX_PANELS = 16
_lock = threading.RLock()


class LayoutError(Exception):
    pass


def _row(top, bottom, cuts):
    """top/bottom: (y_esquerda, y_direita) em 0..1; cuts: lista de (x_no_topo, x_na_base) em 0..1."""
    return {"top": top, "bottom": bottom, "cuts": cuts}


def _flat(y):
    return (y, y)


# Cada modelo: nome, descrição (para o auxiliar, em inglês) e faixas.
_DEFS = [
    ("grade_4", "Grade 2x2 (4 quadros iguais)", "four equal panels in a 2x2 grid",
     [_row(_flat(0), _flat(.5), [(.5, .5)]), _row(_flat(.5), _flat(1), [(.5, .5)])]),
    ("grade_6", "Grade 2x3 (6 quadros iguais)", "six equal panels, 2 columns x 3 rows",
     [_row(_flat(0), _flat(1 / 3), [(.5, .5)]), _row(_flat(1 / 3), _flat(2 / 3), [(.5, .5)]),
      _row(_flat(2 / 3), _flat(1), [(.5, .5)])]),
    ("faixas_3", "3 faixas largas", "three wide horizontal strips (cinematic)",
     [_row(_flat(0), _flat(1 / 3), []), _row(_flat(1 / 3), _flat(2 / 3), []), _row(_flat(2 / 3), _flat(1), [])]),
    ("colunas_3", "3 colunas altas", "three tall vertical panels side by side",
     [_row(_flat(0), _flat(1), [(1 / 3, 1 / 3), (2 / 3, 2 / 3)])]),
    ("destaque_topo_3", "Destaque no topo + 2 embaixo", "one large establishing panel on top, two panels below",
     [_row(_flat(0), _flat(.58), []), _row(_flat(.58), _flat(1), [(.5, .5)])]),
    ("destaque_base_3", "2 em cima + destaque embaixo", "two panels on top, one large climax panel at the bottom",
     [_row(_flat(0), _flat(.42), [(.5, .5)]), _row(_flat(.42), _flat(1), [])]),
    ("classico_5", "Clássico de 5 quadros", "five panels: wide top, two in the middle, two at the bottom",
     [_row(_flat(0), _flat(.34), []), _row(_flat(.34), _flat(.67), [(.45, .45)]),
      _row(_flat(.67), _flat(1), [(.6, .6)])]),
    ("classico_6", "Clássico de 6 quadros (3 linhas variadas)", "six panels in three rows with different widths",
     [_row(_flat(0), _flat(.33), [(.62, .62)]), _row(_flat(.33), _flat(.66), [(.38, .38)]),
      _row(_flat(.66), _flat(1), [(.5, .5)])]),
    ("dinamico_2_dir", "Dinâmico: 2 quadros, corte descendo para a direita",
     "two panels split by one strong diagonal sloping down to the right",
     [_row(_flat(0), (.38, .62), []), _row((.38, .62), _flat(1), [])]),
    ("dinamico_2_esq", "Dinâmico: 2 quadros, corte descendo para a esquerda",
     "two panels split by one strong diagonal sloping down to the left",
     [_row(_flat(0), (.62, .38), []), _row((.62, .38), _flat(1), [])]),
    ("dinamico_3", "Dinâmico: 3 faixas inclinadas para a direita", "three panels separated by strong diagonal borders (action)",
     [_row((0, 0), (.24, .40), []), _row((.24, .40), (.62, .78), []), _row((.62, .78), (1, 1), [])]),
    ("dinamico_3_esq", "Dinâmico: 3 faixas inclinadas para a esquerda",
     "three panels separated by diagonal borders sloping down to the left",
     [_row((0, 0), (.40, .24), []), _row((.40, .24), (.78, .62), []), _row((.78, .62), (1, 1), [])]),
    ("dinamico_3_zigue", "Dinâmico: 3 faixas em zigue-zague", "three panels with alternating diagonal borders (zig-zag)",
     [_row((0, 0), (.26, .40), []), _row((.26, .40), (.74, .60), []), _row((.74, .60), (1, 1), [])]),
    ("misto_4", "Misto: destaque dinâmico + 3 retos", "one large dynamic panel with a slanted bottom on top, three regular panels below",
     [_row(_flat(0), (.54, .64), []), _row((.54, .64), _flat(1), [(1 / 3, 1 / 3), (2 / 3, 2 / 3)])]),
    ("misto_5", "Misto: 2 retos + destaque dinâmico + 2 inclinados",
     "two regular panels on top, a large dynamic impact panel in the middle, two slanted panels at the bottom",
     [_row(_flat(0), _flat(.24), [(.5, .5)]), _row(_flat(.24), (.66, .74), []),
      _row((.66, .74), _flat(1), [(.44, .56)])]),
    ("misto_6", "Misto: 2 retos + 2 dinâmicos grandes + 2 retos",
     "two regular panels on top, two large panels split by a diagonal in the middle, two regular panels at the bottom",
     [_row(_flat(0), _flat(.22), [(.5, .5)]), _row(_flat(.22), _flat(.78), [(.62, .38)]),
      _row(_flat(.78), _flat(1), [(.5, .5)])]),
    ("dinamico_4", "Dinâmico: 4 quadros com cortes inclinados", "four panels with slanted borders (dynamic action page)",
     [_row(_flat(0), (.44, .52), [(.58, .50)]), _row((.44, .52), _flat(1), [(.40, .50)])]),
    ("dinamico_5", "Dinâmico: 5 quadros (impacto no centro)",
     "five panels with diagonal cuts; the middle row holds the impact moment",
     [_row(_flat(0), (.26, .32), [(.55, .47)]), _row((.26, .32), (.70, .64), []),
      _row((.70, .64), _flat(1), [(.42, .52)])]),
    ("dinamico_6", "Dinâmico: 6 quadros em zigue-zague", "six panels with zig-zag slanted borders",
     [_row(_flat(0), (.30, .36), [(.56, .48)]), _row((.30, .36), (.68, .62), [(.44, .54)]),
      _row((.68, .62), _flat(1), [(.58, .48)])]),
    ("pagina_inteira", "Página inteira (splash)", "a single full-page splash panel",
     [_row(_flat(0), _flat(1), [])]),
]


def _lerp(a, b, t):
    return a + (b - a) * t


def _polygons(rows):
    iw, ih = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    g = GUTTER / 2

    def X(fx):
        return MARGIN + fx * iw

    def Y(fy):
        return MARGIN + fy * ih

    polys = []
    for r in rows:
        (tl, tr), (bl, br) = r["top"], r["bottom"]
        # deslocamento do respiro (gutter): só nas bordas internas
        dt = 0 if (tl == 0 and tr == 0) else g
        db = 0 if (bl == 1 and br == 1) else g
        xs = [(0.0, 0.0)] + list(r["cuts"]) + [(1.0, 1.0)]
        for i in range(len(xs) - 1):
            (lt, lb), (rt, rb) = xs[i], xs[i + 1]
            dl = 0 if i == 0 else g
            dr = 0 if i == len(xs) - 2 else g

            def top_y(fx):
                return Y(_lerp(tl, tr, fx)) + dt

            def bot_y(fx):
                return Y(_lerp(bl, br, fx)) - db
            pts = [(X(lt) + dl, top_y(lt)), (X(rt) - dr, top_y(rt)), (X(rb) - dr, bot_y(rb)), (X(lb) + dl, bot_y(lb))]
            polys.append([[round(x), round(y)] for x, y in pts])
    return polys


def _aspect_of(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    ratio = (max(xs) - min(xs)) / max(1, (max(ys) - min(ys)))
    return min(ASPECTS, key=lambda k: abs(ASPECTS[k] - ratio) / ASPECTS[k])


# ---------------------------------------------------------------- personalizados (Paint P&B)

def _custom_file():
    return os.path.join(router.data_dir(), "custom_layouts.json")


def _slug(name):
    plain = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")[:28]
    return s or "modelo"


def list_custom():
    try:
        with open(_custom_file(), "r", encoding="utf-8") as f:
            items = json.load(f).get("layouts", [])
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("id") and isinstance(it.get("panels"), list) and it["panels"]:
                it = dict(it)
                it["custom"] = True
                it["count"] = len(it["panels"])
                out.append(it)
        return out
    except Exception:
        return []


def _save_custom(items):
    path = _custom_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"layouts": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def delete_custom(lid):
    with _lock:
        items = list_custom()
        kept = [it for it in items if it["id"] != lid]
        if len(kept) == len(items):
            raise LayoutError("Modelo personalizado não encontrado.")
        _save_custom(kept)


def _png_luma(data):
    """Lê PNG (1/2/4/8 bits, cinza/RGB/paleta/RGBA) e devolve (w, h, linhas de luminância 0..255 sobre branco)."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LayoutError("Envie uma imagem PNG válida (no painel, BMP/JPG/WEBP são convertidos automaticamente).")
    pos, idat, ihdr, plte, trns = 8, [], None, None, None
    while pos + 8 <= len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"PLTE":
            plte = chunk
        elif typ == b"tRNS":
            trns = chunk
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if not ihdr or not idat:
        raise LayoutError("PNG incompleto ou corrompido.")
    w, h, depth, ctype, comp, filt, interlace = ihdr
    if w < 16 or h < 16 or w > 8000 or h > 8000:
        raise LayoutError("Dimensões da imagem fora do suportado (16 a 8000 px).")
    if interlace or comp or filt or depth not in (1, 2, 4, 8) or ctype not in (0, 2, 3, 4, 6):
        raise LayoutError("Formato PNG não suportado diretamente; abra pelo botão '+ Modelo P&B' do painel.")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = depth * channels
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    try:
        raw = zlib.decompress(b"".join(idat))
    except Exception:
        raise LayoutError("Não foi possível descomprimir o PNG.")
    if len(raw) < h * (1 + stride):
        raise LayoutError("Dados de imagem truncados.")

    rows, prev, idx = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[idx]
        line = bytearray(raw[idx + 1:idx + 1 + stride])
        idx += 1 + stride
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

    def unpack_samples(line):
        if depth == 8:
            return line
        out = bytearray()
        mask = (1 << depth) - 1
        per_byte = 8 // depth
        for byte in line:
            for s in range(per_byte - 1, -1, -1):
                out.append((byte >> (s * depth)) & mask)
        return out[:w * channels]

    max_val = (1 << depth) - 1
    luma_rows = []
    for line in rows:
        s = unpack_samples(line)
        row = bytearray(w)
        if ctype == 0:
            scale = 255 // max_val
            for x in range(w):
                v = s[x] * scale
                if trns and len(trns) >= 2 and s[x] == ((trns[0] << 8) | trns[1]):
                    v = 255
                row[x] = v
        elif ctype == 4:
            for x in range(w):
                v, a = s[2 * x], s[2 * x + 1]
                row[x] = (v * a + 255 * (255 - a)) // 255
        elif ctype == 2:
            for x in range(w):
                r, g, b = s[3 * x], s[3 * x + 1], s[3 * x + 2]
                row[x] = (77 * r + 150 * g + 29 * b) >> 8
        elif ctype == 6:
            for x in range(w):
                r, g, b, a = s[4 * x], s[4 * x + 1], s[4 * x + 2], s[4 * x + 3]
                lum = (77 * r + 150 * g + 29 * b) >> 8
                row[x] = (lum * a + 255 * (255 - a)) // 255
        elif ctype == 3:
            if not plte:
                raise LayoutError("PNG indexado sem paleta.")
            pal = []
            for k in range(0, len(plte), 3):
                idx_p = k // 3
                r, g, b = plte[k], plte[k + 1], plte[k + 2]
                a = trns[idx_p] if trns and idx_p < len(trns) else 255
                lum = (77 * r + 150 * g + 29 * b) >> 8
                pal.append((lum * a + 255 * (255 - a)) // 255)
            for x in range(w):
                row[x] = pal[s[x]] if s[x] < len(pal) else 255
        luma_rows.append(row)
    return w, h, luma_rows


def _normalize_grid(w, h, luma_rows):
    """Normaliza a grade para ~240..360 px no maior lado (min-pooling preserva linhas finas de 1 px)."""
    m = max(w, h)
    if m > 360:
        gw = max(32, round(w * 360 / m))
        gh = max(32, round(h * 360 / m))
        dark = []
        for gy in range(gh):
            y0, y1 = (gy * h) // gh, max((gy * h) // gh + 1, ((gy + 1) * h) // gh)
            row = bytearray(gw)
            for gx in range(gw):
                x0, x1 = (gx * w) // gw, max((gx * w) // gw + 1, ((gx + 1) * w) // gw)
                mn = 255
                for yy in range(y0, y1):
                    seg = luma_rows[yy][x0:x1]
                    if seg:
                        v = min(seg)
                        if v < mn:
                            mn = v
                row[gx] = 1 if mn < 165 else 0
            dark.append(row)
        return gw, gh, dark
    if m < 240:
        gw = max(32, round(w * 240 / m))
        gh = max(32, round(h * 240 / m))
        dark = [bytearray(1 if luma_rows[(gy * h) // gh][(gx * w) // gw] < 165 else 0 for gx in range(gw))
                for gy in range(gh)]
        return gw, gh, dark
    return w, h, [bytearray(1 if v < 165 else 0 for v in r) for r in luma_rows]


def _dilate(grid, w, h, r):
    if r <= 0:
        return [bytearray(row) for row in grid]
    horiz = [bytearray(w) for _ in range(h)]
    for y in range(h):
        row = grid[y]
        out = horiz[y]
        acc = sum(row[:min(w, r + 1)])
        for x in range(w):
            if acc > 0:
                out[x] = 1
            if x + r + 1 < w:
                acc += row[x + r + 1]
            if x - r >= 0:
                acc -= row[x - r]
    res = [bytearray(w) for _ in range(h)]
    for x in range(w):
        acc = sum(horiz[y][x] for y in range(min(h, r + 1)))
        for y in range(h):
            if acc > 0:
                res[y][x] = 1
            if y + r + 1 < h:
                acc += horiz[y + r + 1][x]
            if y - r >= 0:
                acc -= horiz[y - r][x]
    return res


def _components(mask, w, h, min_area):
    seen = [bytearray(w) for _ in range(h)]
    comps = []
    for y in range(h):
        for x in range(w):
            if not mask[y][x] or seen[y][x]:
                continue
            seen[y][x] = 1
            q = deque([(x, y)])
            pts = []
            while q:
                cx, cy = q.popleft()
                pts.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = 1
                        q.append((nx, ny))
            if len(pts) >= min_area:
                comps.append(pts)
    return comps


def _extract_panel_masks(w, h, dark):
    """Detecta quadros: primeiro tenta contornos pretos no fundo branco (fechando microfrestas do Paint);
    se não achar ilhas internas, tenta blocos pretos chapados no fundo branco."""
    pad = 4
    pw, ph = w + 2 * pad, h + 2 * pad
    pdark = [bytearray(pw) for _ in range(ph)]
    for y in range(h):
        pdark[y + pad][pad:pad + w] = dark[y]
    min_area = max(30, int(w * h * 0.015))

    # Tenta r=2 (fecha frestas de ~4 px) e depois r=0 (para sarjetas muito coladas sem frestas)
    for r in (2, 0):
        barrier = _dilate(pdark, pw, ph, r)
        ext = [bytearray(pw) for _ in range(ph)]
        ext[0][0] = 1
        q = deque([(0, 0)])
        while q:
            cx, cy = q.popleft()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < pw and 0 <= ny < ph and not ext[ny][nx] and not barrier[ny][nx]:
                    ext[ny][nx] = 1
                    q.append((nx, ny))
        interior = [bytearray(1 if (not barrier[y][x] and not ext[y][x]) else 0 for x in range(pw))
                    for y in range(ph)]
        comps = _components(interior, pw, ph, min_area)
        if comps:
            masks = []
            for pts in comps:
                m = [bytearray(pw) for _ in range(ph)]
                for x, y in pts:
                    m[y][x] = 1
                if r > 0:
                    m = _dilate(m, pw, ph, r)
                    for y in range(ph):
                        for x in range(pw):
                            if pdark[y][x]:
                                m[y][x] = 0
                masks.append([row[pad:pad + w] for row in m[pad:pad + h]])
            return masks

    # Fallback: quadros desenhados como blocos pretos preenchidos no fundo branco
    comps = _components(dark, w, h, min_area)
    if comps:
        masks = []
        for pts in comps:
            m = [bytearray(w) for _ in range(h)]
            for x, y in pts:
                m[y][x] = 1
            masks.append(m)
        return masks
    raise LayoutError("Não encontrei quadros fechados na imagem. Desenhe cada quadro com linhas pretas fechadas "
                      "(ou blocos pretos) sobre fundo branco.")


def _fill_holes(mask, w, h):
    out_zero = [bytearray(w) for _ in range(h)]
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not mask[y][x] and not out_zero[y][x]:
                out_zero[y][x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not mask[y][x] and not out_zero[y][x]:
                out_zero[y][x] = 1
                q.append((x, y))
    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < w and 0 <= ny < h and not mask[ny][nx] and not out_zero[ny][nx]:
                out_zero[ny][nx] = 1
                q.append((nx, ny))
    return [bytearray(0 if out_zero[y][x] else 1 for x in range(w)) for y in range(h)]


def _trace_boundary(mask, w, h):
    """Contorna o componente em sentido horário pelas arestas da grade de pixels."""
    sx = sy = None
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                sx, sy = x, y
                break
        if sx is not None:
            break
    if sx is None:
        return []

    def cell(x, y):
        return 1 if (0 <= x < w and 0 <= y < h and mask[y][x]) else 0

    dirs = ((1, 0), (0, 1), (-1, 0), (0, -1))
    vx, vy, d = sx, sy, 0
    pts = []
    limit = (w + 2) * (h + 2) * 4
    for _ in range(limit):
        pts.append((float(vx), float(vy)))
        dx, dy = dirs[d]
        vx, vy = vx + dx, vy + dy
        tl, tr, br, bl = cell(vx - 1, vy - 1), cell(vx, vy - 1), cell(vx, vy), cell(vx - 1, vy)
        if d == 0:
            al, ar = tr, br
        elif d == 1:
            al, ar = br, bl
        elif d == 2:
            al, ar = bl, tl
        else:
            al, ar = tl, tr
        if al and ar:
            d = (d + 3) % 4
        elif not al and ar:
            pass
        else:
            d = (d + 1) % 4
        if vx == sx and vy == sy and d == 0:
            break
    return pts


def _pt_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _rdp(pts, eps):
    if len(pts) <= 2:
        return list(pts)
    a, b = pts[0], pts[-1]
    best_i, best_d = 0, -1.0
    for i in range(1, len(pts) - 1):
        d = _pt_seg_dist(pts[i], a, b)
        if d > best_d:
            best_d, best_i = d, i
    if best_d > eps:
        return _rdp(pts[:best_i + 1], eps)[:-1] + _rdp(pts[best_i:], eps)
    return [a, b]


def _simplify_closed(pts, eps):
    if len(pts) <= 4:
        return list(pts)
    i1 = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    i2 = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[i1][0]) ** 2 + (pts[i][1] - pts[i1][1]) ** 2)
    if i1 > i2:
        i1, i2 = i2, i1
    c1 = _rdp(pts[i1:i2 + 1], eps)
    c2 = _rdp(pts[i2:] + pts[:i1 + 1], eps)
    poly = c1[:-1] + c2[:-1]

    # Limpa vértices quase colineares ou micro-segmentos de serrilhado do Paint
    changed = True
    while changed and len(poly) > 3:
        changed = False
        for i in range(len(poly)):
            p_prev = poly[i - 1]
            p_cur = poly[i]
            p_next = poly[(i + 1) % len(poly)]
            if math.hypot(p_cur[0] - p_prev[0], p_cur[1] - p_prev[1]) < eps * 1.1:
                poly.pop(i)
                changed = True
                break
            if _pt_seg_dist(p_cur, p_prev, p_next) < eps * 0.9:
                poly.pop(i)
                changed = True
                break
    return poly


def _snap_straight(poly, page_tol=14):
    """Alinha bordas quase retas (verticais/horizontais desenhadas à mão) e encosta na margem da página."""
    pts = [[float(x), float(y)] for x, y in poly]
    n = len(pts)
    for _ in range(2):
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if dy > 25 and dx <= max(8.0, dy * 0.03):
                mid = (a[0] + b[0]) / 2
                a[0] = b[0] = mid
            elif dx > 25 and dy <= max(8.0, dx * 0.03):
                mid = (a[1] + b[1]) / 2
                a[1] = b[1] = mid
    for p in pts:
        if abs(p[0] - MARGIN) <= page_tol:
            p[0] = MARGIN
        elif abs(p[0] - (PAGE_W - MARGIN)) <= page_tol:
            p[0] = PAGE_W - MARGIN
        if abs(p[1] - MARGIN) <= page_tol:
            p[1] = MARGIN
        elif abs(p[1] - (PAGE_H - MARGIN)) <= page_tol:
            p[1] = PAGE_H - MARGIN
    return [[round(x), round(y)] for x, y in pts]


def _sort_reading_order(polys):
    """Ordena de cima para baixo e, quando dois quadros dividem a mesma faixa vertical, da esquerda p/ a direita."""
    items = []
    for poly in polys:
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        items.append({"poly": poly, "x0": x0, "x1": x1, "y0": y0, "y1": y1,
                      "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "h": max(1, y1 - y0)})
    # Selection sort com comparador de sobreposição vertical (n <= 16)
    ordered = []
    pool = list(items)
    while pool:
        best = 0
        for i in range(1, len(pool)):
            a, b = pool[best], pool[i]
            ov = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
            same_band = ov >= 0.45 * min(a["h"], b["h"])
            if same_band:
                if b["cx"] < a["cx"]:
                    best = i
            else:
                if b["cy"] < a["cy"]:
                    best = i
        ordered.append(pool.pop(best)["poly"])
    return ordered


def parse_bw_image(png_bytes):
    """Extrai os polígonos dos quadros (em coordenadas 1600x2400) a partir dos bytes de um PNG P&B."""
    w, h, luma = _png_luma(png_bytes)
    gw, gh, dark = _normalize_grid(w, h, luma)
    masks = _extract_panel_masks(gw, gh, dark)
    if len(masks) > MAX_PANELS:
        raise LayoutError(f"Encontrei {len(masks)} regiões (máx. {MAX_PANELS} quadros). Use linhas mais grossas ou "
                          "limpe pequenos rabiscos.")
    raw_polys = []
    for m in masks:
        clean = _fill_holes(m, gw, gh)
        ring = _trace_boundary(clean, gw, gh)
        if len(ring) < 4:
            continue
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        poly = _simplify_closed(ring, max(2.2, diag * 0.016))
        if len(poly) >= 3:
            raw_polys.append(poly)
    if not raw_polys:
        raise LayoutError("Não consegui extrair polígonos válidos da imagem.")

    all_x = [p[0] for poly in raw_polys for p in poly]
    all_y = [p[1] for poly in raw_polys for p in poly]
    bx0, bx1 = min(all_x), max(all_x)
    by0, by1 = min(all_y), max(all_y)
    bw, bh = max(1.0, bx1 - bx0), max(1.0, by1 - by0)
    iw, ih = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN

    scaled = []
    for poly in raw_polys:
        pts = [[MARGIN + (x - bx0) / bw * iw, MARGIN + (y - by0) / bh * ih] for x, y in poly]
        scaled.append(_snap_straight(pts))
    ordered = _sort_reading_order(scaled)
    return [{"n": i + 1, "poly": p, "aspect": _aspect_of(p)} for i, p in enumerate(ordered)]


def import_bw_layout(name, data_url_or_bytes):
    """Importa uma imagem P&B (data URL PNG ou bytes PNG), salva em custom_layouts.json e retorna o modelo."""
    label = (name or "").strip()[:50]
    if not label:
        raise LayoutError("Dê um nome ao modelo de página.")
    if isinstance(data_url_or_bytes, (bytes, bytearray)):
        raw = bytes(data_url_or_bytes)
    else:
        m = re.match(r"^data:image/png;base64,(.+)$", (data_url_or_bytes or "").strip(), re.S)
        if not m:
            raise LayoutError("Envie a imagem em PNG (use o botão '+ Modelo P&B' do painel).")
        try:
            raw = base64.b64decode(m.group(1))
        except Exception:
            raise LayoutError("Imagem base64 inválida.")
    if len(raw) > 15 * 1024 * 1024:
        raise LayoutError("Imagem muito grande (máx. 15 MB).")
    panels = parse_bw_image(raw)
    desc = f"custom {len(panels)}-panel layout ({', '.join(p['aspect'] for p in panels)})"
    with _lock:
        items = list_custom()
        existing_ids = {l["id"] for l in _builtin_layouts()} | {l["id"] for l in items}
        base = lid = "custom_" + _slug(label)
        n = 2
        while lid in existing_ids:
            lid, n = f"{base}_{n}", n + 1
        entry = {"id": lid, "name": f"★ {label}", "description": desc, "count": len(panels),
                 "panels": panels, "custom": True}
        items.append(entry)
        _save_custom(items)
    return entry


def _builtin_layouts():
    out = []
    for lid, name, desc, rows in _DEFS:
        polys = _polygons(rows)
        out.append({"id": lid, "name": name, "description": desc, "count": len(polys),
                    "panels": [{"n": i + 1, "poly": p, "aspect": _aspect_of(p)} for i, p in enumerate(polys)]})
    return out


def layouts():
    return {"page": {"width": PAGE_W, "height": PAGE_H, "margin": MARGIN},
            "layouts": _builtin_layouts() + list_custom()}


def get(lid):
    return next((lay for lay in layouts()["layouts"] if lay["id"] == lid), None)


def prompt_list():
    """Lista curta para o auxiliar escolher um modelo quando o usuário deixa no automático."""
    return "\n".join(f"- {lay['id']}: {lay['count']} panels, {lay['description']} (aspects: "
                     f"{', '.join(p['aspect'] for p in lay['panels'])})" for lay in layouts()["layouts"])
