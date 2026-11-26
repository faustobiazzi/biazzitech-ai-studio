@echo off
chcp 65001 >nul
setlocal
:: Abre o painel BiazziTech AI Studio (porta escolhida na instalacao; padrao 9090).
:: Se o servidor ja estiver rodando, so abre o navegador.
set "TOOLS_DIR=%~dp0.."
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo [ERRO] Python nao encontrado.
        pause
        exit /b 1
    )
    set "PY_CMD=py -3"
)
start "BiazziTech AI Studio - servidor (feche para desligar)" /min %PY_CMD% "%TOOLS_DIR%\biazzitech_studio.py" %*
