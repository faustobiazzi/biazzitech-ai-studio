@echo off
chcp 65001 >nul
setlocal
set "TOOLS_DIR=%~dp0.."

echo ========================================================
echo    INSTALADOR PORTATIL DE MOTORES IA (QUALQUER PC)
echo    DeepSeek + Pollinations + MCP Antigravity
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%\instalar_motores.ps1"

echo.
pause
