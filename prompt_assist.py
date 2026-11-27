#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auxiliar de prompt para geração de imagens.

- plan(): a partir de um pedido ("página de 5 quadros estilo X..."), um texto de referência e
  imagens de referência (personagens), monta um prompt completo e independente POR QUADRO,
  repetindo a descrição visual dos personagens em todos (consistência).
- single(): o mesmo, mas para UMA imagem: devolve um prompt pronto para a caixa de geração.
- fix(): recebe o prompt usado, o que saiu errado e (opcional) a imagem gerada, e devolve um
  prompt corrigido com reforços e exclusões adequados ao tipo de erro.
- O modelo é escolhido automaticamente entre os provedores disponíveis (com imagens: modelos
  que enxergam imagens — Gemini, Claude, ChatGPT), ou o que o usuário escolher.
"""

import json
import re

import provider_router as router

# (modelo, provedor, enxerga imagens?) em ordem de preferência
ASSIST_CANDIDATES_VISION = [
    ("gemini-flash-latest", "gemini"),
    ("claude/auto", "anthropic"),
    ("chatgpt/auto", "openai"),
]
ASSIST_CANDIDATES_TEXT = [
    ("claude/auto", "anthropic"),
    ("chatgpt/auto", "openai"),
    ("gemini-flash-latest", "gemini"),
    ("groq/openai/gpt-oss-120b", "groq"),
    ("openrouter/auto-free", "openrouter"),
    ("auto", None),
]

GENERATOR_HINTS = {
    "pollinations": "Target: Flux-family text-to-image (natural language prompts work best; rich detail on subject, "
                    "setting, composition, lighting, color palette and art style).",
    "pixellab": "Target: PixelLab pixel-art generator. Keep prompts short and concrete (under 300 characters): one main "
                "subject, pose/action, view (side view / top-down / 3/4), palette. Mention 'pixel art'. No complex scenes.",
    "retrodiffusion": "Target: Retro Diffusion pixel-art generator. Short concrete prompts (under 300 characters), "
                      "single subject or simple scene, mention pixel art style, palette and view.",
    "scenario": "Target: Scenario custom model (game assets). Concrete descriptive prompts, clear subject and style.",
}

PLAN_SYSTEM = """You are an expert comic/storyboard artist and a prompt engineer for AI image generators.
The user (who writes in Portuguese) wants images for a story: a page of panels, a sequence of scenes or a single illustration.
You receive their request, optionally a reference text (story excerpt) and optionally reference images (characters, outfits, places, style).

Return ONLY a JSON object (no markdown fences, no comments) with this shape:
{
  "style": "concise visual style description in English",
  "characters": [{"name": "name or label", "look": "precise, reusable visual description in English: apparent age, build, face, hair (color/length/style), eyes, skin tone, outfit and armor details, colors, accessories, distinctive marks"}],
  "panels": [{"n": 1, "excerpt": "the part of the reference text this panel shows (keep the original language)", "shot": "framing/camera in English", "prompt": "complete self-contained English prompt", "negative": "things to avoid, comma separated", "aspect": "16:9 | 4:3 | 1:1 | 3:4 | 9:16"}],
  "notes": "short tips in Brazilian Portuguese"
}

Rules:
- Each panel prompt MUST be self-contained: the generator has no memory between images. Repeat the style AND the full "look" of every character that appears in that panel, word for word, in every prompt.
- Derive character looks from the reference images when given (describe what you see; do not invent different features). If an image shows several characters, describe each.
- If the user asks for N panels, produce exactly N. If they say each paragraph is a panel, map paragraphs to panels in order.
- When a style is named after an existing work or artist, describe its visual traits explicitly (e.g. "classic 1980s shonen anime, bold ink outlines, cel shading, dramatic speed lines, glowing ornate armor, intense eyes") so the generator does not depend on the name alone.
- Vary framing across panels like a real comic page (establishing shot, medium, close-up, action, reaction) and pick each panel's aspect to fit a page layout.
- No speech bubbles, captions or written text inside the images unless the user explicitly asks.
- Keep each prompt under ~900 characters (shorter for pixel-art generators).
- Write "excerpt" and "notes" in Portuguese; everything else in English.

