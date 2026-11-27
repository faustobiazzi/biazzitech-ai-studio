// BiazziTech AI Studio - lógica do painel (servido em /ui/studio.js)
const PRESETS = {
  gdscript: "Você é um programador sênior especialista em Godot 4.7 GDScript, shaders e arquitetura de jogos. Escreva código limpo, tipado e direto ao ponto.",
  lua: "Você é um programador sênior de jogos em Lua (LÖVE 2D, Defold, Roblox Luau, Pico-8, scripts embutidos). Escreva código Lua idiomático, comentado e direto; diga para qual engine/versão é quando fizer diferença.",
  python: "Você é um programador sênior em Python (Pygame, Arcade, Ren'Py, ferramentas e automação para jogos). Escreva código Python 3 tipado, limpo e direto, seguindo a PEP 8.",
  csharp: "Você é um programador sênior em C# para jogos (Godot .NET e Unity). Escreva código C# limpo, tipado e direto ao ponto.",
  lore: "Você é um roteirista e escritor especialista em narrativa de jogos: lore, diálogos de NPCs, descrições de cenários e documentos do mundo do jogo. Mantenha consistência com o material de referência fornecido e com o tom pedido. Escreva em português do Brasil.",
  free: "Você é um assistente técnico e criativo prestativo. Responda em português."
};

let currentConv = null;     // id da conversa aberta (null = nova, criada no 1º envio)
let convEditable = true;
let convData = null;
let chatDisplay = '';

function switchTab(name, btn) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'image') loadGallery();
}

// ================= CONVERSAS (guardadas no servidor, com memória) =================
async function convPost(body) {
  const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
  return d.result;
}

async function loadConversations(selectId) {
  const sel = document.getElementById('conv-select');
  if (!sel) return;
  const all = document.getElementById('conv-all').checked;
  let d;
  try { d = await (await fetch('/api/conversations' + (all ? '?all=1' : ''))).json(); } catch (e) { return; }
  if (!d.ok) return;
  convPrefs = d.prefs || {};
  document.getElementById('opt-ai-confirm').checked = !!convPrefs.ai_confirm;
  document.getElementById('opt-partial').checked = !!convPrefs.partial_reset;
  document.getElementById('conv-all-wrap').style.display = d.is_admin ? '' : 'none';
  sel.innerHTML = '';
  const mk = (c, label) => { const o = el('option', null, label); o.value = c.id; return o; };
  const fresh = el('option', null, '(nova conversa)'); fresh.value = ''; sel.appendChild(fresh);
  const mineKeys = d.mine || [d.me];
  const when = ts => { const t = new Date((ts || 0) * 1000); return t.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' + t.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); };
  const mine = d.conversations.filter(c => mineKeys.includes(c.owner));
  const others = d.conversations.filter(c => !mineKeys.includes(c.owner));
  mine.forEach(c => sel.appendChild(mk(c, when(c.updated) + ' · ' + c.title + ' · ' + c.messages + ' msg' +
                                          (c.owner !== d.me ? ' (feita neste PC sem login)' : ''))));
  if (others.length) {
    const g = el('optgroup'); g.label = 'De outros usuários (só leitura)';
    others.forEach(c => g.appendChild(mk(c, '[' + c.owner + '] ' + when(c.updated) + ' · ' + c.title + ' · ' + c.messages + ' msg')));
    sel.appendChild(g);
  }
  const want = selectId !== undefined ? selectId : currentConv;
  if (want && [...sel.options].some(o => o.value === want)) sel.value = want;
  else if (selectId === undefined && currentConv === null && mine.length) { sel.value = mine[0].id; return openConversation(mine[0].id); }
  else sel.value = '';
}

function renderWelcome() {
  const box = document.getElementById('chat-messages');
  box.innerHTML = '';
  addMessage('assistant', 'Conversa nova. Ela fica guardada no servidor (só você e os administradores veem). ' +
             'Quando ela crescer, a IA resume o que importa na 🧠 Memória e as mensagens antigas saem do contexto.', 'Sistema Local');
}

function setConvEditable(editable, owner) {
  convEditable = editable;
  const ro = document.getElementById('conv-readonly');
  ro.style.display = editable ? 'none' : '';
  ro.textContent = editable ? '' : '👁 Conversa de ' + owner + ' (só leitura: administradores podem ver, mas não escrever nela).';
  document.getElementById('chat-input').disabled = !editable;
  document.getElementById('chat-send').disabled = !editable;
}

async function openConversation(id) {
  currentConv = id || null;
  convData = null;
  if (!id) { renderWelcome(); setConvEditable(true); fillMemory(); return; }
  try {
    const d = await (await fetch('/api/conversations/' + encodeURIComponent(id))).json();
    if (!d.ok) throw new Error(d.message);
    convData = d.conversation;
  } catch (e) { alert('Não deu para abrir a conversa: ' + e.message); return; }
  const box = document.getElementById('chat-messages');
  box.innerHTML = '';
  const upto = convData.summarized_upto || 0;
  convData.messages.forEach((m, i) => {
    if (i === upto && upto > 0) box.appendChild(el('div', 'ref-name', '— acima: já resumido na 🧠 Memória (fora do contexto) —'));
    addMessage(m.role, m.display || m.content, m.role === 'assistant' ? 'Modelo: ' + (m.provider ? m.provider + ' / ' : '') + (m.model || '') : undefined, i);
  });
  if (!convData.messages.length) renderWelcome();
  document.getElementById('chat-preset').value = convData.preset && PRESETS[convData.preset] ? convData.preset : 'free';
  setConvEditable(convData.can_edit, convData.owner);
  fillMemory();
  box.scrollTop = box.scrollHeight;
}

function fillMemory() {
  const info = document.getElementById('conv-info');
  const ta = document.getElementById('conv-memory-text');
  if (!convData) { ta.value = ''; info.textContent = '(a conversa é criada na 1ª mensagem)'; renderAnchors(); renderPinsAndUndo(); return; }
  ta.value = convData.memory || '';
  ta.readOnly = !convData.can_edit;
  renderAnchors();
  renderPinsAndUndo();
  const i = convData.info || {};
  info.textContent = i.messages + ' mensagens · ' + Math.round((i.context_chars || 0) / 1000) + ' mil caracteres no contexto · ' +
                     (i.compactions || 0) + ' compactação(ões)';
}

// Contexto inicial: as primeiras perguntas do assunto, guardadas para resgatar se a IA perder o fio
function renderAnchors() {
  const box = document.getElementById('conv-anchors');
  box.innerHTML = '';
  const list = (convData && convData.anchors) || [];
  const head = el('div', 'assist-row');
  head.appendChild(el('strong', null, convData && convData.context_reset ? '📌 Contexto vigente (redefinido por você)' : '📌 Contexto inicial (consulta)'));
  head.appendChild(el('span', 'ref-name', convData && convData.context_reset
    ? 'vai junto em toda resposta; o que conflitar com ele não vale mais.'
    : 'não vai em toda resposta: é resgatado quando você diz que a IA esqueceu/perdeu o contexto. ' +
      'Para trocar, diga algo como "o contexto mudou: agora é...".'));
  box.appendChild(head);
  if (!list.length) { box.appendChild(el('div', 'ref-name', 'Vazio: as primeiras perguntas da conversa (3 a 10, do mesmo assunto) aparecem aqui.')); return; }
  list.forEach((a, i) => {
    const row = el('div', 'anchor-row');
    row.appendChild(el('span', null, (i + 1) + '. ' + (a.text.length > 220 ? a.text.slice(0, 220) + '…' : a.text)));
    if (convData.can_edit) {
      const x = el('button', 'mini-btn', '×'); x.title = 'Tirar do contexto inicial';
      x.onclick = async () => { try { await convPost({ action: 'anchor_remove', id: currentConv, index: i }); await openConversation(currentConv); document.getElementById('conv-memory').style.display = ''; } catch (e) { alert(e.message); } };
      row.appendChild(x);
    }
    box.appendChild(row);
  });
}

let convPrefs = {};

async function saveConvPrefs() {
  try {
    const r = await convPost({ action: 'prefs', ai_confirm: document.getElementById('opt-ai-confirm').checked,
                               partial_reset: document.getElementById('opt-partial').checked });
    convPrefs = r.prefs || {};
    setStatus('Opções com IA salvas' + (convPrefs.ai_confirm || convPrefs.partial_reset ? ' (gastam consulta extra quando usadas).' : '.'));
  } catch (e) { alert(e.message); }
}

async function togglePin(index) {
  if (!currentConv) return;
  const box = document.getElementById('chat-messages');
  const pos = box.scrollTop;
  try { await convPost({ action: 'pin', id: currentConv, index }); await openConversation(currentConv); box.scrollTop = pos; }
  catch (e) { alert(e.message); }
}

// Aviso logo depois de uma redefinição de contexto, com o que saiu e o botão de desfazer
function showUndo(removed) {
  const bar = document.getElementById('chat-messages');
  const n = el('div', 'policy-warn undo-bar');
  n.appendChild(el('div', null, '📌 Entendi como mudança de contexto.' +
    (removed.length ? ' Saiu do contexto: ' + removed.map(t => '“' + (t.length > 80 ? t.slice(0, 80) + '…' : t) + '”').join('; ') : '')));
  const b = el('button', 'mini-btn key-save', '↩ Desfazer (não era mudança de contexto)');
  b.onclick = () => undoReset();
  n.appendChild(b);
  bar.appendChild(n);
  bar.scrollTop = bar.scrollHeight;
}

async function undoReset() {
  try {
    await convPost({ action: 'undo_reset', id: currentConv });
    await openConversation(currentConv);
    setStatus('↩ Redefinição desfeita: o contexto e a memória voltaram como estavam.');
  } catch (e) { alert(e.message); }
}

function renderPinsAndUndo() {
  const pinsBox = document.getElementById('conv-pins');
  const undoBox = document.getElementById('conv-undo');
  pinsBox.innerHTML = '';
  undoBox.style.display = 'none';
  if (!convData) return;
  if (convData.undo && convData.can_edit) {
    undoBox.style.display = '';
    undoBox.innerHTML = '';
    undoBox.appendChild(el('span', null, 'A última redefinição de contexto pode ser desfeita. '));
    const b = el('button', 'mini-btn', '↩ Desfazer redefinição'); b.onclick = () => undoReset();
    undoBox.appendChild(b);
  }
  const pins = convData.pins || [];
  const head = el('div', 'assist-row');
  head.appendChild(el('strong', null, '📌 Mensagens fixadas'));
  head.appendChild(el('span', 'ref-name', pins.length ? 'vão em toda resposta.' : 'nenhuma: use o 📌 de qualquer mensagem.'));
  pinsBox.appendChild(head);
  pins.forEach(i => {
    const m = convData.messages[i];
    if (!m) return;
    const t = m.display || m.content || '';
    const row = el('div', 'anchor-row');
    row.appendChild(el('span', null, (m.role === 'user' ? 'Você: ' : 'IA: ') + (t.length > 200 ? t.slice(0, 200) + '…' : t)));
    if (convData.can_edit) { const x = el('button', 'mini-btn', '×'); x.title = 'Desafixar'; x.onclick = () => togglePin(i); row.appendChild(x); }
    pinsBox.appendChild(row);
  });
}

function toggleMemory() {
  const p = document.getElementById('conv-memory');
  p.style.display = p.style.display === 'none' ? '' : 'none';
  fillMemory();
}

function newConversation() {
  document.getElementById('conv-select').value = '';
  openConversation('');
}

async function saveMemory() {
  if (!currentConv) { alert('Mande a primeira mensagem para criar a conversa.'); return; }
  try {
    await convPost({ action: 'memory', id: currentConv, memory: document.getElementById('conv-memory-text').value });
    await openConversation(currentConv);
    setStatus('Memória salva.');
  } catch (e) { alert(e.message); }
}

async function compactConversation(btn) {
  if (!currentConv) return;
  btn.disabled = true;
  setStatus('Compactando: a IA está resumindo as mensagens antigas na memória...');
  try {
    const r = await convPost({ action: 'compact', id: currentConv, model: document.getElementById('chat-model').value });
    await openConversation(currentConv);
    document.getElementById('conv-memory').style.display = '';
    setStatus(r.summarized + ' mensagem(ns) resumida(s) na memória.');
  } catch (e) { alert(e.message); setStatus('Compactação não feita.'); } finally { btn.disabled = false; }
}

async function clearChat() {
  if (!currentConv) { renderWelcome(); return; }
  if (!convEditable) return;
  if (!confirm('Limpar esta conversa? Apaga as mensagens e a memória (o nome continua).')) return;
  try { await convPost({ action: 'clear', id: currentConv }); await openConversation(currentConv); loadConversations(); setStatus('Conversa limpa.'); }
  catch (e) { alert(e.message); }
}

async function deleteConversation() {
  if (!currentConv) return;
  if (!confirm('Apagar esta conversa de vez?')) return;
  try { await convPost({ action: 'delete', id: currentConv }); currentConv = null; renderWelcome(); await loadConversations(''); setStatus('Conversa apagada.'); }
  catch (e) { alert(e.message); }
}

function addMessage(role, text, metaLabel, index) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  if (index !== undefined && convData && convData.can_edit) {
    const pinned = (convData.pins || []).includes(index);
    if (pinned) div.classList.add('pinned');
    const pin = el('button', 'pin-btn' + (pinned ? ' on' : ''), '📌');
    pin.title = pinned ? 'Desafixar' : 'Fixar: esta mensagem vai junto em toda resposta, mesmo depois de compactar';
    pin.onclick = () => togglePin(index);
    div.appendChild(pin);
  }

  if (role === 'assistant') {
    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    const span = document.createElement('span');
    span.textContent = metaLabel || 'IA';
    const copyBtn = document.createElement('button');
    copyBtn.className = 'mini-btn';
    copyBtn.textContent = 'Copiar';
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(text);
      copyBtn.textContent = 'Copiado!';
      setTimeout(() => copyBtn.textContent = 'Copiar', 1500);
    };
    meta.appendChild(span);
    meta.appendChild(copyBtn);
    div.appendChild(meta);
  }

  const body = document.createElement('div');
  body.textContent = text;
  div.appendChild(body);
  if (role === 'assistant') {
    const files = codeFilesBar(text);
    if (files) div.appendChild(files);
  }
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

// Blocos ```código``` da resposta viram arquivos que dá para copiar ou baixar.
// (A IA só devolve texto: nada é executado na sua máquina.)
const CODE_EXT = {
  gdscript: 'gd', gd: 'gd', godot: 'gd', gdshader: 'gdshader', glsl: 'gdshader', shader: 'gdshader',
  python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', json: 'json',
  html: 'html', css: 'css', csharp: 'cs', cs: 'cs', 'c#': 'cs', cpp: 'cpp', c: 'c', java: 'java',
  lua: 'lua', bash: 'sh', sh: 'sh', powershell: 'ps1', ps1: 'ps1', bat: 'bat', cmd: 'bat',
  xml: 'xml', yaml: 'yml', yml: 'yml', toml: 'toml', ini: 'ini', sql: 'sql', md: 'md', markdown: 'md',
  tscn: 'tscn', tres: 'tres', csv: 'csv', txt: 'txt', text: 'txt'
};

function extractCodeBlocks(text) {
  const re = /```([\w#+.-]*)[^\n]*\n([\s\S]*?)```/g;
  const out = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    const lang = (m[1] || 'txt').toLowerCase();
    out.push({ lang, code: m[2].replace(/\n$/, ''), ext: CODE_EXT[lang] || 'txt' });
  }
  return out;
}

function downloadText(name, content) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function codeFilesBar(text) {
  const blocks = extractCodeBlocks(text);
  if (!blocks.length) return null;
  const bar = el('div', 'code-files');
  bar.appendChild(el('span', 'code-files-title', 'Arquivos na resposta:'));
  blocks.forEach((b, i) => {
    const item = el('span', 'code-file');
    const nameIn = el('input');
    nameIn.value = (blocks.length > 1 ? `arquivo_${i + 1}` : 'arquivo') + '.' + b.ext;
    nameIn.title = 'Nome do arquivo (pode editar)';
    const dl = el('button', 'mini-btn', 'Baixar');
    dl.onclick = () => downloadText(nameIn.value.trim() || ('arquivo.' + b.ext), b.code);
    const cp = el('button', 'mini-btn', 'Copiar');
    cp.onclick = () => { navigator.clipboard.writeText(b.code); cp.textContent = 'Copiado!'; setTimeout(() => cp.textContent = 'Copiar', 1500); };
    item.appendChild(el('span', 'code-lang', b.lang));
    item.appendChild(nameIn);
    item.appendChild(dl);
    item.appendChild(cp);
    bar.appendChild(item);
  });
  return bar;
}

// Controle de ações longas (permite cancelar chat, geração de arte ou planejamento a qualquer momento)
const activeTasks = { chat: null, img: null };

function syncCancelButtons() {
  const cc = document.getElementById('chat-cancel');
  const ic = document.getElementById('img-cancel');
  const sc = document.getElementById('status-cancel');
  if (cc) cc.style.display = activeTasks.chat ? '' : 'none';
  if (ic) ic.style.display = activeTasks.img ? '' : 'none';
  if (sc) sc.style.display = (activeTasks.img || activeTasks.chat) ? '' : 'none';
}

function beginTask(kind, opts) {
  if (activeTasks[kind]) activeTasks[kind].ctrl.abort();
  const ctrl = new AbortController();
  activeTasks[kind] = { ctrl, ...(opts || {}) };
  syncCancelButtons();
  return ctrl.signal;
}

function endTask(kind, signal) {
  if (activeTasks[kind] && activeTasks[kind].ctrl.signal === signal) {
    activeTasks[kind] = null;
    syncCancelButtons();
  }
}

