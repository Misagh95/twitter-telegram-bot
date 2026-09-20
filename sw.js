const CACHE = 'cryptox-v3';
const PRECACHE = ['/', '/manifest.json'];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (e) => {
    if (e.request.method !== 'GET') return;
    const url = e.request.url;
    // Live data must always hit the network — never serve stale tweets.
    if (url.includes('/api/') || url.includes('cdn.tailwindcss')) return;

    e.respondWith(
        fetch(e.request)
            .then(resp => {
                const clone = resp.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return resp;
            })
            .catch(() => caches.match(e.request))
    );
});
