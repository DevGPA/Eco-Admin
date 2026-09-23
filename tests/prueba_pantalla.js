// tests/prueba_pantalla.js — ejecuta el app.js REAL, no una copia de su lógica.
// Uso:  node tests/prueba_pantalla.js
// ─────────────────────────────────────────────────────────────────
// Carga frontend/gpa-api.js y frontend/app.js dentro de un navegador de mentiras
// (lo mínimo que tocan al arrancar) y llama a las funciones de pantalla tal cual.
// El catálogo sale de catalogos.py, para que no se desincronice.
// Lo que esto NO prueba: cómo se ve, ni el CSS, ni los eventos del ratón.
// ─────────────────────────────────────────────────────────────────
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const { execFileSync } = require("child_process");

const RAIZ = path.resolve(__dirname, "..");

// ── navegador de mentiras ──
const nodo = () => ({ innerHTML: "", value: "", hidden: false, checked: false, files: [],
                      dataset: {}, remove() {}, focus() {}, setAttribute() {}, appendChild() {} });
const ctx = {
  console,
  document: { addEventListener() {}, querySelector: () => nodo(), querySelectorAll: () => [],
              createElement: nodo, body: { appendChild() {} } },
  window: { GPA_CONFIG: { apiUrl: "http://api", region: "us-east-1", poolId: "p",
                          clientId: "c", portalUrl: "http://portal" },
            prompt: () => "", addEventListener() {} },
  location: { origin: "http://portal", pathname: "/", search: "", hash: "" },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => "" }),
  setTimeout, clearTimeout, URLSearchParams, URL, TextEncoder, crypto,
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  navigator: { clipboard: { writeText: async () => {} } },
};
ctx.window.location = ctx.location;
ctx.globalThis = ctx;
vm.createContext(ctx);
for (const f of ["gpa-api.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(RAIZ, "frontend", f), "utf8"), ctx, { filename: f });
}

// El catálogo real, el mismo que sirve la API.
ctx.CAT = JSON.parse(execFileSync("python", ["-c",
  "import os,json; os.environ.setdefault('USER_POOL_ID','x');" +
  "import catalogos; print(json.dumps(catalogos.catalogos_publicos()))"],
  { cwd: RAIZ, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } }));

const FALLAS = [];
let TOTAL = 0;
function ok(cond, desc) {
  TOTAL++;
  console.log(`  [${cond ? "ok" : "FALLA"}] ${desc}`);
  if (!cond) FALLAS.push(desc);
}
/** Cuenta cuántas veces aparece un texto: sirve para ver que no se repita de más. */
function veces(texto, aguja) {
  return texto.split(aguja).length - 1;
}

// ═══════════════════════════════════════════════════════════════
console.log("\n1. El resumen de la bandeja separa altas de créditos");
// ═══════════════════════════════════════════════════════════════
ctx.api.sesion = { correo: "oscar@gpa.com.mx", nombre: "Oscar Cabrera",
                   rol: "Administrador", n1: true, n2: true };
const fila = (tipo, estado, dias) => ({
  folio: `${tipo}-${estado}-${dias}`, tipo, estado, dias,
  razonSocial: "Cliente de prueba", rfc: "AAA010101AAA", regimen: "601",
  sucursal: "Matriz", creadoPor: "ventas@gpa.com.mx",
  pedidos: 5, ok: 5, marcados: 0, firmas: 0, firmasRequeridas: 1,
});
ctx.S.bandeja = [
  fila("alta", "captura", 2),
  fila("alta", "recibida", 3),
  fila("alta", "por_autorizar", 9),     // también cuenta como "más de 7 días"
  fila("credito", "devuelta", 1),
  fila("credito", "por_autorizar", 12), // idem
  fila("credito", "por_autorizar", 20), // idem
  fila("credito", "autorizada", 40),    // cerrada: no es "abierta" ni "lenta"
];

const html = ctx.vistaBandeja();
ok(html.includes("Altas de cliente"), "hay un bloque «Altas de cliente»");
ok(html.includes("Solicitudes de crédito"), "y otro «Solicitudes de crédito»");

// Se parte el html en los dos bloques para leer los números de cada uno.
const iAlta = html.indexOf("Altas de cliente");
const iCred = html.indexOf("Solicitudes de crédito");
ok(iAlta > -1 && iCred > iAlta, "el de altas va primero");
const bloqueAlta = html.slice(iAlta, iCred);
const bloqueCred = html.slice(iCred, html.indexOf("<table"));

function valor(bloque, etiqueta) {
  // Cada ficha es …>N</div><div class="l">Etiqueta</div>
  const re = new RegExp(">(\\d+)</div><div class=\"l\">" + etiqueta);
  const m = bloque.match(re);
  return m ? Number(m[1]) : null;
}

console.log("\n   Altas: 3 expedientes, todos abiertos");
ok(bloqueAlta.includes("Altas de cliente · 3 abiertos"), "cuenta 3 altas abiertas");
ok(valor(bloqueAlta, "Esperando al cliente") === 1, "1 esperando al cliente");
ok(valor(bloqueAlta, "Por revisar") === 1, "1 por revisar");
ok(valor(bloqueAlta, "Por autorizar") === 1, "1 por autorizar");
ok(valor(bloqueAlta, "Devueltos") === 0, "0 devueltos");
ok(valor(bloqueAlta, "Más de 7 días") === 1, "1 con más de 7 días");
ok(valor(bloqueAlta, "Autorizados") === 0, "0 autorizados");