function isAbort(err) {
  return !!(err && (err.name === 'AbortError' || /aborted|abort/i.test(err.message || '')));
}

function cancelActiveTask(kind) {
  const k = kind || (activeTasks.img ? 'img' : (activeTasks.chat ? 'chat' : null));
  const t = k && activeTasks[k];
  if (!t) return;
  const prov = t.provider;
  t.ctrl.abort();
  activeTasks[k] = null;
  syncCancelButtons();
  if (prov === 'sdlocal') {
    fetch('/api/image/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  }
  setStatus('⏹ Ação cancelada.');
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send');
  const prompt = input.value.trim();
  if (!prompt) return;

  const model = document.getElementById('chat-model').value;
  const presetKey = document.getElementById('chat-preset').value;
  const sysPrompt = PRESETS[presetKey] || PRESETS.free;

  input.value = '';
  // Anexos viram material de referência dentro da mensagem
  let content = prompt;
  chatDisplay = prompt;
  if (chatAttachments.length) {
    chatDisplay = prompt + '\n📎 ' + chatAttachments.map(a => a.name).join(', ');
    content = 'Material de referência anexado (use como base):\n\n' +
      chatAttachments.map(a => '### Arquivo: ' + a.name + '\n"""\n' + a.text + '\n"""').join('\n\n') +
      '\n\n---\nPedido: ' + prompt;
    addMessage('user', prompt + '\n📎 ' + chatAttachments.map(a => a.name).join(', '));
    chatAttachments = [];
    renderChatAttach();
  } else {
    addMessage('user', prompt);
  }
  const display = chatDisplay;

  btn.disabled = true;
  const signal = beginTask('chat');
  document.getElementById('status-txt').textContent = 'Consultando ' + model + '...';

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: currentConv, content, display, model, system: sysPrompt,
                             preset: presetKey, temperature: 0.7 }),
      signal
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) {
      throw new Error(data.message || ('HTTP ' + resp.status));
    }
    const reply = data.reply || '(Sem conteúdo)';
    const usedModel = data.model || model;
    const prov = data.provider ? data.provider + ' / ' : '';
    const wasNew = !currentConv;
    currentConv = data.conversation_id;
    await openConversation(currentConv);
    if (data.can_undo) showUndo(data.removed_anchors || []);
    const rs = data.rescue || {};
    document.getElementById('status-txt').textContent = 'Resposta recebida (' + prov + usedModel + ')' +
      (data.intent === 'rescue' ? ' — 🔎 resgatei o contexto do início (' + (rs.anchors || 0) + ' pedido(s) iniciais, ' + (rs.snippets || 0) + ' trecho(s) antigos).' : '') +
      (data.intent === 'reset' ? ' — 📌 contexto redefinido: o anterior saiu e a memória está sendo reescrita.' : '') +
      (data.compacting ? ' — a conversa cresceu: compactando a memória em segundo plano.' : '') +
      (data.extra_calls ? ' (+' + data.extra_calls + ' consulta(s) extra da IA)' : '') +
      (data.question ? ' — 💡 respondi com uma pergunta sobre as opções com IA.' : '');
    if (data.intent === 'reset' || data.intent === 'rescue') setTimeout(() => { if (currentConv === data.conversation_id) fetch('/api/conversations/' + currentConv).then(r => r.json()).then(d => { if (d.ok) { convData = d.conversation; fillMemory(); } }); }, data.intent === 'reset' ? 15000 : 500);
    if (wasNew || data.compacting) loadConversations(currentConv);
    if (data.compacting) setTimeout(() => { if (currentConv === data.conversation_id) fetch('/api/conversations/' + currentConv).then(r => r.json()).then(d => { if (d.ok) { convData = d.conversation; fillMemory(); } }); }, 20000);
    refreshKeys();
  } catch (err) {
    if (isAbort(err)) {
      if (!input.value.trim()) input.value = prompt;
      setStatus('⏹ Pedido cancelado (texto devolvido para a caixa).');
    } else {
      addMessage('assistant', 'Erro: ' + err.message, 'Falha');
      document.getElementById('status-txt').textContent = 'Erro na requisição';
    }
  } finally {
    endTask('chat', signal);
    btn.disabled = false;
  }
}

function setStatus(txt) {
  document.getElementById('status-txt').textContent = txt;
}

async function imageAction(action, name) {
  const r = await fetch('/api/image/' + action, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
  return d;
}

// Converte a imagem do cartão em PNG (a área de transferência só aceita PNG)
function imageToPngBlob(img) {
  return new Promise((resolve, reject) => {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0);
    c.toBlob(b => b ? resolve(b) : reject(new Error('falha ao converter')), 'image/png');
  });
}

async function shareImage(data, img, prompt) {
  const src = data.data_url || data.url;
  const blob = await (await fetch(src)).blob();
  const file = new File([blob], data.file_name || 'imagem.jpg', { type: blob.type || 'image/jpeg' });
  // 1) Menu "Compartilhar" do sistema (Windows/Android), quando o navegador permite
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: 'BiazziTech AI Studio', text: prompt || '' });
      setStatus('Imagem compartilhada.');
      return;
    } catch (e) {
      if (e.name === 'AbortError') return; // usuário cancelou
    }
  }
  // 2) Copia a imagem para colar em WhatsApp, Discord, e-mail...
  try {
    const png = await imageToPngBlob(img);
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
    setStatus('Imagem copiada! Cole (Ctrl+V) no WhatsApp, Discord, e-mail...');
    return;
  } catch (e) {}
  // 3) Último recurso: baixar o arquivo
  const a = document.createElement('a');
  a.href = src;
  a.download = data.file_name || 'imagem.jpg';
  a.click();
  setStatus('Seu navegador não permite compartilhar daqui; a imagem foi baixada.');
}

function buildImageCard(data, prompt) {
  const effectivePrompt = prompt !== undefined ? prompt : (data.prompt || '');
  const src = data.data_url || data.url;
  const card = el('div', 'img-card');
  if (data.file_name) card.dataset.file = data.file_name;
  if (data.url) card.dataset.url = data.url;
  const img = el('img');
  img.src = src;
  img.loading = 'lazy';
  img.alt = effectivePrompt || 'Arte gerada';
  img.title = 'Clique para abrir';
  img.style.cursor = 'zoom-in';
  card.appendChild(img);

  const footer = el('div', 'img-card-footer');
  footer.appendChild(el('strong', null, data.model + (data.width ? ` (${data.width}x${data.height})` : '')));
  img.addEventListener('load', () => {
    if (!data.width) footer.firstChild.textContent = data.model + ` (${img.naturalWidth}x${img.naturalHeight})`;
  });
  if (galleryAdmin) footer.appendChild(el('span', 'ref-name', '👤 ' + (data.owner ? (data.owner === galleryMe ? 'você' : data.owner) : 'sem dono (imagem antiga)')));
  footer.appendChild(el('span', null, 'Salvo em: ' + data.saved_path));

  const actions = el('div', 'img-actions');
  const bOpen = el('button', 'mini-btn', 'Abrir');
  const bShare = el('button', 'mini-btn', 'Compartilhar');
  const bDel = el('button', 'mini-btn danger', 'Excluir');

  const openIt = async () => {
    try {
      await imageAction('open', data.file_name);
      setStatus('Imagem aberta no visualizador do Windows.');
    } catch (e) {
      if (data.url) window.open(data.url, '_blank', 'noopener');
      else setStatus('Não deu para abrir: ' + e.message);
    }
  };
  bOpen.onclick = openIt;
  img.onclick = openIt;

  bShare.onclick = async () => {
    bShare.disabled = true;
    try { await shareImage(data, img, effectivePrompt); }
    catch (e) { setStatus('Falha ao compartilhar: ' + e.message); }
    finally { bShare.disabled = false; }
  };

  bDel.onclick = async () => {
    if (!confirm('Excluir esta imagem do computador?\n\n' + data.saved_path)) return;
    try {
      await imageAction('delete', data.file_name);
      card.remove();
      setStatus('Imagem excluída.');
    } catch (e) {
      if (/não encontrada/i.test(e.message)) { card.remove(); setStatus('A imagem já não existia; removida da galeria.'); }
      else alert('Não deu para excluir: ' + e.message);
    }
  };

  // Usar esta imagem como referência / animar com a PixelLab
  const bRef = el('button', 'mini-btn', 'Usar como referência');
  bRef.onclick = () => setRef(src, data.file_name, data.file_name);
  const bAnim = el('button', 'mini-btn', 'Animar');
  bAnim.title = 'Anima esta imagem com a PixelLab (precisa de chave da PixelLab)';
  bAnim.onclick = async () => {
    const action = prompt_('Qual ação animar? (ex.: walking, idle, attack, jump)', 'walking');
    if (!action) return;
    bAnim.disabled = true;
    const signal = beginTask('img');
    setStatus('Animando com a PixelLab (pode levar alguns minutos)...');
    try {
      const d = await requestImages({ provider: 'pixellab', mode: 'animar', prompt: action, reference_name: data.file_name,
                                      transparent: true, frames: 8 }, signal);
      (d.images || [d]).slice().reverse().forEach(im => prependGalleryCard(im, action));
      setStatus((d.images || [d]).length + ' quadro(s) da animação salvos.');
    } catch (e) {
      if (!isAbort(e)) { alert('Não deu para animar: ' + e.message); setStatus('Falha ao animar'); }
    } finally { endTask('img', signal); bAnim.disabled = false; }
  };

  // Reutilizar o prompt / corrigir o que saiu errado
  const bReuse = el('button', 'mini-btn', 'Reutilizar prompt');
  bReuse.title = 'Volta o prompt e as configurações desta imagem para a caixa de geração';
  bReuse.onclick = () => reusePrompt(data);
  const bFix = el('button', 'mini-btn', 'Corrigir');
  bFix.title = 'Diga o que saiu errado: o auxiliar olha a imagem e escreve um prompt corrigido';
  bFix.onclick = () => fixImagePrompt(data, bFix);
  if (!data.prompt) { bReuse.disabled = bFix.disabled = true; bReuse.title = bFix.title = 'Sem prompt registrado para esta imagem'; }
  actions.appendChild(bReuse);
  actions.appendChild(bFix);

  const bGodot = el('button', 'mini-btn', '🎮 Godot');
  bGodot.title = 'Exporta esta spritesheet/tileset para o Godot 4 (SpriteFrames ou TileSet)';
  bGodot.onclick = () => openGodot(data);
  if (!/\.png$/i.test(data.file_name || '')) { bGodot.disabled = true; bGodot.title = 'Só imagens PNG da galeria'; }

  if (!data.file_name) { bOpen.disabled = bDel.disabled = bAnim.disabled = true; }
  actions.appendChild(bOpen);
  actions.appendChild(bShare);
  actions.appendChild(bRef);
  actions.appendChild(bAnim);
  actions.appendChild(bGodot);
  actions.appendChild(bDel);
  footer.appendChild(actions);
  card.appendChild(footer);
  return card;
}

function prependGalleryCard(im, prompt) {
  const gal = document.getElementById('image-gallery');
  if (!gal) return;
  if (im.file_name) {
    gal.querySelectorAll('.img-card').forEach(c => { if (c.dataset.file === im.file_name) c.remove(); });
  }
  gal.prepend(buildImageCard(im, prompt));
}

let _loadingGallery = false;
let galleryAdmin = false, galleryMe = '';

async function loadGallery(notify) {
  if (_loadingGallery) return;
  _loadingGallery = true;
  try {
    const r = await fetch('/api/images', { cache: 'no-store' });
    if (!r.ok) return;
    const d = await r.json();
    const gal = document.getElementById('image-gallery');
    if (!gal) return;
    galleryAdmin = !!d.is_admin; galleryMe = d.me || '';
    const filt = document.getElementById('gallery-owner');
    if (filt) filt.style.display = galleryAdmin ? '' : 'none';
    const onlyMine = filt && filt.value === 'mine';
    const list = (d.images || []).filter(im => !onlyMine || im.owner === galleryMe);
    const diskMap = new Map(list.map(im => [im.file_name, im]));
    // Remove cartões de imagens que foram apagadas no disco
    [...gal.querySelectorAll('.img-card')].forEach(c => {
      const fn = c.dataset.file;
      if (fn && !diskMap.has(fn)) c.remove();
    });
    const byFile = new Map([...gal.querySelectorAll('.img-card')].filter(c => c.dataset.file).map(c => [c.dataset.file, c]));
    let cursor = gal.firstElementChild;
    for (const im of list) {
      let card = byFile.get(im.file_name);
      if (card) {
        // Se a imagem foi editada/alterada no disco, reconstrói o cartão com o cache-buster novo
        if (im.url && card.dataset.url && card.dataset.url !== im.url) {
          const fresh = buildImageCard(im, im.prompt || '');
          card.replaceWith(fresh);
          card = fresh;
        }
        if (card === cursor) cursor = cursor.nextElementSibling;
      } else {
        card = buildImageCard(im, im.prompt || '');
        gal.insertBefore(card, cursor || null);
      }
    }
    if (notify) setStatus(list.length + ' imagem(ns) sincronizada(s) na galeria.');
  } catch (e) {} finally {
    _loadingGallery = false;
  }
}

function prompt_(msg, def) { return window.prompt(msg, def); }

// ================= AUXILIAR DE PROMPT =================
let currentPlan = null;

function onAssistToggle() {
  const on = document.getElementById('assist-on').checked;
  if (on) { loadLayouts(); loadCharacters(); }
  document.getElementById('assist-panel').style.display = on ? '' : 'none';
  document.getElementById('img-send').textContent = on ? 'Planejar quadros' : 'Gerar Arte';
  document.getElementById('assist-single').style.display = on ? '' : 'none';
  document.getElementById('img-input').placeholder = on
    ? 'O que você quer? Ex.: "página de 5 quadros estilo anime shonen dos anos 80 com os personagens das imagens; cada parágrafo é um quadro"'
    : (PIX_HINTS[document.getElementById('img-provider').value] || '');
}

async function applySettings(d) {
  const sel = document.getElementById('img-provider');
  const prov = d.provider && [...sel.options].some(o => o.value === d.provider) ? d.provider : 'pollinations';
  sel.value = prov;
  await onImgProviderChange();
  const st = d.settings || {};
  if (prov === 'pollinations') {
    if (st.model) document.getElementById('img-model').value = st.model;
    if (st.aspect) document.getElementById('img-aspect').value = st.aspect;
  } else if (prov === 'sdlocal' || isRemoteSd(prov)) {
    const sm = document.getElementById('sd-model');
    if (st.model && [...sm.options].some(o => o.value === st.model)) sm.value = st.model;
    if (st.aspect) document.getElementById('sd-aspect').value = st.aspect;
    if (st.fast != null) document.getElementById('sd-fast').checked = !!st.fast;
    if (st.strength != null) document.getElementById('sd-strength').value = st.strength;
  } else {
    if (st.mode) { document.getElementById('pix-mode').value = st.mode; onPixModeChange(); }
    if (st.width) document.getElementById('pix-w').value = st.width;
    if (st.height) document.getElementById('pix-h').value = st.height;
    if (st.transparent != null) document.getElementById('pix-transp').checked = !!st.transparent;
    if (st.model_id) document.getElementById('pix-model-id').value = st.model_id;
  }
}

async function reusePrompt(d) {
  await applySettings(d);
  if (document.getElementById('assist-on').checked) { document.getElementById('assist-on').checked = false; onAssistToggle(); }
  const inp = document.getElementById('img-input');
  inp.value = d.prompt || '';
  inp.focus();
  setStatus('Prompt e configurações recolocados. Ajuste se quiser e clique em Gerar Arte.');
}

async function fixImagePrompt(d, btn) {
  const problem = prompt_('O que saiu errado nesta imagem?\n(ex.: mãos deformadas; o cabelo deveria ser branco; apareceu texto; estilo errado; faltou um personagem)', '');
  if (!problem) return;
  btn.disabled = true;
  const signal = beginTask('img');
  setStatus('O auxiliar está analisando a imagem e corrigindo o prompt...');
  try {
    const r = await fetch('/api/prompt-fix', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: d.prompt, problem, image_name: d.file_name, generator: d.provider || 'pollinations',
                             model: document.getElementById('assist-model').value }), signal });
    const f = await r.json().catch(() => ({}));
    if (!r.ok || !f.ok) throw new Error(f.message || ('HTTP ' + r.status));
    showAssistWarning(f);
    await applySettings(d);
    if (document.getElementById('assist-on').checked) { document.getElementById('assist-on').checked = false; onAssistToggle(); }
    const full = f.prompt + (f.negative ? '\nAvoid: ' + f.negative : '');
    document.getElementById('img-input').value = full;
    const again = confirm('Prompt corrigido por ' + (f.provider || '') + ' / ' + (f.model || '') + '.\n\nO que mudou: ' +
                          (f.explanation || '-') + '\n\nGerar de novo agora com o prompt corrigido?');
    setStatus('Prompt corrigido colocado na caixa de geração.');
    endTask('img', signal);
    if (again) generateImage({ direct: true });
  } catch (e) {
    if (!isAbort(e)) { alert('Não deu para corrigir: ' + e.message); setStatus('Falha ao corrigir o prompt'); }
  } finally { endTask('img', signal); btn.disabled = false; }
}

function setAspectSelects(aspect) {
  if (!aspect) return;
  for (const id of ['img-aspect', 'sd-aspect']) {
    const asp = document.getElementById(id);
    if (asp && [...asp.options].some(o => o.value === aspect)) asp.value = aspect;
  }
}

