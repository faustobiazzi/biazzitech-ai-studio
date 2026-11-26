"""Ambiente isolado para os testes: pasta pessoal e de dados temporárias, sem chaves reais.

Importe este módulo ANTES dos módulos do projeto (from _env import ROOT, TMP, write_env).
Nenhum teste acessa a internet.
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="biazzitech-tests-")
DATA = os.path.join(TMP, "dados")

# tira do ambiente qualquer chave real que o PC tenha
for k in list(os.environ):
    if re.search(r"(_API_KEY|_KEY)(_\d+)?$", k) or k in ("OLLAMA_ENABLED", "ROUTER_ORDER", "BIAZZITECH_PORT"):
        os.environ.pop(k, None)
os.environ.update({"USERPROFILE": TMP, "HOME": TMP, "BIAZZITECH_HOME": DATA, "ROUTER_KEY_DELAY": "0"})
os.makedirs(DATA, exist_ok=True)
os.chdir(TMP)  # o roteador também lê ./.env
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def write_env(**values):
    """Reescreve o ~/.env temporário com os valores dados."""
    with open(os.path.join(TMP, ".env"), "w", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")


def clear_data():
    """Apaga os arquivos de dados (estado do rodízio, usuários, personagens...)."""
    for name in os.listdir(DATA):
        p = os.path.join(DATA, name)
        if os.path.isfile(p):
            os.remove(p)
