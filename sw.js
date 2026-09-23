const CACHE_NAME = "booksmaxxing-shell-v4";
const SHELL = [
    "./",
    "./index.html",
    "./manifest.webmanifest",
    "./assets/logo.png",
    "./assets/favicon.png",
    "./data/catalog.json",
    "./data/build.json"
];

async function cacheResponse(request, response) {
    if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, response.clone());
    }
    return response;
}

async function networkFirst(request) {
    try {
        return await cacheResponse(request, await fetch(request));
    } catch {
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }
        const fallback = await caches.match("./index.html");
        if (request.mode === "navigate" && fallback) {
            return fallback;
        }
        throw new Error("Offline resource unavailable");
    }
}

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(SHELL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", event => {
    const request = event.request;
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    if (url.pathname.includes("/books/")) {
        return;
    }

    if (
        request.mode === "navigate" ||
        url.pathname.endsWith("/index.html") ||
        url.pathname.endsWith("/data/catalog.json") ||
        url.pathname.endsWith("/data/build.json")
    ) {
        event.respondWith(networkFirst(request));
        return;
    }

    event.respondWith(
        caches.match(request).then(cached => cached || fetch(request).then(response => cacheResponse(request, response)))
    );
});
