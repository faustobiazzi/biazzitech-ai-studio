// BiazziTech AI Studio — service worker do app instalável (PWA).
// Guarda só a "casca" do painel (HTML, CSS, JS, ícones) para abrir rápido e mostrar um aviso se o servidor
// estiver desligado. NUNCA guarda respostas da API, conversas, imagens ou dados de login.
const CACHE = 'bt-studio-v1';
const SHELL = ['/', '/ui/studio.css', '/ui/studio.js', '/ui/icon-192.png', '/ui/manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const shell = url.pathname === '/' || url.pathname.startsWith('/ui/');
  if (!shell) return;  // API, imagens, conversas: sempre direto do servidor
  // rede primeiro (painel sempre atualizado); sem servidor, a cópia guardada
  e.respondWith(fetch(e.request).then(resp => {
    if (resp.ok) { const copy = resp.clone(); caches.open(CACHE).then(c => c.put(url.pathname === '/' ? '/' : e.request, copy)); }
    return resp;
  }).catch(() => caches.match(url.pathname === '/' ? '/' : e.request).then(r => r || new Response(
    '<meta charset="utf-8"><body style="background:#0f1115;color:#e6edf3;font-family:sans-serif;padding:24px">' +
    '<h2>⚙ BiazziTech AI Studio</h2><p>O servidor do painel não está respondendo. Ligue o Studio no PC ' +
    '(ou no Termux) e abra de novo.</p></body>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } }))));
});
