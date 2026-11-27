"""
Verificação de saúde dos modelos e detecção/atualização automática de descontinuidade.

Uso rápido:
    python model_health.py                     # checa catálogo (/models) e estado dos provedores
    python model_health.py --probe             # testa 1 token real no modelo principal de cada provedor
    python model_health.py --provider gemini --probe
    python model_health.py --heal              # detecta modelos 404/descontinuados e sugere substituto via regex/descoberta
    python model_health.py --heal --apply      # atualiza provider_router.py automaticamente quando achar substituto válido
    python model_health.py --heal --apply --cli  # se regex/descoberta falhar, chama uma CLI de IA instalada (claude/codex/gemini/agy)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import provider_router as pr

ROUTER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "provider_router.py")
HEALTH_CACHE_TTL = 300  # 5 minutos
CLI_CANDIDATES = ("claude", "codex", "gemini", "agy")


def _health_cache_path():
    return os.path.join(pr.data_dir(), "model_health.json")


def _looks_like_concrete_model(name):
    """Distingue nomes concretos (ex.: 'gemini-2.5-flash') de padrões genéricos de prefer (ex.: 'flash', 'qwen')."""
    if not name:
        return False
    return any(ch in name for ch in ("-", ".", "/", ":"))


def _fetch_catalog(pid, timeout=12):
    cfg = pr.PROVIDERS[pid]
    if cfg.get("no_discovery") or cfg.get("api") == "anthropic":
        return None, None
    key = pr.provider_key(pid)
    headers = pr.auth_headers(pid, key) if key and not cfg.get("local") else None
    try:
        data = pr._http_json(cfg["base"] + "/models", timeout=timeout, headers=headers)
        ids = [(m.get("id") or "").removeprefix("models/") for m in data.get("data", []) if m.get("id")]
        return ids, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)[:120]


def probe_model(pid, model, timeout=12):
    """Envia uma requisição mínima (1 token) para testar se o modelo responde ou retornou 404/503."""
    cfg = pr.PROVIDERS[pid]
    key = pr.provider_key(pid)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "OK"}],
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
    }
    t0 = time.time()
    try:
        if cfg.get("api") == "anthropic":
            resp = pr._open_anthropic(pid, key, model, payload, timeout)
            resp.close()
        else:
            headers = pr.auth_headers(pid, key)
            headers["Content-Type"] = "application/json"
            if pr.base_id(pid) == "openrouter":
                headers["X-Title"] = "BiazziTech AI Studio"
            req = urllib.request.Request(
                cfg["base"] + "/chat/completions",
                data=pr._build_body(pid, model, payload),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read(64)
        return {
            "model": model,
            "ok": True,
            "status": 200,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": None,
            "replacement": None,
        }
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        repl = pr.extract_replacement_model(body, model) if e.code == 404 else None
        return {
            "model": model,
            "ok": False,
            "status": e.code,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": (body or str(e))[:250],
            "replacement": repl,
        }
    except Exception as e:
        return {
            "model": model,
            "ok": False,
            "status": "rede",
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e)[:250],
            "replacement": None,
        }


def check_provider_health(pid, probe=False, timeout=12):
    """Consulta a saúde de um provedor e de seus modelos candidatos."""
    cfg = pr.PROVIDERS[pid]
    reason = pr.unavailable_reason(pid)
    base_res = {
        "provider": pid,
        "label": cfg["label"],
        "available": reason is None,
        "reason": reason,
        "default_model": cfg.get("default_model"),
        "default_in_catalog": None,
        "models": [],
        "catalog_error": None,
        "probe": None,
        "ok": False,
    }
    if reason:
        return base_res

    catalog, cat_err = _fetch_catalog(pid, timeout=timeout)
    base_res["catalog_error"] = cat_err
    if catalog is not None and cfg.get("default_model"):
        base_res["default_in_catalog"] = cfg["default_model"] in catalog

    models = pr.resolve_models(pid, "auto")
    base_res["models"] = models
    if not probe:
        base_res["ok"] = bool(models) and cat_err is None
        return base_res

    if models:
        res = probe_model(pid, models[0], timeout=timeout)
        base_res["probe"] = res
        base_res["ok"] = res["ok"]
    return base_res


def check_all_health(providers=None, probe=False, timeout=12, save_cache=True):
    """Consulta a saúde de todos os provedores configurados (ou dos listados em `providers`)."""
    pr.load_env()
    pids = list(providers) if providers else pr.provider_order(with_instances=False)
    results = []
    for pid in pids:
        if pid not in pr.PROVIDERS:
            continue
        results.append(check_provider_health(pid, probe=probe, timeout=timeout))
    if save_cache:
        try:
            os.makedirs(pr.data_dir(), exist_ok=True)
            with open(_health_cache_path(), "w", encoding="utf-8") as f:
                json.dump({"at": time.time(), "results": results}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return results


def is_model_healthy(pid, model, max_age=HEALTH_CACHE_TTL):
    """Consulta rápida no cache local de saúde (sem fazer chamada de rede)."""
    try:
        with open(_health_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("at", 0) > max_age:
            return None
        for item in data.get("results", []):
            if item.get("provider") == pid:
                p = item.get("probe")
                if p and p.get("model") == model:
                    return bool(p.get("ok"))
                if item.get("models"):
                    return model in item["models"] and item.get("ok", True)
                return item.get("available")
    except Exception:
        pass
    return None


def _patch_router_model(old_model, new_model, router_path=ROUTER_FILE):
    """Substitui o nome do modelo descontinuado em provider_router.py."""
    with open(router_path, "r", encoding="utf-8") as f:
        text = f.read()
    quoted_old = f'"{old_model}"'
    quoted_new = f'"{new_model}"'
    if quoted_old not in text:
        return False
    updated = text.replace(quoted_old, quoted_new)
    if updated == text:
        return False
    with open(router_path, "w", encoding="utf-8") as f:
        f.write(updated)
    return True


def find_available_cli(cli_cmd=None):
    """Retorna o caminho de uma CLI de código instalada no sistema, ou None."""
    candidates = (cli_cmd,) if cli_cmd else CLI_CANDIDATES
    for name in candidates:
        if not name:
            continue
        found = shutil.which(name)
        if found:
            return found
    return None


def invoke_cli_updater(pid, deprecated_model, error_text, cli_cmd=None, router_path=ROUTER_FILE, timeout=180):
    """Chama a CLI de IA instalada para localizar o novo modelo e atualizar provider_router.py."""
    exe = find_available_cli(cli_cmd)
    if not exe:
        return {"invoked": False, "reason": "nenhuma CLI encontrada no PATH (claude/codex/gemini/agy)"}

    prompt = (
        f"O modelo '{deprecated_model}' do provedor '{pid}' retornou erro 404/descontinuado:\n"
        f"{error_text[:400]}\n\n"
        f"Localize o modelo substituto atual do provedor '{pid}' e atualize '{router_path}' "
        f"trocando '{deprecated_model}' pelo novo modelo. Rode os testes em seguida."
    )
    base = os.path.basename(exe).lower()
    if "claude" in base:
        cmd = [exe, "-p", prompt]
    elif "codex" in base:
        cmd = [exe, "exec", prompt]
    else:
        cmd = [exe, prompt]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "invoked": True,
            "cli": exe,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-500:],
            "stderr": (proc.stderr or "")[-300:],
        }
    except Exception as e:
        return {"invoked": True, "cli": exe, "returncode": -1, "error": str(e)}


def _pick_discovery_replacement(pid, exclude_model):
    pr._update(pid, lambda s: s.pop("discovered", None))
    discovered = pr._discover_models(pid)
    for m in discovered:
        if m != exclude_model:
            return m
    return None


def check_and_heal(providers=None, apply=False, use_cli=False, cli_cmd=None, timeout=12, router_path=ROUTER_FILE):
    """
    Verifica descontinuidade nos modelos configurados (default_model e prefer concretos).
    Tenta: 1) regex na mensagem 404, 2) redescoberta em /models, 3) fallback para CLI se use_cli=True.
    """
    pr.load_env()
    pids = list(providers) if providers else pr.provider_order(with_instances=False)
    actions = []

    for pid in pids:
        if pid not in pr.PROVIDERS or pr.unavailable_reason(pid):
            continue
        cfg = pr.PROVIDERS[pid]
        candidates = []
        if cfg.get("default_model"):
            candidates.append(cfg["default_model"])
        for p in cfg.get("prefer", []):
            if _looks_like_concrete_model(p) and p not in candidates:
                candidates.append(p)
        if not candidates:
            continue

        catalog, _ = _fetch_catalog(pid, timeout=timeout)
        for model in candidates:
            # Se está no catálogo de /models e não queremos gastar requisição à toa, pula;
            # se sumiu do catálogo (ou provedor não tem /models), faz probe real.
            if catalog is not None and model in catalog:
                continue
            res = probe_model(pid, model, timeout=timeout)
            if res["status"] != 404:
                continue

            replacement = res.get("replacement") or pr.extract_replacement_model(res.get("error") or "", model)
            source = "regex" if replacement else None

            if not replacement:
                replacement = _pick_discovery_replacement(pid, model)
                if replacement:
                    source = "discovery"

            validated = None
            if replacement:
                check = probe_model(pid, replacement, timeout=timeout)
                if check["ok"] or check["status"] in (429, 503):
                    validated = replacement

            patched = False
            cli_result = None
            if validated and apply:
                patched = _patch_router_model(model, validated, router_path=router_path)
            elif not validated and use_cli:
                cli_result = invoke_cli_updater(pid, model, res.get("error") or "404", cli_cmd=cli_cmd, router_path=router_path)

            actions.append({
                "provider": pid,
                "deprecated_model": model,
                "error": res.get("error"),
                "replacement": validated or replacement,
                "source": source,
                "validated": bool(validated),
                "applied": patched,
                "cli": cli_result,
            })

    return actions


def _print_health(results):
    for r in results:
        if not r["available"]:
            print(f"[OFF] {r['provider']:14s} ({r['label']}): {r['reason']}")
            continue
        status = "OK" if r["ok"] else "WARN"
        models = ", ".join(r["models"][:3]) or "-"
        extra = ""
        if r["probe"]:
            p = r["probe"]
            extra = f" | probe {p['model']}: {p['status']} ({p['latency_ms']}ms)"
            if p.get("replacement"):
                extra += f" -> substituto sugerido: {p['replacement']}"
        elif r["catalog_error"]:
            extra = f" | /models erro: {r['catalog_error']}"
        print(f"[{status:4s}] {r['provider']:14s}: {models}{extra}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Saúde e auto-atualização de modelos dos provedores de IA.")
    parser.add_argument("--provider", action="append", help="Filtra por provedor (ex.: gemini, groq). Pode repetir.")
    parser.add_argument("--probe", action="store_true", help="Envia 1 token real para testar se o modelo responde.")
    parser.add_argument("--heal", action="store_true", help="Verifica modelos descontinuados (404) e busca substitutos.")
    parser.add_argument("--apply", action="store_true", help="Aplica o substituto validado em provider_router.py.")
    parser.add_argument("--cli", action="store_true", help="Chama a CLI de IA instalada se regex/descoberta falhar.")
    parser.add_argument("--cli-cmd", help="Nome ou caminho explícito da CLI (ex.: claude, codex, gemini).")
    parser.add_argument("--timeout", type=int, default=12, help="Timeout por requisição em segundos (padrão: 12).")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Saída em JSON.")
    args = parser.parse_args(argv)

    providers = []
    for p in (args.provider or []):
        providers.extend([x.strip() for x in p.split(",") if x.strip()])
    providers = providers or None

    if args.heal:
        actions = check_and_heal(
            providers=providers,
            apply=args.apply,
            use_cli=args.cli,
            cli_cmd=args.cli_cmd,
            timeout=args.timeout,
        )
        if args.as_json:
            print(json.dumps(actions, ensure_ascii=False, indent=2))
        elif not actions:
            print("Nenhum modelo descontinuado (404) encontrado.")
        else:
            for a in actions:
                print(
                    f"[{a['provider']}] {a['deprecated_model']} -> {a['replacement'] or '?'} "
                    f"(fonte={a['source']}, validado={a['validated']}, aplicado={a['applied']})"
                )
        return 0

    results = check_all_health(providers=providers, probe=args.probe, timeout=args.timeout)
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print_health(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
