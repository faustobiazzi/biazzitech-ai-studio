@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "TOOLS_DIR=%~dp0.."
set "OUT_DIR=%TOOLS_DIR%\output\codigo"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

:: Detecta Python na maquina atual
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "OUT_FILE=%OUT_DIR%\gdscript_!TS!.md"

:: Modo direto via linha de comando: Gerar_GDScript_IA.bat "pedido de codigo"
if not "%~1"=="" (
    %PY_CMD% "%TOOLS_DIR%\studio_cli.py" "%~1" --code --out "!OUT_FILE!"
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo     GERADOR DE CODIGO GDSCRIPT / GODOT 4 (0 TOKENS CHAT)
echo     Motor: DeepSeek + Fallback Automatico Codex
echo ========================================================
echo.
set /p "PROMPT_TXT=Descreva o script ou funcao Godot 4 que deseja gerar: "
if "!PROMPT_TXT!"=="" (
    echo [CANCELADO] Nenhum pedido informado.
    pause
    exit /b 1
)

echo.
echo [AGUARDE] Consultando motor de codigo...
echo.
%PY_CMD% "%TOOLS_DIR%\studio_cli.py" "!PROMPT_TXT!" --code --out "!OUT_FILE!"

if exist "!OUT_FILE!" (
    echo.
    echo [ARQUIVO SALVO] !OUT_FILE!
)

echo.
pause
