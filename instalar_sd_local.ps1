# =====================================================================
# BIAZZITECH AI STUDIO - STABLE DIFFUSION LOCAL (IMAGENS OFFLINE, COM LORAS)
# Motor: stable-diffusion.cpp (executavel pequeno, sem Python/PyTorch;
#        Vulkan = qualquer placa NVIDIA/AMD/Intel, inclusive integrada; ou so CPU)
# Analisa a maquina, instala a versao LEVE (SD 1.5) e, se sobrar recurso,
# oferece tambem a PESADA (SDXL). Compativel com Windows PowerShell 5.1+.
# =====================================================================
#
# Uso:
#   .\instalar_sd_local.ps1                         -> analisa e pergunta
#   .\instalar_sd_local.ps1 -SomenteVerificar       -> so mostra a analise
#   .\instalar_sd_local.ps1 -Instalar sim           -> instala a leve sem perguntar
#   .\instalar_sd_local.ps1 -Instalar sim -Versao ambas   -> leve + pesada (se a maquina aguentar)
#   .\instalar_sd_local.ps1 -Instalar sim -Versao pesado -Forcar  -> pesada mesmo sem recurso
#   .\instalar_sd_local.ps1 -Backend cpu            -> forca o motor so de processador

param (
    [ValidateSet("perguntar", "sim", "nao")]
    [string]$Instalar = "perguntar",
    [ValidateSet("auto", "leve", "pesado", "ambas")]
    [string]$Versao = "auto",
    [ValidateSet("auto", "vulkan", "cpu")]
    [string]$Backend = "auto",
    [switch]$SomenteVerificar,
    [switch]$Forcar,
    [switch]$SemTeste
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$envPath = Join-Path $userHome ".env"
$dataDir = if ($env:BIAZZITECH_HOME) { $env:BIAZZITECH_HOME } else { Join-Path $userHome ".biazzitech" }
$sdDir = Join-Path $dataDir "sdlocal"
$porta = 7861

# Downloads (fontes oficiais; conferidos em 2026-11)
$ENGINE_REPO = "leejet/stable-diffusion.cpp"
$HF = "https://huggingface.co"
$LEVE = @(
    @{ Nome = "SD 1.5 (quantizado Q8, GGUF)"; Url = "$HF/second-state/stable-diffusion-v1-5-GGUF/resolve/main/stable-diffusion-v1-5-pruned-emaonly-Q8_0.gguf"; Pasta = "checkpoints"; Arquivo = "stable-diffusion-v1-5-pruned-emaonly-Q8_0.gguf"; MB = 1764 },
    @{ Nome = "LoRA LCM para SD 1.5 (modo rapido)"; Url = "$HF/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors"; Pasta = "loras"; Arquivo = "lcm-lora-sdv1-5.safetensors"; MB = 135 }
)
$PESADO = @(
    @{ Nome = "SDXL base 1.0"; Url = "$HF/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"; Pasta = "checkpoints"; Arquivo = "sd_xl_base_1.0.safetensors"; MB = 6938 },
    @{ Nome = "VAE do SDXL (fp16 corrigido)"; Url = "$HF/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors"; Pasta = "vae"; Arquivo = "sdxl.vae.safetensors"; MB = 335 },
    @{ Nome = "LoRA LCM para SDXL (modo rapido)"; Url = "$HF/latent-consistency/lcm-lora-sdxl/resolve/main/pytorch_lora_weights.safetensors"; Pasta = "loras"; Arquivo = "lcm-lora-sdxl.safetensors"; MB = 394 },
    @{ Nome = "LoRA de pixel art para SDXL (pixel-art-xl)"; Url = "$HF/nerijs/pixel-art-xl/resolve/main/pixel-art-xl.safetensors"; Pasta = "loras"; Arquivo = "pixel-art-xl.safetensors"; MB = 171 }
)

$MIN_RAM_GB = 7.5          # leve: 8 GB nominais
$MIN_DISK_LEVE_GB = 5
$PESADO_REC_VRAM = 7.5     # pesado recomendado: placa de 8 GB
$PESADO_MIN_VRAM = 3.5     # pesado possivel: placa de 4 GB ...
$PESADO_MIN_RAM = 23       # ... com 24 GB de RAM (parte do modelo fica na RAM)
$MIN_DISK_PESADO_GB = 12

function Write-Linha($txt, $cor = "Gray") { Write-Host $txt -ForegroundColor $cor }
function Test-Interativo { try { return (-not [Console]::IsInputRedirected) -and [Environment]::UserInteractive } catch { return $false } }
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
    if ($val -ne "") { $lines += "$key=$val" }
    [System.IO.File]::WriteAllLines($file, [string[]]$lines, $utf8NoBom)
}

