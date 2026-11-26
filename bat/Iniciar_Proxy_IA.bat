@echo off
chcp 65001 >nul
setlocal
:: Sobe o servidor/proxy OpenAI neste terminal, sem abrir o navegador (Ctrl+C para parar).
:: Porta: a escolhida na instalacao (padrao 9090). Outra porta: Iniciar_Proxy_IA.bat --port 9191
set "TOOLS_DIR=%~dp0.."
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)
echo ========================================================
echo     BIAZZITECH AI STUDIO + PROXY OPENAI
echo ========================================================
%PY_CMD% "%TOOLS_DIR%\biazzitech_studio.py" --no-browser %*
pause
