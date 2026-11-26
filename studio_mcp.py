#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor MCP (Model Context Protocol) do BiazziTech AI Studio.
Ferramentas de código (GDScript/Godot), texto/lore (rodízio entre provedores) e imagens
(Pollinations, PixAI) para o Antigravity ou qualquer cliente MCP.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_router as router

import free_image_gen  # noqa: E402
import pixai_gen  # noqa: E402

load_env = router.load_env
load_env()


def call_ai(prompt: str, system: str = "", model: str = "auto", temperature: float = 0.7) -> str:
    """Texto/código via roteador de provedores (rodízio automático entre chaves do ~/.env)."""
    load_env()
    try:
        res = router.simple_chat(prompt, system=system, model=model or "auto", temperature=temperature)
    except router.RouterError as e:
        return f"ERRO: {e}"
    except Exception as e:
        return f"ERRO inesperado no roteador: {e}"
    out = [f"[Provedor: {res['provider']} / {res['model']}]\n"]
    if res.get("reasoning_content"):
        out.append(f"<raciocinio>\n{res['reasoning_content']}\n</raciocinio>\n")
    out.append(res.get("content", ""))
    return "".join(out)


def providers_report() -> str:
    data = router.status(refresh=True)
    lines = ["Provedores de IA (ordem de rodízio):"]
    for p in data["providers"]:
        st = "ATIVO" if p["available"] else f"OFF - {p['reason']}"
        if p["cooldown_seconds"]:
            st += f" (volta em {p['cooldown_seconds'] // 60} min)"
        t = p.get("today") or {}
        lines.append(f"- {p['label']}: {st} | hoje {t.get('ok', 0)} ok, {t.get('errors', 0)} erros"
                     + (f" | modelo {p['last_model']}" if p.get("last_model") else ""))
    return "\n".join(lines)

def _stderr(msg):
    print(msg, file=sys.stderr)  # stdout é o canal do protocolo MCP


def call_pixai(prompt: str, negative_prompt: str = "", aspect_ratio: str = "1:1", output_path: str = "") -> str:
    try:
        saved = pixai_gen.generate_pixai_image(prompt, negative_prompt=negative_prompt, aspect_ratio=aspect_ratio,
                                               output_path=output_path or None, log=_stderr)
    except Exception as e:
        return f"ERRO PixAI: {e}"
    return f"Imagem PixAI gerada e salva em: {saved}"


def call_free_image(prompt: str, model: str = "flux", aspect_ratio: str = "1:1", output_path: str = "") -> str:
    w, h = free_image_gen.ASPECT_SIZES.get(aspect_ratio, (1024, 1024))
    try:
        saved = free_image_gen.generate_pollinations_image(prompt, output_path=output_path or None, width=w, height=h,
                                                            model=model, log=_stderr)
    except Exception as e:
        return f"Erro ao gerar imagem no Pollinations: {e}"
    return f"Imagem gerada via Pollinations ({model}, {w}x{h}), privada e sem marca d'água.\nSalva em: {saved}"


