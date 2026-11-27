# =====================================================================
# GERA "BiazziTech AI Studio.exe" (roda em maquinas SEM Python)
# Precisa de Python + PyInstaller so na maquina que GERA o .exe.
# =====================================================================
#
# Uso:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
# Saida: dist\BiazziTech AI Studio.exe
#
# O .exe le as chaves de %USERPROFILE%\.env e guarda imagens/estado em
# %USERPROFILE%\.biazzitech, igual a versao em Python.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pyExe = $null
$pyPre = @()
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $pyExe = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = "py"; $pyPre = @("-3") }
if (-not $pyExe) { Write-Host "[ERRO] Python nao encontrado (necessario so para GERAR o .exe)." -ForegroundColor Red; exit 1 }

function Invoke-Py { param([string[]]$a) & $pyExe @($pyPre + $a) }

$temPyInstaller = $true
try { Invoke-Py @("-m", "PyInstaller", "--version") *> $null; if ($LASTEXITCODE -ne 0) { $temPyInstaller = $false } } catch { $temPyInstaller = $false }
if (-not $temPyInstaller) {
    Write-Host "O PyInstaller (ferramenta que empacota Python em .exe) nao esta instalado." -ForegroundColor Yellow
    $r = Read-Host "Instalar agora com 'pip install --user pyinstaller' (baixa do PyPI)? [s/N]"
    if ($r -notmatch "^(s|sim|y|yes)$") { Write-Host "Cancelado." ; exit 1 }
    Invoke-Py @("-m", "pip", "install", "--user", "--upgrade", "pyinstaller")
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERRO] Falha ao instalar o PyInstaller." -ForegroundColor Red; exit 1 }
}

# Leitura de PDF: inclui a biblioteca pypdf no .exe se ela estiver instalada aqui
$extra = @()
try { Invoke-Py @("-c", "import pypdf") *> $null; if ($LASTEXITCODE -eq 0) { $extra = @("--hidden-import", "pypdf", "--collect-submodules", "pypdf") } } catch {}
if (-not $extra) { Write-Host "Aviso: pypdf nao instalado; o .exe vai ler PDF so de forma basica (pip install pypdf para incluir)." -ForegroundColor DarkYellow }

Write-Host "Gerando o .exe (leva 1-2 minutos)..." -ForegroundColor Green
$sep = ";"   # separador do --add-data no Windows
Invoke-Py (@(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
    "--name", "BiazziTech AI Studio",
    "--add-data", ((Join-Path $root "studio_ui.html") + "${sep}."),
    "--add-data", ((Join-Path $root "ui") + "${sep}ui"),
    "--paths", $root,
    "--hidden-import", "studio_server",
    "--hidden-import", "provider_router",
    "--hidden-import", "image_providers",
    "--hidden-import", "access_control",
    "--hidden-import", "doc_extract",
    "--hidden-import", "prompt_assist",
    "--hidden-import", "characters",
    "--hidden-import", "comic_layouts",
    "--hidden-import", "conversations",
    "--hidden-import", "web_search",
    "--hidden-import", "godot_export",
    "--hidden-import", "sd_local",
    # arquivos temporarios fora do OneDrive (ele trava arquivos durante a limpeza)
    "--distpath", (Join-Path $root "dist"),
    "--workpath", (Join-Path $env:TEMP "biazzitech_build\work"),
    "--specpath", (Join-Path $env:TEMP "biazzitech_build"),
    (Join-Path $root "biazzitech_studio.py")
) + $extra)
if ($LASTEXITCODE -ne 0) { Write-Host "[ERRO] O PyInstaller falhou." -ForegroundColor Red; exit 1 }

$exe = Join-Path $root "dist\BiazziTech AI Studio.exe"
Write-Host "`nPronto: $exe" -ForegroundColor Green
Write-Host "Copie esse arquivo para qualquer PC com Windows 10/11 e de duplo-clique." -ForegroundColor Gray
Write-Host "As chaves ficam em %USERPROFILE%\.env (pode criar pela aba Provedores do painel)." -ForegroundColor Gray
Write-Host "Obs.: alguns antivirus estranham .exe gerados pelo PyInstaller; se bloquear, libere o arquivo." -ForegroundColor DarkYellow
