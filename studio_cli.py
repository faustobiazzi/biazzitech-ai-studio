#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Linha de comando do BiazziTech AI Studio: código (GDScript/Godot) e texto/lore pelo rodízio
de provedores (Gemini, Groq, OpenRouter, Claude, ChatGPT, DeepSeek, Ollama...).
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_router as router

load_env = router.load_env

def query_ai(
    prompt: str,
    system_prompt: str = "Você é um assistente de IA especialista em programação GDScript (Godot 4), arquitetura de jogos e roteiro narrativo para jogos.",
    model: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    provider: str = "auto"
) -> dict:
    load_env()
    only = None if provider == "auto" else provider
    res = router.simple_chat(prompt, system=system_prompt, model=model, temperature=temperature, only=only)
    print(f"[Provedor: {res['provider']} / {res['model']}]", file=sys.stderr)
    return res

def main():
    parser = argparse.ArgumentParser(description="BiazziTech AI Studio - codigo e texto pelo rodizio de provedores")
    parser.add_argument("prompt", nargs="?", default="", help="Prompt para o motor")
    parser.add_argument("--file", "-f", default="", help="Carregar prompt de arquivo")
    parser.add_argument("--system", "-s", default="", help="System prompt personalizado")
    parser.add_argument(
        "--model", "-m", default="auto",
        help="Modelo: auto (rodízio), deepseek-chat, deepseek-reasoner, codex, gemini-flash-latest, groq/<modelo>..."
    )
    parser.add_argument(
        "--provider", "-p", default="auto", choices=["auto"] + list(router.PROVIDERS),
        help="Provedor: auto (rodízio entre todos com chave) ou um provedor específico"
    )
    parser.add_argument("--out", "-o", default="", help="Salvar resposta em arquivo")
    parser.add_argument("--code", "-c", action="store_true", help="Otimizar para geração estrita de código GDScript")

    args = parser.parse_args()

    prompt_text = args.prompt
    if args.file and os.path.isfile(args.file):
        with open(args.file, "r", encoding="utf-8-sig") as f:
            prompt_text = f.read()

    if not prompt_text:
        print("Erro: Nenhum prompt informado.", file=sys.stderr)
        sys.exit(1)

    system = args.system
    if args.code and not system:
        system = "Você é um programador sênior em Godot 4.7.2 GDScript. Responda apenas com código limpo, tipado e devidamente comentado, pronto para produção."

    try:
        res = query_ai(
            prompt_text,
            system_prompt=system or "Você é um assistente prestativo especialista em desenvolvimento de jogos e narrativa.",
            model=args.model,
            provider=args.provider
        )
        if res.get("reasoning_content"):
            print("=== RACIOCÍNIO ===")
            print(res["reasoning_content"])
            print("================================")
        print(res["content"])

        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(res["content"])
            print(f"\n[Salvo em {args.out}]")
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
