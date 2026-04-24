const CACHE_NAME = 'lavinia-portfolio-v1';
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/style.css',
    '/script.js',
    '/image-manifest.json',
    '/favicon.svg',
    '/fonts/inter-latin.woff2',
    '/fonts/playfair-display-latin.woff2',
];

// Install: cache static shell
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch: stale-while-revalidate for images, cache-first for static assets
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Images and videos: stale-while-revalidate
    if (url.pathname.startsWith('/images/')) {
        event.respondWith(
            caches.open(CACHE_NAME).then(cache =>
                cache.match(event.request).then(cached => {
                    const fetchPromise = fetch(event.request).then(networkResponse => {
                        if (networkResponse.ok) {
                            cache.put(event.request, networkResponse.clone());
                        }
                        return networkResponse;
                    }).catch(() => cached);
                    return cached || fetchPromise;
                })
            )
        );
        return;
    }

    // Static assets: cache-first
    event.respondWith(
        caches.open(CACHE_NAME).then(cache =>
            cache.match(event.request).then(cached => {
                const fetchPromise = fetch(event.request).then(networkResponse => {
                    if (networkResponse.ok) {
                        cache.put(event.request, networkResponse.clone());
                    }
                    return networkResponse;
                });
                return cached || fetchPromise;
            })
        )
    );
});
