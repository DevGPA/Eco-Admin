// sw.js — Service Worker de GPA Operaciones (PWA)
// Cachea el "app shell" (estáticos) para que la app abra sin red.
// Las llamadas a la API y a Cognito SIEMPRE van a la red (datos frescos).
const CACHE = "gpa-ops-v1";
const SHELL = [
  "./", "./index.html", "./gpa-api.js", "./config.js",
  "./manifest.webmanifest", "./icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // No cachear API, Cognito ni S3 (datos/credenciales dinámicas)
  if (url.hostname.includes("amazonaws.com") || e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match("./index.html"))
    )
  );
});