async function assistSinglePrompt() {
  const instruction = document.getElementById('img-input').value.trim();
  const text = document.getElementById('assist-text').value;
  const layout = document.getElementById('comic-layout').value;
  const layout_text = document.getElementById('layout-text').value;
  const sfx_text = document.getElementById('sfx-text').value;
  const layObj = layoutById(layout);
  if (!instruction && !text.trim()) { alert('Escreva na caixa de baixo o que você quer na imagem/página (ou cole um texto de referência).'); return; }
  const btn = document.getElementById('assist-single');
  const sendBtn = document.getElementById('img-send');
  btn.disabled = sendBtn.disabled = true;
  const signal = beginTask('img');
  setStatus((layObj && layObj.count > 1 ? 'O auxiliar está gerando os prompts dos ' + layObj.count + ' quadros' : 'O auxiliar está escrevendo o(s) prompt(s)') +
            (refs.length ? ' e analisando ' + refs.length + ' imagem(ns)' : '') + '...');
  try {
    const images = [], image_names = [];
    for (const r of refs) {
      if (r.name) image_names.push(r.name);
      else images.push(await shrinkDataUrl(r.data));
    }
    const resp = await fetch('/api/prompt-assist', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'auto', instruction, text, images, image_names,
                             model: document.getElementById('assist-model').value,
                             generator: document.getElementById('img-provider').value,
                             layout, layout_text, sfx_text,
                             sfx_mode: document.getElementById('sfx-draw').checked ? 'draw' : 'overlay',
                             characters: [...selectedChars], auto_characters: true }), signal });
    const d = await resp.json().catch(() => ({}));
    if (!resp.ok || !d.ok) throw new Error(d.message || ('HTTP ' + resp.status));
    showAssistWarning(d);
    if (refs.length && d.images_used) refsInPrompt = refsKey();
    if (d.kind === 'panels') {
      currentPlan = d;
      currentPlan.instruction = instruction;
      renderPlan();
      (d.characters_used || []).forEach(id => selectedChars.add(id));
      renderCharChips();
      setStatus('Prompts gerados para ' + d.panels.length + ' quadro(s) por ' + (d.provider || '') + ' / ' + (d.model || '') + '. Gere cada quadro como imagem ou todos de uma vez.');
      return;
    }
    (d.characters_used || []).forEach(id => selectedChars.add(id));
    renderCharChips();
    document.getElementById('assist-on').checked = false;
    onAssistToggle();
    setAspectSelects(d.aspect);
    const inp = document.getElementById('img-input');
    inp.value = d.prompt + (d.negative ? '\nAvoid: ' + d.negative : '');
    inp.focus();
    setStatus('Prompt de tela inteira (splash) escrito por ' + (d.provider || '') + ' / ' + (d.model || '') +
              (d.explanation ? ' — ' + d.explanation : '') + ' Revise e clique em Gerar Arte.');
  } catch (e) {
    if (!isAbort(e)) {
      alert('O auxiliar não conseguiu escrever o prompt: ' + e.message);
      setStatus('Falha no auxiliar de prompt');
    }
  } finally { endTask('img', signal); btn.disabled = sendBtn.disabled = false; }
}

async function planPanels() {
  const instruction = document.getElementById('img-input').value.trim();
  if (!instruction) { alert('Escreva o pedido na caixa de baixo (ex.: página de 5 quadros...).'); return; }
  const btn = document.getElementById('img-send');
  btn.disabled = true;
  const signal = beginTask('img');
  setStatus('O auxiliar está planejando os quadros' + (refs.length ? ' e analisando ' + refs.length + ' imagem(ns)' : '') + '...');
  try {
    const images = [], image_names = [];
    for (const r of refs) {
      if (r.name) image_names.push(r.name);
      else images.push(await shrinkDataUrl(r.data));
    }
    const resp = await fetch('/api/prompt-assist', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction, text: document.getElementById('assist-text').value, images, image_names,
                             model: document.getElementById('assist-model').value,
                             generator: document.getElementById('img-provider').value,
                             layout: document.getElementById('comic-layout').value,
                             layout_text: document.getElementById('layout-text').value,
                             sfx_text: document.getElementById('sfx-text').value,
                             sfx_mode: document.getElementById('sfx-draw').checked ? 'draw' : 'overlay',
                             characters: [...selectedChars], auto_characters: true }), signal });
    const d = await resp.json().catch(() => ({}));
    if (!resp.ok || !d.ok) throw new Error(d.message || ('HTTP ' + resp.status));
    showAssistWarning(d);
    currentPlan = d;
    currentPlan.instruction = instruction;
    renderPlan();
    (d.characters_used || []).forEach(id => selectedChars.add(id));
    renderCharChips();
    setStatus(d.panels.length + ' quadro(s) planejados por ' + (d.provider || '') + ' / ' + (d.model || '') +
              (d.images_used ? ' (viu ' + d.images_used + ' imagem(ns))' : '') +
              ((d.characters_used || []).length ? ', fichas: ' + d.characters_used.length : '') + '. Revise e gere.');
  } catch (e) {
    if (!isAbort(e)) {
      alert('O auxiliar não conseguiu planejar: ' + e.message);
      setStatus('Falha no auxiliar de prompt');
    }
  } finally { endTask('img', signal); btn.disabled = false; }
}

function renderPlan() {
  const box = document.getElementById('assist-plan');
  box.innerHTML = '';
  const p = currentPlan;
  if (!p) return;
  const head = el('div', 'plan-head');
  if (p.style) head.appendChild(row('Estilo', p.style));
  const lay = layoutById(p.layout);
  if (lay) head.appendChild(row('Página', lay.name + ' — ' + lay.count + ' quadros'));
  (p.characters || []).forEach(c => {
    const r = row('Personagem ' + (c.name || ''), c.look || '');
    const known = charList.some(k => (k.name || '').toLowerCase() === (c.name || '').toLowerCase());
    if (!known && c.name && c.look) {
      const b = el('button', 'mini-btn', '💾 Salvar como ficha');
      b.title = 'Guarda esta descrição para usar em outras páginas';
      b.onclick = () => openCharacters({ name: c.name, look: c.look });
      r.appendChild(b);
    }
    head.appendChild(r);
  });
  if (p.notes) head.appendChild(el('div', 'policy-warn', '💡 ' + p.notes));
  box.appendChild(head);

  const actions = el('div', 'plan-actions');
  const all = el('button', 'mini-btn key-save', 'Gerar todos os quadros');
  all.onclick = () => generateAllPanels(all);
  const mont = el('button', 'mini-btn', 'Montar página');
  mont.onclick = () => montagePage(mont);
  actions.appendChild(all); actions.appendChild(mont);
  actions.appendChild(el('span', 'ref-name', 'Cada quadro usa o gerador e as configurações escolhidos lá em cima. Os prompts podem ser editados.'));
  box.appendChild(actions);

  p.panels.forEach((pn, i) => {
    const card = el('div', 'panel-card');
    const left = el('div');
    left.appendChild(el('strong', null, 'Quadro ' + (pn.n || i + 1) + (pn.shot ? ' — ' + pn.shot : '')));
    if (pn.excerpt) left.appendChild(el('div', 'excerpt', '“' + pn.excerpt + '”'));
    const ta = el('textarea'); ta.value = pn.prompt || ''; ta.oninput = () => { pn.prompt = ta.value; };
    left.appendChild(ta);
    const neg = el('input'); neg.placeholder = 'evitar (negativo)'; neg.value = pn.negative || '';
    neg.oninput = () => { pn.negative = neg.value; };
    left.appendChild(neg);
    left.appendChild(panelExtras(pn));
    const side = el('div', 'panel-side');
    const asp = el('select');
    ['16:9', '4:3', '1:1', '3:4', '9:16'].forEach(a => { const o = el('option', null, a); o.value = a; asp.appendChild(o); });
    asp.value = pn.aspect || '1:1'; asp.onchange = () => { pn.aspect = asp.value; };
    asp.title = 'Proporção (usada pelo Flux/Pollinations)';
    const thumb = el('img'); thumb.style.display = pn.result ? '' : 'none'; if (pn.result) thumb.src = pn.result.data_url;
    const gen = el('button', 'mini-btn', pn.result ? 'Gerar de novo' : 'Gerar este');
    gen.onclick = () => generatePanel(i, gen, thumb);
    side.appendChild(asp); side.appendChild(thumb); side.appendChild(gen);
    card.appendChild(left); card.appendChild(side);
    pn._thumb = thumb; pn._btn = gen;
    box.appendChild(card);
  });
}

async function generatePanel(i, btn, thumb, sharedSignal) {
  const pn = currentPlan.panels[i];
  const prompt = (pn.prompt || '').trim() + (pn.negative ? '\nAvoid: ' + pn.negative : '');
  if (!prompt.trim()) return true;
  btn.disabled = true;
  const req = withCharacterLoras(currentImageRequest(prompt, pn.aspect));
  const ownSignal = sharedSignal ? null : beginTask('img', { provider: req.provider });
  const signal = sharedSignal || ownSignal;
  setStatus('Gerando quadro ' + (pn.n || i + 1) + '...');
  try {
    const data = await requestImages(req, signal);
    const list = data.images || [data];
    list.slice().reverse().forEach(im => prependGalleryCard(im, prompt));
    pn.result = list[0];
    thumb.src = list[0].data_url; thumb.style.display = '';
    btn.textContent = 'Gerar de novo';
    setStatus('Quadro ' + (pn.n || i + 1) + ' pronto.');
    return true;
  } catch (e) {
    if (isAbort(e)) return false;
    alert('Quadro ' + (pn.n || i + 1) + ': ' + e.message);
    setStatus('Falha no quadro ' + (pn.n || i + 1));
    return true;
  } finally {
    if (ownSignal) endTask('img', ownSignal);
    btn.disabled = false;
  }
}

async function generateAllPanels(btn) {
  btn.disabled = true;
  const prov = document.getElementById('img-provider').value;
  const signal = beginTask('img', { provider: prov });
  try {
    for (let i = 0; i < currentPlan.panels.length; i++) {
      if (signal.aborted) break;
      const pn = currentPlan.panels[i];
      const cont = await generatePanel(i, pn._btn, pn._thumb, signal);
      if (!cont || signal.aborted) break;
    }
    if (!signal.aborted) setStatus('Todos os quadros gerados. Use "Montar página" para juntar.');
  } finally {
    endTask('img', signal);
    btn.disabled = false;
  }
}

function loadImg(src) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; });
}

// Junta os quadros gerados numa página (linhas de 1 ou 2 quadros; quadros largos ocupam a linha toda)
async function montagePage(btn) {
  const done = (currentPlan ? currentPlan.panels : []).filter(p => p.result);
  if (!done.length) { alert('Gere pelo menos um quadro primeiro.'); return; }
  if (layoutById(currentPlan.layout)) return montageLayout(btn);
  btn.disabled = true;
  try {
    const imgs = await Promise.all(done.map(p => loadImg(p.result.data_url)));
    const W = 1600, G = 24, B = 6;
    const wide = im => im.naturalWidth / im.naturalHeight > 1.25;
    const rows = [];
    for (let i = 0; i < imgs.length;) {
      if (wide(imgs[i]) || i === imgs.length - 1 || wide(imgs[i + 1])) { rows.push([i]); i += 1; }
      else { rows.push([i, i + 1]); i += 2; }
    }
    const rowH = rows.map(r => {
      const cw = (W - G * (r.length + 1)) / r.length;
      const hs = r.map(k => cw * imgs[k].naturalHeight / imgs[k].naturalWidth);
      return Math.round(Math.min(Math.max(...hs), cw * 1.5));
    });
    const H = G + rowH.reduce((s, h) => s + h + G, 0);
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d');
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, W, H);
    g.imageSmoothingEnabled = !(document.getElementById('img-provider').value !== 'pollinations');
    let y = G;
    rows.forEach((r, ri) => {
      const cw = (W - G * (r.length + 1)) / r.length, ch = rowH[ri];
      r.forEach((k, j) => {
        const im = imgs[k], x = G + j * (cw + G);
        const s = Math.max(cw / im.naturalWidth, ch / im.naturalHeight);   // "cover"
        const sw = cw / s, sh = ch / s;
        g.drawImage(im, (im.naturalWidth - sw) / 2, (im.naturalHeight - sh) / 2, sw, sh, x, y, cw, ch);
        g.lineWidth = B; g.strokeStyle = '#000'; g.strokeRect(x, y, cw, ch);
      });
      y += ch + G;
    });
    const dataUrl = c.toDataURL('image/png');
    const r = await fetch('/api/image/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_url: dataUrl, label: 'pagina_quadros', prompt: currentPlan.instruction || '' }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
    prependGalleryCard(d, currentPlan.instruction || 'página');
    setStatus('Página montada com ' + done.length + ' quadro(s) e salva em ' + d.saved_path);
  } catch (e) {
    alert('Não deu para montar a página: ' + e.message);
  } finally { btn.disabled = false; }
}

async function requestImages(req, signal) {
  const resp = await fetch('/api/image', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.error) throw new Error(data.error || ('HTTP ' + resp.status));
  return data;
}

// ----- imagens de referência (até 6): a 1ª vai para PixelLab/Retro Diffusion, todas para o auxiliar
const MAX_REFS = 6;
let refs = [];  // {data, name (arquivo da galeria ou null), label}
let refsInPrompt = '';  // assinatura das referências já usadas pelo auxiliar no prompt da caixa
const refsKey = () => refs.map(r => r.name || r.data.slice(-40)).join('|');
// geradores que recebem a imagem de referência (os outros só usam o texto do prompt)
const usesReference = p => p !== 'pollinations';
function showAssistWarning(d) { if (d && d.warning) alert('Atenção: ' + d.warning); }
const REF_EMPTY = 'nenhuma (até 6 — a 1ª vai para PixelLab/Retro Diffusion; todas vão para o auxiliar)';

function renderRefs() {
  const list = document.getElementById('ref-list');
  list.innerHTML = '';
  refs.forEach((r, i) => {
    const it = el('span', 'ref-item');
    const im = el('img'); im.src = r.data; im.title = (i === 0 ? '1ª (vai para o gerador): ' : '') + r.label;
    const x = el('button', null, '×'); x.title = 'Remover'; x.onclick = () => { refs.splice(i, 1); renderRefs(); };
    it.appendChild(im); it.appendChild(x); list.appendChild(it);
  });
  document.getElementById('ref-name').textContent = refs.length ? refs.length + ' imagem(ns)' : REF_EMPTY;
  document.getElementById('ref-clear').style.display = refs.length ? '' : 'none';
}

function setRef(dataUrl, fileName, label) {
  if (refs.some(r => r.data === dataUrl)) return;
  if (refs.length >= MAX_REFS) { alert('Máximo de ' + MAX_REFS + ' imagens de referência.'); return; }
  refs.push({ data: dataUrl, name: fileName || null, label: label || 'imagem' });
  renderRefs();
  setStatus('Referência adicionada (' + refs.length + '/' + MAX_REFS + ').');
}

function clearRef() {
  refs = [];
  renderRefs();
  document.getElementById('ref-file').value = '';
}

// Reduz imagens grandes antes de enviar ao auxiliar (máx. 1024 px, JPEG)
function shrinkDataUrl(dataUrl, max = 1024) {
  return new Promise(resolve => {
    const im = new Image();
    im.onload = () => {
      const k = Math.min(1, max / Math.max(im.naturalWidth, im.naturalHeight));
      if (k >= 1 && dataUrl.length < 1500000) return resolve(dataUrl);
      const c = document.createElement('canvas');
      c.width = Math.round(im.naturalWidth * k); c.height = Math.round(im.naturalHeight * k);
      const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(im, 0, 0, c.width, c.height);
      resolve(c.toDataURL('image/jpeg', 0.9));
    };
    im.onerror = () => resolve(dataUrl);
    im.src = dataUrl;
  });
}

function onRefFile(input) {
  [...(input.files || [])].forEach(f => {
    if (f.size > 8 * 1024 * 1024) { alert(f.name + ': imagem muito grande (máx. 8 MB).'); return; }
    const r = new FileReader();
    r.onload = () => setRef(r.result, null, f.name);
    r.readAsDataURL(f);
  });
  input.value = '';
}

// ----- anexos de texto (.docx/.md/.txt/.pdf)
let chatAttachments = [];

function readAsDataUrl(file) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
}

