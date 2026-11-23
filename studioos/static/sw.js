/* StudioOS service worker: keeps the app shell (the page, scripts and styles) so StudioOS opens with no signal. It never keeps API
   answers (they are private to the signed-in person) and it never sends anything on its own; unsent drafts wait in the page outbox
   (outbox.js). The server supplies a versioned cache name and its complete asset list. */
const CACHE = 'studioos-shell-version';
const ASSETS = ['/'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('studioos-shell-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/mcp' || url.pathname === '/sw.js') return;     // never keep private answers
  if (req.mode === 'navigate' && url.pathname === '/') {
    event.respondWith(fetch(req).catch(() => caches.open(CACHE).then(c => c.match('/'))));
    return;
  }
  if (ASSETS.includes(url.pathname + url.search)) {
    event.respondWith(caches.open(CACHE).then(c => c.match(req)).then(hit => hit || fetch(req)));
  }
});
