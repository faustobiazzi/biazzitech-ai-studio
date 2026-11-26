@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "TOOLS_DIR=%~dp0.."
set "OUT_DIR=%TOOLS_DIR%\output\imagens"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

:: Detecta Python na maquina atual
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

:: Modo direto via linha de comando: Gerar_Imagem_IA.bat "prompt" [modelo] [aspect]
if not "%~1"=="" (
    set "PROMPT_TXT=%~1"
    set "MODEL_SEL=%~2"
    if "!MODEL_SEL!"=="" set "MODEL_SEL=flux"
    set "ASPECT_SEL=%~3"
    if "!ASPECT_SEL!"=="" set "ASPECT_SEL=1:1"
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
    set "OUT_FILE=%OUT_DIR%\img_!MODEL_SEL!_!TS!.jpg"
    %PY_CMD% "%TOOLS_DIR%\free_image_gen.py" "!PROMPT_TXT!" --model "!MODEL_SEL!" --aspect "!ASPECT_SEL!" --output "!OUT_FILE!"
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo     GERADOR DE IMAGENS PRIVADO (POLLINATIONS - 0 TOKENS)
echo ========================================================
echo.
set /p "PROMPT_TXT=Descreva a imagem (ingles ou portugues): "
if "!PROMPT_TXT!"=="" (
    echo [CANCELADO] Nenhum prompt informado.
    pause
    exit /b 1
)

echo.
echo Modelos disponiveis:
echo   [1] flux      (Padrao - rapido e nitido)
echo   [2] flux-pro  (Alta fidelidade / detalhes)
echo   [3] anime     (Animagine - anime / concept)
echo   [4] turbo     (Z-Image Turbo - ultra rapido)
set /p "M_OPT=Escolha [1-4, Enter=1]: "
set "MODEL_SEL=flux"
if "!M_OPT!"=="2" set "MODEL_SEL=flux-pro"
if "!M_OPT!"=="3" set "MODEL_SEL=anime"
if "!M_OPT!"=="4" set "MODEL_SEL=turbo"

echo.
echo Proporcoes disponiveis:
echo   [1] 1:1 (Quadrada 1024x1024)
echo   [2] 16:9 (Paisagem / Widescreen 1280x720)
echo   [3] 9:16 (Retrato / Vertical 720x1280)
echo   [4] 3:4 (Retrato Personagem 768x1024)
echo   [5] 4:3 (Classica 1024x768)
set /p "A_OPT=Escolha [1-5, Enter=1]: "
set "ASPECT_SEL=1:1"
if "!A_OPT!"=="2" set "ASPECT_SEL=16:9"
if "!A_OPT!"=="3" set "ASPECT_SEL=9:16"
if "!A_OPT!"=="4" set "ASPECT_SEL=3:4"
if "!A_OPT!"=="5" set "ASPECT_SEL=4:3"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "OUT_FILE=%OUT_DIR%\img_!MODEL_SEL!_!TS!.jpg"

echo.
%PY_CMD% "%TOOLS_DIR%\free_image_gen.py" "!PROMPT_TXT!" --model "!MODEL_SEL!" --aspect "!ASPECT_SEL!" --output "!OUT_FILE!"

if exist "!OUT_FILE!" (
    echo.
    echo [SUCESSO] Abrindo imagem gerada...
    start "" "!OUT_FILE!"
)

echo.
pause
