@echo off
chcp 65001 >nul
setlocal
set "TOOLS_DIR=%~dp0.."

echo ========================================================
echo    IMAGENS OFFLINE COM LORAS (STABLE DIFFUSION LOCAL)
echo    BiazziTech AI Studio - analisa a maquina antes
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%\instalar_sd_local.ps1"

echo.
pause
