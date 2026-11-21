/* TRACKROOM v6.9.2 — public app shell. Never cache account, room or API data. */
const SHELL_CACHE = 'trackroom-shell-v6.9.2';
const SHELL_FILES = [
  '/offline.html', '/style.css?v=6.9.2', '/app.js?v=6.9.2', '/room-bubbles.js?v=6.9.2', '/room-bubbles.css?v=6.9.2', '/home.css?v=6.9.2', '/home.js?v=6.9.2',
  '/catalog-filters.js?v=6.9.2', '/catalog-filters.css?v=6.9.2',
  '/login-prism.webp', '/fonts/bricolage.woff2', '/fonts/plex-sans.woff2', '/fonts/plex-mono.woff2',
  '/favicon.svg', '/manifest.webmanifest',
  '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/icon-maskable-512.png', '/icons/apple-touch-icon.png'
];
const SHELL_PATHS = new Set(SHELL_FILES.map(path => path.split('?')[0]));

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await cache.addAll(SHELL_FILES);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('trackroom-shell-') && name !== SHELL_CACHE)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Cookies, member data, search, and song data always come from the live server.
  if (url.pathname.startsWith('/api/') || url.pathname === '/health') return;

  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try { return await fetch(request); }
      catch {
        return await caches.match('/offline.html') ||
          new Response('인터넷 연결을 확인한 뒤 다시 접속해 주세요.',
            {status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});
      }
    })());
    return;
  }

  if (!SHELL_PATHS.has(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(SHELL_CACHE);
    try {
      const response = await fetch(request);
      if (response.ok) await cache.put(request, response.clone());
      return response;
    } catch {
      return await cache.match(request) || Response.error();
    }
  })());
});
