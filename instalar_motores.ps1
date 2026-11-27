# =====================================================================
# INSTALADOR - BIAZZITECH AI STUDIO
# Funciona STAND-ALONE (so precisa de Python) e, se o Google Antigravity
# estiver na maquina, tambem como painel lateral (Sidecar) + servidor MCP.
# Compativel com Windows PowerShell 5.1+ e PowerShell 7+
# =====================================================================
#
# Exemplos:
#   .\instalar_motores.ps1                          -> detecta o Antigravity sozinho
#   .\instalar_motores.ps1 -Modo standalone         -> nao mexe no Antigravity
#   .\instalar_motores.ps1 -IniciarComWindows       -> servidor sobe junto com o Windows
#   .\instalar_motores.ps1 -Porta 9191 -AcessoRede sim  -> outra porta, liberado na rede local
#   .\instalar_motores.ps1 -Ollama nao -SemPerguntas  -> sem perguntas (automatizado)

param (
    [string]$DeepSeekKey = "",
    [string]$PollinationsKey = "",
    [string]$PixAIKey = "",
    [string]$GeminiKey = "",
    [string]$GroqKey = "",
    [string]$OpenRouterKey = "",
    [string]$XaiKey = "",
    [string]$OllamaCloudKey = "",
    [string]$OpenAIKey = "",
    [string]$ClaudeKey = "",
    [string]$PixelLabKey = "",
    [string]$RetroDiffusionKey = "",
    [string]$ScenarioKey = "",
    # auto = integra com o Antigravity so se ele estiver instalado
    [ValidateSet("auto", "standalone", "antigravity")]
    [string]$Modo = "auto",
    # IA local (Ollama): perguntar | sim | nao
    [ValidateSet("perguntar", "sim", "nao")]
    [string]$Ollama = "perguntar",
    # Imagens offline com LoRAs (Stable Diffusion local): perguntar | sim | nao
    [ValidateSet("perguntar", "sim", "nao")]
    [string]$SDLocal = "perguntar",
    # Porta do servidor (0 = perguntar / manter a atual; padrao 9090)
    [int]$Porta = 0,
    # Acesso por outras maquinas da rede local: perguntar | sim | nao
    [ValidateSet("perguntar", "sim", "nao")]
    [string]$AcessoRede = "perguntar",
    # Servidor sobe junto com o Windows (sem abrir o navegador)
    [switch]$IniciarComWindows,
    # Nao criar atalho na Area de Trabalho
    [switch]$SemAtalho,
    # Nao fazer perguntas (chaves que faltam, iniciar com o Windows)
    [switch]$SemPerguntas
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$envPath = Join-Path $userHome ".env"
$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Pasta propria do kit (stand-alone): scripts, imagens geradas e estado do rodizio
$appHome = Join-Path $userHome ".biazzitech"
$appDir = Join-Path $appHome "app"

# Pastas do Antigravity (usadas so na integracao)
$geminiDir = Join-Path $userHome ".gemini"
$geminiConfigDir = Join-Path $geminiDir "config"
$geminiPluginsDir = Join-Path $geminiConfigDir "plugins"
$geminiScriptsDir = Join-Path (Join-Path $geminiDir "antigravity") "scripts"

$interativo = $false
try { $interativo = (-not [Console]::IsInputRedirected) -and [Environment]::UserInteractive } catch {}

function Read-SimNao([string]$pergunta, [bool]$padrao) {
    if (-not $interativo -or $SemPerguntas) { return $padrao }
    $sufixo = if ($padrao) { "[S/n]" } else { "[s/N]" }
    try { $r = Read-Host "$pergunta $sufixo" } catch { return $padrao }
    if ([string]::IsNullOrWhiteSpace($r)) { return $padrao }
    return ($r.Trim().ToLower() -in @("s", "sim", "y", "yes"))
}

# Antigravity instalado nesta maquina?
$temAntigravity = (Test-Path $geminiDir) -or
    (Test-Path (Join-Path $env:LOCALAPPDATA "Programs\Antigravity")) -or
    [bool](Get-Command antigravity -ErrorAction SilentlyContinue)
$integrarAntigravity = switch ($Modo) {
    "standalone" { $false }
    "antigravity" { $true }
    default { $temAntigravity }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  INSTALADOR - BIAZZITECH AI STUDIO                       " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan
if ($integrarAntigravity) {
    Write-Host "  Modo: stand-alone + integracao com o Antigravity (Sidecar e MCP)" -ForegroundColor Gray
} else {
    Write-Host "  Modo: stand-alone (Antigravity nao encontrado ou desativado com -Modo standalone)" -ForegroundColor Gray
}

# ------------------------------------------------------------ 1. Chaves
Write-Host "`n[1/6] Gravando chaves de API em $envPath..." -ForegroundColor Green

function Set-EnvKey([string]$file, [string]$key, [string]$val) {
    if (-not $val) { return }
    $lines = @()
    if (Test-Path $file) {
        $lines = @(Get-Content $file -Encoding UTF8 | ForEach-Object { $_.TrimStart([char]0xFEFF) } |
            Where-Object { $_.Trim() -ne "" -and $_ -notmatch "^$key=" })
    }
    $lines += "$key=$val"
    [System.IO.File]::WriteAllLines($file, [string[]]$lines, $utf8NoBom)
}

function Get-EnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return "" }
    foreach ($l in (Get-Content $file -Encoding UTF8)) {
        $c = $l.TrimStart([char]0xFEFF)
        if ($c -match "^$key=(.*)$") { return $Matches[1].Trim() }
    }
    return ""
}

