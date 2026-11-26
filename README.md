# ⚙ BiazziTech AI Studio

Estúdio de IA para quem cria jogos e histórias: código (Godot 4 / GDScript, Lua, Python, C#), lore, **páginas de quadrinho com personagens consistentes**, pixel art e **exportação direta para o Godot** — alternando sozinho entre vários provedores de IA, gratuitos primeiro.

- **Roda sozinho** (precisa só de Python, ou nem isso com o `.exe`) **ou dentro do Google Antigravity** como painel lateral (Sidecar) + servidor MCP.
- **Rodízio automático** entre Gemini, Groq, OpenRouter, Ollama Cloud, DeepSeek, ChatGPT, Claude, xAI, Ollama local e Pollinations: se um dá limite, falta de saldo ou erro, o próximo responde.
- **Quadrinhos**: fichas de personagem reutilizáveis, 22 modelos de página (grades, dinâmicos com cortes inclinados, mistos), divisão da página descrita em texto, personagem que "vaza" do quadro e **onomatopeias** (hachurado, explosão, tremido) letreiradas na montagem.
- **Imagens**: Flux/Pollinations e **pixel art para jogos** (PixelLab, Retro Diffusion, Scenario), com imagem de referência e animação.
- **Godot 4**: spritesheet vira `SpriteFrames` com animações nomeadas; tileset vira `TileSet` pronto — é só copiar a pasta para o projeto.
- **Imagens offline com LoRAs**: Stable Diffusion local leve (SD 1.5, ~1.9 GB, roda até em placa integrada) e, se a máquina aguentar, o SDXL.
- **Proxy compatível com OpenAI** para Continue, Cline e outras ferramentas.
- **Usuários, senhas e acesso pela rede** (com HTTPS opcional); **porta configurável**.
- Só usa a biblioteca padrão do Python (sem `pip`); testes automáticos a cada envio.

![Chat](docs/img/01-chat.png)

> ### ☕ Pague um cafézinho pro dev!
> O BiazziTech AI Studio é um projeto independente, feito com dedicação e sem anúncios. Se ele te ajudou, apoie a evolução com qualquer valor:
>
> | | |
> |---|---|
> | **PIX** (chave e-mail) | `fausto@biazzitech.com.br` — Favorecido: BiazziTech / Fausto Sousa |
> | **PicPay** | [@faustobiazzi](https://picpay.me/faustobiazzi) |
>
> [![PIX](https://img.shields.io/badge/PIX-fausto%40biazzitech.com.br-32BCAD?logo=pix&logoColor=white)](#-pague-um-cafézinho-pro-dev) [![PicPay](https://img.shields.io/badge/PicPay-%40faustobiazzi-11C76F)](https://picpay.me/faustobiazzi)
>
> No painel, o botão **☕ Pague um cafézinho** (no topo) mostra as mesmas opções com botões de copiar.

---

## Sumário

1. [Instalação](#1-instalação)
2. [Como abrir](#2-como-abrir)
3. [O painel](#3-o-painel)
4. [Rodízio de provedores e chaves](#4-rodízio-de-provedores-e-chaves)
5. [Claude e ChatGPT](#5-claude-e-chatgpt)
6. [Imagens e pixel art](#6-imagens-e-pixel-art) — [quadrinhos](#páginas-de-quadrinho-modelos-divisão-e-onomatopeias) · [fichas de personagem](#fichas-de-personagem) · [Godot](#exportar-para-o-godot-4)
7. [IA local (Ollama)](#7-ia-local-ollama) — [imagens offline com LoRAs](#imagens-offline-com-loras-stable-diffusion-local)
8. [Usuários, senhas, rede e porta](#8-usuários-senhas-rede-e-porta)
9. [Versão .exe (sem Python)](#9-versão-exe-sem-python)
10. [Continue, Cline e outras ferramentas (proxy OpenAI)](#10-continue-cline-e-outras-ferramentas-proxy-openai)
11. [Pastas e arquivos](#11-pastas-e-arquivos)
12. [Segurança](#12-segurança)
13. [Problemas comuns](#13-problemas-comuns)
14. [Licença](#14-licença)
15. [Como o projeto é feito](#15-como-o-projeto-é-feito)

---

## 1. Instalação

**Pré-requisitos:** Windows 10/11, **Python 3.8+** (`python --version`) e Git. O Google Antigravity é **opcional**.

```powershell
git clone https://github.com/faustobiazzi/biazzitech-ai-studio.git
cd biazzitech-ai-studio
powershell -ExecutionPolicy Bypass -File .\instalar_motores.ps1
```

(ou dê duplo-clique em `bat\Instalar_Motores_IA.bat`)

O instalador faz 6 passos e pergunta o que precisar:

| Passo | O que faz |
|---|---|
| 1. Chaves | Grava as chaves em `%USERPROFILE%\.env`. Se faltar chave de um provedor **gratuito** (Gemini, Groq, OpenRouter), oferece abrir o site para criar e colar ali mesmo. |
| 2. App | Instala em `%USERPROFILE%\.biazzitech\app`. |
| 3. Porta, usuários e rede | Pergunta a **porta** (padrão 9090; recusa 8080 e portas ocupadas), oferece criar um **usuário administrador** e — só se houver usuário — explica os riscos e pergunta se libera o **acesso pela rede**. |
| 4. Antigravity | Só se o Antigravity estiver instalado: cria o painel lateral (Sidecar) e registra o servidor MCP `biazzitech`, sem apagar outros MCPs (instalações antigas com o MCP `deepseek` são migradas sozinhas). |
| 5. Atalhos | Atalho **BiazziTech AI Studio** na Área de Trabalho e, se quiser, iniciar com o Windows. |
| 6. IA local | **Analisa a capacidade da máquina** para modelos locais (recomendado / mínimo / abaixo do mínimo) e pergunta se instala o Ollama. |

**Opções úteis:**

```powershell
.\instalar_motores.ps1 -Modo standalone              # nunca mexe no Antigravity
.\instalar_motores.ps1 -Porta 9191 -AcessoRede sim   # outra porta, liberado na rede local
.\instalar_motores.ps1 -IniciarComWindows            # servidor sobe junto com o Windows
.\instalar_motores.ps1 -Ollama nao -SemPerguntas     # automatizado, sem perguntas
.\instalar_motores.ps1 -GroqKey "gsk_..." -GeminiKey "AIza..." -OpenAIKey "sk-..." -ClaudeKey "sk-ant-..."
```

Outras chaves aceitas: `-DeepSeekKey`, `-PollinationsKey`, `-OpenRouterKey`, `-XaiKey`, `-OllamaCloudKey`, `-PixelLabKey`, `-RetroDiffusionKey`, `-ScenarioKey` (formato `CHAVE:SEGREDO`), `-PixAIKey`.

---

## 2. Como abrir

| Jeito | Como |
|---|---|
| **Atalho** (stand-alone) | Duplo-clique em **BiazziTech AI Studio** na Área de Trabalho. Sobe o servidor numa janela minimizada (feche-a para desligar) e abre o navegador. Se já estiver rodando, só abre o painel. |
| **Dentro do Antigravity** | Reinicie o Antigravity → *Skills & Customizations* → *Plugins* → **BiazziTech AI Studio** → em *Sidecars*, **Enable**. Depois, no painel da direita, botão **+** → BiazziTech AI Studio. |
| **Navegador** | `http://localhost:9090` (ou a porta escolhida) com o servidor rodando. |
| **Linha de comando** | `python %USERPROFILE%\.biazzitech\app\biazzitech_studio.py [--port 9191] [--no-browser]` |
| **.bat do repositório** | `bat\Abrir_Painel_Studio_IA.bat`, `bat\Iniciar_Proxy_IA.bat`, `bat\Gerar_GDScript_IA.bat`, `bat\Gerar_Texto_Lore_IA.bat`, `bat\Gerar_Imagem_IA.bat` |

---

## 3. O painel

### Código & Lore
Escolha o **Modelo** (ou *Automático* = rodízio) e o **Modo** (Godot 4.7 GDScript, Lua, Python, C#, Lore & Diálogos, Assistente Livre). Cada resposta mostra qual provedor/modelo respondeu.

**📎 Anexar:** `.docx`, `.md`, `.txt` e `.pdf` entram como material de referência do pedido (até 60 mil caracteres por arquivo). PDF usa a biblioteca `pypdf`: o instalador oferece instalar (ou `pip install pypdf`) e o `.exe` já vem com ela.

As IAs **só devolvem texto — nada é executado na sua máquina**. Quando a resposta tem blocos de código, aparece **"Arquivos na resposta"** com nome sugerido (`.gd`, `.gdshader`, `.py`...), editável, e botões **Baixar** e **Copiar**.

### Imagens
![Imagens](docs/img/02-imagens.png)

Escolha o **Gerador** (Flux/Pollinations, PixelLab, Retro Diffusion, Scenario), o modo/estilo, o tamanho e, se quiser, uma **imagem de referência**. Cada imagem da galeria tem **Abrir**, **Compartilhar**, **Usar como referência**, **Animar**, **Reutilizar prompt**, **Corrigir**, **🎮 Godot** e **Excluir**. Detalhes na [seção 6](#6-imagens-e-pixel-art).

### Provedores
![Provedores](docs/img/03-provedores.png)

Um cartão por provedor, na ordem do rodízio: **ATIVO**, **EM ESPERA** (com o motivo e quando volta) ou **SEM CHAVE**; pedidos de hoje, limites informados pelo provedor e último erro. Sem chave? **Criar chave ↗** abre o site certo e o campo ao lado salva a chave (ela é testada antes). Também: **Trocar chave**, **+ Outra chave**, **Tentar de novo agora**.

### Acesso
![Acesso](docs/img/04-acesso.png)

Liga/desliga o **acesso pela rede**, mostra se o **HTTPS** está ativo (e como ativar), muda a **porta** e gerencia **usuários e permissões**. Só para administradores. Detalhes na [seção 8](#8-usuários-senhas-rede-e-porta).

---

## 4. Rodízio de provedores e chaves

O painel, o proxy, o MCP e os `.bat` usam o `provider_router.py`, que tenta os provedores **nesta ordem** e pula os que não podem responder:

| # | Provedor | Chave no `~/.env` | Plano |
|---|---|---|---|
| 1 | Google Gemini | `GEMINI_API_KEY` | grátis (com limites) |
| 2 | Groq | `GROQ_API_KEY` | grátis (com limites) |
| 3 | OpenRouter | `OPENROUTER_API_KEY` | usa só modelos `:free` |
| 4 | Ollama Cloud | `OLLAMA_API_KEY` | pago (créditos/assinatura) |
| 5 | DeepSeek | `DEEPSEEK_API_KEY` | pago (pré-pago) |
| 6 | ChatGPT (OpenAI) | `OPENAI_API_KEY` | pago |
| 7 | Claude (Anthropic) | `CLAUDE_API_KEY` | pago |
| 8 | xAI Grok | `XAI_API_KEY` | pago |
| 9 | Ollama (local) | `OLLAMA_ENABLED=1`, `OLLAMA_MODEL` | grátis, no seu PC |
| 10 | Pollinations | `POLLINATIONS_API_KEY` | rede de segurança |

**Como decide:**
- **429 (limite)** → espera o tempo que o provedor informar (ou até o reset diário); **402 (sem saldo)** e **401/403 (chave recusada)** → 6 h; **erro de rede/5xx** → 30 s. Volta sozinho.
- Na OpenRouter, se um modelo grátis estiver congestionado, tenta o próximo `:free` antes de pausar o provedor.
- Pedir um modelo específico (`deepseek-reasoner`, `groq/llama-3.3-70b-versatile`, `claude/auto`...) põe o provedor dele em primeiro; os outros ficam de reserva.
- O modelo de cada provedor é escolhido automaticamente (lista renovada a cada 24 h). Para fixar: `GROQ_MODEL=openai/gpt-oss-120b`, `OPENAI_MODEL=...`, `ANTHROPIC_MODEL=...`.
- Mudar a ordem: `ROUTER_ORDER=groq,gemini,openrouter,pollinations`. Limite local por dia: `GEMINI_DAILY_LIMIT=250`.

**Várias chaves do mesmo provedor:** botão **+ Outra chave** (ou `GROQ_API_KEY_2` ... `_9`). Cada uma vira um cartão ("Groq #2") e vai para o **fim do rodízio**: só é usada depois que **todos os outros provedores** falharem. Exceção: se você pedir um modelo daquele serviço (`groq/...`, `groq:...`), a principal e as extras dele vêm primeiro. Entre uma chave e outra do mesmo provedor há uma pausa de `ROUTER_KEY_DELAY` segundos (padrão **5**).

> ⚠ Ter mais de uma chave é normal em alguns casos (conta pessoal e do trabalho, projetos separados), mas **criar várias contas no mesmo serviço só para somar limites grátis costuma violar os termos de uso** e pode levar ao bloqueio de todas as contas. O painel avisa antes; a responsabilidade é de quem usa.

**Terminal:** `python provider_router.py status` · `python provider_router.py teste` · `python provider_router.py reset`

### Provedores personalizados (qualquer servidor compatível com a OpenAI)

Na aba **Provedores**, botão **+ Provedor personalizado** (só administradores). Serve para:

- **Ollama de outro PC da rede** — `http://IP-DO-PC:11434/v1` (no outro PC, deixe o Ollama aceitar conexões da rede com a variável `OLLAMA_HOST=0.0.0.0`).
- **LM Studio** — `http://localhost:1234/v1`.
- **vLLM / SGLang / llama.cpp server** na nuvem ou num servidor próprio — inclusive modelos abertos grandes (ex.: versões abertas do Grok), que não cabem num PC comum.

Campos: **nome**, **URL** (pode digitar só `host:porta`; o painel completa com `/v1`), **chave** (opcional), **modelo** (*Testar conexão* lista os modelos do servidor), **posição no rodízio** (antes de todos, depois dos gratuitos, antes do Ollama local/Pollinations ou no fim), **enxerga imagens** (para o auxiliar de prompt usar com referências) e **é pago**.

- Aparece como cartão no painel, entra no rodízio na posição escolhida e nos menus de modelo do chat e do auxiliar (★ Nome). No proxy: `<id>/auto` (ex.: `custom_ollama_da_sala/auto`).
- Se o servidor estiver desligado, o cartão mostra *servidor não responde* e o rodízio pula para o próximo.
- Ficam em `%USERPROFILE%\.biazzitech\custom_providers.json`; a chave (se houver) vai para o `~/.env`.

---

## 5. Claude e ChatGPT

- **ChatGPT:** `OPENAI_API_KEY` (platform.openai.com/api-keys). No painel: *ChatGPT*; no proxy: `chatgpt/auto` ou um nome `gpt-...`.
- **Claude:** `CLAUDE_API_KEY` (platform.claude.com/settings/keys) — de propósito **não** é `ANTHROPIC_API_KEY`, para não interferir em outras ferramentas. Padrão: **Claude Opus 5.5** (`claude-opus-5-5`); para gastar menos, `ANTHROPIC_MODEL=claude-sonnet-5-5` ou `claude-haiku-5-5`. O roteador fala com a API Messages nativa, não envia `temperature` (recusado pela versão atual da API) e liga o *fallback* automático do servidor quando um pedido é recusado pelos filtros de segurança.
- Os dois são pagos e entram no rodízio depois dos gratuitos e da DeepSeek.

---

## 6. Imagens e pixel art

| Gerador | Chave | Modos | Referência |
|---|---|---|---|
| **Flux / Pollinations** | `POLLINATIONS_API_KEY` | Flux Schnell, Flux Pro, Flux Flex, Animagine, Z-Image Turbo | — |
| **PixelLab** | `PIXELLAB_API_KEY` | Sprite/imagem, personagem 4 ou 8 direções, tileset top-down (prompt `chão \| topo`), animar | ✔ |
| **Retro Diffusion** | `RETRODIFFUSION_API_KEY` | Estilos (geral, plataforma, top-down, isométrico...), tiles, animações prontas (andar 4 direções, batalha, VFX, rotação 8 dir.), animar referência | ✔ |
| **Scenario** | `SCENARIO_API_KEY` = `CHAVE:SEGREDO` | Qualquer modelo pelo `modelId` | ainda não |

- **Referências (até 6):** *Adicionar imagens...* ou *Usar como referência* numa imagem da galeria. A 1ª vai para PixelLab/Retro Diffusion; todas vão para o auxiliar de prompt.
- **Animar:** botão *Animar* em qualquer imagem (PixelLab, 8 quadros). Animações da Retro Diffusion voltam como **spritesheet PNG**.
- Personagens em várias direções e tilesets voltam como várias imagens (uma por direção/tile).
- Tudo é salvo em `%USERPROFILE%\.biazzitech\imagens`.
- **Reutilizar prompt:** volta o prompt e as configurações daquela imagem para a caixa de geração.
- **Corrigir:** diga o que saiu errado ("mãos deformadas", "o cabelo devia ser preto", "apareceu texto"). O auxiliar olha a imagem, reescreve o prompt com reforços e exclusões adequados ao erro, explica o que mudou e oferece gerar de novo.

### Auxiliar de prompt (quadrinhos, storyboards, sequências)

![Exemplo: página de 2 quadros planejada pelo auxiliar a partir de 1 imagem de referência e 2 parágrafos](docs/img/06-auxiliar.png)

1. Marque **Auxiliar de prompt** na aba Imagens.
2. Cole o **texto de referência** (ou *📎 Texto de .docx/.md/.pdf/.txt*) e adicione as **imagens dos personagens**.
3. Escreva o pedido, por exemplo: *"página de 5 quadros estilo anime shonen dos anos 80 com os personagens das imagens; cada parágrafo é um quadro"*, e clique em **Planejar quadros**.
4. O auxiliar descreve o estilo e cada personagem a partir das imagens e monta **um prompt completo por quadro**, repetindo a descrição dos personagens em todos (é o que mantém a consistência, já que o gerador não tem memória). Cada quadro mostra o trecho do texto, o enquadramento, a proporção e o que evitar — tudo editável.
5. **Gerar este** / **Gerar todos os quadros** usam o gerador escolhido lá em cima; **Montar página** junta os quadros numa página com bordas (salva na galeria).

Se o modelo escolhido falhar ou devolver uma resposta quebrada, o auxiliar tenta sozinho o próximo (até 3). Pedidos com imagens só vão para provedores que enxergam imagens.

### Páginas de quadrinho: modelos, divisão e onomatopeias

<img src="docs/img/07-pagina.jpg" alt="Página montada no modelo misto de 5 quadros, com o quadro 3 vazando e onomatopeias hachurada, explosiva e tremida" width="360" align="right">

Com o auxiliar ligado aparecem três campos extras (veja o print da aba Imagens, na seção 3):

- **Página de quadrinho** — *Sem página* (quadros soltos), *Automático* (o auxiliar escolhe o modelo pelo número de quadros e pela ação) ou um dos **22 modelos**: grades iguais (2x2, 2x3), faixas, colunas, destaques, clássicos de 5 e 6 quadros, **dinâmicos** com cortes inclinados para a direita, para a esquerda ou em zigue-zague (2 a 6 quadros), **mistos** (quadros dinâmicos grandes junto com quadros retos) e página inteira. Uma miniatura mostra o desenho da página. Cada quadro já é pedido na proporção do espaço dele.
- **Divisão da página** — texto livre: *"quadros dinâmicos com cortes em diagonal acompanhando a ação"*, *"o personagem do quadro 4 vaza para o quadro 3"*, *"quadro 1 bem largo como abertura"*. O auxiliar reforça o movimento nos prompts e marca **vaza do quadro** onde for o caso: na montagem esse quadro fica por cima dos vizinhos, com moldura branca.
- **Onomatopeias e efeitos** — *"quadro 2: 'SOC!' hachurado ao lado do personagem; quadro 4: 'BANG!' explosivo no canto de cima à direita"*. Cada quadro do plano ganha a lista de efeitos (texto, estilo **hachurado / explosão / tremido / simples**, posição e tamanho), editável. Por padrão o **painel escreve as onomatopeias na montagem** (letras sempre certas) e pede ao gerador para deixar o espaço livre; marcando *"pedir ao gerador para desenhar"*, elas entram no prompt (fica mais integrado ao desenho, mas os geradores costumam errar letras).

<br clear="right">

### Fichas de personagem

![Fichas de personagem](docs/img/08-fichas.png)

Botão **👤 Fichas de personagem** (no auxiliar). Cada ficha guarda **nome, apelidos, aparência** (em inglês, do jeito que vai no prompt), notas e **até 4 imagens**.

- **✨ Descrever pelas imagens** escreve a aparência a partir das fotos (com um modelo que enxerga imagens); revise e salve.
- **💾 Salvar como ficha** aparece nos personagens de um plano que ainda não têm ficha.
- Quando o **nome ou um apelido aparece no pedido ou no texto de referência** (sem ligar para acento ou maiúsculas), a ficha entra sozinha — o chip do personagem mostra *(citado)*. Também dá para marcar à mão quem está na cena.
- O auxiliar repete a aparência da ficha **palavra por palavra** em todos os quadros em que o personagem aparece e envia as imagens dela como referência. É isso que mantém o personagem igual de uma página para a outra.
- Ficam em `%USERPROFILE%\.biazzitech\personagens.json` (imagens em `personagens\`).

### Exportar para o Godot 4

![Exportar para o Godot](docs/img/09-godot.png)

Botão **🎮 Godot** em qualquer PNG da galeria (spritesheets da Retro Diffusion/PixelLab, tilesets, folhas feitas por você):

- **Animação (SpriteFrames):** informe o tamanho do quadro e as animações (nome, linha, primeiro quadro, quantidade, fps, repete). Sem animações, cada linha da folha vira uma. Quadros vazios (transparentes) ficam de fora.
- **Tileset (TileSet):** tamanho do tile, margem e espaçamento; um tile é criado para cada célula com algum pixel visível.
- A grade aparece por cima da imagem para conferir. Informe a **pasta no projeto Godot** (ex.: `res://assets/heroi/`): os `.tres` já apontam para ela.
- Saída em `%USERPROFILE%\.biazzitech\imagens\godot\<nome>_<data>\` (PNG + `.tres` + LEIA-ME) e um **.zip para baixar**. No Godot: copie a pasta para o caminho escolhido e carregue o `.tres` no *AnimatedSprite2D* (Sprite Frames) ou no *TileMapLayer* (Tile Set).

**Modelo do auxiliar:** *Automático* escolhe o mais adequado disponível — com imagens, um modelo que enxerga imagens (Gemini, Claude, ChatGPT ou um `:free` com visão na OpenRouter); só com texto, Claude/ChatGPT/Gemini/GPT-OSS. Também dá para escolher um modelo fixo. Quando um estilo é citado pelo nome de uma obra, o auxiliar descreve as características visuais dele no prompt.

- PixelLab, Retro Diffusion e Scenario são pagos (créditos). As APIs mudam com frequência: se algum modo der erro de formato, ajuste em `image_providers.py`.

---

## 7. IA local (Ollama)

Roda um modelo **no seu PC**: grátis, sem limite e sem internet. O passo 6 do instalador (ou `bat\Instalar_Ollama_IA.bat`) **analisa a máquina antes**:

| Resultado | Critério | O que acontece |
|---|---|---|
| Recomendado | RAM ≥ 16 GB e GPU NVIDIA/AMD ≥ 6 GB | instala |
| Mínimo | RAM ≥ 8 GB, ≥ 4 núcleos, ≥ 10 GB livres, Windows 10 22H2+ 64 bits | instala, avisando que pode ficar lento |
| Abaixo do mínimo | algum item acima não atendido | **NÃO RECOMENDADO** — mostra o motivo e avisa que o desempenho pode ser muito prejudicado; você decide (padrão: não) |

- O modelo é escolhido pelo hardware (`qwen2.5-coder` 14b/7b/3b/1.5b); escolha outro com `-Modelo "gemma4:26b-a4b-it-qat"` ou troque depois com `ollama pull <modelo>` + `OLLAMA_MODEL=<modelo>` no `~/.env`.
- Opções: `-SomenteVerificar`, `-Instalar sim|nao`, `-Forcar`.
- No painel, modelo **Ollama local** (`ollama/auto`) usa só ele. Modelos locais são bem mais fracos que Claude/Gemini para código complexo; servem para tarefas pequenas, tradução e uso offline.

### Imagens offline com LoRAs (Stable Diffusion local)

O "Ollama das imagens": gera **no seu PC, sem internet e sem créditos**, e aceita **LoRAs** (estilos e personagens treinados). Feito para **máquinas simples**: o motor é o [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp), um executável pequeno sem Python/PyTorch que usa **qualquer placa de vídeo** (NVIDIA, AMD ou Intel, inclusive integrada, via Vulkan) ou só o processador.

`bat\Instalar_SD_Local_IA.bat` (ou o passo 6 do instalador principal) **analisa a máquina** e oferece:

| Versão | O que baixa | Para quem |
|---|---|---|
| **Leve** | SD 1.5 quantizado (GGUF Q8) + LoRA LCM — **~1.9 GB** | 8 GB de RAM bastam; com placa de vídeo sai em segundos, só com processador leva 1–3 min |
| **Pesada** (opcional) | SDXL + VAE corrigido + LoRA LCM SDXL + LoRA de pixel art — **~7.8 GB** | só é oferecida se sobrar recurso: placa de 8 GB, ou 4 GB + 24 GB de RAM (mais lenta) |

- O motor vai para `%USERPROFILE%\.biazzitech\sdlocal` (motor, `models\checkpoints`, `models\loras`, `models\vae`). Downloads interrompidos continuam de onde pararam.
- Se o motor de placa de vídeo (Vulkan) não funcionar, o instalador troca sozinho para o de processador.
- No painel: **Gerador → Stable Diffusion local**. Escolha o modelo (leve/pesado), a proporção e **rápido (LCM)** — 6 passos em vez de ~22, o que deixa tudo várias vezes mais rápido. O motor liga sozinho na primeira imagem e libera a memória depois de 10 minutos parado.
- **LoRAs:** botão **LoRAs (n)** lista as instaladas, com peso. Para adicionar, baixe o `.safetensors` (ex.: civitai.com, huggingface.co) do **mesmo tipo do modelo** (SD 1.5 ou SDXL) e coloque em `models\loras`. Muitas pedem uma palavra de ativação no prompt.
- **Imagem de referência:** a 1ª referência vira "imagem para imagem"; **força da ref.** controla quanto a nova pode mudar.
- **Fichas de personagem:** campos **LoRA do personagem**, peso e **palavra de ativação**. Quando o personagem está na cena (citado ou marcado), a LoRA e a palavra entram sozinhas — inclusive em cada quadro das páginas de quadrinho. O botão **📦 Pacote para treinar LoRA** baixa as imagens da ficha com legendas no formato dos treinadores (Civitai, kohya_ss, OneTrainer).
- Licenças: SD 1.5 e SDXL usam licenças abertas OpenRAIL (uso livre, inclusive comercial, com restrições de uso nocivo); o instalador mostra o aviso antes de baixar.
- Opções do instalador: `-SomenteVerificar`, `-Instalar sim|nao`, `-Versao leve|pesado|ambas`, `-Backend vulkan|cpu`, `-Forcar`. No `~/.env`: `SDLOCAL_ENABLED`, `SDLOCAL_MODEL`, `SDLOCAL_PORT` (padrão 7861), `SDLOCAL_ARGS`, `SDLOCAL_ARGS_SDXL`, `SDLOCAL_URL` (usar um `sd-server` que já roda em outro PC).

---

## 8. Usuários, senhas, rede e porta

![Login](docs/img/05-login.png)

**Sem nenhum usuário cadastrado o acesso é livre, mas só neste PC.** A rede exige pelo menos um usuário com senha. Para controlar quem usa:

- Crie o primeiro usuário na instalação ou na aba **Acesso** — ele vira **administrador** automaticamente.
- Permissões simples: **Chat/código**, **Imagens**, **Admin** (chaves, usuários, rede, porta).
- Cada usuário recebe um **token** (`btk_...`) para usar no Continue/Cline no lugar da chave de API.
- Senhas guardadas com hash + salt (PBKDF2-SHA256), nunca em texto. 5 senhas erradas bloqueiam o IP por 5 minutos.
- Quem usa **o próprio PC do servidor** entra direto; marque *"Exigir login também neste PC"* para mudar isso.

**Acesso pela rede** (aba Acesso ou `-AcessoRede sim` na instalação):
- Só liga com **usuário cadastrado** e depois de você **confirmar que leu os riscos** (a data fica registrada). Liga/desliga **na hora**, sem reiniciar; apagar o último usuário fecha a rede sozinho.
- As outras máquinas acessam o endereço que o painel mostra. Se o Windows perguntar sobre o firewall, permita em **Redes privadas**.
- Os logins (certos, errados e bloqueados) ficam em `%USERPROFILE%\.biazzitech\acessos.log` — sem senhas.

**HTTPS na rede (recomendado):** sem HTTPS, senha e conversas trafegam sem criptografia na rede. Para ativar:

```powershell
winget install FiloSottile.mkcert
mkcert -install
cd $env:USERPROFILE\.biazzitech
mkcert -cert-file cert.pem -key-file key.pem 192.168.0.10 localhost 127.0.0.1   # troque pelo IP deste PC
```

Com `cert.pem` e `key.pem` nessa pasta e a rede ligada, o painel passa a atender a rede em **`https://<IP>:<porta+1>`** (ex.: 9091) em poucos segundos, e a porta normal fica só neste PC. Nas outras máquinas o navegador pode avisar que não conhece o certificado: rode `mkcert -install` nelas com o mesmo certificado raiz (`mkcert -CAROOT` mostra onde está) ou aceite o aviso.

**Fora de casa:** use uma VPN como o **Tailscale** (rede privada criptografada entre seus aparelhos). **Nunca** abra a porta do painel no roteador para a internet.

**Porta:** escolhida na instalação ou na aba Acesso (vale no próximo início). A 8080 e portas ocupadas são recusadas. Fica em `%USERPROFILE%\.biazzitech\config.json`.

**Terminal:** `python access_control.py show` · `set port 9191` · `set lan true` (exige usuário) · `add-user NOME --perms chat,imagens` · `del-user NOME`

---

## 9. Versão .exe (sem Python)

1. Numa máquina **com** Python, rode `bat\Gerar_EXE.bat`. Na primeira vez ele pede para instalar o **PyInstaller**.
2. Saída: `dist\BiazziTech AI Studio.exe` (um arquivo, ~8 MB). Copie para qualquer Windows 10/11 e dê duplo-clique.
3. Cadastre as chaves pela aba **Provedores** (ficam em `%USERPROFILE%\.env` daquele PC).

O `.exe` tem o painel, o rodízio, as imagens e o controle de acesso. A integração com o Antigravity e o Ollama ficam com o instalador em PowerShell. Alguns antivírus estranham `.exe` do PyInstaller; se bloquear, libere o arquivo.

---

## 10. Continue, Cline e outras ferramentas (proxy OpenAI)

| Campo | Valor |
|---|---|
| Base URL | `http://localhost:9090/v1` (ou a porta/IP configurados) |
| API Key | `local` — ou o **token `btk_...`** do usuário, se houver usuários cadastrados e o acesso for pela rede |
| Modelos | `auto`, `gemini-flash-latest`, `groq/openai/gpt-oss-120b`, `openrouter/auto-free`, `claude/auto`, `chatgpt/auto`, `ollama/auto`, `deepseek-chat`, `deepseek-reasoner`, `openai/gpt-5.3-codex`, `<provedor personalizado>/auto`... |

Streaming (SSE) funciona. A resposta traz o campo `provider` com quem respondeu.

---

## 11. Pastas e arquivos

| O que | Onde |
|---|---|
| Chaves | `%USERPROFILE%\.env` |
| App instalado | `%USERPROFILE%\.biazzitech\app` |
| Imagens geradas | `%USERPROFILE%\.biazzitech\imagens` |
| Porta / rede | `%USERPROFILE%\.biazzitech\config.json` |
| Usuários | `%USERPROFILE%\.biazzitech\users.json` |
| Provedores personalizados | `%USERPROFILE%\.biazzitech\custom_providers.json` |
| Estado do rodízio | `%USERPROFILE%\.biazzitech\router_state.json` |
| Fichas de personagem | `%USERPROFILE%\.biazzitech\personagens.json` e `personagens\` |
| Exportações para o Godot | `%USERPROFILE%\.biazzitech\imagens\godot\` |
| Stable Diffusion local (motor, modelos, LoRAs) | `%USERPROFILE%\.biazzitech\sdlocal\` |
| Registro de logins | `%USERPROFILE%\.biazzitech\acessos.log` |
| Certificado HTTPS (opcional) | `%USERPROFILE%\.biazzitech\cert.pem` e `key.pem` |
| Sidecar do Antigravity | `%USERPROFILE%\.gemini\config\plugins\biazzitech-ai-studio` |

**Repositório:**

| Arquivo | Função |
|---|---|
| `instalar_motores.ps1` | Instalador (porta, usuários, rede, Antigravity, atalhos, Ollama) |
| `instalar_ollama.ps1` | IA local com análise de hardware |
| `biazzitech_studio.py` | Lançador stand-alone |
| `studio_server.py` | Servidor do painel, API e proxy OpenAI |
| `studio_ui.html` + `ui/studio.css` + `ui/studio.js` | Painel (HTML, estilos e lógica) |
| `provider_router.py` | Rodízio de provedores e chaves |
| `image_providers.py` | PixelLab, Retro Diffusion, Scenario |
| `access_control.py` | Porta, rede, usuários e senhas |
| `prompt_assist.py` | Auxiliar de prompt (planejar quadros, corrigir prompts, descrever personagens) |
| `characters.py` | Fichas de personagem |
| `comic_layouts.py` | Modelos de página de quadrinho |
| `godot_export.py` | Exportação de spritesheets/tilesets para o Godot 4 |
| `sd_local.py` + `instalar_sd_local.ps1` | Stable Diffusion local (offline, LoRAs) e o instalador dele |
| `doc_extract.py` | Texto de anexos .docx/.md/.txt/.pdf |
| `studio_mcp.py` | Servidor MCP para o Antigravity (ferramentas `studio_code`, `studio_text`, imagens e status) |
| `studio_cli.py`, `free_image_gen.py`, `pixai_gen.py` | Ferramentas de linha de comando |
| `tests/` | Testes automáticos (sem internet e sem chaves) |
| `build_exe.ps1` | Gera o `.exe` |
| `plugin_antigravity/` | Plugin/Sidecar do Antigravity |
| `bat/` | Atalhos de duplo-clique |
| `docs/img/` | Prints deste README |

---

## 12. Segurança

- O servidor escuta **só neste PC** até você liberar a rede — e a rede exige usuário com senha.
- **Outros sites abertos no navegador não conseguem usar o painel** nem suas chaves: todo pedido de envio confere a origem, e o navegador só libera leitura das respostas para o próprio painel.
- Cookie de sessão `HttpOnly` + `SameSite=Strict` (e `Secure` com HTTPS); senhas com PBKDF2; bloqueio após 5 erros; registro de logins.
- Imagens, fichas e exportações só podem ser lidas/apagadas dentro das próprias pastas.
- As chaves nunca são mostradas inteiras no painel (só os 4 últimos caracteres).
- Achou uma falha? Veja o [SECURITY.md](SECURITY.md) para avisar em particular.

### Responsabilidade de uso

O BiazziTech AI Studio é uma ferramenta para uso local. Liberar o acesso pela rede é uma decisão de quem instala. Cada usuário é responsável pelas próprias chaves, pelo cumprimento dos termos de uso de cada provedor de IA (inclusive quanto ao uso de várias contas) e pelo conteúdo que gerar. O projeto não coleta dados nem envia nada ao autor. O software é fornecido sem garantias, conforme as seções 15 e 16 da licença.

---

## 13. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Painel sem a aba Provedores/Acesso ou com versão antiga | Rode o instalador de novo e recarregue a página (ou reinicie o Antigravity). |
| "Todos os provedores falharam" | Veja a aba Provedores: chaves faltando ou todos em espera. Cadastre uma chave grátis (Gemini/Groq/OpenRouter). |
| DeepSeek/Ollama Cloud em espera "sem saldo (402)" | A conta precisa de créditos; o rodízio segue com os outros. |
| Outra máquina não abre o painel | Confira se o acesso pela rede está ligado, o IP/porta certos e se o firewall do Windows permitiu o Python em redes privadas. |
| Porta ocupada | Escolha outra na aba Acesso ou rode o instalador com `-Porta 9191`. |
| Ollama lento | Normal em máquinas sem GPU dedicada; use modelos menores ou deixe o rodízio usar os provedores online. |

---

## 14. Licença

Copyright © 2026 BiazziTech (Fausto Sousa).

O BiazziTech AI Studio é software livre sob a **[GNU Affero General Public License v3.0](LICENSE)** (AGPL-3.0):

- Você pode usar, estudar, modificar e redistribuir, inclusive para fins comerciais.
- Se distribuir uma versão modificada **ou oferecê-la como serviço pela rede** (ex.: hospedar o painel para outras pessoas), precisa disponibilizar o código-fonte completo dessa versão sob a mesma licença.
- Sem garantias de qualquer tipo (veja o texto da licença).

**Licença comercial:** para usar o código em um produto fechado, sem as obrigações da AGPL, fale com o autor: `fausto@biazzitech.com.br`.

**Contribuições** são bem-vindas — leia o [CONTRIBUTING.md](CONTRIBUTING.md) antes de abrir um pull request.

---

## 15. Como o projeto é feito

O BiazziTech AI Studio é **desenvolvido com auxílio de IA** (Claude e Google Antigravity). A ideia, as decisões de produto, a revisão e a responsabilidade pelo projeto são do autor; as IAs ajudam a escrever e revisar o código.

**Testes:** `python -m unittest discover -s tests -t tests` — cobrem o rodízio, o controle de acesso, a segurança das rotas (inclusive HTTPS de verdade), anexos, auxiliar de prompt, quadrinhos, fichas e a exportação para o Godot. Rodam sem internet e sem chaves, e rodam sozinhos no GitHub a cada envio.
