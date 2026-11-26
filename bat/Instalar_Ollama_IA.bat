@echo off
chcp 65001 >nul
setlocal
set "TOOLS_DIR=%~dp0.."

echo ========================================================
echo    IA LOCAL (OLLAMA) - BIAZZITECH AI STUDIO
echo    Analisa a maquina antes de instalar
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%\instalar_ollama.ps1"

echo.
pause