Set-EnvKey $envPath "DEEPSEEK_API_KEY" $DeepSeekKey
Set-EnvKey $envPath "POLLINATIONS_API_KEY" $PollinationsKey
Set-EnvKey $envPath "PIXAI_API_KEY" $PixAIKey
Set-EnvKey $envPath "GEMINI_API_KEY" $GeminiKey
Set-EnvKey $envPath "GROQ_API_KEY" $GroqKey
Set-EnvKey $envPath "OPENROUTER_API_KEY" $OpenRouterKey
Set-EnvKey $envPath "XAI_API_KEY" $XaiKey
Set-EnvKey $envPath "OLLAMA_API_KEY" $OllamaCloudKey
Set-EnvKey $envPath "OPENAI_API_KEY" $OpenAIKey
Set-EnvKey $envPath "CLAUDE_API_KEY" $ClaudeKey
Set-EnvKey $envPath "PIXELLAB_API_KEY" $PixelLabKey
Set-EnvKey $envPath "RETRODIFFUSION_API_KEY" $RetroDiffusionKey
Set-EnvKey $envPath "SCENARIO_API_KEY" $ScenarioKey

# Se faltar chave de algum provedor gratuito, oferece abrir o site e colar a chave aqui
if ($interativo -and -not $SemPerguntas) {
    $gratis = @(
        @{ Nome = "Google Gemini"; Chave = "GEMINI_API_KEY"; Url = "https://aistudio.google.com/apikey" },
        @{ Nome = "Groq"; Chave = "GROQ_API_KEY"; Url = "https://console.groq.com/keys" },
        @{ Nome = "OpenRouter"; Chave = "OPENROUTER_API_KEY"; Url = "https://openrouter.ai/settings/keys" }
    )
    foreach ($g in $gratis) {
        if (Get-EnvValue $envPath $g.Chave) { continue }
        Write-Host ("  Nenhuma chave {0} encontrada ({1} tem plano gratis)." -f $g.Chave, $g.Nome) -ForegroundColor Yellow
        if (Read-SimNao "  Abrir o site para criar a chave agora?" $false) {
            Start-Process $g.Url
            $k = Read-Host "  Cole a chave aqui (ou Enter para pular)"
            if ($k -and $k.Trim()) {
                Set-EnvKey $envPath $g.Chave $k.Trim()
                Write-Host "  -> Chave $($g.Chave) salva." -ForegroundColor Gray
            }
        }
    }
    Write-Host "  (Tambem da para criar/trocar chaves depois na aba Provedores do painel.)" -ForegroundColor Gray
}