# ------------------------------------------------------------ 1. Analise da maquina
Write-Linha "`n==========================================================" Cyan
Write-Linha "   STABLE DIFFUSION LOCAL - ANALISE DA MAQUINA" Yellow
Write-Linha "==========================================================" Cyan

$cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor)
$ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$cores = ($cpu | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
$is64 = [Environment]::Is64BitOperatingSystem
$driveLetter = (Split-Path -Qualifier $userHome).TrimEnd(":")
$diskFreeGB = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)

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
$gpus = @($gpus | Where-Object { $_.Nome -notmatch "Basic Display|Remote|Virtual|Parsec|Meta" } | Sort-Object Nome -Unique)
$vramGB = 0
if ($gpus) { $vramGB = ($gpus | Measure-Object -Property VramGB -Maximum).Maximum }

Write-Linha ("  Processador:    {0} ({1} nucleos logicos)" -f (($cpu[0].Name -replace "\s+", " ").Trim()), $cores)
Write-Linha ("  Memoria RAM:    {0} GB" -f $ramGB)
Write-Linha ("  Disco livre:    {0} GB em {1}:" -f $diskFreeGB, $driveLetter)
foreach ($g in $gpus) { Write-Linha ("  Placa de video: {0} ({1} GB)" -f $g.Nome, $g.VramGB) }

if ($Backend -eq "auto") { $Backend = if ($gpus) { "vulkan" } else { "cpu" } }
Write-Linha ("  Motor:          stable-diffusion.cpp ({0})" -f $(if ($Backend -eq "vulkan") { "Vulkan: usa a placa de video" } else { "so processador - funciona, mas e lento" }))

# Leve
$probLeve = @()
if (-not $is64) { $probLeve += "Windows 32 bits (precisa de 64 bits)" }
if ($ramGB -lt $MIN_RAM_GB) { $probLeve += "RAM de $ramGB GB (minimo 8 GB)" }
if ($diskFreeGB -lt $MIN_DISK_LEVE_GB) { $probLeve += "apenas $diskFreeGB GB livres (minimo $MIN_DISK_LEVE_GB GB)" }
# Pesado
if ($vramGB -ge $PESADO_REC_VRAM -and $diskFreeGB -ge $MIN_DISK_PESADO_GB) { $pesado = "recomendado" }
elseif ($vramGB -ge $PESADO_MIN_VRAM -and $ramGB -ge $PESADO_MIN_RAM -and $diskFreeGB -ge $MIN_DISK_PESADO_GB) { $pesado = "possivel" }
else { $pesado = "nao" }

Write-Linha ""
if ($probLeve) {
    Write-Linha "  VERSAO LEVE (SD 1.5): ABAIXO DO MINIMO - NAO RECOMENDADO." Red
    foreach ($p in $probLeve) { Write-Linha "   - $p" Red }
} elseif ($Backend -eq "cpu") {
    Write-Linha "  VERSAO LEVE (SD 1.5): FUNCIONA, mas sem placa de video cada imagem pode levar 1-3 minutos (modo rapido LCM)." Yellow
} else {
    Write-Linha "  VERSAO LEVE (SD 1.5): OK - imagens 512px em segundos com o modo rapido (LCM). ~1.9 GB para baixar." Green
}
switch ($pesado) {
    "recomendado" { Write-Linha "  VERSAO PESADA (SDXL): RECOMENDADA - a placa aguenta bem. ~7.8 GB para baixar." Green }
    "possivel" { Write-Linha "  VERSAO PESADA (SDXL): POSSIVEL, mas lenta (placa de $vramGB GB; parte do modelo fica na RAM). ~7.8 GB." Yellow }
    "nao" { Write-Linha "  VERSAO PESADA (SDXL): nao recomendada nesta maquina (precisa de placa com 8 GB, ou 4 GB + 24 GB de RAM)." DarkYellow }
}