Comic pages (only when the request is a page/sequence of panels) - extra fields per panel and at the top level:
  top level: "layout": "<layout id>" (see PAGE LAYOUT below; empty string when there is no page)
  per panel: "sfx": [{"text": "SOC!", "style": "hachurado | explosao | tremido | neutro", "position": "left | right | top | bottom | center | top-left | top-right | bottom-left | bottom-right", "size": "s | m | l", "angle": -12}],
             "bleed": false, "layout_note": "short note in Portuguese about how this panel sits on the page (optional)"
- PAGE LAYOUT: follow the page-division instructions. With a fixed layout, produce EXACTLY its number of panels in
  reading order (left to right, top to bottom) and compose each image for that panel's aspect. With "auto", pick
  the best layout id from the list (its panel count must match your panels) and return it in "layout".
  Dynamic/angled divisions: reinforce motion in the prompts (dutch angle, diagonal composition, speed lines).
  If a character must break out of / overflow a panel ("vaza para o quadro X"), set "bleed": true on that panel and add
  to its prompt: the character bursts out of the panel frame, body overlapping the border, dynamic comic composition.
- SOUND EFFECTS (onomatopoeias): turn the user's instructions into "sfx" entries on the right panels. Keep the text
  exactly as the user wrote it (e.g. "SOC!", "BANG!", "KABOOM"). Style: hatched/cross-hatched/rachurado -> "hachurado";
  explosive/impact -> "explosao"; shaky/trembling/tremido -> "tremido"; otherwise "neutro". Position next to the
  character or object as described. Panels without effects get "sfx": [].
  SFX MODE overlay: do NOT write the effect text in the prompt (the app letters it on top); instead ask the generator
  to leave some clear space at that position. SFX MODE draw: include it in the prompt as large hand-drawn comic
  sound-effect lettering with the requested shading and position, and do not put "text"/"letters" in the negative.
"""

DESCRIBE_SYSTEM = """You write reusable character sheets for AI image generation.
Look at the reference image(s) of ONE character and return ONLY a JSON object:
{"look": "precise English description: apparent age, build/height, face, hair (color, length, style), eyes, skin tone, outfit and armor details with colors, accessories/weapons, distinctive marks. One paragraph, no story, no style words.",
 "notes": "1-2 short sentences in Brazilian Portuguese with tips (e.g. what changes between images)"}
Describe only what is visible; if a name or hint is given, use it only to disambiguate who to describe.
"""

SFX_STYLES = ("hachurado", "explosao", "tremido", "neutro")
SFX_POSITIONS = ("left", "right", "top", "bottom", "center", "top-left", "top-right", "bottom-left", "bottom-right")

FIX_SYSTEM = """You fix prompts for AI image generators. The user (Portuguese) says what went wrong with an image.
You receive the original prompt, the complaint and possibly the generated image.

Return ONLY a JSON object: {"prompt": "the corrected complete English prompt", "negative": "comma separated things to avoid", "explanation": "1-3 short sentences in Brazilian Portuguese explaining what you changed"}

How to fix:
- Keep everything that was right; change only what addresses the complaint.
- State the fix as concrete positive instructions placed EARLY in the prompt (generators weigh the beginning more).
- Typical fixes: hands/fingers -> "anatomically correct hands, five fingers on each hand" (+ negative "extra fingers, fused fingers, deformed hands");
  faces/eyes -> "symmetrical detailed face, clear eyes"; wrong character look -> restate the full look (hair, eyes, outfit, colors) explicitly;
  extra/missing people -> state the exact count ("exactly two characters: ..."); text/watermarks -> negative "text, letters, watermark, signature";
  wrong style -> describe the style's visual traits explicitly; framing -> exact shot ("full body shot", "close-up of the face", "wide establishing shot");
  colors/lighting -> exact palette and light direction; blurry/low detail -> "sharp focus, highly detailed, clean line art".
- If you see the image, use it: describe precisely what is wrong in it and counter it.
- Keep the prompt self-contained and under ~900 characters (shorter for pixel-art generators).
"""


SINGLE_SYSTEM = """You are a prompt engineer for AI image generators. The user (usually writing in Portuguese) describes ONE image
they want, possibly with a reference text, character sheets and reference images.

