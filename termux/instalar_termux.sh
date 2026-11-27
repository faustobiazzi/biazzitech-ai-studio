#!/data/data/com.termux/files/usr/bin/bash
# BiazziTech AI Studio no Android, pelo Termux (sem PC, sem root).
#
# No Termux (instale pelo F-Droid ou pelo GitHub do Termux; a versão da Play Store está desatualizada):
#   pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/faustobiazzi/biazzitech-ai-studio/main/termux/instalar_termux.sh | bash
#
# Depois, para abrir:  studio            (porta 9090)  ou  studio 9191
# Funciona: chat com rodízio, conversas e memória, busca na web, lugares perto, imagens online (Pollinations,
# PixelLab, Retro Diffusion, SD de outro PC), quadrinhos e fichas. Não funciona aqui: SD local e Ollama.
set -e

REPO="https://github.com/faustobiazzi/biazzitech-ai-studio.git"
DIR="$HOME/biazzitech-ai-studio"

echo "== 1/3 Pacotes (python, git, certificados)"
pkg update -y
pkg install -y python git ca-certificates

echo "== 2/3 Baixando o Studio em $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi

echo "== 3/3 Atalho 'studio'"
cat > "$PREFIX/bin/studio" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
# Abre o BiazziTech AI Studio. Uso: studio [porta]
PORT="${1:-9090}"
cd "$HOME/biazzitech-ai-studio" || exit 1
git pull --ff-only -q 2>/dev/null || true          # atualiza quando tiver internet
termux-wake-lock 2>/dev/null || true               # impede o Android de pausar o servidor com a tela apagada
( sleep 3; termux-open-url "http://localhost:$PORT/" ) &
echo "Studio em http://localhost:$PORT  (Ctrl+C para desligar)"
python biazzitech_studio.py --no-browser --port "$PORT"
termux-wake-unlock 2>/dev/null || true
EOS
chmod +x "$PREFIX/bin/studio"

cat <<'EOF'

Pronto! Para abrir o Studio:  studio

Primeira vez:
  1. O navegador abre em http://localhost:9090 (no próprio celular: a localização funciona, é "localhost").
  2. Sem chaves ele abre em modo demo: imagens já funcionam; para o chat, crie uma chave grátis
     (Gemini, Groq ou OpenRouter) e cole na aba Provedores.
  3. No menu do Chrome, "Instalar app" (ou o botão 📲 do painel) põe um ícone na tela inicial.
     Deixe o Termux aberto (ou com a notificação ativa) enquanto usa o app.
Dados (chaves, conversas, imagens) ficam em ~/.biazzitech e ~/.env, dentro do Termux.
EOF