if ($SomenteVerificar) { Write-Linha "`n[Somente verificacao] Nada foi instalado." Gray; return }

# ------------------------------------------------------------ 2. Decisao
if ($Instalar -eq "nao") { Write-Linha "`n[SD local] Instalacao ignorada (-Instalar nao)." Gray; return }
$querLeve = $true
$querPesado = $false
if ($Versao -eq "pesado") { $querLeve = $false; $querPesado = $true }
if ($Versao -eq "ambas") { $querPesado = $true }
if ($Instalar -eq "perguntar") {
    if ($Versao -in @("auto", "leve", "ambas")) {
        $querLeve = Read-SimNao "`n  Instalar a versao LEVE (SD 1.5, ~1.9 GB)?" (-not $probLeve)
    }
    if ($Versao -eq "auto" -and $pesado -ne "nao") {
        $querPesado = Read-SimNao "  A maquina aguenta: instalar TAMBEM a versao PESADA (SDXL, ~7.8 GB)?" ($pesado -eq "recomendado")
    }
}
if ($querLeve -and $probLeve -and -not $Forcar -and $Instalar -ne "perguntar") {
    Write-Linha "  Leve abaixo do minimo: use -Forcar para instalar mesmo assim." Red; $querLeve = $false
}
if ($querPesado -and $pesado -eq "nao" -and -not $Forcar) {
    Write-Linha "  Pesada nao recomendada nesta maquina: use -Forcar para instalar mesmo assim." Yellow; $querPesado = $false
}
if (-not ($querLeve -or $querPesado)) { Write-Linha "`n[SD local] Nada para instalar." Gray; return }

Write-Linha "`n  Licencas: os modelos SD 1.5 / SDXL e as LoRAs usam licencas abertas OpenRAIL (uso livre, inclusive" Gray
Write-Linha "  comercial, com restricoes de uso nocivo) e MIT. Ao continuar voce aceita esses termos:" Gray
Write-Linha "  https://huggingface.co/spaces/CompVis/stable-diffusion-license" Gray
if ($Instalar -eq "perguntar" -and -not (Read-SimNao "  Continuar?" $true)) { return }

# ------------------------------------------------------------ 3. Motor (stable-diffusion.cpp)
foreach ($d in @($sdDir, (Join-Path $sdDir "bin"), (Join-Path $sdDir "models\checkpoints"), (Join-Path $sdDir "models\loras"), (Join-Path $sdDir "models\vae"))) {
    New-Item -ItemType Directory -Force $d | Out-Null
}

function Install-Engine([string]$tipo) {
    Write-Linha "`n[1/3] Baixando o motor stable-diffusion.cpp ($tipo)..." Green
    $rel = Invoke-RestMethod "https://api.github.com/repos/$ENGINE_REPO/releases/latest" -Headers @{ "User-Agent" = "BiazziTech-AI-Studio" }
    $asset = $rel.assets | Where-Object { $_.name -match "bin-win-$tipo-x64\.zip$" } | Select-Object -First 1
    if (-not $asset) { throw "Nao achei o pacote win-$tipo na versao $($rel.tag_name)." }
    Write-Linha ("  {0} ({1} MB) - versao {2}" -f $asset.name, [math]::Round($asset.size / 1MB), $rel.tag_name)
    $zip = Join-Path $env:TEMP $asset.name
    & curl.exe -L --fail --progress-bar -o $zip $asset.browser_download_url
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar o motor." }
    $bin = Join-Path $sdDir "bin"
    Get-ChildItem $bin -Force | Remove-Item -Recurse -Force
    Expand-Archive -Path $zip -DestinationPath $bin -Force
    Remove-Item $zip -Force
    $exe = Get-ChildItem $bin -Recurse -Filter "sd-server.exe" | Select-Object -First 1
    if (-not $exe) { throw "O pacote nao trouxe o sd-server.exe." }
    if ($exe.DirectoryName -ne $bin) {  # pacote com subpasta: traz tudo para bin\
        Get-ChildItem $exe.DirectoryName -Force | Move-Item -Destination $bin -Force
    }
    Set-Content (Join-Path $sdDir "versao.txt") "$($rel.tag_name) $tipo" -Encoding ascii
    Write-Linha "  -> motor em $bin" Gray
}

