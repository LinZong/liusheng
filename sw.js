const CACHE_PREFIX = 'liusheng-shell-';
const CACHE_NAME = CACHE_PREFIX + 'v9';
const SHELL = [
  '/', '/manifest.webmanifest', '/icons/icon.svg',
  '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/icon-maskable-512.png', '/icons/apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(SHELL);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // Only the application shell is cached. API calls always need a live server;
  // sending text is never cached, queued or replayed when connectivity returns.
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  const path = url.pathname === '/index.html' ? '/' : url.pathname;
  if (!SHELL.includes(path)) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    try {
      const response = await fetch(request);
      if (response.ok) {
        await cache.put(path, response.clone()).catch(() => {});
        return response;
      }
      return (await cache.match(path)) || response;
    } catch (error) {
      const cached = await cache.match(path);
      if (cached) return cached;
      throw error;
    }
  })());
});