# ------------------------------------------------------------ Python
$pythonCmd = $null      # comando curto (python / py) para o Antigravity
$pythonExe = $null      # caminho completo para os atalhos
$pythonArgsPrefix = ""
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd -and $cmd.Source -notmatch "WindowsApps") {
    $pythonCmd = "python"; $pythonExe = $cmd.Source
} else {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $pythonCmd = "py"; $pythonExe = $cmd.Source; $pythonArgsPrefix = "-3 " }
}
if (-not $pythonExe) {
    Write-Host "`n[ERRO] Python 3.8+ nao encontrado. Instale em https://www.python.org/downloads/ (marque 'Add to PATH')" -ForegroundColor Red
    Write-Host "       ou use a versao .exe do BiazziTech AI Studio (build_exe.ps1), que nao precisa de Python." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------ 2. App stand-alone
Write-Host "[2/6] Instalando o BiazziTech AI Studio em $appDir..." -ForegroundColor Green
New-Item -ItemType Directory -Path $appDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appHome "imagens") -Force | Out-Null

$tools = @("biazzitech_studio.py", "studio_server.py", "provider_router.py", "image_providers.py", "access_control.py", "doc_extract.py", "prompt_assist.py", "characters.py", "comic_layouts.py", "conversations.py", "godot_export.py", "sd_local.py", "studio_ui.html",
           "studio_mcp.py", "studio_cli.py", "free_image_gen.py", "pixai_gen.py")
foreach ($t in $tools) {
    $src = Join-Path $sourceDir $t
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $appDir $t) -Force
        Write-Host "  -> $t" -ForegroundColor Gray
    }
}
# Arquivos do painel (CSS/JS)
$uiSrc = Join-Path $sourceDir "ui"
if (Test-Path $uiSrc) {
    $uiDst = Join-Path $appDir "ui"
    New-Item -ItemType Directory -Path $uiDst -Force | Out-Null
    Copy-Item -Path (Join-Path $uiSrc "*") -Destination $uiDst -Recurse -Force
    Write-Host "  -> ui\" -ForegroundColor Gray
}
# Nomes antigos (antes da v1.0): deepseek_proxy/mcp/cli viraram studio_server/mcp/cli
foreach ($velho in @("deepseek_proxy.py", "deepseek_mcp.py", "deepseek_cli.py")) {
    foreach ($pasta in @($appDir, $geminiScriptsDir)) {
        $v = Join-Path $pasta $velho
        if (Test-Path $v) { Remove-Item $v -Force; Write-Host "  -> removido nome antigo: $v" -ForegroundColor Gray }
    }
}
# Leitura de PDF nos anexos: biblioteca opcional pypdf
$pyPre = @(); if ($pythonArgsPrefix) { $pyPre = @("-3") }
& $pythonExe @($pyPre + @("-c", "import pypdf")) 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  A biblioteca 'pypdf' (para ler anexos .pdf) nao esta instalada." -ForegroundColor Yellow
    if (Read-SimNao "  Instalar agora com pip (baixa do PyPI)?" $true) {
        & $pythonExe @($pyPre + @("-m", "pip", "install", "--user", "--quiet", "pypdf"))
        if ($LASTEXITCODE -eq 0) { Write-Host "  -> pypdf instalado." -ForegroundColor Gray }
        else { Write-Host "  [AVISO] Nao deu para instalar o pypdf; PDFs serao lidos so de forma basica." -ForegroundColor Yellow }
    } else {
        Write-Host "  -> Sem pypdf: .docx/.md/.txt funcionam; PDF so de forma basica." -ForegroundColor Gray
    }
}

# Aproveita o estado do rodizio da instalacao antiga (esperas, uso do dia)
$oldState = Join-Path (Join-Path $geminiDir "antigravity") "router_state.json"
$newState = Join-Path $appHome "router_state.json"
if ((Test-Path $oldState) -and -not (Test-Path $newState)) { Copy-Item $oldState $newState }

