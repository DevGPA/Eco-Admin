// sw.js — Service Worker mínimo (app shell) para GPA ViaticOS
// Cachea los archivos estáticos para arranque offline. NUNCA cachea config.js
// ni llamadas a la API/Cognito (deben ir siempre a la red).
const CACHE = "viaticos-v1";
const SHELL = [
  "./index.html",
  "./gpa-api.js",
  "./viaticos-app.jsx",
  "./manifest.webmanifest",
  "./icon.svg",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Nunca interceptar API, Cognito ni config.js
  if (e.request.method !== "GET" ||
      url.pathname.endsWith("config.js") ||
      url.hostname.includes("amazonaws.com") ||
      url.hostname.includes("execute-api")) {
    return;
  }
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => hit))
  );
});
