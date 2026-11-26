@echo off
chcp 65001 >nul
setlocal
set "TOOLS_DIR=%~dp0.."
echo ========================================================
echo    GERAR "BiazziTech AI Studio.exe" (roda sem Python)
echo ========================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS_DIR%\build_exe.ps1"
echo.
pause
