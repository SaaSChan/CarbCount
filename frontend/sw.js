const CACHE_NAME = 'carbcount-v2';
const SHELL_URLS = ['/app/', '/app/style.css', '/app/app.js', '/app/manifest.json'];

self.addEventListener('install', event => {
    self.skipWaiting();
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_URLS)));
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    if (event.request.url.includes('/api/')) return;
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