async function extractFile(file) {
  const data = await readAsDataUrl(file);
  const r = await fetch('/api/extract', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify({ name: file.name, data }) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
  return d;
}

function renderChatAttach() {
  const bar = document.getElementById('chat-attach-bar');
  bar.innerHTML = '';
  bar.style.display = chatAttachments.length ? '' : 'none';
  chatAttachments.forEach((a, i) => {
    const c = el('span', 'chip' + (a.warning ? ' warn' : ''), '📎 ' + a.name + ' (' + a.text.length.toLocaleString('pt-BR') + ' caract.)');
    if (a.warning) c.title = a.warning;
    const x = el('button', null, '×'); x.title = 'Remover'; x.onclick = () => { chatAttachments.splice(i, 1); renderChatAttach(); };
    c.appendChild(x); bar.appendChild(c);
  });
}

async function onChatFiles(input) {
  const files = [...(input.files || [])];
  input.value = '';
  for (const f of files) {
    setStatus('Lendo ' + f.name + '...');
    try {
      const d = await extractFile(f);
      chatAttachments.push({ name: f.name, text: d.text, warning: d.warning });
      setStatus('Anexado: ' + f.name + (d.warning ? ' — ' + d.warning : ''));
    } catch (e) { alert(f.name + ': ' + e.message); setStatus('Falha ao ler ' + f.name); }
  }
  renderChatAttach();
}

async function onAssistFile(input) {
  const f = input.files && input.files[0];
  input.value = '';
  if (!f) return;
  setStatus('Lendo ' + f.name + '...');
  try {
    const d = await extractFile(f);
    const ta = document.getElementById('assist-text');
    ta.value = (ta.value.trim() ? ta.value.trim() + '\n\n' : '') + d.text;
    setStatus('Texto de ' + f.name + ' carregado' + (d.warning ? ' — ' + d.warning : '.'));
  } catch (e) { alert(f.name + ': ' + e.message); }
}

// ----- geradores de pixel art
let imgOptions = null;
const PIX_HINTS = {
  pollinations: 'Descreva a arte (ex: dark dieselpunk bunker corridor, eerie green emergency light, gothic soldier)...',
  pixellab: 'Descreva o sprite/personagem em inglês (ex: knight with red cape, side view). Tileset: "grass | dirt path". Animar: a ação (walking).',
  retrodiffusion: 'Descreva em inglês (ex: small slime monster, idle). Estilos "Animar referência" usam a imagem de referência.',
  scenario: 'Descreva o asset. Informe o modelId do modelo da Scenario ao lado.',
  sdlocal: 'Descreva em inglês (ex: pixel art knight, side view, red cape). Roda no seu PC, sem internet; escolha LoRAs no botão ao lado.'
};

async function loadImgOptions() {
  if (imgOptions) return imgOptions;
  try { imgOptions = await (await fetch('/api/image/options')).json(); } catch (e) { imgOptions = {}; }
  return imgOptions;
}

async function onImgProviderChange() {
  const prov = document.getElementById('img-provider').value;
  const sd = prov === 'sdlocal' || isRemoteSd(prov);
  const pix = prov !== 'pollinations' && !sd;
  document.getElementById('pix-controls').style.display = pix ? '' : 'none';
  document.getElementById('poll-controls').style.display = prov === 'pollinations' ? '' : 'none';
  document.getElementById('sd-controls').style.display = sd ? '' : 'none';
  document.getElementById('pix-model-id').style.display = prov === 'scenario' ? '' : 'none';
  document.getElementById('img-input').placeholder = PIX_HINTS[prov] || '';
  if (!sd) document.getElementById('lora-panel').style.display = 'none';
  if (sd) { await loadSdLocal(true); return; }
  if (!pix) return;
  const opts = (await loadImgOptions())[prov] || [];
  const sel = document.getElementById('pix-mode');
  sel.innerHTML = '';
  opts.forEach(o => {
    const op = el('option', null, o.label);
    op.value = o.id;
    op.dataset.fixed = o.fixed ? o.fixed.join('x') : '';
    sel.appendChild(op);
  });
  if (prov === 'scenario') { document.getElementById('pix-w').value = 512; document.getElementById('pix-h').value = 512; }
  else if (parseInt(document.getElementById('pix-w').value, 10) > 256) {
    document.getElementById('pix-w').value = 64; document.getElementById('pix-h').value = 64;
  }
  onPixModeChange();
}

// ----- Stable Diffusion local (offline, LoRAs)
let sdStatus = null;
const sdLoraSel = {};   // nome da LoRA -> peso

function isRemoteSd(prov) {
  const o = document.querySelector('#img-provider option[value="' + prov + '"]');
  return !!(o && o.dataset.custom);
}

async function loadSdLocal(force) {
  const prov = document.getElementById('img-provider').value;
  const remote = isRemoteSd(prov);
  if (force || !sdStatus) {
    setStatus(remote ? 'Consultando os modelos e LoRAs do servidor...' : 'Carregando o Stable Diffusion local...');
    try {
      const r = await fetch('/api/image/sd-info?id=' + encodeURIComponent(remote ? prov : 'sdlocal'));
      sdStatus = await r.json();
      if (!r.ok) { setStatus('Servidor de imagens: ' + (sdStatus.message || 'não respondeu')); sdStatus = { models: [], loras: [] }; return; }
    } catch (e) { sdStatus = {}; }
  }
  if (remote) {
    const sel0 = document.getElementById('sd-model');
    sel0.innerHTML = '';
    (sdStatus.models || []).forEach(m => { const o = el('option', null, m.label); o.value = m.file; sel0.appendChild(o); });
    sel0.value = sdStatus.default_model || '';
    updateLoraButton();
    setStatus((sdStatus.label || 'Servidor') + ': ' + (sdStatus.models || []).length + ' modelo(s), ' +
              (sdStatus.loras || []).length + ' LoRA(s) disponíveis.');
    return;
  }
  const sel = document.getElementById('sd-model');
  const cur = sel.value;
  sel.innerHTML = '';
  (sdStatus.models || []).forEach(m => {
    const o = el('option', null, m.label + (m.family === 'sdxl' ? ' (SDXL, pesado)' : ' (SD 1.5, leve)'));
    o.value = m.file; sel.appendChild(o);
  });
  sel.value = cur && [...sel.options].some(o => o.value === cur) ? cur : (sdStatus.default_model || '');
  updateLoraButton();
  if (!sdStatus.installed) {
    setStatus('Stable Diffusion local não instalado: rode bat\\Instalar_SD_Local_IA.bat (ele analisa a máquina e instala a versão leve).');
  } else if (!sdStatus.enabled) {
    setStatus('Stable Diffusion local instalado mas desligado: SDLOCAL_ENABLED=1 no ~/.env (o instalador grava).');
  } else {
    setStatus('Stable Diffusion local pronto' + (sdStatus.running ? ' (motor ligado).' : ': o motor liga sozinho na primeira imagem (pode levar ~1 min).'));
  }
}

function updateLoraButton() {
  const n = Object.keys(sdLoraSel).length;
  const b = document.getElementById('sd-lora-btn');
  if (b) b.textContent = 'LoRAs (' + n + ')';
}

function toggleLoraPanel() {
  const box = document.getElementById('lora-panel');
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  box.innerHTML = '';
  box.appendChild(el('strong', null, 'LoRAs instaladas'));
  const fam = ((sdStatus.models || []).find(m => m.file === document.getElementById('sd-model').value) || {}).family || 'sd15';
  const loras = (sdStatus.loras || []).filter(l => !l.lcm);
  if (!loras.length) {
    box.appendChild(el('div', 'ref-name', 'Nenhuma LoRA ainda (a LCM do modo rápido é usada sozinha e não aparece aqui).'));
  }
  loras.forEach(l => {
    const line = el('div', 'key-line');
    const cb = el('input'); cb.type = 'checkbox'; cb.checked = l.name in sdLoraSel;
    const w = el('input'); w.type = 'number'; w.min = -2; w.max = 2; w.step = 0.05; w.style.width = '64px';
    w.value = sdLoraSel[l.name] ?? 0.8; w.title = 'peso (0.6 a 1.0 costuma funcionar)';
    const sync = () => { if (cb.checked) sdLoraSel[l.name] = parseFloat(w.value) || 0.8; else delete sdLoraSel[l.name]; updateLoraButton(); };
    cb.onchange = sync; w.oninput = sync;
    const lab = el('label', null, ' ' + l.file); lab.prepend(cb);
    line.appendChild(lab); line.appendChild(w);
    box.appendChild(line);
  });
  box.appendChild(el('div', 'ref-name', 'Use LoRAs do mesmo tipo do modelo (' + (fam === 'sdxl' ? 'SDXL' : 'SD 1.5') +
    '). Para adicionar: baixe o .safetensors (ex.: civitai.com, huggingface.co) e coloque em ' + (sdStatus.folder_loras || 'sdlocal\\models\\loras') +
    '. Muitas LoRAs pedem uma palavra de ativação no prompt (veja a página dela).'));
  const re = el('button', 'mini-btn', 'Atualizar lista');
  re.onclick = async () => { await loadSdLocal(true); box.style.display = 'none'; toggleLoraPanel(); };
  box.appendChild(re);
  box.style.display = '';
}

// No SD local, soma as LoRAs e as palavras de ativação das fichas em cena ao pedido
function withCharacterLoras(req) {
  if (req.provider !== 'sdlocal' && !isRemoteSd(req.provider)) return req;
  const ex = characterLoraExtras();
  const names = new Set((req.loras || []).map(l => l.name));
  req.loras = (req.loras || []).concat(ex.loras.filter(l => !names.has(l.name)));
  const missing = ex.triggers.filter(t => !req.prompt.toLowerCase().includes(t.toLowerCase()));
  if (missing.length) req.prompt = missing.join(', ') + ', ' + req.prompt;
  return req;
}

// LoRAs e palavras de ativação das fichas citadas no plano (só para o SD local)
function characterLoraExtras() {
  const ids = new Set([...(currentPlan && currentPlan.characters_used || []), ...selectedChars, ...autoChars]);
  const loras = [], triggers = [];
  charList.filter(c => ids.has(c.id)).forEach(c => {
    if (c.lora) loras.push({ name: c.lora, weight: c.lora_weight || 0.8 });
    if (c.trigger) triggers.push(c.trigger);
  });
  return { loras, triggers };
}

function onPixModeChange() {
  const sel = document.getElementById('pix-mode');
  const op = sel.options[sel.selectedIndex];
  const fixed = op && op.dataset.fixed;
  const w = document.getElementById('pix-w'), h = document.getElementById('pix-h');
  if (fixed) { const [a, b] = fixed.split('x'); w.value = a; h.value = b; }
  w.disabled = h.disabled = !!fixed;
}

// Monta o pedido de geração com as configurações atuais da tela
function currentImageRequest(prompt, aspectOverride) {
  const provider = document.getElementById('img-provider').value;
  const req = { provider, prompt };
  if (provider === 'pollinations') {
    req.model = document.getElementById('img-model').value;
    req.aspect = aspectOverride || document.getElementById('img-aspect').value;
  } else if (provider === 'sdlocal' || isRemoteSd(provider)) {
    req.model = document.getElementById('sd-model').value;
    req.aspect = aspectOverride || document.getElementById('sd-aspect').value;
    req.fast = document.getElementById('sd-fast').checked;
    req.loras = Object.entries(sdLoraSel).map(([name, weight]) => ({ name, weight }));
    req.strength = parseFloat(document.getElementById('sd-strength').value) || 0.6;
    const r0 = refs[0];
    if (r0 && r0.name) req.reference_name = r0.name;
    else if (r0) req.reference_data = r0.data;
  } else {
    req.mode = document.getElementById('pix-mode').value;
    req.width = parseInt(document.getElementById('pix-w').value, 10) || 64;
    req.height = parseInt(document.getElementById('pix-h').value, 10) || 64;
    req.transparent = document.getElementById('pix-transp').checked;
    req.model_id = document.getElementById('pix-model-id').value.trim();
    const r0 = refs[0];
    if (r0 && r0.name) req.reference_name = r0.name;
    else if (r0) req.reference_data = r0.data;
  }
  return req;
}

async function generateImage(opts) {
  opts = opts || {};
  if (!opts.direct && document.getElementById('assist-on').checked) return planPanels();
  const input = document.getElementById('img-input');
  const btn = document.getElementById('img-send');
  const prompt = input.value.trim();
  if (!prompt) return;

  const req = withCharacterLoras(currentImageRequest(prompt));
  const provider = req.provider;
  if (!opts.direct && refs.length && !usesReference(provider) && refsInPrompt !== refsKey()) {
    const ok = confirm('O Flux/Pollinations não recebe a imagem de referência: ele só lê o texto do prompt.\n\n' +
                       'OK = o auxiliar olha a(s) ' + refs.length + ' referência(s) e reescreve o prompt descrevendo o ' +
                       'personagem/estilo (depois é só clicar em Gerar Arte).\n' +
                       'Cancelar = gerar agora só com o texto.\n\n' +
                       'Para usar a imagem de verdade, escolha o Stable Diffusion local, PixelLab ou Retro Diffusion.');
    if (ok) return assistSinglePrompt();
  }

  btn.disabled = true;
  const signal = beginTask('img', { provider });
  setStatus(provider === 'pollinations'
    ? 'Gerando imagem privada (' + req.model + ', ' + req.aspect + ')...'
    : (provider === 'sdlocal' || isRemoteSd(provider))
      ? (isRemoteSd(provider) ? 'Gerando no servidor de imagens' : 'Gerando no seu PC') + ' (' + req.model + (req.loras.length ? ', ' + req.loras.length + ' LoRA(s)' : '') + ')... a 1ª imagem liga o motor e demora mais.'
      : 'Gerando com ' + provider + ' (' + req.mode + ')... pode levar alguns minutos.');

  try {
    const data = await requestImages(req, signal);
    const list = data.images || [data];
    list.slice().reverse().forEach(im => prependGalleryCard(im, prompt));
    setStatus(list.length > 1 ? list.length + ' imagens salvas em ' + list[0].saved_path.replace(/[^\\/]+$/, '')
                              : 'Imagem salva em ' + list[0].saved_path);
  } catch (err) {
    if (!isAbort(err)) {
      alert('Erro ao gerar imagem: ' + err.message);
      document.getElementById('status-txt').textContent = 'Erro ao gerar imagem';
    }
  } finally {
    endTask('img', signal);
    btn.disabled = false;
  }
}

document.getElementById('chat-input').addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') sendChat();
});
document.getElementById('img-input').addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') generateImage();
});

function fmtWait(secs) {
  if (!secs) return '';
  if (secs < 90) return secs + ' s';
  if (secs < 5400) return Math.round(secs / 60) + ' min';
  return (secs / 3600).toFixed(1) + ' h';
}

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '—';
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function row(label, value) {
  const d = el('div', 'prov-row');
  d.appendChild(document.createTextNode(label + ': '));
  d.appendChild(el('b', null, value));
  return d;
}

let showHiddenProviders = false;

function toggleHiddenProviders() {
  showHiddenProviders = !showHiddenProviders;
  renderProviders(lastProvidersData);
}

