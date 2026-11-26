#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de imagens pela Pollinations (linha de comando e módulo).
Com POLLINATIONS_API_KEY usa o gateway autenticado (sem marca d'água, privado); sem chave, o endpoint público.
Usado pelo .bat Gerar_Imagem_IA e pelo servidor MCP.
"""

import os
import sys
import time
import argparse
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_router as router  # noqa: E402

load_env = router.load_env  # um só leitor de ~/.env para o projeto todo

POLLINATIONS_MODEL_MAP = {
    "flux": "black-forest-labs/flux.1-schnell",
    "flux-pro": "black-forest-labs/flux.1.1-pro",
    "flux-flex": "black-forest-labs/flux.2-flex",
    "turbo": "tongyi-mai/z-image-turbo",
    "anime": "community/vendouple/animagine",
}

ASPECT_SIZES = {"1:1": (1024, 1024), "16:9": (1280, 720), "9:16": (720, 1280), "3:4": (768, 1024), "4:3": (1024, 768)}


def _log(msg):
    print(msg, file=sys.stderr)


def generate_pollinations_image(
    prompt: str,
    output_path: str = None,
    width: int = 1024,
    height: int = 1024,
    model: str = "flux",
    seed: int = None,
    log=print
) -> str:
    """
    Gera imagem via gateway autenticado gen.pollinations.ai (sem marca d'água e privado)
    quando POLLINATIONS_API_KEY está presente, com fallback resiliente entre modelos.
    """
    load_env()
    api_key = os.environ.get("POLLINATIONS_API_KEY")

    encoded_prompt = urllib.parse.quote(prompt)
    resolved_primary = POLLINATIONS_MODEL_MAP.get(model, model)

    if api_key:
        candidates = [resolved_primary, "black-forest-labs/flux.1-schnell", "tongyi-mai/z-image-turbo"]
    else:
        candidates = [model if model in ("flux", "turbo") else "flux", "turbo"]

    models_to_try = []
    for m in candidates:
        if m not in models_to_try:
            models_to_try.append(m)

    image_bytes = None
    used_model = resolved_primary
    last_err = None

    headers = {
        "User-Agent": "BiazziTech-AI-Studio/1.0"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for current_model in models_to_try:
        encoded_model = urllib.parse.quote(current_model, safe="/-._")
        if api_key:
            url = (
                f"https://gen.pollinations.ai/image/{encoded_prompt}"
                f"?width={width}&height={height}&model={encoded_model}&nologo=true&private=true"
            )
        else:
            url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}&height={height}&model={encoded_model}&nologo=true&private=true"
            )
        if seed is not None:
            url += f"&seed={seed}"

        log(f"[Pollinations] Gerando imagem (Modelo: {current_model}, {width}x{height})...")
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                image_bytes = resp.read()
                if image_bytes and len(image_bytes) > 1000:
                    used_model = current_model
                    break
        except Exception as e:
            last_err = e
            log(f"[Pollinations] Aviso: falha no modelo '{current_model}' ({e}). Tentando próximo modelo...")

    if not image_bytes:
        raise RuntimeError(f"Erro ao gerar imagem no Pollinations: {str(last_err)}")

    if not output_path:
        ts = int(time.time())
        safe_name = used_model.split("/")[-1].replace(".", "_")
        output_path = f"generated_{safe_name}_{ts}.png"

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    log(f"[Pollinations] Imagem salva com sucesso: {output_path} ({len(image_bytes)} bytes)")
    return output_path

def main():
    parser = argparse.ArgumentParser(description="Gerador Privado de Imagens (Pollinations Gateway)")
    parser.add_argument("prompt", help="Prompt descritivo da imagem")
    parser.add_argument("--output", "-o", default="", help="Caminho do arquivo final (.png/.jpg)")
    parser.add_argument(
        "--model", "-m", default="flux",
        help="Modelo: flux, flux-pro, flux-flex, turbo, anime (ou ID completo do gen.pollinations.ai)"
    )
    parser.add_argument("--aspect", "-a", default="1:1", choices=["1:1", "16:9", "9:16", "3:4", "4:3"], help="Proporção da imagem")
    parser.add_argument("--seed", "-s", type=int, default=None, help="Seed para reproducibilidade")

    args = parser.parse_args()

    w, h = ASPECT_SIZES.get(args.aspect, (1024, 1024))

    try:
        saved = generate_pollinations_image(
            prompt=args.prompt,
            output_path=args.output or None,
            width=w,
            height=h,
            model=args.model,
            seed=args.seed
        )
        print(f"Sucesso: {saved}")
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
