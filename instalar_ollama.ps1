# =====================================================================
# BIAZZITECH AI STUDIO - INSTALADOR DO OLLAMA (IA LOCAL, SEM INTERNET)
# Analisa o hardware, avisa se a maquina estiver abaixo do minimo e
# deixa o usuario decidir se quer continuar mesmo assim.
# Compativel com Windows PowerShell 5.1+ e PowerShell 7+
# =====================================================================
#
# Uso:
#   .\instalar_ollama.ps1                      -> analisa e pergunta
#   .\instalar_ollama.ps1 -SomenteVerificar    -> so mostra a analise
#   .\instalar_ollama.ps1 -Instalar sim        -> instala sem perguntar (avisa se abaixo do minimo)
#   .\instalar_ollama.ps1 -Instalar sim -Forcar  -> instala mesmo abaixo do minimo, sem perguntar
#   .\instalar_ollama.ps1 -Modelo "qwen2.5-coder:3b"  -> escolhe o modelo manualmente

param (
    [ValidateSet("perguntar", "sim", "nao")]
    [string]$Instalar = "perguntar",
    [string]$Modelo = "",
    [switch]$SomenteVerificar,
    [switch]$Forcar
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$envPath = Join-Path $userHome ".env"

# Requisitos (referencia: Ollama para Windows + modelos de 3B a 14B)
$MIN_RAM_GB = 7.5   # 8 GB nominais (Windows reserva parte)
$REC_RAM_GB = 15    # 16 GB nominais
$MIN_DISK_GB = 10
$MIN_CORES = 4
$MIN_WIN_BUILD = 19045   # Windows 10 22H2
$REC_VRAM_GB = 5.5   # 6 GB nominais

function Write-Linha($txt, $cor = "Gray") { Write-Host $txt -ForegroundColor $cor }

function Test-Interativo {
    try { return (-not [Console]::IsInputRedirected) -and [Environment]::UserInteractive } catch { return $false }
}

function Read-SimNao([string]$pergunta, [bool]$padrao) {
    if (-not (Test-Interativo)) { return $padrao }
    $sufixo = if ($padrao) { "[S/n]" } else { "[s/N]" }
    try { $r = Read-Host "$pergunta $sufixo" } catch { return $padrao }
    if ([string]::IsNullOrWhiteSpace($r)) { return $padrao }
    return ($r.Trim().ToLower() -in @("s", "sim", "y", "yes"))
}

function Set-EnvKey([string]$file, [string]$key, [string]$val) {
    $lines = @()
    if (Test-Path $file) {
        $lines = @(Get-Content $file -Encoding UTF8 | ForEach-Object { $_.TrimStart([char]0xFEFF) } |
            Where-Object { $_.Trim() -ne "" -and $_ -notmatch "^$key=" })
    }
    $lines += "$key=$val"
    [System.IO.File]::WriteAllLines($file, [string[]]$lines, $utf8NoBom)
}

# ------------------------------------------------------------ 1. Analise de hardware
Write-Linha "`n==========================================================" Cyan
Write-Linha "   OLLAMA LOCAL - ANALISE DA MAQUINA" Yellow
Write-Linha "==========================================================" Cyan

$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = @(Get-CimInstance Win32_Processor)
$ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$cores = ($cpu | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
$cpuName = ($cpu[0].Name -replace "\s+", " ").Trim()
$build = [int]$os.BuildNumber
$is64 = [Environment]::Is64BitOperatingSystem

# Disco onde os modelos ficam (~\.ollama)
$driveLetter = (Split-Path -Qualifier $userHome).TrimEnd(":")
$disk = Get-PSDrive -Name $driveLetter
$diskFreeGB = [math]::Round($disk.Free / 1GB, 1)

# GPUs e VRAM (registro tem o valor de 64 bits; WMI limita a 4 GB)
$gpus = @()
$classKey = "HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
if (Test-Path $classKey) {
    Get-ChildItem $classKey -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -match "^\d{4}$" } | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        if ($p -and $p.DriverDesc) {
            $mem = 0
            if ($p."HardwareInformation.qwMemorySize") { $mem = [double]$p."HardwareInformation.qwMemorySize" }
            elseif ($p."HardwareInformation.MemorySize") {
                $raw = $p."HardwareInformation.MemorySize"
                if ($raw -is [byte[]]) { $mem = [double][BitConverter]::ToUInt32($raw, 0) } else { $mem = [double]$raw }
            }
            $gpus += [PSCustomObject]@{ Nome = $p.DriverDesc; VramGB = [math]::Round($mem / 1GB, 1) }
        }
    }
}
if (-not $gpus) {
    Get-CimInstance Win32_VideoController | ForEach-Object {
        $gpus += [PSCustomObject]@{ Nome = $_.Name; VramGB = [math]::Round([double]$_.AdapterRAM / 1GB, 1) }
    }
}
$gpus = @($gpus | Sort-Object Nome -Unique)
# GPU dedicada que o Ollama aproveita: NVIDIA ou AMD Radeon
$gpuUtil = @($gpus | Where-Object { $_.Nome -match "NVIDIA|GeForce|RTX|Quadro|Radeon RX|Radeon Pro" })
$vramGB = 0
if ($gpuUtil) { $vramGB = ($gpuUtil | Measure-Object -Property VramGB -Maximum).Maximum }