async function providerEdit(body) {
  const r = await fetch('/api/providers/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.message || ('HTTP ' + r.status));
  return d;
}

// Editar um provedor padrão (ou uma chave extra): nome exibido, modelo fixo, ligado/desligado, remover
function providerEditForm(p, card) {
  if (card.querySelector('.prov-edit')) return;
  const box = el('div', 'key-box prov-edit');
  const mk = (label, input) => { const l = el('div', 'key-line'); const t = el('label', null, label); t.style.minWidth = '95px'; l.appendChild(t); l.appendChild(input); box.appendChild(l); return input; };
  const name = mk('Nome exibido', el('input')); name.value = p.label; name.placeholder = p.orig_label || p.label;
  let model = null;
  if (!p.local && p.kind !== 'image') {
    model = mk('Modelo fixo', el('input')); model.value = p.user_model || '';
    model.placeholder = 'vazio = automático (ex.: ' + (p.last_model || 'nome-do-modelo') + ')';
  }
  const lab = el('label'); const on = el('input'); on.type = 'checkbox'; on.checked = !p.disabled;
  lab.appendChild(on); lab.appendChild(document.createTextNode(' ligado (participa do rodízio / da lista)'));
  box.appendChild(lab);
  const msg = el('div', 'key-msg');
  const line = el('div', 'key-line');
  const save = el('button', 'mini-btn key-save', 'Salvar');
  save.onclick = async () => {
    try {
      const body = { id: p.id, label: name.value, disabled: !on.checked };
      if (model) body.model = model.value;
      await providerEdit(body);
      loadProviders(true);
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
  };
  const rm = el('button', 'mini-btn danger', p.instance ? 'Remover esta chave' : 'Remover');
  rm.onclick = async () => {
    const txt = p.instance
      ? 'Remover a chave extra "' + p.label + '"? Ela é apagada do ~/.env.'
      : 'Remover "' + p.label + '" do painel e do rodízio?\n\n' + (p.local ? '' : 'A chave dele é apagada do ~/.env. ') +
        'Dá para trazer de volta em "Mostrar removidos" (aí é só cadastrar a chave de novo).';
    if (!confirm(txt)) return;
    try { const d = await providerEdit({ id: p.id, action: 'remove' }); setStatus(d.message); loadProviders(true); }
    catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
  };
  const cancel = el('button', 'mini-btn', 'Cancelar'); cancel.onclick = () => box.remove();
  line.appendChild(save); line.appendChild(rm); line.appendChild(cancel);
  box.appendChild(line); box.appendChild(msg);
  card.insertBefore(box, card.children[1] || null);
}

function renderProviders(data) {
  const list = document.getElementById('providers-list');
  list.innerHTML = '';
  const hiddenCount = (data.providers || []).filter(p => p.hidden).length;
  const hb = document.getElementById('btn-show-hidden');
  if (hb) {
    hb.style.display = hiddenCount && canAdmin() ? '' : 'none';
    hb.textContent = showHiddenProviders ? 'Esconder removidos' : 'Mostrar removidos (' + hiddenCount + ')';
  }
  let n = 0;
  (data.providers || []).forEach((p) => {
    if (p.hidden && !showHiddenProviders) return;
    const idx = p.kind === 'image' || p.hidden ? -1 : n++;
    const cls = p.hidden ? 'off' : (!p.configured || p.disabled ? 'off' : (p.available ? 'ok' : 'wait'));
    const card = el('div', 'prov-card ' + cls);
    const head = el('div', 'prov-head');
    const title = el('strong', null, (idx < 0 ? '' : (idx + 1) + '. ') + p.label);
    if (p.kind === 'image') title.appendChild(el('span', 'kind-badge', 'imagem'));
    if (!p.custom && canAdmin() && !p.hidden) {
      const eb = el('button', 'mini-btn', '✎');
      eb.title = 'Editar: nome, modelo fixo, ligar/desligar, remover';
      eb.style.marginLeft = '6px';
      eb.onclick = () => providerEditForm(p, card);
      title.appendChild(eb);
    }
    head.appendChild(title);
    let state = 'ATIVO';
    if (p.hidden) state = 'REMOVIDO';
    else if (p.disabled) state = 'DESLIGADO';
    else if (!p.configured) state = p.local ? 'DESATIVADO' : 'SEM CHAVE';
    else if (!p.available) state = 'EM ESPERA' + (p.cooldown_seconds ? ' · volta em ' + fmtWait(p.cooldown_seconds) : '');
    head.appendChild(el('span', 'prov-state', state));
    card.appendChild(head);

    if (p.hidden) {
      card.appendChild(el('div', 'prov-row', 'Removido por você: fora do painel e do rodízio.'));
      const rb = el('button', 'mini-btn key-save', 'Restaurar');
      rb.onclick = async () => { try { const d = await providerEdit({ id: p.id, action: 'restore' }); setStatus(d.message); loadProviders(true); } catch (e) { alert(e.message); } };
      card.appendChild(rb);
      list.appendChild(card);
      return;
    }
    if (p.disabled) card.appendChild(el('div', 'prov-row', '⏸ Desligado por você: não participa do rodízio. Use ✎ para ligar de novo.'));
    if (p.user_model) card.appendChild(row('Modelo fixo', p.user_model));

    if (!p.configured) {
      if (p.id === 'sdlocal') {
        card.appendChild(el('div', 'prov-row', 'Gerador de imagens offline (com LoRAs) desativado. Rode bat\\Instalar_SD_Local_IA.bat: ele analisa a placa de vídeo e instala a versão leve (SD 1.5) — e a pesada (SDXL), se a máquina aguentar.'));
      } else if (p.local) {
        card.appendChild(el('div', 'prov-row', 'IA local desativada. Rode bat\\Instalar_Ollama_IA.bat (analisa a máquina antes de instalar).'));
        const a = el('a', 'key-link', 'Baixar Ollama ↗');
        a.href = p.key_url; a.target = '_blank'; a.rel = 'noopener';
        card.appendChild(a);
      } else {
        card.appendChild(el('div', 'prov-row', 'Nenhuma chave encontrada' + (p.free_tier ? ' — este provedor tem plano grátis.' : ' — provedor pago (crédito pré-pago).')));
        if (canAdmin()) card.appendChild(keyEditor(p));
      }
    } else {
      if (p.custom) {
        card.appendChild(row('Usado para', (p.uses || ['texto']).map(u => u === 'imagens' ? 'imagens (Stable Diffusion)' : 'texto').join(' e ')));
      card.appendChild(row('Servidor', p.base_url || ''));
        card.appendChild(row('Modelo', p.custom_model || 'automático (o servidor escolhe/lista)'));
        card.appendChild(row('Chave', p.has_key ? (p.key_mask || '••••') : 'nenhuma'));
        card.appendChild(row('Posição', (lastProvidersData.custom_positions || {})[p.position] || p.position || ''));
        if (p.vision) card.appendChild(el('div', 'prov-row', '👁 enxerga imagens (usado pelo auxiliar de prompt)'));
        if (canAdmin()) {
          const line = el('div', 'key-line');
          const ed = el('button', 'mini-btn', 'Editar');
          ed.onclick = () => openCustomForm(p.id);
          const rm = el('button', 'mini-btn danger', 'Remover');
          rm.onclick = async () => {
            if (!confirm('Remover o provedor personalizado "' + p.label + '"?')) return;
            try { await customPost({ action: 'delete', id: p.id }); loadProviders(true); refreshModelMenus(); }
            catch (e) { alert(e.message); }
          };
          line.appendChild(ed); line.appendChild(rm);
          card.appendChild(line);
        }
      } else if (!p.local && canAdmin()) {
        const kr = row('Chave', p.key_mask || '••••');
        const tb = el('button', 'mini-btn', 'Trocar chave');
        tb.style.marginLeft = '8px';
        tb.onclick = () => {
          if (card.querySelector('.key-box')) return;
          card.insertBefore(keyEditor(p, true), kr.nextSibling);
        };
        kr.appendChild(tb);
        if (!p.instance) {
          // Mais uma chave do mesmo provedor (vira "Provedor #2", "#3"...)
          const ab = el('button', 'mini-btn', '+ Outra chave');
          ab.style.marginLeft = '6px';
          ab.title = 'Adicionar outra chave deste provedor ao rodízio';
          ab.onclick = () => {
            if (card.querySelector('.key-box')) return;
            const ok = confirm(
              'Atenção às políticas de uso\n\n' +
              'Ter mais de uma chave é normal em alguns casos (conta pessoal e do trabalho, projetos separados).\n' +
              'Mas criar várias contas no mesmo serviço só para somar limites gratuitos costuma VIOLAR os termos de uso, ' +
              'e o provedor pode bloquear TODAS as contas envolvidas.\n\n' +
              'A responsabilidade é sua. O rodízio espera ' + (lastProvidersData.key_delay || 5) +
              ' s entre o uso de uma chave e outra do mesmo provedor (ROUTER_KEY_DELAY).\n\nContinuar?');
            if (!ok) return;
            card.insertBefore(keyEditor(p, false, true), kr.nextSibling);
          };
          kr.appendChild(ab);
        }
        card.appendChild(kr);
      }
      if (p.reason) card.appendChild(row('Motivo', p.reason));
      if (p.note) card.appendChild(el('div', 'prov-err', '⚠ ' + p.note));
      const t = p.today || {};
      card.appendChild(row('Hoje', `${t.ok || 0} ok · ${t.errors || 0} erros` + (p.daily_limit ? ` · limite local ${p.daily_limit}` : '')));
      if (p.last_model) card.appendChild(row('Modelo', p.last_model));
      card.appendChild(row('Último sucesso', fmtTime(p.last_ok)));
      const rl = p.ratelimit || {};
      const remReq = rl['x-ratelimit-remaining-requests'] || rl['x-ratelimit-remaining'];
      const limReq = rl['x-ratelimit-limit-requests'] || rl['x-ratelimit-limit'];
      if (remReq) card.appendChild(row('Pedidos restantes (informado)', remReq + (limReq ? ' de ' + limReq : '')));
      if (rl['x-ratelimit-remaining-tokens']) card.appendChild(row('Tokens restantes', rl['x-ratelimit-remaining-tokens']));
      if (p.account) {
        const a = p.account;
        card.appendChild(row('Conta', (a.is_free_tier ? 'plano grátis' : 'com créditos') +
          (a.limit_remaining != null ? ' · restante ' + a.limit_remaining : '') +
          (a.usage_daily != null ? ' · uso hoje $' + a.usage_daily : '')));
      }
      if (p.last_error) {
        card.appendChild(el('div', 'prov-err', 'Último erro (' + fmtTime(p.last_error.at) + ', ' + (p.last_error.code || 'rede') + '): ' + (p.last_error.message || '').slice(0, 160)));
      }
      if (!p.available) {
        const b = el('button', 'mini-btn', 'Tentar de novo agora');
        b.onclick = () => resetProvider(p.id);
        card.appendChild(b);
      }
    }
    list.appendChild(card);
  });
}

// Editor de chave: link para criar a chave + campo para colar + salvar/remover
function keyEditor(p, isChange, isAdd) {
  const box = el('div', 'key-box');
  const a = el('a', 'key-link', (isChange || isAdd ? 'Abrir site da chave' : (p.free_tier ? 'Criar chave grátis' : 'Criar chave')) + ' ↗');
  a.href = p.key_url; a.target = '_blank'; a.rel = 'noopener';
  box.appendChild(a);
  if (isAdd) box.appendChild(el('div', 'policy-warn', 'Nova chave extra deste provedor: fica no FIM do rodízio (só é usada se todos os outros provedores falharem, ou quando você pedir um modelo deste serviço).'));
  if (p.key_hint) box.appendChild(el('div', 'prov-row', p.key_hint));

  const line = el('div', 'key-line');
  const inp = el('input');
  inp.type = 'password';
  inp.placeholder = isAdd ? 'Cole aqui a chave extra' : 'Cole aqui a chave ' + p.key_env;
  inp.autocomplete = 'off';
  inp.spellcheck = false;
  const save = el('button', 'mini-btn key-save', 'Salvar');
  line.appendChild(inp);
  line.appendChild(save);
  box.appendChild(line);

  const msg = el('div', 'key-msg');
  box.appendChild(msg);

  if (isChange) {
    const actions = el('div', 'key-line');
    const cancel = el('button', 'mini-btn', 'Cancelar');
    cancel.onclick = () => { box.remove(); };
    actions.appendChild(cancel);
    const rm = el('button', 'mini-btn danger', 'Remover chave');
    rm.onclick = async () => {
      if (!confirm('Remover a chave de ' + p.label + ' do ~/.env?')) return;
      await sendKey(p, { action: 'remove' }, msg, box);
    };
    actions.appendChild(rm);
    box.appendChild(actions);
  }

  const doSave = async () => {
    const key = inp.value.trim();
    if (!key) { msg.className = 'key-msg err'; msg.textContent = 'Cole a chave primeiro.'; return; }
    save.disabled = true;
    msg.className = 'key-msg'; msg.textContent = 'Testando a chave...';
    await sendKey(p, isAdd ? { key, action: 'add' } : { key }, msg, box);
    save.disabled = false;
  };
  save.onclick = doSave;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') doSave(); });
  return box;
}

async function sendKey(p, payload, msg, box) {
  try {
    const r = await fetch('/api/providers/key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ provider: p.id }, payload))
    });
    const d = await r.json();
    msg.className = 'key-msg ' + (d.ok ? 'ok' : 'err');
    msg.textContent = d.message || (d.ok ? 'OK' : 'Falhou');
    if (d.ok) {
      box.querySelectorAll('input').forEach(i => i.value = '');
      setTimeout(() => { if (d.status) renderProviders(d.status); }, 1200);
    }
  } catch (e) {
    msg.className = 'key-msg err';
    msg.textContent = 'Erro: ' + e.message;
  }
}

// Não redesenha os cartões enquanto o usuário está digitando uma chave
function isEditingKey() {
  return [...document.querySelectorAll('.key-box input')].some(i => i.value || i === document.activeElement);
}

let lastProvidersData = {};
let customPositions = null;
let customUses = null;

async function customPost(body) {
  const r = await fetch('/api/custom-providers', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                  body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) { const e = new Error(d.message || ('HTTP ' + r.status)); e.data = d; throw e; }
  return d;
}

// Coloca os provedores personalizados nos menus de modelo (chat e auxiliar)
function refreshModelMenus() {
  const all = (lastProvidersData.providers || []).filter(p => p.custom);
  const customs = all.filter(p => (p.uses || ['texto']).includes('texto'));
  const imgSel = document.getElementById('img-provider');
  if (imgSel) {
    const cur = imgSel.value;
    [...imgSel.querySelectorAll('option[data-custom]')].forEach(o => o.remove());
    all.filter(p => (p.uses || []).includes('imagens')).forEach(p => {
      const o = el('option', null, '★ ' + p.label + ' (Stable Diffusion de outro PC)');
      o.value = p.id; o.dataset.custom = '1'; imgSel.appendChild(o);
    });
    if ([...imgSel.options].some(o => o.value === cur)) imgSel.value = cur;
  }
  [['chat-model', ''], ['assist-model', 'vision-or-text']].forEach(([id]) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    [...sel.querySelectorAll('option[data-custom]')].forEach(o => o.remove());
    customs.forEach(p => {
      const o = el('option', null, '★ ' + p.label + ' (personalizado' + (id === 'assist-model' ? (p.vision ? ', vê imagens' : ', só texto') : '') + ')');
      o.value = p.id + '/auto';
      o.dataset.custom = '1';
      sel.appendChild(o);
    });
  });
  filterModelMenus();
}

// Mostra nas listas só os modelos/geradores com chave funcionando e ativos (os em espera curta ficam marcados)
async function filterModelMenus() {
  const ids = ['chat-model', 'assist-model', 'img-provider'];
  const sels = ids.map(id => document.getElementById(id)).filter(Boolean);
  const values = [...new Set(sels.flatMap(sel => [...sel.options].map(o => o.value)).filter(v => v && v !== 'pollinations'))];
  let av = {};
  try {
    const r = await fetch('/api/models/availability?' + values.map(v => 'm=' + encodeURIComponent(v)).join('&'));
    av = (await r.json()).models || {};
  } catch (e) { return; }  // sem resposta: deixa as listas como estão
  sels.forEach(sel => {
    let selectedHidden = false;
    [...sel.options].forEach(o => {
      if (o.dataset.label === undefined) o.dataset.label = o.textContent;
      const a = av[o.value];
      if (!a) { o.hidden = false; o.disabled = false; return; }
      o.hidden = o.disabled = !a.show;
      o.textContent = o.dataset.label + (a.show && a.waiting ? ' — em espera' : '');
      o.title = a.reason || '';
      if (!a.show && o.selected) selectedHidden = true;
    });
    if (selectedHidden) {
      const first = [...sel.options].find(o => !o.hidden);
      if (first) { sel.value = first.value; sel.dispatchEvent(new Event('change')); }
    }
  });
}

