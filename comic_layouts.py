#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelos de página de quadrinho.

Cada modelo é descrito por faixas (linhas) e cortes (colunas). As bordas podem ser inclinadas, o que
gera quadros "dinâmicos" (diagonais). O painel desenha a página a partir dos polígonos calculados aqui
e o auxiliar de prompt recebe a proporção de cada quadro para pedir a imagem no formato certo.

Coordenadas em pixels numa página retrato de 1600 x 2400 (2:3).
"""

PAGE_W, PAGE_H = 1600, 2400
MARGIN, GUTTER = 48, 28
ASPECTS = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}


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


def layouts():
    out = []
    for lid, name, desc, rows in _DEFS:
        polys = _polygons(rows)
        out.append({"id": lid, "name": name, "description": desc, "count": len(polys),
                    "panels": [{"n": i + 1, "poly": p, "aspect": _aspect_of(p)} for i, p in enumerate(polys)]})
    return {"page": {"width": PAGE_W, "height": PAGE_H, "margin": MARGIN}, "layouts": out}


def get(lid):
    return next((lay for lay in layouts()["layouts"] if lay["id"] == lid), None)


def prompt_list():
    """Lista curta para o auxiliar escolher um modelo quando o usuário deixa no automático."""
    return "\n".join(f"- {lay['id']}: {lay['count']} panels, {lay['description']} (aspects: "
                     f"{', '.join(p['aspect'] for p in lay['panels'])})" for lay in layouts()["layouts"])
