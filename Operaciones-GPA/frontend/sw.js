// sw.js — Service Worker de GPA Operaciones (PWA)
// Estrategia "network-first" para la app: SIEMPRE intenta traer la versión más
// reciente desde la red y solo cae al caché cuando no hay conexión. Así, cada
// vez que se publica una nueva versión, los usuarios la reciben (sin quedarse
// con una copia vieja). Las llamadas a API/Cognito/S3 nunca se cachean.
const CACHE = "gpa-ops-v3";
const SHELL = [
  "./", "./index.html", "./gpa-api.js", "./config.js",
  "./manifest.webmanifest", "./icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Datos/credenciales dinámicas: directo a la red, sin cachear.
  if (url.hostname.includes("amazonaws.com") || e.request.method !== "GET") return;

  // Network-first: trae lo más nuevo; si falla (offline), usa el caché.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() =>
        caches.match(e.request).then((hit) => hit || caches.match("./index.html"))
      )
  );
});