async function openCustomForm(editId) {
  const slot = document.getElementById('custom-form-slot');
  slot.innerHTML = '';
  let positions = customPositions;
  let existing = null;
  try {
    const d = await (await fetch('/api/custom-providers')).json();
    positions = customPositions = d.positions || {};
    customUses = d.uses || null;
    existing = (d.providers || []).find(c => c.id === editId) || null;
  } catch (e) {}
  const f = el('div', 'acc-section custom-form');
  f.appendChild(el('h3', null, existing ? 'Editar provedor personalizado' : 'Novo provedor personalizado'));
  f.appendChild(el('div', 'prov-row', 'Texto: qualquer servidor compatível com a API da OpenAI — Ollama de outro PC (http://IP:11434/v1), LM Studio (http://localhost:1234/v1), vLLM/SGLang, um modelo aberto hospedado. Imagens: um Stable Diffusion de outro PC com a API WebUI ligada — stable-diffusion.cpp (http://IP:1234), AUTOMATIC1111/Forge com --api (http://IP:7860); os modelos e LoRAs dele aparecem na aba Imagens.'));
  const mk = (label, input) => { const l = el('div', 'key-line'); const t = el('label', null, label); t.style.minWidth = '120px'; l.appendChild(t); l.appendChild(input); f.appendChild(l); return input; };
  const uses = el('select');
  Object.entries(customUses || { texto: 'Texto', imagens: 'Imagens', ambos: 'Os dois' }).forEach(([k, v]) => { const o = el('option', null, v); o.value = k; uses.appendChild(o); });
  uses.value = existing ? (existing.uses || 'texto') : 'texto';
  mk('Usar para', uses);
  const name = mk('Nome', el('input')); name.placeholder = 'ex.: Ollama do PC da sala / SD do Fulano'; name.value = existing ? existing.label : '';
  const base = mk('URL do servidor', el('input')); base.placeholder = 'ex.: http://192.168.0.20:11434/v1'; base.value = existing ? existing.base : '';
  const key = mk('Chave (opcional)', el('input')); key.type = 'password'; key.autocomplete = 'off';
  key.placeholder = existing && existing.has_key ? '(manter a atual)' : 'deixe vazio se o servidor não pede chave';
  const modelSel = el('select');
  const optAuto = el('option', null, 'automático (primeiro modelo do servidor)'); optAuto.value = ''; modelSel.appendChild(optAuto);
  if (existing && existing.model) { const o = el('option', null, existing.model); o.value = existing.model; modelSel.appendChild(o); modelSel.value = existing.model; }
  mk('Modelo', modelSel);
  const pos = el('select');
  Object.entries(positions || {}).forEach(([k, v]) => { const o = el('option', null, v); o.value = k; pos.appendChild(o); });
  pos.value = existing ? existing.position : 'antes_locais';
  mk('Posição no rodízio', pos);
  const syncUses = () => {
    const txt = uses.value !== 'imagens';
    pos.parentNode.style.display = txt ? '' : 'none';
    base.placeholder = txt ? 'ex.: http://192.168.0.20:11434/v1' : 'ex.: http://192.168.0.20:7860';
    key.placeholder = existing && existing.has_key ? '(manter a atual)'
      : (txt ? 'deixe vazio se o servidor não pede chave' : 'vazio, a --api-key do sd-server ou usuario:senha do --api-auth');
  };
  uses.onchange = () => { syncUses(); visionLabel.style.display = uses.value === 'imagens' ? 'none' : ''; };
  const checks = el('div', 'key-line');
  const cb = (txt, val) => { const l = el('label'); const c = el('input'); c.type = 'checkbox'; c.checked = !!val; l.appendChild(c); l.appendChild(document.createTextNode(' ' + txt)); checks.appendChild(l); return c; };
  const vision = cb('enxerga imagens (pode ser usado pelo auxiliar com referências)', existing && existing.vision);
  const visionLabel = vision.parentNode;
  const paid = cb('é pago', existing && existing.paid);
  const skip = cb('salvar mesmo se não conectar agora', false);
  const rmKey = existing && existing.has_key ? cb('remover a chave', false) : null;
  f.appendChild(checks);
  syncUses(); visionLabel.style.display = uses.value === 'imagens' ? 'none' : '';
  const msg = el('div', 'key-msg');
  const btns = el('div', 'key-line');
  const test = el('button', 'mini-btn', 'Testar conexão e listar modelos');
  test.onclick = async () => {
    msg.className = 'key-msg'; msg.textContent = 'Testando...';
    try {
      const d = await customPost({ action: 'test', base: base.value, key: key.value, id: existing && existing.id, uses: uses.value });
      base.value = d.base;
      const cur = modelSel.value;
      [...modelSel.options].slice(1).forEach(o => o.remove());
      (d.models || []).forEach(m => { const o = el('option', null, m); o.value = m; modelSel.appendChild(o); });
      if (cur && [...modelSel.options].some(o => o.value === cur)) modelSel.value = cur;
      msg.className = 'key-msg ok'; msg.textContent = d.message;
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
  };
  const save = el('button', 'mini-btn key-save', 'Salvar');
  save.onclick = async () => {
    msg.className = 'key-msg'; msg.textContent = 'Salvando...';
    try {
      const d = await customPost({ action: 'save', id: existing && existing.id, label: name.value, base: base.value,
        key: key.value, model: modelSel.value, position: pos.value, vision: vision.checked, paid: paid.checked,
        skip_test: skip.checked, remove_key: rmKey ? rmKey.checked : false, uses: uses.value });
      msg.className = 'key-msg ok'; msg.textContent = d.message;
      setTimeout(() => { slot.innerHTML = ''; loadProviders(true); }, 800);
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
  };
  const cancel = el('button', 'mini-btn', 'Cancelar');
  cancel.onclick = () => { slot.innerHTML = ''; };
  btns.appendChild(test); btns.appendChild(save); btns.appendChild(cancel);
  f.appendChild(btns);
  f.appendChild(msg);
  slot.appendChild(f);
  name.focus();
}

async function loadProviders(refresh) {
  if (isEditingKey()) return;
  try {
    const r = await fetch('/api/providers' + (refresh ? '?refresh=1' : ''));
    const d = await r.json();
    lastProvidersData = d;
    refreshModelMenus();
    renderProviders(d);
    const active = (d.providers || []).filter(p => p.available && p.kind !== 'image').map(p => p.id);
    document.getElementById('keys-txt').textContent =
      'Ativos: ' + (active.length ? active.join(', ') : 'nenhum') + ' | Porta: ' + location.port;
  } catch (e) {}
}

async function resetProvider(id) {
  await fetch('/api/providers/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: id })
  });
  loadProviders(true);
}

function refreshKeys() { loadProviders(false); }

// ================= QUADRINHOS: modelos de página, onomatopeias, vazamento =================
let comicLayouts = null;        // {page, layouts: [{id, name, count, panels: [{n, poly, aspect}]}]}

async function loadLayouts(force = false, selectId = null) {
  if (comicLayouts && !force) return comicLayouts;
  try {
    const r = await fetch('/api/comic/layouts');
    if (!r.ok) return null;
    comicLayouts = await r.json();
    const sel = document.getElementById('comic-layout');
    const prev = selectId !== null ? selectId : sel.value;
    [...sel.options].slice(2).forEach(o => o.remove());
    comicLayouts.layouts.forEach(l => { const o = el('option', null, l.name + ' (' + l.count + ')'); o.value = l.id; sel.appendChild(o); });
    if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
    onLayoutChange();
  } catch (e) {}
  return comicLayouts;
}

function layoutById(id) {
  return comicLayouts && id ? comicLayouts.layouts.find(l => l.id === id) || null : null;
}

function drawLayoutThumb(canvas, lay) {
  const g = canvas.getContext('2d');
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.fillStyle = '#fff'; g.fillRect(0, 0, canvas.width, canvas.height);
  if (!lay || !comicLayouts) {
    g.fillStyle = '#999'; g.font = '20px sans-serif'; g.textAlign = 'center';
    g.fillText(canvas.parentNode && document.getElementById('comic-layout').value === 'auto' ? '?' : '–', canvas.width / 2, canvas.height / 2 + 7);
    return;
  }
  const k = canvas.width / comicLayouts.page.width;
  lay.panels.forEach(p => {
    g.beginPath();
    p.poly.forEach(([x, y], i) => i ? g.lineTo(x * k, y * k) : g.moveTo(x * k, y * k));
    g.closePath(); g.fillStyle = '#d6e4f5'; g.fill(); g.lineWidth = 1; g.strokeStyle = '#000'; g.stroke();
  });
}

function onLayoutChange() {
  const lay = layoutById(document.getElementById('comic-layout').value);
  drawLayoutThumb(document.getElementById('layout-preview'), lay);
  const delBtn = document.getElementById('layout-del-btn');
  if (delBtn) delBtn.style.display = lay && lay.custom ? '' : 'none';
  const sbtn = document.getElementById('assist-single');
  if (sbtn) sbtn.textContent = (lay && lay.count > 1) ? ('✨ Gerar prompts (' + lay.count + ' quadros)') : '✨ Gerar prompt';
}

async function onLayoutFile(input) {
  const f = input.files && input.files[0];
  input.value = '';
  if (!f) return;
  const defName = (f.name || 'meu_modelo').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
  const name = prompt_('Nome para este modelo de página:', defName || 'Meu modelo');
  if (!name) return;
  try {
    const rawUrl = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.onerror = () => rej(new Error('Falha ao ler arquivo'));
      fr.readAsDataURL(f);
    });
    // Converte qualquer formato (BMP/JPG/WEBP/PNG do Paint) em PNG normalizado
    const im = await loadImg(rawUrl);
    const maxSide = 720;
    const sc = Math.min(1, maxSide / Math.max(im.naturalWidth || 1, im.naturalHeight || 1));
    const c = document.createElement('canvas');
    c.width = Math.max(16, Math.round(im.naturalWidth * sc));
    c.height = Math.max(16, Math.round(im.naturalHeight * sc));
    const g = c.getContext('2d');
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, c.width, c.height);
    g.drawImage(im, 0, 0, c.width, c.height);
    const r = await fetch('/api/comic/layouts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'import', name: name.trim(), data_url: c.toDataURL('image/png') })
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
    await loadLayouts(true, d.layout.id);
    setStatus(d.message);
  } catch (e) {
    alert('Não deu para importar o modelo: ' + e.message);
  }
}

async function deleteCurrentLayout() {
  const lay = layoutById(document.getElementById('comic-layout').value);
  if (!lay || !lay.custom) return;
  if (!confirm('Excluir o modelo personalizado "' + lay.name + '"?')) return;
  try {
    const r = await fetch('/api/comic/layouts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'delete', id: lay.id })
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
    await loadLayouts(true, 'auto');
    setStatus(d.message);
  } catch (e) {
    alert('Erro ao excluir modelo: ' + e.message);
  }
}

const SFX_STYLES = { hachurado: 'Hachurado', explosao: 'Explosão', tremido: 'Tremido', neutro: 'Simples' };
const SFX_POS = { left: 'esquerda', right: 'direita', top: 'em cima', bottom: 'embaixo', center: 'centro',
                  'top-left': 'sup. esquerdo', 'top-right': 'sup. direito', 'bottom-left': 'inf. esquerdo', 'bottom-right': 'inf. direito' };

// Onomatopeias e "vaza do quadro" editáveis em cada quadro do plano
function panelExtras(pn) {
  const box = el('div');
  pn.sfx = pn.sfx || [];
  const list = el('div');
  const mkSel = (opts, val, on) => {
    const s = el('select');
    Object.entries(opts).forEach(([k, v]) => { const o = el('option', null, v); o.value = k; s.appendChild(o); });
    s.value = val; s.onchange = () => on(s.value); return s;
  };
  const draw = () => {
    list.innerHTML = '';
    pn.sfx.forEach((s, i) => {
      const line = el('div', 'sfx-line');
      const t = el('input'); t.value = s.text; t.placeholder = 'SOC!'; t.oninput = () => { s.text = t.value; };
      line.appendChild(t);
      line.appendChild(mkSel(SFX_STYLES, s.style, v => { s.style = v; }));
      line.appendChild(mkSel(SFX_POS, s.position, v => { s.position = v; }));
      line.appendChild(mkSel({ s: 'P', m: 'M', l: 'G' }, s.size, v => { s.size = v; }));
      const x = el('button', 'mini-btn danger', '×'); x.title = 'Remover efeito';
      x.onclick = () => { pn.sfx.splice(i, 1); draw(); };
      line.appendChild(x);
      list.appendChild(line);
    });
  };
  draw();
  const flags = el('div', 'panel-flags');
  const add = el('button', 'mini-btn', '+ Onomatopeia');
  add.onclick = () => { pn.sfx.push({ text: 'POW!', style: 'explosao', position: 'right', size: 'm', angle: -8 }); draw(); };
  const bl = el('label');
  const cb = el('input'); cb.type = 'checkbox'; cb.checked = !!pn.bleed; cb.onchange = () => { pn.bleed = cb.checked; };
  bl.appendChild(cb); bl.appendChild(document.createTextNode(' vaza do quadro (fica por cima dos vizinhos na montagem)'));
  flags.appendChild(add); flags.appendChild(bl);
  if (pn.layout_note) flags.appendChild(el('span', 'ref-name', '📐 ' + pn.layout_note));
  box.appendChild(list); box.appendChild(flags);
  return box;
}

function polyPath(g, poly, scale = 1, cx = 0, cy = 0) {
  g.beginPath();
  poly.forEach(([x, y], i) => {
    const px = cx + (x - cx) * scale, py = cy + (y - cy) * scale;
    i ? g.lineTo(px, py) : g.moveTo(px, py);
  });
  g.closePath();
}

function bboxOf(poly) {
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y, cx: xs.reduce((a, b) => a + b) / xs.length,
           cy: ys.reduce((a, b) => a + b) / ys.length };
}

function pointInPoly(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
}

// Maior retângulo interno de um quadro (4 cantos inclinados ou N cantos côncavos vindos do Paint)
function innerBox(poly) {
  const b = bboxOf(poly);
  if (poly.length === 4) {
    const [tl, tr, br, bl] = poly;
    const x = Math.max(tl[0], bl[0]), r = Math.min(tr[0], br[0]);
    const y = Math.max(tl[1], tr[1]), bt = Math.min(bl[1], br[1]);
    if (r > x + 20 && bt > y + 20) return { x, y, w: r - x, h: bt - y, cx: (x + r) / 2, cy: (y + bt) / 2 };
  }
  const N = 24, cw = b.w / N, ch = b.h / N;
  if (cw < 1 || ch < 1) return b;
  const h = new Array(N).fill(0);
  let best = { area: 0, x: b.x + b.w * 0.15, y: b.y + b.h * 0.15, w: b.w * 0.7, h: b.h * 0.7 };
  for (let r = 0; r < N; r++) {
    for (let c = 0; c < N; c++) {
      h[c] = pointInPoly(b.x + (c + 0.5) * cw, b.y + (r + 0.5) * ch, poly) ? h[c] + 1 : 0;
    }
    for (let c1 = 0; c1 < N; c1++) {
      let minH = h[c1];
      for (let c2 = c1; c2 < N && minH > 0; c2++) {
        if (h[c2] < minH) minH = h[c2];
        const wPx = (c2 - c1 + 1) * cw, hPx = minH * ch, area = wPx * hPx;
        if (area > best.area) best = { area, x: b.x + c1 * cw, y: b.y + (r - minH + 1) * ch, w: wPx, h: hPx };
      }
    }
  }
  return { x: best.x, y: best.y, w: best.w, h: best.h, cx: best.x + best.w / 2, cy: best.y + best.h / 2 };
}

function drawCover(g, im, b) {
  const s = Math.max(b.w / im.naturalWidth, b.h / im.naturalHeight);
  const sw = b.w / s, sh = b.h / s;
  g.drawImage(im, (im.naturalWidth - sw) / 2, (im.naturalHeight - sh) / 2, sw, sh, b.x, b.y, b.w, b.h);
}

function hatchPattern(g) {
  const c = document.createElement('canvas'); c.width = c.height = 10;
  const h = c.getContext('2d');
  h.fillStyle = '#fff'; h.fillRect(0, 0, 10, 10);
  h.strokeStyle = '#111'; h.lineWidth = 2.2;
  h.beginPath(); h.moveTo(-2, 12); h.lineTo(12, -2); h.moveTo(-2, 2); h.lineTo(2, -2); h.moveTo(8, 12); h.lineTo(12, 8); h.stroke();
  return g.createPattern(c, 'repeat');
}

// Letreiro de onomatopeia sobre o quadro (estilos: hachurado, explosão, tremido, simples)
function drawSfx(g, s, b) {
  const text = (s.text || '').toUpperCase();
  const font = px => `900 ${Math.round(px)}px Impact, "Arial Black", sans-serif`;
  // tamanho pedido, reduzido se a palavra não couber em ~85% da largura do quadro
  let size = { s: 0.12, m: 0.18, l: 0.26 }[s.size] * Math.min(b.w, b.h * 1.4);
  g.font = font(size);
  const fit = (b.w * 0.85) / Math.max(1, g.measureText(text).width * (s.style === 'explosao' ? 1.6 : 1.15));
  if (fit < 1) size *= fit;
  g.font = font(size);
  const w = g.measureText(text).width;
  // meia-largura/altura ocupadas (com contorno ou explosão), para manter o efeito dentro do quadro
  const hw = (s.style === 'explosao' ? w * 0.75 + size * 0.3 : w / 2 + size * 0.2) + 6;
  const hh = (s.style === 'explosao' ? size * 1.05 : size * 0.65) + 6;
  const L = b.x + hw, R = b.x + b.w - hw, T = b.y + hh, B = b.y + b.h - hh;
  const mid = (lo, hi) => lo > hi ? (lo + hi) / 2 : null;
  const px = { left: L, right: R, 'top-left': L, 'bottom-left': L, 'top-right': R, 'bottom-right': R }[s.position] ?? b.cx;
  const py = { top: T, bottom: B, 'top-left': T, 'top-right': T, 'bottom-left': B, 'bottom-right': B }[s.position] ?? b.cy;
  const clamp = (v, lo, hi) => mid(lo, hi) ?? Math.min(Math.max(v, lo), hi);
  const pos = [clamp(px, L, R), clamp(py, T, B)];
  g.save();
  g.translate(pos[0], pos[1]);
  g.rotate((s.angle || (s.style === 'tremido' ? 0 : -8)) * Math.PI / 180);
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.lineJoin = 'round';
  if (s.style === 'explosao') {
    g.beginPath();
    const rx = w * 0.75 + size * 0.3, ry = size * 1.05, spikes = 14;
    for (let i = 0; i < spikes * 2; i++) {
      const a = Math.PI * i / spikes, r = i % 2 ? 0.62 : 1;
      i ? g.lineTo(Math.cos(a) * rx * r, Math.sin(a) * ry * r) : g.moveTo(Math.cos(a) * rx * r, Math.sin(a) * ry * r);
    }
    g.closePath(); g.fillStyle = '#ffe14d'; g.fill(); g.lineWidth = size * 0.06; g.strokeStyle = '#111'; g.stroke();
  }
  const paint = (dx, dy, fill, str = text) => {
    g.lineWidth = size * 0.32; g.strokeStyle = '#fff'; g.strokeText(str, dx, dy);
    g.lineWidth = size * 0.14; g.strokeStyle = '#111'; g.strokeText(str, dx, dy);
    g.fillStyle = fill; g.fillText(str, dx, dy);
  };
  if (s.style === 'tremido') {
    // letra por letra, sacudidas, com um "rastro" apagado ao lado
    // contornos de todas as letras primeiro, depois o miolo (um contorno não cobre a letra vizinha)
    const letters = [];
    let x = -w / 2;
    [...text].forEach((ch, i) => { const cw = g.measureText(ch).width; letters.push([ch, x + cw / 2, i]); x += cw; });
    const each = fn => letters.forEach(([ch, cx, i]) => {
      g.save(); g.translate(cx, (i % 2 ? -1 : 1) * size * 0.07); g.rotate((i % 2 ? 6 : -6) * Math.PI / 180); fn(ch); g.restore();
    });
    each(ch => { g.globalAlpha = 0.25; g.fillStyle = '#ffd23f'; g.fillText(ch, -size * 0.1, 0); g.globalAlpha = 1; });
    each(ch => { g.lineWidth = size * 0.32; g.strokeStyle = '#fff'; g.strokeText(ch, 0, 0); });
    each(ch => { g.lineWidth = size * 0.14; g.strokeStyle = '#111'; g.strokeText(ch, 0, 0); });
    each(ch => { g.fillStyle = '#ffd23f'; g.fillText(ch, 0, 0); });
  } else if (s.style === 'hachurado') {
    paint(0, 0, hatchPattern(g));
  } else if (s.style === 'explosao') {
    paint(0, 0, '#e8301c');
  } else {
    paint(0, 0, '#ffd23f');
  }
  g.restore();
}

// Monta a página no modelo escolhido: quadros recortados no formato, vazamentos por cima, onomatopeias por último
async function montageLayout(btn) {
  const lay = layoutById(currentPlan.layout);
  const W = comicLayouts.page.width, H = comicLayouts.page.height;
  btn.disabled = true;
  try {
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d');
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, W, H);
    g.imageSmoothingEnabled = document.getElementById('img-provider').value === 'pollinations';
    const slots = lay.panels.map((slot, i) => ({ slot, pn: currentPlan.panels[i] }));
    const imgs = await Promise.all(slots.map(s => s.pn && s.pn.result ? loadImg(s.pn.result.data_url) : null));
    const order = slots.map((s, i) => i).sort((a, b) => (slots[a].pn && slots[a].pn.bleed ? 1 : 0) - (slots[b].pn && slots[b].pn.bleed ? 1 : 0));
    for (const i of order) {
      const { slot, pn } = slots[i];
      const b = bboxOf(slot.poly);
      const bleed = pn && pn.bleed;
      const k = bleed ? 1.06 : 1;
      const bb = bleed ? { x: b.cx - b.w * k / 2, y: b.cy - b.h * k / 2, w: b.w * k, h: b.h * k, cx: b.cx, cy: b.cy } : b;
      g.save();
      polyPath(g, slot.poly, k, b.cx, b.cy);
      if (bleed) { g.lineWidth = 22; g.strokeStyle = '#fff'; g.stroke(); }
      g.clip();
      if (imgs[i]) drawCover(g, imgs[i], bb);
      else { g.fillStyle = '#eef1f5'; g.fillRect(bb.x, bb.y, bb.w, bb.h); }
      g.restore();
      polyPath(g, slot.poly, k, b.cx, b.cy);
      g.lineWidth = 7; g.strokeStyle = '#000'; g.stroke();
    }
    if ((currentPlan.sfx_mode || 'overlay') === 'overlay') {
      slots.forEach(({ slot, pn }) => (pn && pn.sfx || []).forEach(s => drawSfx(g, s, innerBox(slot.poly))));
    }
    const dataUrl = c.toDataURL('image/png');
    const r = await fetch('/api/image/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_url: dataUrl, label: 'pagina_' + lay.id, prompt: currentPlan.instruction || '' }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
    prependGalleryCard(d, currentPlan.instruction || 'página');
    const missing = slots.filter(s => !(s.pn && s.pn.result)).length;
    setStatus('Página "' + lay.name + '" montada' + (missing ? ' (' + missing + ' quadro(s) ainda vazios)' : '') + ' e salva em ' + d.saved_path);
  } catch (e) {
    alert('Não deu para montar a página: ' + e.message);
  } finally { btn.disabled = false; }
}