# ------------------------------------------------------------ 3. Porta, usuarios e acesso pela rede
Write-Host "[3/6] Porta, usuarios e acesso pela rede..." -ForegroundColor Green
$ac = Join-Path $appDir "access_control.py"
function Invoke-Access { param([string[]]$a, [string]$stdin = $null)
    $full = @()
    if ($pythonArgsPrefix) { $full += "-3" }
    $full += $ac
    $full += $a
    if ($null -ne $stdin) { return ($stdin | & $pythonExe @full) }
    return (& $pythonExe @full)
}
$cfgAtual = (Invoke-Access @("show") | Out-String | ConvertFrom-Json)
$portaAtual = [int]$cfgAtual.config.port

# Porta: o servidor do proprio kit rodando nela nao conta como "ocupada"
function Test-NossaPorta([int]$p) {
    try { return ((Invoke-RestMethod "http://127.0.0.1:$p/healthz" -TimeoutSec 2).app -eq "biazzitech") } catch { return $false }
}
$portaEscolhida = $Porta
if ($portaEscolhida -eq 0 -and $interativo -and -not $SemPerguntas) {
    while ($true) {
        $r = Read-Host "  Porta do servidor (Enter = $portaAtual; evite 8080 do Tomcat)"
        if ([string]::IsNullOrWhiteSpace($r)) { $portaEscolhida = $portaAtual; break }
        if ($r -notmatch "^\d+$") { Write-Host "  Digite so numeros." -ForegroundColor Yellow; continue }
        $extra = @(); if (Test-NossaPorta ([int]$r)) { $extra = @("--allow-in-use") }
        $res = Invoke-Access (@("check-port", $r) + $extra)
        if ($res -match "^ok") { $portaEscolhida = [int]$r; break }
        Write-Host "  $res" -ForegroundColor Yellow
    }
}
if ($portaEscolhida -eq 0) { $portaEscolhida = $portaAtual }
$extra = @(); if (Test-NossaPorta $portaEscolhida) { $extra = @("--allow-in-use") }
$res = Invoke-Access (@("set", "port", "$portaEscolhida") + $extra)
if ($res -notmatch "^ok") {
    Write-Host "  [AVISO] $res  -> mantendo a porta $portaAtual" -ForegroundColor Yellow
    $portaEscolhida = $portaAtual
}
Write-Host "  -> Porta: $portaEscolhida" -ForegroundColor Gray

# Usuario administrador (opcional; sem usuarios o acesso e livre)
$temUsuarios = @($cfgAtual.users).Count -gt 0
if (-not $temUsuarios -and $interativo -and -not $SemPerguntas) {
    Write-Host "  Sem usuarios cadastrados o acesso e livre (recomendado criar um se for liberar na rede)." -ForegroundColor Gray
    if (Read-SimNao "  Criar um usuario administrador agora?" $false) {
        while ($true) {
            $nome = Read-Host "    Nome do usuario"
            $s1 = Read-Host "    Senha (min. 6)" -AsSecureString
            $s2 = Read-Host "    Repita a senha" -AsSecureString
            $p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
            $p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
            if ($p1 -ne $p2) { Write-Host "    As senhas nao conferem." -ForegroundColor Yellow; continue }
            $out = Invoke-Access @("add-user", $nome, "--perms", "chat,imagens,admin") $p1
            $p1 = $null; $p2 = $null
            if (($out | Out-String) -match "ERRO") { Write-Host "    $out" -ForegroundColor Yellow; continue }
            $tok = (($out | Select-String "TOKEN_API=") -replace "TOKEN_API=", "")
            Write-Host "    -> Administrador '$nome' criado." -ForegroundColor Gray
            Write-Host "    -> Token para Continue/Cline (guarde, nao aparece de novo): $tok" -ForegroundColor DarkYellow
            $temUsuarios = $true
            break
        }
    }
}

