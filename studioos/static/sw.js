/* StudioOS service worker: keeps the app shell (the page, scripts and styles) so StudioOS opens with no signal. It never keeps API
   answers (they are private to the signed-in person) and it never sends anything on its own; unsent drafts wait in the page outbox
   (outbox.js). Same-origin only. Change CACHE when the shell changes so old copies are dropped. */
const CACHE = 'studioos-shell-v1';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(['/'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('studioos-shell-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/mcp' || url.pathname === '/sw.js') return;     // never keep private answers
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put('/', copy)); return r; }).catch(() => caches.match('/')));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(req).then(hit => {
      const fresh = fetch(req).then(r => { if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return r; }).catch(() => hit);
      return hit || fresh;
    }));
  }
});