// ================= FICHAS DE PERSONAGEM =================
let charList = [];
const selectedChars = new Set();
const autoChars = new Set();

async function loadCharacters() {
  try {
    const r = await fetch('/api/characters');
    if (!r.ok) return;
    charList = (await r.json()).characters || [];
  } catch (e) { return; }
  [...selectedChars].forEach(id => { if (!charList.some(c => c.id === id)) selectedChars.delete(id); });
  renderCharChips();
  renderCharList();
  detectCharsSoon();
}

function renderCharChips() {
  const box = document.getElementById('char-chips');
  if (!box) return;
  box.innerHTML = '';
  if (!charList.length) { box.appendChild(el('span', 'ref-name', 'nenhuma ficha ainda')); return; }
  charList.forEach(c => {
    const on = selectedChars.has(c.id) || autoChars.has(c.id);
    const chip = el('span', 'char-chip' + (on ? ' on' : ''));
    const im = el('img'); if (c.image_urls && c.image_urls[0]) im.src = c.image_urls[0]; chip.appendChild(im);
    chip.appendChild(document.createTextNode(c.name));
    if (autoChars.has(c.id) && !selectedChars.has(c.id)) chip.appendChild(el('span', 'auto', '(citado)'));
    chip.title = on ? 'Vai para o auxiliar. Clique para tirar' : 'Clique para usar nesta cena';
    chip.onclick = () => {
      if (selectedChars.has(c.id)) selectedChars.delete(c.id);
      else if (autoChars.has(c.id)) { autoChars.delete(c.id); }
      else selectedChars.add(c.id);
      renderCharChips();
    };
    box.appendChild(chip);
  });
}

let detectTimer = null;
function detectCharsSoon() {
  clearTimeout(detectTimer);
  detectTimer = setTimeout(async () => {
    if (!charList.length) return;
    const text = document.getElementById('img-input').value + '\n' + document.getElementById('assist-text').value;
    try {
      const r = await fetch('/api/characters', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                 body: JSON.stringify({ action: 'detect', text }) });
      const d = await r.json();
      autoChars.clear(); (d.ids || []).forEach(id => autoChars.add(id));
      renderCharChips();
    } catch (e) {}
  }, 600);
}
document.getElementById('img-input').addEventListener('input', () => { if (document.getElementById('assist-on').checked) detectCharsSoon(); });
document.getElementById('assist-text').addEventListener('input', detectCharsSoon);

function openCharacters(prefill) {
  document.getElementById('char-overlay').style.display = 'flex';
  loadCharacters().then(() => { if (prefill) openCharForm(null, prefill); });
}
function closeCharacters() {
  const o = document.getElementById('char-overlay');
  if (o) o.style.display = 'none';
}

function renderCharList() {
  const box = document.getElementById('char-list');
  if (!box) return;
  box.innerHTML = '';
  if (!charList.length) { box.appendChild(el('div', 'ref-name', 'Nenhuma ficha. Clique em "+ Nova ficha" ou salve um personagem de um plano do auxiliar.')); return; }
  charList.forEach(c => {
    const card = el('div', 'char-card');
    const title = el('strong', null, c.name + (c.aliases && c.aliases.length ? ' (' + c.aliases.join(', ') + ')' : ''));
    card.appendChild(title);
    const th = el('div', 'thumbs');
    (c.image_urls || []).forEach(u => { const im = el('img'); im.src = u; th.appendChild(im); });
    card.appendChild(th);
    card.appendChild(el('div', 'look', c.look || '(sem descrição: o auxiliar descreve pelas imagens)'));
    const line = el('div', 'key-line');
    const ed = el('button', 'mini-btn', 'Editar'); ed.onclick = () => openCharForm(c);
    const use = el('button', 'mini-btn', selectedChars.has(c.id) ? 'Na cena ✓' : 'Usar na cena');
    use.onclick = () => { selectedChars.has(c.id) ? selectedChars.delete(c.id) : selectedChars.add(c.id); renderCharChips(); renderCharList(); };
    const rm = el('button', 'mini-btn danger', 'Apagar');
    rm.onclick = async () => {
      if (!confirm('Apagar a ficha de ' + c.name + ' (e as imagens dela)?')) return;
      try { await charPost({ action: 'delete', id: c.id }); selectedChars.delete(c.id); loadCharacters(); }
      catch (e) { alert(e.message); }
    };
    line.appendChild(ed); line.appendChild(use); line.appendChild(rm);
    card.appendChild(line);
    box.appendChild(card);
  });
}

async function charPost(body) {
  const r = await fetch('/api/characters', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.message || ('HTTP ' + r.status));
  return d;
}

function openCharForm(c, prefill) {
  const slot = document.getElementById('char-form-slot');
  slot.innerHTML = '';
  c = c || null;
  const f = el('div', 'char-form');
  f.appendChild(el('strong', null, c ? 'Editar ficha' : 'Nova ficha'));
  const name = el('input'); name.placeholder = 'Nome (ex.: Kael)'; name.value = c ? c.name : (prefill && prefill.name) || '';
  const aliases = el('input'); aliases.placeholder = 'Apelidos, separados por vírgula (ex.: o mestre, capitão)'; aliases.value = c ? (c.aliases || []).join(', ') : '';
  const look = el('textarea'); look.placeholder = 'Aparência em inglês, como vai no prompt (ex.: young man, spiky silver hair, scar over left eye, black armor with gold trim...). Pode deixar o auxiliar escrever pelas imagens.';
  look.value = c ? c.look || '' : (prefill && prefill.look) || '';
  const notes = el('textarea'); notes.placeholder = 'Notas (opcional): personalidade, idade, o que nunca muda...'; notes.style.minHeight = '40px';
  notes.value = c ? c.notes || '' : '';
  const keep = c ? [...(c.images || [])] : [];
  const removed = [];
  const added = [];
  const th = el('div', 'thumbs');
  const drawThumbs = () => {
    th.innerHTML = '';
    keep.forEach((n, i) => {
      const w = el('span', 'thumb-wrap'); const im = el('img'); im.src = '/api/characters/img/' + n;
      const x = el('button', null, '×'); x.onclick = () => { removed.push(n); keep.splice(i, 1); drawThumbs(); };
      w.appendChild(im); w.appendChild(x); th.appendChild(w);
    });
    added.forEach((u, i) => {
      const w = el('span', 'thumb-wrap'); const im = el('img'); im.src = u;
      const x = el('button', null, '×'); x.onclick = () => { added.splice(i, 1); drawThumbs(); };
      w.appendChild(im); w.appendChild(x); th.appendChild(w);
    });
  };
  drawThumbs();
  const file = el('input'); file.type = 'file'; file.multiple = true; file.accept = 'image/png,image/jpeg,image/webp'; file.style.display = 'none';
  file.onchange = () => {
    [...file.files].forEach(fl => {
      if (keep.length + added.length >= 4) { alert('Até 4 imagens por ficha.'); return; }
      const rd = new FileReader();
      rd.onload = async () => { added.push(await shrinkDataUrl(rd.result, 1024)); drawThumbs(); };
      rd.readAsDataURL(fl);
    });
    file.value = '';
  };
  const addImg = el('button', 'mini-btn', '🖼 Adicionar imagens');
  addImg.onclick = () => file.click();
  const fromRefs = el('button', 'mini-btn', 'Usar as referências atuais');
  fromRefs.title = 'Copia as imagens de referência que estão na barra "Referências"';
  fromRefs.onclick = async () => {
    for (const r of refs) { if (keep.length + added.length < 4) added.push(await shrinkDataUrl(r.data, 1024)); }
    drawThumbs();
  };
  const msg = el('div', 'key-msg');
  const describe = el('button', 'mini-btn', '✨ Descrever pelas imagens (IA)');
  describe.title = 'Um modelo que enxerga imagens escreve a aparência a partir das fotos da ficha';
  describe.onclick = async () => {
    describe.disabled = true; msg.className = 'key-msg'; msg.textContent = 'Analisando as imagens...';
    try {
      const d = await charPost({ action: 'describe', id: c && c.id, images: added, name: name.value,
                                 model: document.getElementById('assist-model').value });
      look.value = d.look;
      if (d.notes && !notes.value) notes.value = d.notes;
      msg.className = 'key-msg ok'; msg.textContent = 'Descrição escrita por ' + (d.provider || '') + ' / ' + (d.model || '') + '. Revise e salve.';
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
    finally { describe.disabled = false; }
  };
  const save = el('button', 'mini-btn key-save', 'Salvar ficha');
  save.onclick = async () => {
    save.disabled = true;
    try {
      const d = await charPost({ action: 'save', id: c && c.id, name: name.value, aliases: aliases.value, look: look.value,
                                 notes: notes.value, new_images: added, remove_images: removed,
                                 lora: lora.value, lora_weight: loraW.value, trigger: trigger.value });
      msg.className = 'key-msg ok'; msg.textContent = d.message;
      selectedChars.add(d.character.id);
      slot.innerHTML = '';
      loadCharacters();
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; save.disabled = false; }
  };
  const cancel = el('button', 'mini-btn', 'Cancelar'); cancel.onclick = () => { slot.innerHTML = ''; };
  [name, aliases].forEach(x => f.appendChild(x));
  const imgLine = el('div', 'key-line'); imgLine.appendChild(addImg); imgLine.appendChild(fromRefs); imgLine.appendChild(file);
  f.appendChild(th); f.appendChild(imgLine);
  f.appendChild(look); f.appendChild(notes);
  // LoRA do personagem (usada pelo Stable Diffusion local)
  const loraLine = el('div', 'key-line');
  const lora = el('input'); lora.placeholder = 'LoRA do personagem (nome do arquivo, opcional)'; lora.value = c ? c.lora || '' : '';
  lora.setAttribute('list', 'char-lora-options');
  const dl = el('datalist'); dl.id = 'char-lora-options';
  ((sdStatus && sdStatus.loras) || []).filter(l => !l.lcm).forEach(l => { const o = el('option'); o.value = l.name; dl.appendChild(o); });
  const loraW = el('input'); loraW.type = 'number'; loraW.min = -2; loraW.max = 2; loraW.step = 0.05; loraW.style.width = '70px';
  loraW.value = c && c.lora_weight != null ? c.lora_weight : 0.8; loraW.title = 'peso da LoRA';
  const trigger = el('input'); trigger.placeholder = 'palavra de ativação (ex.: kael_hero)'; trigger.value = c ? c.trigger || '' : '';
  loraLine.appendChild(lora); loraLine.appendChild(dl); loraLine.appendChild(loraW); loraLine.appendChild(trigger);
  f.appendChild(el('div', 'ref-name', 'Stable Diffusion local: com uma LoRA treinada do personagem, ele sai igual em todos os quadros. A palavra de ativação entra sozinha no prompt.'));
  f.appendChild(loraLine);
  const btns = el('div', 'key-line'); btns.appendChild(describe); btns.appendChild(save); btns.appendChild(cancel);
  if (c && (c.images || []).length) {
    const ds = el('button', 'mini-btn', '📦 Pacote para treinar LoRA');
    ds.title = 'Baixa as imagens da ficha com legendas, no formato dos treinadores de LoRA (Civitai, kohya, OneTrainer)';
    ds.onclick = async () => {
      const r = await fetch('/api/characters', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                 body: JSON.stringify({ action: 'dataset', id: c.id }) });
      if (!r.ok) { const e = await r.json().catch(() => ({})); alert(e.message || 'Não deu para gerar o pacote.'); return; }
      const a = el('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'dataset_' + c.id + '.zip'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    };
    btns.appendChild(ds);
  }
  f.appendChild(btns); f.appendChild(msg);
  slot.appendChild(f);
  name.focus();
}

// ================= EXPORTAR PARA O GODOT =================
function closeGodot() {
  const o = document.getElementById('godot-overlay');
  if (o) o.style.display = 'none';
}

function openGodot(data) {
  document.getElementById('godot-overlay').style.display = 'flex';
  const body = document.getElementById('godot-body');
  body.innerHTML = '';
  const img = el('img', 'godot-preview'); img.src = data.data_url || data.url;
  const canvas = el('canvas', 'godot-preview');
  const box = el('div', 'modal-box'); box.style.cssText = 'border:none;padding:0;width:100%';
  const grid = el('div', 'godot-grid');
  const field = (label, input) => { const l = el('label', null, label); l.appendChild(input); grid.appendChild(l); return input; };
  const kind = el('select');
  [['spriteframes', 'Animação (SpriteFrames)'], ['tileset', 'Tileset (TileSet)']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; kind.appendChild(o); });
  field('Tipo', kind);
  const num = v => { const i = el('input'); i.type = 'number'; i.min = 1; i.value = v; return i; };
  const pixW = parseInt(document.getElementById('pix-w').value, 10) || 0;
  const fw = field('Largura do quadro (px)', num(pixW || ''));
  const fh = field('Altura do quadro (px)', num(parseInt(document.getElementById('pix-h').value, 10) || ''));
  const nm = el('input'); nm.value = (data.file_name || 'sprite').replace(/\.png$/i, '').replace(/_\d{9,}$/, '');
  field('Nome', nm);
  const resp = el('input'); resp.value = 'res://assets/' + nm.value.toLowerCase().replace(/[^a-z0-9_]+/g, '_') + '/';
  field('Pasta no projeto Godot', resp);
  const margin = field('Margem (tileset)', num(0)); margin.min = 0;
  const sep = field('Espaço entre tiles', num(0)); sep.min = 0;
  const info = el('div', 'ref-name');
  const animsBox = el('div');
  const anims = [];
  const drawAnims = () => {
    animsBox.innerHTML = '';
    if (kind.value !== 'spriteframes') return;
    const hd = el('div', 'anim-line anim-head');
    ['nome', 'linha', '1º quadro', 'qtde', 'fps', 'repete', ''].forEach(t => hd.appendChild(el('span', null, t)));
    animsBox.appendChild(hd);
    anims.forEach((a, i) => {
      const line = el('div', 'anim-line');
      const inp = (k, type) => { const x = el('input'); x.type = type || 'number'; x.value = a[k]; x.oninput = () => { a[k] = type === 'text' ? x.value : parseFloat(x.value); }; return x; };
      line.appendChild(inp('name', 'text')); line.appendChild(inp('row')); line.appendChild(inp('start'));
      line.appendChild(inp('count')); line.appendChild(inp('fps'));
      const lp = el('input'); lp.type = 'checkbox'; lp.checked = a.loop; lp.onchange = () => { a.loop = lp.checked; }; line.appendChild(lp);
      const x = el('button', 'mini-btn danger', '×'); x.onclick = () => { anims.splice(i, 1); drawAnims(); }; line.appendChild(x);
      animsBox.appendChild(line);
    });
    const add = el('button', 'mini-btn', '+ Animação');
    add.onclick = () => { anims.push({ name: ['idle', 'andar', 'atacar', 'pular', 'morrer'][anims.length] || 'anim_' + (anims.length + 1), row: anims.length + 1, start: 1, count: 0, fps: 8, loop: true }); drawAnims(); };
    animsBox.appendChild(add);
    animsBox.appendChild(el('div', 'ref-name', 'Linha e 1º quadro contam a partir de 1; qtde 0 = a linha inteira. Sem animações, cada linha vira uma animação. Quadros vazios (transparentes) ficam de fora.'));
  };
  const redraw = () => {
    const W = img.naturalWidth, H = img.naturalHeight;
    if (!W) return;
    if (!fw.value) { fw.value = H <= W ? H : W; }
    if (!fh.value) { fh.value = H <= W ? H : W; }
    canvas.width = W; canvas.height = H;
    const g = canvas.getContext('2d');
    g.imageSmoothingEnabled = false;
    g.drawImage(img, 0, 0);
    const w = +fw.value, h = +fh.value, m = kind.value === 'tileset' ? +margin.value : 0, s = kind.value === 'tileset' ? +sep.value : 0;
    if (w > 0 && h > 0) {
      g.strokeStyle = 'rgba(255,80,80,0.9)'; g.lineWidth = Math.max(1, W / 400);
      const cols = Math.floor((W - 2 * m + s) / (w + s)), rows = Math.floor((H - 2 * m + s) / (h + s));
      for (let r = 0; r < rows; r++) for (let c2 = 0; c2 < cols; c2++) g.strokeRect(m + c2 * (w + s) + 0.5, m + r * (h + s) + 0.5, w - 1, h - 1);
      info.textContent = `Imagem ${W}x${H} → ${cols} coluna(s) x ${rows} linha(s) de ${w}x${h}.`;
    }
    margin.parentNode.style.display = sep.parentNode.style.display = kind.value === 'tileset' ? '' : 'none';
  };
  [fw, fh, margin, sep].forEach(x => x.oninput = redraw);
  kind.onchange = () => { redraw(); drawAnims(); };
  img.onload = redraw;
  const msg = el('div', 'key-msg');
  const go = el('button', 'mini-btn key-save', 'Exportar');
  go.onclick = async () => {
    go.disabled = true; msg.className = 'key-msg'; msg.textContent = 'Exportando...';
    try {
      const payload = { image: data.file_name, kind: kind.value, frame_w: +fw.value, frame_h: +fh.value, name: nm.value,
                        res_path: resp.value, margin: +margin.value, separation: +sep.value,
                        animations: anims.map(a => ({ name: a.name, row: Math.max(0, (a.row || 1) - 1), start: Math.max(0, (a.start || 1) - 1),
                                                       count: a.count || 0, fps: a.fps || 8, loop: a.loop })) };
      const r = await fetch('/api/godot/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
      msg.className = 'key-msg ok';
      msg.textContent = '✔ ' + d.how + '  Arquivos em: ' + d.folder;
      const dl = el('button', 'mini-btn', '⬇ Baixar .zip');
      dl.onclick = async () => {
        const z = await fetch('/api/godot/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: d.zip }) });
        if (!z.ok) { alert('Não deu para baixar.'); return; }
        const a = el('a'); a.href = URL.createObjectURL(await z.blob()); a.download = d.zip; a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      };
      msg.appendChild(document.createElement('br')); msg.appendChild(dl);
    } catch (e) { msg.className = 'key-msg err'; msg.textContent = e.message; }
    finally { go.disabled = false; }
  };
  body.appendChild(canvas);
  body.appendChild(info);
  body.appendChild(grid);
  body.appendChild(animsBox);
  const btns = el('div', 'key-line'); btns.appendChild(go); body.appendChild(btns);
  body.appendChild(msg);
  drawAnims();
  if (img.complete) redraw();
}

// ================= APOIO (cafézinho) — dados em um lugar só =================
const DONATE = {
  pix: 'fausto@biazzitech.com.br',
  beneficiary: 'Favorecido: BiazziTech / Fausto Sousa',
  picpayUser: '@faustobiazzi',
  picpayUrl: 'https://picpay.me/faustobiazzi'
};

function openCoffee() {
  document.getElementById('coffee-pix').textContent = DONATE.pix;
  document.getElementById('coffee-benef').textContent = DONATE.beneficiary;
  document.getElementById('coffee-picpay').textContent = DONATE.picpayUser;
  document.getElementById('coffee-copy-pp').textContent = '⧉ Copiar ' + DONATE.picpayUser;
  document.getElementById('coffee-pp-link').href = DONATE.picpayUrl;
  document.getElementById('coffee-msg').textContent = '';
  document.getElementById('coffee-overlay').style.display = 'flex';
}

function closeCoffee() { document.getElementById('coffee-overlay').style.display = 'none'; }

async function copyCoffee(kind) {
  const val = kind === 'pix' ? DONATE.pix : DONATE.picpayUser;
  const msg = document.getElementById('coffee-msg');
  try { await navigator.clipboard.writeText(val); msg.className = 'key-msg ok'; msg.textContent = (kind === 'pix' ? 'Chave PIX copiada: ' : 'Usuário PicPay copiado: ') + val + ' — obrigado! ☕'; }
  catch (e) { msg.className = 'key-msg'; msg.textContent = 'Copie manualmente: ' + val; }
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeCoffee(); closeCharacters(); closeGodot(); } });

// ================= ACESSO: login, permissões, rede, porta, usuários =================
let me = { perms: ['chat', 'imagens', 'admin'], auth_enabled: false };
function canAdmin() { return (me.perms || []).includes('admin'); }

// Qualquer resposta 401 pedindo login abre a tela de login
const _origFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const r = await _origFetch(...args);
  if (r.status === 401) {
    r.clone().json().then(d => { if (d && d.login) showLogin(); }).catch(() => {});
  }
  return r;
};