Write-Linha ("  Windows:        build {0} {1}" -f $build, $(if ($is64) { "(64 bits)" } else { "(32 bits)" }))
Write-Linha ("  Processador:    {0} ({1} nucleos logicos)" -f $cpuName, $cores)
Write-Linha ("  Memoria RAM:    {0} GB" -f $ramGB)
Write-Linha ("  Disco livre:    {0} GB em {1}:" -f $diskFreeGB, $driveLetter)
foreach ($g in $gpus) { Write-Linha ("  Placa de video: {0} ({1} GB)" -f $g.Nome, $g.VramGB) }
if (-not $gpuUtil) { Write-Linha "  Aceleracao:     sem GPU NVIDIA/AMD dedicada -> o modelo rodara no processador (CPU)" DarkYellow }

# ------------------------------------------------------------ 2. Classificacao
$problemas = @()
if (-not $is64) { $problemas += "Windows 32 bits (o Ollama exige 64 bits)" }
if ($build -lt $MIN_WIN_BUILD) { $problemas += "Windows desatualizado (build $build; minimo $MIN_WIN_BUILD = Windows 10 22H2)" }
if ($ramGB -lt $MIN_RAM_GB) { $problemas += "RAM de $ramGB GB (minimo 8 GB)" }
if ($cores -lt $MIN_CORES) { $problemas += "processador com $cores nucleos logicos (minimo $MIN_CORES)" }
if ($diskFreeGB -lt $MIN_DISK_GB) { $problemas += "apenas $diskFreeGB GB livres no disco (minimo $MIN_DISK_GB GB)" }

if ($problemas) { $tier = "abaixo_minimo" }
elseif ($ramGB -ge $REC_RAM_GB -and $vramGB -ge $REC_VRAM_GB) { $tier = "recomendado" }
else { $tier = "minimo" }

# Modelo sugerido conforme o hardware
if (-not $Modelo) {
    if ($vramGB -ge 11.5) { $Modelo = "qwen2.5-coder:14b" }
    elseif ($vramGB -ge 5.5 -or $ramGB -ge 15) { $Modelo = "qwen2.5-coder:7b" }
    elseif ($ramGB -ge 7.5) { $Modelo = "qwen2.5-coder:3b" }
    else { $Modelo = "qwen2.5-coder:1.5b" }
}
$tamanhos = @{ "qwen2.5-coder:14b" = 9; "qwen2.5-coder:7b" = 4.7; "qwen2.5-coder:3b" = 1.9; "qwen2.5-coder:1.5b" = 1 }
$tamanho = if ($tamanhos.ContainsKey($Modelo)) { $tamanhos[$Modelo] } else { $null }

Write-Linha ""
switch ($tier) {
    "recomendado" { Write-Linha "  RESULTADO: RECOMENDADO - a maquina atende bem ao Ollama." Green }
    "minimo" {
        Write-Linha "  RESULTADO: ATENDE AO MINIMO - vai funcionar, mas as respostas locais podem ser lentas." Yellow
        if (-not $gpuUtil) { Write-Linha "  (Sem GPU dedicada, tudo roda no processador.)" Yellow }
    }
    "abaixo_minimo" {
        Write-Linha "  RESULTADO: ABAIXO DO MINIMO - NAO RECOMENDADO." Red
        foreach ($p in $problemas) { Write-Linha "   - $p" Red }
        Write-Linha "  Se continuar, o desempenho pode ser MUITO prejudicado (respostas muito lentas," Red
        Write-Linha "  travamentos do PC durante a geracao ou falta de memoria)." Red
    }
}
$tamTxt = if ($tamanho) { " (~$tamanho GB para baixar)" } else { "" }
Write-Linha "  Modelo sugerido: $Modelo$tamTxt" Cyan

if ($SomenteVerificar) {
    Write-Linha "`n[Somente verificacao] Nada foi instalado." Gray
    return
}