console.log("\n   Créditos: 4 expedientes, 3 abiertos y 1 ya autorizado");
ok(bloqueCred.includes("Solicitudes de crédito · 3 abiertos"), "cuenta 3 créditos abiertos");
ok(valor(bloqueCred, "Esperando al cliente") === 0, "0 esperando al cliente");
ok(valor(bloqueCred, "Por revisar") === 0, "0 por revisar");
ok(valor(bloqueCred, "Por autorizar") === 2, "2 por autorizar");
ok(valor(bloqueCred, "Devueltos") === 1, "1 devuelto");
ok(valor(bloqueCred, "Más de 7 días") === 2, "2 con más de 7 días (el autorizado no cuenta)");
ok(valor(bloqueCred, "Autorizados") === 1, "1 autorizado");

console.log("\n   Y no se mezclan:");
ok(valor(bloqueAlta, "Por autorizar") + valor(bloqueCred, "Por autorizar") === 3,
   "los 3 «por autorizar» quedan repartidos entre los dos bloques, no sumados en uno");
ok(veces(html, 'class="tiles"') === 2, "son exactamente dos resúmenes, no uno solo ni tres");

// ═══════════════════════════════════════════════════════════════
console.log("\n2. Firma quien tiene la sesión abierta");
// ═══════════════════════════════════════════════════════════════
ctx.S.firmantes = {
  nivel1: [{ correo: "oscar@gpa.com.mx", nombre: "Oscar Cabrera" },
           { correo: "ana@gpa.com.mx", nombre: "Ana Ruiz" }],
  nivel2: [{ correo: "oscar@gpa.com.mx", nombre: "Oscar Cabrera" },
           { correo: "ana@gpa.com.mx", nombre: "Ana Ruiz" }],
};
const casoCredito = { folio: "CR-2609-0001", tipo: "credito", estado: "por_autorizar",
                      autorizaciones: [] };

let f = ctx.bloqueFirmas(casoCredito);
ok(!f.includes("data-firmasel"), "ya no hay selector de firmante en la pantalla");
ok(!f.includes("<select"), "ni ningún otro desplegable en el bloque de autorización");
ok(f.includes("Firma usted: Oscar Cabrera"), "dice con todas sus letras quién va a firmar");
ok(f.includes("data-firmar=\"1\""), "y deja firmar el nivel 1");

console.log("\n   Si usted no está habilitado, no puede firmar:");
ctx.api.sesion = { correo: "ceci@gpa.com.mx", nombre: "Cecilia Medrano",
                   rol: "Comité de Crédito", n1: false, n2: false };
f = ctx.bloqueFirmas(casoCredito);
ok(f.includes("no está habilitado para firmar el nivel 1"), "se lo dice claro");
ok(!f.includes("data-firmar=\"1\""), "y no le pinta el botón");
ok(f.includes("pueden firmarlo: Oscar Cabrera, Ana Ruiz"),
   "pero le dice a quién pedírselo, para no dejarlo atorado");

console.log("\n   Nadie firma dos veces el mismo expediente:");
ctx.api.sesion = { correo: "oscar@gpa.com.mx", nombre: "Oscar Cabrera",
                   rol: "Administrador", n1: true, n2: true };
const yaFirmado = { folio: "CR-2609-0002", tipo: "credito", estado: "por_autorizar",
                    autorizaciones: [{ nivel: 1, usuarioId: "oscar@gpa.com.mx",
                                       nombre: "Oscar Cabrera", rol: "Administrador",
                                       fecha: "22 de septiembre de 2026" }] };
f = ctx.bloqueFirmas(yaFirmado);
ok(f.includes("Usted ya firmó este expediente"), "avisa que usted ya firmó");
ok(!f.includes("data-firmar=\"2\""), "y no le deja firmar también el nivel 2");
ok(f.includes("pueden firmarlo: Ana Ruiz"),
   "el nivel 2 lo tiene que firmar alguien más, y lo nombra");

console.log("\n   Un rol que no autoriza tampoco ve el botón:");
ctx.api.sesion = { correo: "ventas@gpa.com.mx", nombre: "Mesa de Control",
                   rol: "Ventas", n1: true, n2: true };
f = ctx.bloqueFirmas(casoCredito);
ok(f.includes("no autoriza"), "le dice que su rol no autoriza");
ok(!f.includes("data-firmar="), "y no hay botón de firmar por ningún lado");

// ═══════════════════════════════════════════════════════════════
console.log("\n" + "=".repeat(62));
if (FALLAS.length) {
  console.log(`${FALLAS.length} falla(s) de ${TOTAL}:`);
  FALLAS.forEach((x) => console.log("  · " + x));
  process.exit(1);
}
console.log(`Sin fallas. ${TOTAL} comprobaciones sobre las pantallas reales.`);