Install-Engine $Backend

# ------------------------------------------------------------ 4. Modelos
function Get-Arquivo($item) {
    $dest = Join-Path (Join-Path $sdDir "models") (Join-Path $item.Pasta $item.Arquivo)
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt ($item.MB * 1000000 * 0.99))) {
        Write-Linha ("  -> {0}: ja baixado" -f $item.Nome) Gray; return
    }
    Write-Linha ("  {0} (~{1} MB)" -f $item.Nome, $item.MB)
    & curl.exe -L --fail -C - --progress-bar -o $dest $item.Url   # -C -: continua de onde parou
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar $($item.Nome). Rode de novo para continuar de onde parou." }
}
Write-Linha "`n[2/3] Baixando os modelos (da para interromper e rodar de novo: continua de onde parou)..." Green
$lista = @()
if ($querLeve) { $lista += $LEVE }
if ($querPesado) { $lista += $PESADO }
foreach ($item in $lista) { Get-Arquivo $item }

# ------------------------------------------------------------ 5. Configuracao + teste
$modeloPadrao = if ($querLeve) { $LEVE[0].Arquivo } else { $PESADO[0].Arquivo }
Set-EnvKey $envPath "SDLOCAL_ENABLED" "1"
Set-EnvKey $envPath "SDLOCAL_MODEL" $modeloPadrao
Set-EnvKey $envPath "SDLOCAL_BACKEND" $Backend
# SDXL em placa de menos de 8 GB: parte do modelo fica na RAM (mais lento, mas cabe)
Set-EnvKey $envPath "SDLOCAL_ARGS_SDXL" $(if ($querPesado -and $vramGB -lt $PESADO_REC_VRAM) { "--offload-to-cpu" } else { "" })

function Test-Motor {
    $exe = Join-Path $sdDir "bin\sd-server.exe"
    $modelo = Join-Path $sdDir "models\checkpoints\$modeloPadrao"
    $log = Join-Path $sdDir "teste.log"
    $p = Start-Process -FilePath $exe -ArgumentList @("--model-dir", "`"$(Join-Path $sdDir 'models')`"", "--listen-ip", "127.0.0.1",
        "--listen-port", "$porta", "--model", "`"$modelo`"") -WorkingDirectory $sdDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    $ok = $false
    for ($i = 0; $i -lt 90 -and -not $ok -and -not $p.HasExited; $i++) {
        Start-Sleep -Seconds 1
        $r = & curl.exe -s -f "http://127.0.0.1:$porta/sdapi/v1/options"
        $ok = ($LASTEXITCODE -eq 0 -and $r)
    }
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    return $ok
}

if (-not $SemTeste) {
    Write-Linha "`n[3/3] Testando o motor..." Green
    $ok = Test-Motor
    if (-not $ok -and $Backend -eq "vulkan") {
        Write-Linha "  O motor Vulkan nao iniciou nesta placa; trocando para o motor so de processador..." Yellow
        Install-Engine "cpu"
        Set-EnvKey $envPath "SDLOCAL_BACKEND" "cpu"
        $ok = Test-Motor
    }
    if ($ok) { Write-Linha "  -> motor OK" Green }
    else { Write-Linha "  [AVISO] O motor nao respondeu no teste. Veja $sdDir\teste.log" Yellow }
}

Write-Linha "`n==========================================================" Cyan
Write-Linha "  STABLE DIFFUSION LOCAL INSTALADO" Green
Write-Linha "==========================================================" Cyan
Write-Linha "  No painel: aba Imagens > Gerador: 'Stable Diffusion local (offline, LoRAs)'."
Write-Linha "  Modelos: $(Join-Path $sdDir 'models\checkpoints')"
Write-Linha "  LoRAs:   $(Join-Path $sdDir 'models\loras')  (coloque aqui as que baixar, ex.: civitai.com)"
Write-Linha "  Reinicie o painel (feche e abra o atalho) para ele ler a configuracao nova."
