@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "TOOLS_DIR=%~dp0.."
set "OUT_DIR=%TOOLS_DIR%\output\lore"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

:: Detecta Python na maquina atual
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "OUT_FILE=%OUT_DIR%\lore_!TS!.md"
set "SYS_LORE=Voce e um roteirista e escritor especialista em narrativa de jogos: lore, dialogos de NPCs, descricoes de cenarios e documentos do mundo. Mantenha consistencia com o material de referencia e com o tom pedido. Escreva em portugues do Brasil."

:: Modo direto via linha de comando: Gerar_Texto_Lore_IA.bat "instrucao narrativa"
if not "%~1"=="" (
    %PY_CMD% "%TOOLS_DIR%\studio_cli.py" "%~1" --system "!SYS_LORE!" --out "!OUT_FILE!"
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo     GERADOR DE ROTEIRO, DIALOGOS E LORE
echo     Consumo ZERO de tokens do chat Antigravity
echo ========================================================
echo.
set /p "PROMPT_TXT=Descreva a cena, documento ou dialogo que deseja criar: "
if "!PROMPT_TXT!"=="" (
    echo [CANCELADO] Nenhuma instrucao informada.
    pause
    exit /b 1
)

echo.
echo [AGUARDE] Escrevendo texto...
echo.
%PY_CMD% "%TOOLS_DIR%\studio_cli.py" "!PROMPT_TXT!" --system "!SYS_LORE!" --out "!OUT_FILE!"

if exist "!OUT_FILE!" (
    echo.
    echo [ARQUIVO SALVO] !OUT_FILE!
)

echo.
pause