# Acesso pela rede local
$lan = $null
if ($AcessoRede -eq "sim") { $lan = $true }
elseif ($AcessoRede -eq "nao") { $lan = $false }
elseif ($interativo -and -not $SemPerguntas) {
    if (-not $temUsuarios) {
        Write-Host "  (Acesso pela rede exige um usuario com senha; sem usuarios o painel funciona so neste PC.)" -ForegroundColor Gray
    } else {
        Write-Host "  Riscos: na rede, outras maquinas usam as chaves deste PC (com login). Sem HTTPS, senha e conversas" -ForegroundColor Yellow
        Write-Host "  trafegam sem criptografia. Use so em rede de confianca e NUNCA abra a porta no roteador (para acesso" -ForegroundColor Yellow
        Write-Host "  de fora, use uma VPN como o Tailscale). Software sem garantias (AGPL-3.0)." -ForegroundColor Yellow
        $lan = Read-SimNao "  Entendi os riscos. Liberar acesso por outras maquinas da rede local?" ([bool]$cfgAtual.config.lan)
    }
}
if ($lan -and -not $temUsuarios) {
    Write-Host "  [AVISO] Acesso pela rede nao liberado: crie um usuario antes (aba Acesso do painel ou rode o instalador de novo)." -ForegroundColor Yellow
    $lan = $null
}
if ($null -ne $lan) { $null = Invoke-Access @("set", "lan", "$lan".ToLower()) }
$cfgFinal = (Invoke-Access @("show") | Out-String | ConvertFrom-Json)
if ($cfgFinal.lan_active) {
    $esquema = if ($cfgFinal.https.ready) { "https" } else { "http" }
    $portaRede = if ($cfgFinal.https.ready) { $cfgFinal.https.port } else { $portaEscolhida }
    Write-Host "  -> Rede: LIBERADA. Outras maquinas: $((@($cfgFinal.lan_ips) | ForEach-Object { "$($esquema)://$($_):$portaRede" }) -join '  ')" -ForegroundColor Gray
    if (-not $cfgFinal.https.ready) { Write-Host "     Sem HTTPS: veja no README como ativar (mkcert)." -ForegroundColor Yellow }
    Write-Host "     (se o Windows perguntar sobre o firewall, permita em 'Redes privadas')" -ForegroundColor Gray
} else {
    Write-Host "  -> Rede: somente este PC (da para liberar depois na aba Acesso do painel)" -ForegroundColor Gray
}

