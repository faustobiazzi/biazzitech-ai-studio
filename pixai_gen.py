#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PixAI Image Generation Tool (CLI & Module)
Gera imagens pela API oficial da PixAI (v2) usando a sua conta e os seus créditos.
"""

import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error

PIXAI_BASE_URL = "https://api.pixai.art/v2"
DEFAULT_MODEL_VERSION = "2024383379556065549"  # Tsubaki / PixAI Anime & Illustration

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_router as router  # noqa: E402

load_env = router.load_env  # um só leitor de ~/.env para o projeto todo

def get_api_key(explicit_key=None):
    load_env()
    return explicit_key or os.environ.get("PIXAI_API_KEY")

def generate_pixai_image(
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "1:1",
    model_version_id: str = DEFAULT_MODEL_VERSION,
    output_path: str = None,
    api_key: str = None,
    steps: int = 25,
    cfg_scale: float = 7.0,
    poll_interval: float = 2.0,
    timeout: float = 120.0,
    log=print
) -> str:
    key = get_api_key(api_key)
    if not key:
        raise ValueError(
            "PIXAI_API_KEY não encontrada! Configure a variável de ambiente PIXAI_API_KEY "
            "ou adicione no seu arquivo ~/.env."
        )

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "BiazziTech-AI-Studio/1.0"
    }

    payload = {
        "modelVersionId": model_version_id,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "steps": steps,
        "cfgScale": cfg_scale
    }
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{PIXAI_BASE_URL}/image/create", data=data, headers=headers, method="POST")

    log("[PixAI] Enviando requisição de geração...")
    try:
        with urllib.request.urlopen(req) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Erro na API PixAI ({e.code}): {err_msg}")

    task_id = res_data.get("id")
    if not task_id:
        raise RuntimeError(f"A API do PixAI não retornou task ID: {res_data}")

    log(f"[PixAI] Tarefa iniciada com sucesso! Task ID: {task_id}")
    task_url = f"{PIXAI_BASE_URL}/task/{task_id}"

    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(poll_interval)
        poll_req = urllib.request.Request(task_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(poll_req) as resp:
                task_res = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise RuntimeError(f"Erro ao verificar tarefa ({e.code}): {e.read().decode('utf-8', errors='ignore')}")

        status = task_res.get("status")
        log(f"[PixAI] Status da geração: {status}")

        if status == "completed":
            outputs = task_res.get("outputs", {})
            media_urls = outputs.get("mediaUrls", [])

            if not media_urls:
                media_ids = outputs.get("mediaIds", [])
                if media_ids:
                    batch_url = f"{PIXAI_BASE_URL}/media/batch?ids={','.join(media_ids)}"
                    b_req = urllib.request.Request(batch_url, headers=headers, method="GET")
                    with urllib.request.urlopen(b_req) as b_resp:
                        b_data = json.loads(b_resp.read().decode("utf-8"))
                        for item in b_data:
                            if isinstance(item, dict) and "url" in item:
                                media_urls.append(item["url"])

            if not media_urls:
                raise RuntimeError(f"Geração concluída mas nenhuma URL de mídia foi retornada: {outputs}")

            img_url = media_urls[0]
            log(f"[PixAI] Imagem concluída! URL: {img_url}")

            if not output_path:
                ts = int(time.time())
                output_path = f"pixai_gen_{ts}.png"

            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            log(f"[PixAI] Baixando imagem para {output_path}...")
            dl_req = urllib.request.Request(img_url, headers={"User-Agent": "BiazziTech-AI-Studio/1.0"})
            with urllib.request.urlopen(dl_req) as dl_resp, open(output_path, "wb") as f_out:
                f_out.write(dl_resp.read())

            log(f"[PixAI] Imagem salva com sucesso: {output_path}")
            return output_path

        elif status in ["failed", "cancelled"]:
            raise RuntimeError(f"Tarefa PixAI falhou ou foi cancelada. Status: {status}, Detalhes: {task_res}")

    raise TimeoutError(f"Tempo limite atingido ({timeout}s) esperando pela geração da imagem.")

def main():
    parser = argparse.ArgumentParser(description="Gerador de imagens PixAI")
    parser.add_argument("--prompt", "-p", required=True, help="Prompt da imagem")
    parser.add_argument("--negative-prompt", "-n", default="", help="Prompt negativo")
    parser.add_argument("--aspect-ratio", "-a", default="1:1", choices=["1:1", "3:4", "4:3", "9:16", "16:9"], help="Proporção da imagem")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL_VERSION, help="ID da versão do modelo PixAI (modelVersionId)")
    parser.add_argument("--output", "-o", default="", help="Caminho do arquivo final (PNG/WEBP/JPG)")
    parser.add_argument("--api-key", "-k", default=None, help="Chave API da PixAI (opcional se configurado em ~/.env)")

    args = parser.parse_args()
    try:
        saved_file = generate_pixai_image(
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            aspect_ratio=args.aspect_ratio,
            model_version_id=args.model,
            output_path=args.output or None,
            api_key=args.api_key
        )
        print(f"Sucesso: {saved_file}")
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