Return ONLY a JSON object: {"prompt": "complete self-contained English prompt", "negative": "comma separated things to avoid", "aspect": "16:9|4:3|1:1|3:4|9:16", "explanation": "1-2 short sentences in Brazilian Portuguese saying what you emphasized"}

Rules:
- One single full-frame / splash illustration (never split into comic panels or borders).
- Put the main subject and action first, then setting, composition/shot, lighting, color palette and art style.
- Restate the full visual look of every character in the image (hair, eyes, outfit, colors, body type); use the
  character sheets and reference images for that. If a character sheet has a trigger word, include it.
- Translate everything to English; keep proper names. Never add text/lettering unless the user asks.
- Choose the aspect that fits a full-screen/splash composition (epic wide scene -> 16:9, comic splash/character -> 3:4, square icon/sprite -> 1:1).
- Keep it under ~900 characters (much shorter for pixel-art generators, as the target hint says).
"""

_MULTI_PANEL_RE = re.compile(
    r"(\b([2-9]|1[0-6]|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|v[aá]ri[oa]s|m[uú]ltipl[oa]s)"
    r"\s*(quadros?|pain[eé]is|panels?|tiras?|cenas?)\b"
    r"|cada\s+par[aá]grafo\s+[eé]\s+um\s+quadro"
    r"|um\s+quadro\s+por\s+par[aá]grafo"
    r"|\b(quadros?|pain[eé]is)\s+(din[aâ]micos?|iguais|inclinados?|dividid\w*)"
    r"|\b(quadro|painel|panel)\s*#?\s*([2-9]|1[0-6])\b"
    r"|\b(storyboard|hist[oó]ria\s+em\s+quadrinhos|p[aá]gina\s+de\s+quadrinhos|sequ[eê]ncia\s+de\s+(quadros|cenas|imagens))\b)",
    re.I,
)
_SINGLE_SPLASH_RE = re.compile(
    r"\b((1|um|uma)\s+(uúnic[oa]\s+|só\s+)?(quadro|painel|panel|imagem|ilustra[cç][aã]o|arte)|tela\s+inteira|p[aá]gina\s+inteira|splash(\s+page)?)\b",
    re.I,
)


def is_multi_panel(instruction="", text="", layout="", layout_text="", sfx_text=""):
    """True se o pedido/configuração descreve uma página composta (vários quadros);
    False se for 1 quadro só ou não informar (assume imagem única de tela inteira / splash)."""
    import comic_layouts
    lid = (layout or "").strip()
    if lid and lid != "auto":
        lay = comic_layouts.get(lid)
        if lay:
            return lay["count"] > 1
    probe = "\n".join([instruction or "", layout_text or "", sfx_text or ""])
    if _MULTI_PANEL_RE.search(probe):
        return True
    if _SINGLE_SPLASH_RE.search(probe):
        return False
    return False


class AssistError(Exception):
    pass


def _available(provider):
    if provider is None:
        return True
    router.load_env()
    return any(not router.unavailable_reason(p) for p in router.instances_of(provider))


def candidate_models(has_images, preferred=None):
    """Modelos do auxiliar em ordem: o escolhido pelo usuário (se houver) e depois os mais adequados disponíveis."""
    router.load_env()
    customs = router.custom_ids()
    if has_images:
        candidates = ASSIST_CANDIDATES_VISION + [(f"{c}/auto", c) for c in customs if router.PROVIDERS[c].get("vision")]
        candidates += [("openrouter/auto-free", "openrouter")]  # o rodízio prefere os ':free' que enxergam
    else:  # personalizados entram antes do rodízio geral
        candidates = ASSIST_CANDIDATES_TEXT[:-1] + [(f"{c}/auto", c) for c in customs] + ASSIST_CANDIDATES_TEXT[-1:]
    out = [m for m, prov in candidates if _available(prov)]
    if preferred and preferred not in ("auto", "auto-assist", ""):
        out = [preferred] + [m for m in out if m != preferred]
    return out or ["auto"]


def pick_model(has_images, preferred=None):
    """Modelo do auxiliar: o escolhido pelo usuário ou o mais adequado disponível."""
    return candidate_models(has_images, preferred)[0]


def _content(text, images):
    if not images:
        return text
    parts = [{"type": "text", "text": text}]
    for url in images[:6]:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def _parse_json(raw):
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise AssistError("O modelo não devolveu JSON.")
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        # tenta remover vírgulas sobrando
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw[start:end + 1]))
        except json.JSONDecodeError as e:
            raise AssistError(f"JSON inválido do modelo: {e}")


def _ask(system, user_text, images, model):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": _content(user_text, images)}],
        "max_tokens": 12000,
    }
    try:
        data, info = router.chat_completion(payload, timeout=180)
    except router.RouterError as e:
        raise AssistError(str(e))
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    content = msg.get("content") or ""
    if not content.strip() and "{" in (msg.get("reasoning_content") or msg.get("reasoning") or ""):
        content = msg.get("reasoning_content") or msg.get("reasoning")  # modelos que "pensam" e esgotam a resposta
    return content, info


def _ask_json(system, user_text, images, models, check):
    """Tenta os modelos em ordem até um devolver JSON válido que passe em check(data). Até 3 tentativas."""
    errors, last_raw, last_info = [], "", {}
    used = set()
    for model in models:
        if len(errors) >= 3:
            break
        prov = router.native_provider(model) or model
        if prov in used:
            continue
        used.add(prov)
        try:
            raw, info = _ask(system, user_text, images, model)
        except AssistError as e:
            errors.append(f"{model}: {e}")
            continue
        used.add(info.get("provider"))
        last_raw, last_info = raw, info
        try:
            data = _parse_json(raw)
            if check(data):
                return data, info, errors
            errors.append(f"{info.get('provider')}/{info.get('model')}: resposta incompleta")
        except AssistError as e:
            errors.append(f"{info.get('provider')}/{info.get('model')}: {e}")
    return None, last_info, errors + [("__raw__", last_raw)]


IMAGES_IGNORED = ("Nenhum modelo que enxerga imagens respondeu (Gemini/OpenRouter sem chave, em espera ou sem cota), "
                  "então o prompt foi escrito SEM olhar as imagens de referência, só pelo texto e pelas fichas.")
NO_VISION_NOTE = ("NOTE: reference images were provided by the user but could not be shown to you. "
                  "Rely on the text and the character sheets; do not invent details about the images.")


def _ask_json_images(system, user_text, images, preferred, check):
    """Como _ask_json, mas com imagens tenta primeiro os modelos que enxergam; se nenhum responder,
    cai para os modelos de texto (sem as imagens) em vez de falhar. Devolve (data, info, errors, viu_imagens)."""
    if not images:
        data, info, errors = _ask_json(system, user_text, [], candidate_models(False, preferred), check)
        return data, info, errors, False
    data, info, errors = _ask_json(system, user_text, images, candidate_models(True, preferred), check)
    if data is not None:
        return data, info, errors, True
    data2, info2, errors2 = _ask_json(system, user_text + "\n\n" + NO_VISION_NOTE, [], candidate_models(False), check)
    if data2 is not None or any(isinstance(e, tuple) and e[1].strip() for e in errors2):
        return data2, info2, [e for e in errors if not isinstance(e, tuple)] + errors2, False
    return data, info, errors + errors2, True


def _clean_sfx(items):
    out = []
    for s in items if isinstance(items, list) else []:
        if not isinstance(s, dict) or not str(s.get("text") or "").strip():
            continue
        try:
            angle = max(-45, min(45, float(s.get("angle") or 0)))
        except (TypeError, ValueError):
            angle = 0
        out.append({"text": str(s["text"]).strip()[:24],
                    "style": s.get("style") if s.get("style") in SFX_STYLES else "neutro",
                    "position": s.get("position") if s.get("position") in SFX_POSITIONS else "right",
                    "size": s.get("size") if s.get("size") in ("s", "m", "l") else "m",
                    "angle": angle})
    return out


def plan(instruction, text="", images=None, model=None, generator="pollinations", characters=None,
         layout="", layout_text="", sfx_text="", sfx_mode="overlay"):
    """characters: fichas (dicts de characters.py) com 'image_data' opcional (lista de data URLs).
    layout: id de comic_layouts, "auto" ou "" (sem página)."""
    import comic_layouts
    images = list(images or [])
    chars = characters or []
    user_images = len(images)
    for c in chars:
        for u in c.get("image_data") or []:
            if len(images) < 6:
                images.append(u)
    parts = [f"REQUEST:\n{instruction.strip()}"]
    if text and text.strip():
        parts.append(f"REFERENCE TEXT:\n{text.strip()}")
    if chars:
        import characters as charmod
        parts.append(charmod.prompt_block(chars))
    if images:
        parts.append(f"{len(images)} reference image(s) attached: the first {user_images} from the user"
                     + (", the rest from the character sheets above (in the same order)." if len(images) > user_images else "."))
    else:
        parts.append("No reference images.")
    lay = comic_layouts.get(layout) if layout and layout != "auto" else None
    if lay:
        parts.append(f"PAGE LAYOUT: fixed layout '{lay['id']}' ({lay['description']}) with exactly {lay['count']} panels. "
                     "Panel aspects in reading order: " + ", ".join(f"{p['n']}={p['aspect']}" for p in lay["panels"]) + ".")
    elif layout == "auto":
        parts.append("PAGE LAYOUT: auto. Choose one of these layouts:\n" + comic_layouts.prompt_list())
    if layout_text and layout_text.strip():
        parts.append(f"PAGE DIVISION INSTRUCTIONS (user, Portuguese):\n{layout_text.strip()}")
    if sfx_text and sfx_text.strip():
        parts.append(f"SOUND EFFECTS INSTRUCTIONS (user, Portuguese):\n{sfx_text.strip()}")
    parts.append(f"SFX MODE: {'draw' if sfx_mode == 'draw' else 'overlay'}")
    parts.append(GENERATOR_HINTS.get(generator, GENERATOR_HINTS["pollinations"]))
    data, info, errors, seen = _ask_json_images(PLAN_SYSTEM, "\n\n".join(parts), images, model,
                                                lambda d: isinstance(d.get("panels"), list) and len(d["panels"]) > 0)
    if data is None:
        raw = next((e[1] for e in errors if isinstance(e, tuple)), "")
        msgs = [e for e in errors if not isinstance(e, tuple)]
        if not raw.strip():
            raise AssistError("Nenhum modelo devolveu o plano (" + "; ".join(msgs)[:400] + "). Tente de novo ou escolha "
                              "outro modelo do auxiliar.")
        data = {"style": "", "characters": [], "notes": "O modelo não respondeu no formato esperado; o texto veio como um prompt só.",
                "panels": [{"n": 1, "excerpt": "", "shot": "", "prompt": raw.strip()[:1500], "negative": "", "aspect": "1:1"}]}
    panels = data.get("panels") or []
    for i, p in enumerate(panels, 1):
        p.setdefault("n", i)
        p.setdefault("negative", "")
        if p.get("aspect") not in ("16:9", "4:3", "1:1", "3:4", "9:16"):
            p["aspect"] = "1:1"
        p["sfx"] = _clean_sfx(p.get("sfx"))
        p["bleed"] = bool(p.get("bleed"))
    data["panels"] = panels
    # modelo de página: o fixo manda; no automático, só vale um id que exista e tenha o mesmo nº de quadros
    if not lay and layout == "auto":
        lay = comic_layouts.get(str(data.get("layout") or ""))
        if lay and lay["count"] != len(panels):
            lay = next((x for x in comic_layouts.layouts()["layouts"] if x["count"] == len(panels)), None)
    data["layout"] = lay["id"] if lay else ""
    if lay:
        for p, slot in zip(panels, lay["panels"]):
            p["aspect"] = slot["aspect"]
        if len(panels) != lay["count"]:
            data["notes"] = ((data.get("notes") or "") + f" Atenção: o modelo de página tem {lay['count']} quadros e o "
                             f"auxiliar devolveu {len(panels)}.").strip()
    data["sfx_mode"] = "draw" if sfx_mode == "draw" else "overlay"
    data["characters_used"] = [c.get("id") for c in chars]
    data["model"] = info.get("model")
    data["provider"] = info.get("provider")
    data["images_used"] = len(images) if seen else 0
    if images and not seen:
        data["warning"] = IMAGES_IGNORED
    return data


def single(instruction, text="", images=None, model=None, generator="pollinations", characters=None):
    """Um prompt só (uma imagem), a partir do pedido, texto de referência, fichas e imagens."""
    images = list(images or [])
    chars = characters or []
    user_images = len(images)
    for c in chars:
        for u in c.get("image_data") or []:
            if len(images) < 6:
                images.append(u)
    request = (instruction or "").strip() or "(use the reference text below)"
    parts = [f"REQUEST:\n{request}"]
    if text and text.strip():
        parts.append(f"REFERENCE TEXT:\n{text.strip()}")
    if chars:
        import characters as charmod
        parts.append(charmod.prompt_block(chars))
    if images:
        parts.append(f"{len(images)} reference image(s) attached: the first {user_images} from the user"
                     + (", the rest from the character sheets above." if len(images) > user_images else "."))
    parts.append(GENERATOR_HINTS.get(generator, GENERATOR_HINTS["pollinations"]))
    data, info, errors, seen = _ask_json_images(SINGLE_SYSTEM, "\n\n".join(parts), images, model,
                                                lambda d: bool((d.get("prompt") or "").strip()))
    if data is None:
        raw = next((e[1] for e in errors if isinstance(e, tuple)), "")
        if not raw.strip():
            raise AssistError("Nenhum modelo devolveu o prompt (" + "; ".join(e for e in errors if not isinstance(e, tuple))[:300]
                              + "). Tente de novo ou escolha outro modelo do auxiliar.")
        data = {"prompt": raw.strip()[:1500], "explanation": "O modelo não respondeu no formato esperado; veio o texto puro."}
    if data.get("aspect") not in ("16:9", "4:3", "1:1", "3:4", "9:16"):
        data["aspect"] = "1:1"
    return {"prompt": data["prompt"].strip(), "negative": (data.get("negative") or "").strip(),
            "aspect": data["aspect"], "explanation": (data.get("explanation") or "").strip(),
            "characters_used": [c.get("id") for c in chars], "images_used": len(images) if seen else 0,
            "warning": IMAGES_IGNORED if images and not seen else "",
            "model": info.get("model"), "provider": info.get("provider")}


def describe_character(images, name="", hint="", model=None):
    """Escreve a descrição visual (look) de um personagem a partir das imagens de referência."""
    if not images:
        raise AssistError("Adicione pelo menos uma imagem do personagem.")
    user = (f"Character name: {name or '(not given)'}\nHint: {hint or '(none)'}\n"
            f"{len(images)} image(s) of this character attached.")
    data, info, errors = _ask_json(DESCRIBE_SYSTEM, user, images[:4], candidate_models(True, model),
                                   lambda d: bool((d.get("look") or "").strip()))
    if data is None:
        raise AssistError("Nenhum modelo que enxerga imagens respondeu (" + "; ".join(e for e in errors if not isinstance(e, tuple))[:300]
                          + "). Para descrever personagens pela imagem, cadastre a chave grátis do Gemini ou do OpenRouter.")
    return {"look": data["look"].strip(), "notes": (data.get("notes") or "").strip(),
            "model": info.get("model"), "provider": info.get("provider")}


def fix(prompt, problem, image=None, model=None, generator="pollinations", negative=""):
    user = (f"ORIGINAL PROMPT:\n{prompt}\n\nORIGINAL NEGATIVE:\n{negative or '(none)'}\n\n"
            f"WHAT WENT WRONG (user, Portuguese):\n{problem}\n\n"
            f"{'The generated image is attached.' if image else 'No image attached.'}\n"
            f"{GENERATOR_HINTS.get(generator, GENERATOR_HINTS['pollinations'])}")
    data, info, errors, seen = _ask_json_images(FIX_SYSTEM, user, [image] if image else [], model,
                                                lambda d: bool((d.get("prompt") or "").strip()))
    if data is None:
        raise AssistError("O modelo não devolveu um prompt corrigido (" + "; ".join(e for e in errors if not isinstance(e, tuple))[:300] + ").")
    data.setdefault("negative", "")
    data.setdefault("explanation", "")
    data["warning"] = IMAGES_IGNORED if image and not seen else ""
    data["model"] = info.get("model")
    data["provider"] = info.get("provider")
    return data