# ------------------------------------------------------------ 4. Antigravity (opcional)
if ($integrarAntigravity) {
    Write-Host "[4/6] Integrando com o Antigravity (Sidecar + MCP)..." -ForegroundColor Green
    foreach ($d in @($geminiConfigDir, $geminiPluginsDir, $geminiScriptsDir)) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }
    # Copia de compatibilidade (atalhos antigos usam esta pasta)
    foreach ($t in $tools) {
        $src = Join-Path $sourceDir $t
        if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $geminiScriptsDir $t) -Force }
    }

    # Plugin + Sidecar (pasta de usuario: sobrevive aos updates do Antigravity)
    $pluginSrc = Join-Path $sourceDir "plugin_antigravity"
    $pluginDst = Join-Path $geminiPluginsDir "biazzitech-ai-studio"
    $sidecarDst = Join-Path (Join-Path $pluginDst "sidecars") "studio"
    $assetsDst = Join-Path $pluginDst "assets"
    if (Test-Path $pluginSrc) {
        New-Item -ItemType Directory -Path $sidecarDst -Force | Out-Null
        New-Item -ItemType Directory -Path $assetsDst -Force | Out-Null
        Copy-Item -Path (Join-Path $pluginSrc "plugin.json") -Destination (Join-Path $pluginDst "plugin.json") -Force
        Copy-Item -Path (Join-Path $pluginSrc "README.md") -Destination (Join-Path $pluginDst "README.md") -Force
        Copy-Item -Path (Join-Path (Join-Path $pluginSrc "assets") "logo.svg") -Destination (Join-Path $assetsDst "logo.svg") -Force
        Get-ChildItem $sidecarDst -Filter "deepseek_*.py" -ErrorAction SilentlyContinue | Remove-Item -Force
        foreach ($t in @("studio_server.py", "provider_router.py", "image_providers.py", "access_control.py", "doc_extract.py", "prompt_assist.py", "characters.py", "comic_layouts.py", "conversations.py", "godot_export.py", "sd_local.py", "studio_ui.html")) {
            Copy-Item -Path (Join-Path $sourceDir $t) -Destination (Join-Path $sidecarDst $t) -Force
        }
        if (Test-Path $uiSrc) {
            New-Item -ItemType Directory -Path (Join-Path $sidecarDst "ui") -Force | Out-Null
            Copy-Item -Path (Join-Path $uiSrc "*") -Destination (Join-Path $sidecarDst "ui") -Recurse -Force
        }
        $sidecarObj = [PSCustomObject]@{
            command        = $pythonCmd
            args           = @("studio_server.py", "$portaEscolhida")
            description    = "Painel BiazziTech AI Studio (rodizio de IAs, pixel art) e Proxy OpenAI na porta $portaEscolhida."
            display_name   = "BiazziTech AI Studio"
            has_web_ui     = $true
            restart_policy = "always"
            ui_config      = [PSCustomObject]@{
                display_name = "BiazziTech AI Studio"
                views        = @([PSCustomObject]@{
                    entrypoint = "SIDECAR_UI_ENTRYPOINT_AUX_PANE"
                    path       = "/ui.html"
                    title      = "BiazziTech AI Studio"
                })
            }
        }
        [System.IO.File]::WriteAllText((Join-Path $sidecarDst "sidecar.json"), ($sidecarObj | ConvertTo-Json -Depth 10), $utf8NoBom)
        Write-Host "  -> Sidecar: $pluginDst" -ForegroundColor Gray
    }

    # Servidor MCP (preserva outros MCPs da maquina) apontando para a pasta stand-alone
    $mcpJsonPath = Join-Path $geminiConfigDir "mcp_config.json"
    $mcpConfig = $null
    if (Test-Path $mcpJsonPath) {
        try {
            $rawJson = [System.IO.File]::ReadAllText($mcpJsonPath, [System.Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
            if ($rawJson.Trim()) { $mcpConfig = $rawJson | ConvertFrom-Json }
        } catch { $mcpConfig = $null }
    }
    if (-not $mcpConfig) { $mcpConfig = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} } }
    if (-not $mcpConfig.PSObject.Properties["mcpServers"] -or -not $mcpConfig.mcpServers) {
        $mcpConfig | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{}) -Force
    }
    $mcpArgs = @()
    if ($pythonCmd -eq "py") { $mcpArgs += "-3" }
    $mcpArgs += (Join-Path $appDir "studio_mcp.py").Replace("\", "/")
    # registro antigo ("deepseek" -> deepseek_mcp.py) sai; o novo se chama "biazzitech"
    $antigo = $mcpConfig.mcpServers.PSObject.Properties["deepseek"]
    if ($antigo -and (($antigo.Value.args -join " ") -match "deepseek_mcp\.py")) { $mcpConfig.mcpServers.PSObject.Properties.Remove("deepseek") }
    $mcpConfig.mcpServers | Add-Member -NotePropertyName "biazzitech" -NotePropertyValue ([PSCustomObject]@{ command = $pythonCmd; args = $mcpArgs }) -Force
    [System.IO.File]::WriteAllText($mcpJsonPath, ($mcpConfig | ConvertTo-Json -Depth 10), $utf8NoBom)
    Write-Host "  -> MCP 'biazzitech' registrado em: $mcpJsonPath" -ForegroundColor Gray
} else {
    Write-Host "[4/6] Integracao com o Antigravity: pulada (modo stand-alone)." -ForegroundColor Green
}

