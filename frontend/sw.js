const CACHE_NAME = "ledger-lens-shell-v1";
const SHELL_ASSETS = [
  "./index.html",
  "./app.js",
  "./manifest.json",
  "./icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Network-first for API calls (they need live data), cache-first for the
// static app shell so the dashboard still opens offline.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isApiCall = url.pathname.startsWith("/api/");

  if (isApiCall) {
    event.respondWith(
      fetch(event.request).catch(
        () =>
          new Response(
            JSON.stringify({ error: "offline", message: "You're offline. Reconnect to sync." }),
            { headers: { "Content-Type": "application/json" }, status: 503 }
          )
      )
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