TOOLS = [
    {
        "name": "studio_code",
        "description": "Motor auxiliar externo (rodízio automático Gemini/Groq/OpenRouter/DeepSeek/xAI/Pollinations) para projetar, refatorar, depurar ou gerar código GDScript (Godot 4), shaders e arquitetura de sistemas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Descrição do código ou tarefa técnica"},
                "model": {"type": "string", "default": "auto", "description": "'auto' (rodízio entre provedores), 'deepseek-chat', 'deepseek-reasoner', 'codex', 'gemini-flash-latest', 'groq/<modelo>', 'openrouter/<modelo>:free', 'claude/auto' ou 'claude-opus-5-5', 'chatgpt/auto' ou 'gpt-<modelo>', 'grok-<modelo>'"},
                "system_context": {"type": "string", "description": "Contexto do sistema ou regras técnicas específicas"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "studio_text",
        "description": "Motor externo (rodízio automático entre provedores) para criação, expansão e revisão de texto narrativo, diálogos de NPCs e lore de jogos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Instrução narrativa ou cena"},
                "model": {"type": "string", "default": "auto", "description": "'auto' (rodízio) ou um modelo específico, ex.: 'gemini-flash-latest', 'claude/auto'"},
                "style_instructions": {"type": "string", "description": "Diretrizes de estilo ou tom"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "pixai_image_create",
        "description": "Gera imagens na sua conta PixAI (usa a sua chave e os seus créditos).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Prompt positivo para a arte"},
                "negative_prompt": {"type": "string", "description": "Prompt negativo (opcional)"},
                "aspect_ratio": {"type": "string", "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"], "default": "1:1"},
                "output_path": {"type": "string", "description": "Caminho do arquivo de destino (opcional)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "free_image_create",
        "description": "Gera imagens pela Pollinations (Flux, Turbo, Animagine) em modo privado (não aparecem no feed público) e sem marca d'água quando há chave. Bom para concept art, anime e cenários de jogo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Prompt descritivo da arte"},
                "model": {"type": "string", "enum": ["flux", "flux-pro", "flux-flex", "turbo", "anime"], "default": "flux", "description": "Modelo gerador no gateway Pollinations"},
                "aspect_ratio": {"type": "string", "enum": ["1:1", "16:9", "9:16", "3:4", "4:3"], "default": "1:1"},
                "output_path": {"type": "string", "description": "Caminho do arquivo final (opcional)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "ai_providers_status",
        "description": "Mostra quais provedores de IA externos estão ativos, em espera (limite/sem saldo) ou sem chave, e o uso de hoje.",
        "inputSchema": {"type": "object", "properties": {}}
    }
]

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "biazzitech-ai-studio",
                    "version": "1.0.0"
                }
            }
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        result_text = ""
        if tool_name in ("studio_code", "deepseek_code"):  # deepseek_*: nomes antigos
            sys_msg = args.get("system_context") or "Você é um programador especialista sênior em Godot 4.7.2 e GDScript. Escreva código eficiente, limpo e direto."
            result_text = call_ai(args.get("prompt", ""), system=sys_msg, model=args.get("model", "auto"))
        elif tool_name in ("studio_text", "deepseek_text"):
            sys_msg = args.get("style_instructions") or "Você é um roteirista e escritor especialista em narrativa de jogos: lore, diálogos de NPCs, descrições de cenários e documentos do mundo do jogo. Mantenha consistência com o material de referência fornecido e com o tom pedido. Escreva em português do Brasil."
            result_text = call_ai(args.get("prompt", ""), system=sys_msg, model=args.get("model", "auto"))
        elif tool_name == "ai_providers_status":
            result_text = providers_report()
        elif tool_name == "pixai_image_create":
            result_text = call_pixai(
                prompt=args.get("prompt", ""),
                negative_prompt=args.get("negative_prompt", ""),
                aspect_ratio=args.get("aspect_ratio", "1:1"),
                output_path=args.get("output_path", "")
            )
        elif tool_name == "free_image_create":
            result_text = call_free_image(
                prompt=args.get("prompt", ""),
                model=args.get("model", "flux"),
                aspect_ratio=args.get("aspect_ratio", "1:1"),
                output_path=args.get("output_path", "")
            )
        else:
            result_text = f"Ferramenta desconhecida: {tool_name}"

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result_text
                    }
                ]
            }
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

def main():
    # Processa mensagens JSON-RPC via stdin/stdout
    for line in sys.stdin:
        line = line.strip().lstrip("﻿")  # alguns clientes no Windows mandam BOM
        if not line:
            continue
        try:
            req = json.loads(line)
            res = handle_request(req)
            if res is not None:
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
        except Exception as e:
            err_res = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            sys.stdout.write(json.dumps(err_res) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