# ------------------------------------------------------------ 3. Decisao do usuario
$continuar = $false
if ($Instalar -eq "nao") {
    Write-Linha "`n[Ollama] Instalacao ignorada (-Instalar nao)." Gray
    return
}
if ($Instalar -eq "perguntar") {
    $padrao = ($tier -ne "abaixo_minimo")
    $continuar = Read-SimNao "`nDeseja instalar o Ollama e baixar o modelo $Modelo?" $padrao
    if (-not (Test-Interativo)) {
        Write-Linha "[Ollama] Sem terminal interativo; use -Instalar sim para instalar." Gray
        $continuar = $false
    }
}
else { $continuar = $true }

if ($continuar -and $tier -eq "abaixo_minimo" -and -not $Forcar) {
    Write-Linha "`n  ATENCAO: esta maquina esta abaixo do minimo. A IA local pode ficar muito lenta" Red
    Write-Linha "  e deixar o computador pesado enquanto responde." Red
    $continuar = Read-SimNao "  Quer continuar mesmo assim?" $false
    if (-not (Test-Interativo)) {
        Write-Linha "  [Ollama] Sem terminal interativo; use -Forcar para instalar mesmo abaixo do minimo." Gray
    }
}
if (-not $continuar) {
    Write-Linha "`n[Ollama] Instalacao nao realizada. O kit continua funcionando com os provedores online." Gray
    return
}
if ($tamanho -and $diskFreeGB -lt ($tamanho + 2)) {
    Write-Linha "[Ollama] Espaco insuficiente para o modelo $Modelo ($tamanho GB + folga). Libere espaco ou use -Modelo menor." Red
    return
}

# ------------------------------------------------------------ 4. Instalar o Ollama
function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $p = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $p) { return $p }
    return $null
}

$ollamaExe = Find-Ollama
if ($ollamaExe) {
    Write-Linha "`n[Ollama] Ja instalado em $ollamaExe" Green
}
else {
    Write-Linha "`n[Ollama] Instalando..." Green
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
    }
    if (-not (Find-Ollama)) {
        $setup = Join-Path $env:TEMP "OllamaSetup.exe"
        Write-Linha "  Baixando instalador oficial de https://ollama.com/download/OllamaSetup.exe ..." Gray
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing
        Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait
        Remove-Item $setup -Force -ErrorAction SilentlyContinue
    }
    $ollamaExe = Find-Ollama
    if (-not $ollamaExe) {
        Write-Linha "[Ollama] Nao foi possivel instalar automaticamente. Instale por https://ollama.com/download e rode este script de novo." Red
        return
    }
    Write-Linha "  -> Instalado em $ollamaExe" Gray
}

# ------------------------------------------------------------ 5. Servidor e modelo
function Test-OllamaServer {
    try { $null = Invoke-WebRequest "http://127.0.0.1:11434/api/version" -UseBasicParsing -TimeoutSec 3; return $true } catch { return $false }
}
if (-not (Test-OllamaServer)) {
    Write-Linha "[Ollama] Iniciando servidor local..." Green
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Test-OllamaServer); $i++) { Start-Sleep -Seconds 1 }
}
if (-not (Test-OllamaServer)) {
    Write-Linha "[Ollama] O servidor nao respondeu em http://127.0.0.1:11434. Abra o app Ollama e rode o script de novo." Red
    return
}

Write-Linha "[Ollama] Baixando modelo $Modelo (pode demorar)..." Green
$ErrorActionPreference = "Continue"
& $ollamaExe pull $Modelo
if ($LASTEXITCODE -ne 0) {
    Write-Linha "[Ollama] Falha ao baixar $Modelo. Verifique a internet ou escolha outro com -Modelo." Red
    return
}

# ------------------------------------------------------------ 6. Ligar no rodizio
Set-EnvKey $envPath "OLLAMA_ENABLED" "1"
Set-EnvKey $envPath "OLLAMA_MODEL" $Modelo
Set-EnvKey $envPath "OLLAMA_HW_TIER" $tier

Write-Linha "`n==========================================================" Cyan
Write-Linha "  OLLAMA PRONTO: modelo $Modelo ligado ao rodizio do BiazziTech AI Studio" Green
if ($tier -eq "abaixo_minimo") {
    Write-Linha "  Lembrete: maquina abaixo do minimo -> desempenho pode ser muito prejudicado." Red
}
Write-Linha "  No painel/proxy use o modelo 'ollama/auto' para forcar o uso local." Gray
Write-Linha "==========================================================" Cyan