# ------------------------------------------------------------ 5. Atalhos
Write-Host "[5/6] Atalhos..." -ForegroundColor Green
function New-Atalho([string]$caminho, [string]$extraArgs, [string]$descricao) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($caminho)
    $lnk.TargetPath = $pythonExe
    $lnk.Arguments = ($pythonArgsPrefix + '"' + (Join-Path $appDir "biazzitech_studio.py") + '" ' + $extraArgs).Trim()
    $lnk.WorkingDirectory = $appDir
    $lnk.WindowStyle = 7   # janela minimizada (feche-a para desligar o servidor)
    $lnk.Description = $descricao
    $lnk.Save()
}
if (-not $SemAtalho) {
    $desk = [Environment]::GetFolderPath("Desktop")
    $atalho = Join-Path $desk "BiazziTech AI Studio.lnk"
    New-Atalho $atalho "" "Abre o painel BiazziTech AI Studio (http://localhost:$portaEscolhida)"
    Write-Host "  -> Area de Trabalho: $atalho" -ForegroundColor Gray
}
$startupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "BiazziTech AI Studio (servidor).lnk"
$querAutostart = $IniciarComWindows -or (Read-SimNao "  Iniciar o servidor junto com o Windows (sem abrir o navegador)?" $false)
if ($querAutostart) {
    New-Atalho $startupLnk "--no-browser" "Servidor BiazziTech AI Studio (porta $portaEscolhida)"
    Write-Host "  -> Inicia com o Windows: $startupLnk" -ForegroundColor Gray
} elseif (Test-Path $startupLnk) {
    Write-Host "  -> (ja inicia com o Windows; apague '$startupLnk' para desativar)" -ForegroundColor Gray
}

# ------------------------------------------------------------ 6. IA local + capacidade da maquina
Write-Host "[6/6] IA local (Ollama) e capacidade desta maquina para modelos locais..." -ForegroundColor Green
$ollamaScript = Join-Path $sourceDir "instalar_ollama.ps1"
if (Test-Path $ollamaScript) {
    try { & $ollamaScript -Instalar $Ollama } catch { Write-Host "  [Ollama] Erro: $_" -ForegroundColor Red }
}
# Imagens offline com LoRAs (Stable Diffusion local / stable-diffusion.cpp); sem perguntas = nao baixa nada
$sdScript = Join-Path $sourceDir "instalar_sd_local.ps1"
if (Test-Path $sdScript) {
    $sdModo = $SDLocal
    if ($SemPerguntas -and $sdModo -eq "perguntar") { $sdModo = "nao" }
    try { & $sdScript -Instalar $sdModo } catch { Write-Host "  [SD local] Erro: $_" -ForegroundColor Red }
}


# ------------------------------------------------------------ Resumo
Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  INSTALACAO CONCLUIDA! Painel: http://localhost:$portaEscolhida" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Abrir:        atalho 'BiazziTech AI Studio' na Area de Trabalho" -ForegroundColor White
Write-Host "              (ou: $pythonCmd `"$appDir\biazzitech_studio.py`")" -ForegroundColor Gray
Write-Host "Arquivos:     $appHome  (imagens em $appHome\imagens)" -ForegroundColor White
if ($integrarAntigravity) {
    Write-Host "Antigravity:  reinicie e ative o Sidecar em Plugins > BiazziTech AI Studio" -ForegroundColor White
}
Write-Host "Rodizio IA:   Gemini > Groq > OpenRouter > Ollama Cloud > DeepSeek > ChatGPT > Claude > xAI > Ollama > Pollinations" -ForegroundColor Gray
Write-Host "Proxy OpenAI: http://localhost:$portaEscolhida/v1 (chave: local; com usuarios, use o token btk_ do usuario)" -ForegroundColor Yellow
if ($cfgFinal.lan_active) { Write-Host "Na rede:      $((@($cfgFinal.lan_ips) | ForEach-Object { "$($esquema)://$($_):$portaRede" }) -join '  ')" -ForegroundColor White }
Write-Host "==========================================================" -ForegroundColor Cyan