function showLogin(msg) {
  document.getElementById('login-overlay').style.display = 'flex';
  document.getElementById('login-msg').textContent = msg || '';
  setTimeout(() => document.getElementById('login-user').focus(), 50);
}

async function doLogin(ev) {
  ev.preventDefault();
  const user = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const r = await _origFetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user, password })
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) { document.getElementById('login-msg').textContent = d.message || 'Falha no login'; return; }
  location.reload();
}

async function doLogout() {
  await _origFetch('/api/auth/logout', { method: 'POST' });
  location.reload();
}

async function loadMe() {
  setStatus('Pronto — Endpoint OpenAI em ' + location.origin + '/v1');
  try { me = await (await _origFetch('/api/auth/me')).json(); } catch (e) { return; }
  const chip = document.getElementById('user-chip');
  if (me.user) {
    chip.style.display = '';
    chip.textContent = '👤 ' + me.user + ' ';
    const out = el('button', 'mini-btn', 'Sair');
    out.onclick = doLogout;
    chip.appendChild(out);
  } else if (me.auth_enabled && !me.is_local) {
    chip.style.display = 'none';
  }
  // Mostra só as abas que o usuário pode usar
  const can = p => (me.perms || []).includes(p);
  const vis = { chat: can('chat'), image: can('imagens'), providers: can('chat') || can('admin'), access: can('admin') };
  const addBtn = document.getElementById('btn-add-custom');
  if (addBtn) addBtn.style.display = can('admin') ? '' : 'none';
  document.querySelectorAll('.tab-btn[data-tab]').forEach(b => { b.style.display = vis[b.dataset.tab] ? '' : 'none'; });
  if (!(me.perms || []).length) { showLogin(me.auth_enabled ? '' : 'Sem permissão.'); return; }
  const active = document.querySelector('.tab-btn.active');
  if (active && active.style.display === 'none') {
    const first = [...document.querySelectorAll('.tab-btn[data-tab]')].find(b => b.style.display !== 'none');
    if (first) first.click();
  }
  if (vis.chat) loadConversations();
  if (vis.image) loadGallery(false);
  if (vis.providers) { loadProviders(true); setInterval(() => loadProviders(false), 15000); }
  // ?tab=image|providers|access abre direto numa aba
  const want = new URLSearchParams(location.search).get('tab');
  const wb = want && document.querySelector(`.tab-btn[data-tab="${want}"]`);
  if (wb && wb.style.display !== 'none') wb.click();
}

function permBoxes(selected, disabled) {
  const wrap = el('span', 'perm-boxes');
  [['chat', 'Chat/código'], ['imagens', 'Imagens'], ['admin', 'Admin']].forEach(([id, label]) => {
    const l = el('label');
    const c = el('input'); c.type = 'checkbox'; c.value = id; c.checked = selected.includes(id); c.disabled = !!disabled;
    l.appendChild(c); l.appendChild(document.createTextNode(' ' + label));
    wrap.appendChild(l);
  });
  wrap.values = () => [...wrap.querySelectorAll('input:checked')].map(c => c.value);
  return wrap;
}

async function accessPost(path, body) {
  const r = await fetch('/api/access/' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.message || ('HTTP ' + r.status));
  return d;
}

function section(title) {
  const s = el('div', 'acc-section');
  s.appendChild(el('h3', null, title));
  return s;
}

async function loadAccess() {
  const box = document.getElementById('access-body');
  box.innerHTML = '';
  let d;
  try {
    const r = await fetch('/api/access');
    d = await r.json();
    if (!r.ok) { box.appendChild(el('div', 'prov-err', d.message || 'Sem permissão.')); return; }
  } catch (e) { box.appendChild(el('div', 'prov-err', 'Erro: ' + e.message)); return; }
  const noUsers = !d.users.length;
  const msgLine = el('div', 'key-msg');

  // ---- Rede
  const net = section('Acesso pela rede');
  const lanOn = d.config.lan;
  const https = d.https || {};
  const lanActive = !!d.lan_active;
  net.appendChild(row('Situação', lanActive ? ('LIBERADO para outras máquinas da rede' + (https.ready ? ' (HTTPS)' : ' (sem HTTPS)'))
    : (lanOn && noUsers ? 'Somente este PC (a rede espera um usuário ser criado)' : 'Somente este PC')));
  if (lanActive) {
    const addrs = (d.lan_ips || []).map(ip => https.ready ? `https://${ip}:${https.port}` : `http://${ip}:${d.running_port}`).join('   ');
    net.appendChild(row('Endereço para outras máquinas', addrs || '(IP não detectado)'));
    if (!https.ready) {
      net.appendChild(el('div', 'policy-warn', '⚠ Sem HTTPS: a senha e as conversas trafegam sem criptografia na rede. Use só em rede de confiança ou ative o HTTPS (abaixo).'));
    }
  }
  if (noUsers) {
    net.appendChild(el('div', 'policy-warn', '🔒 Para liberar na rede é preciso ter pelo menos um usuário com senha (crie em "Usuários e permissões", abaixo). Sem usuários o painel funciona livre, mas só neste PC.'));
  }
  const tgl = el('button', 'mini-btn key-save', lanOn ? 'Desligar acesso pela rede' : 'Liberar acesso pela rede');
  if (!lanOn && noUsers) tgl.disabled = true;
  tgl.onclick = async () => {
    let body = { lan: !lanOn };
    if (!lanOn) {
      if (!confirm('LIBERAR O ACESSO PELA REDE\n\n' + (d.risk_text || '') +
        '\n\nClique em OK para confirmar que você leu e entende esses riscos.')) return;
      body.accept_risk = true;
    }
    tgl.disabled = true;
    try {
      const r = await accessPost('network', body);
      msgLine.className = 'key-msg ok'; msgLine.textContent = r.message;
      setTimeout(loadAccess, 1500);
    } catch (e) { msgLine.className = 'key-msg err'; msgLine.textContent = e.message; tgl.disabled = false; }
  };
  net.appendChild(tgl);
  net.appendChild(msgLine);
  box.appendChild(net);

  // ---- HTTPS
  const hs = section('HTTPS na rede (criptografia)');
  hs.appendChild(row('Situação', https.ready ? `Ativo: a rede usa https na porta ${https.port}; a porta ${d.running_port} fica só neste PC.`
    : 'Não configurado'));
  if (!https.ready) {
    hs.appendChild(el('div', 'prov-row', 'Para ativar: instale o mkcert (winget install FiloSottile.mkcert), rode "mkcert -install" e gere o certificado com o IP deste PC:'));
    const ip = (d.lan_ips || [])[0] || 'IP-DESTE-PC';
    const cmd = `cd "${https.folder}"\nmkcert -cert-file cert.pem -key-file key.pem ${ip} localhost 127.0.0.1`;
    const pre = el('pre', 'acc-code', cmd);
    hs.appendChild(pre);
    hs.appendChild(el('div', 'prov-row', `Pronto: com a rede ligada, o painel passa a responder em https://${ip}:${https.port} em alguns segundos. Nas outras máquinas o navegador pode avisar que não conhece o certificado (rode "mkcert -install" nelas com o mesmo certificado raiz, ou aceite o aviso). Para acessar de fora de casa, use uma VPN como o Tailscale — nunca abra a porta no roteador.`));
  }
  box.appendChild(hs);

  // ---- Porta e Servidor
  const portS = section('Porta e Servidor');
  portS.appendChild(row('Em uso agora', String(d.running_port)));
  const pl = el('div', 'key-line');
  const pin = el('input'); pin.type = 'number'; pin.min = 1024; pin.max = 65535; pin.value = d.config.port; pin.style.width = '110px';
  const pbtn = el('button', 'mini-btn', 'Salvar porta');
  const rbtn = el('button', 'mini-btn danger', '↻ Reiniciar servidor');
  rbtn.title = 'Recarrega configurações, chaves e aplica mudança de porta (só administradores)';
  const pmsg = el('div', 'key-msg');
  pbtn.onclick = async () => {
    try { const r = await accessPost('port', { port: parseInt(pin.value, 10) }); pmsg.className = 'key-msg ok'; pmsg.textContent = r.message; }
    catch (e) { pmsg.className = 'key-msg err'; pmsg.textContent = e.message; }
  };
  rbtn.onclick = async () => {
    if (!confirm('Reiniciar o servidor do BiazziTech AI Studio agora?\n\nPedidos em andamento serão interrompidos e configurações/porta serão recarregadas.')) return;
    rbtn.disabled = true;
    pmsg.className = 'key-msg'; pmsg.textContent = 'Reiniciando servidor... aguarde alguns segundos.';
    try {
      const r = await accessPost('restart', {});
      const targetPort = r.port || d.running_port;
      const samePort = String(targetPort) === String(location.port || d.running_port);
      const targetOrigin = samePort ? location.origin : (location.protocol + '//' + location.hostname + ':' + targetPort);
      await new Promise(res => setTimeout(res, 900));
      let up = false;
      for (let i = 0; i < 25; i++) {
        try {
          const h = await fetch(targetOrigin + '/healthz', { cache: 'no-store' });
          if (h.ok) { up = true; break; }
        } catch (e) {}
        await new Promise(res => setTimeout(res, 600));
      }
      if (!samePort && up) { location.href = targetOrigin + '/?tab=access'; return; }
      if (up) {
        pmsg.className = 'key-msg ok'; pmsg.textContent = 'Servidor reiniciado e pronto!';
        setStatus('Servidor reiniciado com sucesso.');
        loadMe(); loadProviders(true); setTimeout(loadAccess, 800);
      } else {
        pmsg.className = 'key-msg err'; pmsg.textContent = 'O servidor demorou para voltar. Atualize a página (ou acesse a porta ' + targetPort + ').';
      }
    } catch (e) {
      pmsg.className = 'key-msg err'; pmsg.textContent = e.message;
    } finally { rbtn.disabled = false; }
  };
  pl.appendChild(pin); pl.appendChild(pbtn); pl.appendChild(rbtn);
  portS.appendChild(pl); portS.appendChild(pmsg);
  box.appendChild(portS);

  // ---- Usuários
  const us = section('Usuários e permissões');
  us.appendChild(el('div', 'prov-row', noUsers
    ? 'Nenhum usuário: o acesso é livre, só neste PC. O primeiro usuário criado vira administrador.'
    : 'Com usuários cadastrados, quem acessa pela rede precisa entrar com usuário e senha. O token serve para Continue/Cline (no lugar da chave de API).'));
  d.users.forEach(u => {
    const line = el('div', 'user-line');
    line.appendChild(el('strong', null, u.name));
    const pb = permBoxes(u.perms);
    line.appendChild(pb);
    const save = el('button', 'mini-btn', 'Salvar');
    const pw = el('button', 'mini-btn', 'Nova senha');
    const tk = el('button', 'mini-btn', 'Novo token');
    const del = el('button', 'mini-btn danger', 'Excluir');
    const um = el('div', 'key-msg');
    save.onclick = async () => { try { const r = await accessPost('users', { action: 'update', name: u.name, perms: pb.values() }); um.className = 'key-msg ok'; um.textContent = r.message; } catch (e) { um.className = 'key-msg err'; um.textContent = e.message; } };
    pw.onclick = async () => {
      const np = prompt_('Nova senha para ' + u.name + ' (mín. 6 caracteres):', '');
      if (!np) return;
      try { const r = await accessPost('users', { action: 'update', name: u.name, password: np }); um.className = 'key-msg ok'; um.textContent = r.message; } catch (e) { um.className = 'key-msg err'; um.textContent = e.message; }
    };
    tk.onclick = async () => {
      if (!confirm('Gerar um novo token para ' + u.name + '? O antigo para de funcionar.')) return;
      try { const r = await accessPost('users', { action: 'token', name: u.name }); um.className = 'key-msg ok'; um.textContent = 'Novo token (copie agora, ele não aparece de novo): ' + r.token; } catch (e) { um.className = 'key-msg err'; um.textContent = e.message; }
    };
    del.onclick = async () => {
      if (!confirm('Excluir o usuário ' + u.name + '?')) return;
      try { const r = await accessPost('users', { action: 'delete', name: u.name }); alert(r.message); loadAccess(); loadMe(); } catch (e) { um.className = 'key-msg err'; um.textContent = e.message; }
    };
    [save, pw, tk, del].forEach(b => line.appendChild(b));
    us.appendChild(line);
    us.appendChild(um);
  });
  // novo usuário
  const nf = el('div', 'user-line new-user');
  const nn = el('input'); nn.placeholder = 'novo usuário'; nn.style.width = '140px';
  const np = el('input'); np.type = 'password'; np.placeholder = 'senha (mín. 6)'; np.style.width = '140px';
  const npb = permBoxes(noUsers ? ['chat', 'imagens', 'admin'] : ['chat', 'imagens'], noUsers);
  const nb = el('button', 'mini-btn key-save', noUsers ? 'Criar administrador' : 'Criar usuário');
  const nm = el('div', 'key-msg');
  nb.onclick = async () => {
    try {
      const r = await accessPost('users', { action: 'add', name: nn.value.trim(), password: np.value, perms: npb.values() });
      nm.className = 'key-msg ok';
      nm.textContent = r.message + ' Token de API (copie agora, não aparece de novo): ' + r.token;
      nn.value = np.value = '';
      setTimeout(() => { loadAccess(); loadMe(); }, 4000);
    } catch (e) { nm.className = 'key-msg err'; nm.textContent = e.message; }
  };
  [nn, np, npb, nb].forEach(x => nf.appendChild(x));
  us.appendChild(nf);
  us.appendChild(nm);
  if (!noUsers) {
    const al = el('label', 'prov-row');
    const ac = el('input'); ac.type = 'checkbox'; ac.checked = !!d.config.auth_local;
    ac.onchange = async () => { try { await accessPost('auth_local', { value: ac.checked }); } catch (e) { alert(e.message); } };
    al.appendChild(ac);
    al.appendChild(document.createTextNode(' Exigir login também neste PC (por padrão, quem usa o próprio PC do servidor entra direto)'));
    us.appendChild(al);
  }
  box.appendChild(us);
}

loadMe();
