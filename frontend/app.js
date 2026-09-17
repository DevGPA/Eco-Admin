// app.js — pantallas de GPA Alta de Clientes
// ─────────────────────────────────────────────────────────────────
// Dos aplicaciones en el mismo archivo, separadas por la dirección:
//   /alta/{token}  o  ?t={token}   → portal del cliente (sin cuenta)
//   cualquier otra                 → panel interno (Cognito)
//
// Las reglas NO viven aquí: el servidor dice qué se puede editar, quién puede
// firmar y qué falta. Esta capa solo dibuja y avisa.
// ─────────────────────────────────────────────────────────────────
"use strict";

var api = new GpaApi();
var portal = null;
var CAT = null;

var S = {
  modo: "interno",          // interno | portal
  vista: "bandeja",         // bandeja | nueva | usuarios | expediente
  folio: null,
  bandeja: [],
  caso: null,
  usuarios: [],
  firmas: null,
  firmantes: { nivel1: [], nivel2: [] },
  nueva: null,
  ligaNueva: null,          // { liga, clave, folio } — la clave se ve una sola vez
  borrador: "",
  firmaSel: {},
  cargando: false,
  error: "",
  aviso: "",
  // portal
  casoCliente: null,
  pasoCliente: "acceso",
  errorClave: "",
  retoCognito: null,
  mostrarFaltantes: false,   // se prende al intentar enviar
};

// ── utilidades ───────────────────────────────────────────────────
/** Logo de GPA. Es el archivo real de la empresa, el mismo de Operaciones. */
function logoGPA(ancho) {
  return '<span class="logo-suelto" style="width:' + (ancho || 110) + 'px">' +
    '<img src="logo.png" alt="General de Productos para el Agua"></span>';
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function $(sel) { return document.querySelector(sel); }
function limpia(s) { return String(s).replace(/<[^>]+>/g, ""); }

function toast(msg) {
  var prev = $(".toast");
  if (prev) prev.remove();
  var el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  el.setAttribute("role", "status");
  document.body.appendChild(el);
  setTimeout(function () { el.remove(); }, 3400);
}

/** Un error siempre se ve donde la persona está mirando, no solo en un aviso pasajero. */
function conError(fn) {
  return function () {
    var args = arguments;
    S.error = "";
    S.cargando = true;
    render();
    return Promise.resolve()
      .then(function () { return fn.apply(null, args); })
      .catch(function (e) { S.error = e.message || String(e); })
      .then(function () { S.cargando = false; render(); });
  };
}

function bannerError() {
  if (!S.error) return "";
  return '<div class="banner banner-stop"><span><b>No se pudo.</b> ' + esc(S.error) + "</span></div>";
}
function bannerAviso() {
  if (!S.aviso) return "";
  return '<div class="banner banner-info"><span>' + esc(S.aviso) + "</span></div>";
}

function tipoDe(caso) { return (CAT.tipos[(caso || {}).tipo]) || CAT.tipos.alta; }
function modulo(id) { return CAT.modulos.filter(function (m) { return m.id === id; })[0]; }
function doc(id) { return CAT.documentos.filter(function (d) { return d.id === id; })[0]; }
function regimen(cod) { return CAT.regimenes.filter(function (r) { return r.c === cod; })[0]; }

function personaDe(cod, rfc) {
  var r = regimen(cod);
  if (r && r.t === "M") return "Moral";
  if (r && r.t === "F") return "Física";
  var limpio = String(rfc || "").replace(/[^A-Za-z0-9]/g, "");
  if (limpio.length === 12) return "Moral";
  if (limpio.length === 13) return "Física";
  return "Moral";
}
function conflictoRfc(cod, rfc) {
  var r = regimen(cod);
  var limpio = String(rfc || "").replace(/[^A-Za-z0-9]/g, "");
  var porRfc = limpio.length === 12 ? "Moral" : limpio.length === 13 ? "Física" : "";
  if (!r || !porRfc || r.t === "FM") return "";
  var porReg = r.t === "M" ? "Moral" : "Física";
  if (porReg === porRfc) return "";
  return "El régimen " + r.c + " es de persona " + porReg.toLowerCase() + ", pero el RFC tiene " +
    limpio.length + " caracteres, que corresponde a persona " + porRfc.toLowerCase() + ".";
}

function camposDe(mod) {
  if (mod.id !== "contactos") return mod.campos || [];
  var out = [];
  (mod.roles || []).forEach(function (r, i) {
    out.push({ k: "c" + i + "_nombre", l: r, w: "half", req: i < 3 });
    out.push({ k: "c" + i + "_cel", l: "Celular", w: "third", mono: true });
    out.push({ k: "c" + i + "_mail", l: "Correo", w: "third" });
  });
  return out;
}
function modulosActivos(caso) {
  return tipoDe(caso).modulos
    .filter(function (id) { return (caso.modulos || {})[id]; })
    .map(modulo);
}
function docsAplicables(caso) {
  return (caso.docsAplicables || []).map(doc).filter(Boolean);
}
function etiquetaTipo(tid) {
  var T = CAT.tipos[tid] || CAT.tipos.alta;
  return '<span class="tag ' + (tid === "credito" ? "tag-credito" : "tag-alta") + '">' + esc(T.corto) + "</span>";
}
function pill(estado) {
  var e = CAT.estados[estado] || { t: estado, c: "p-borrador" };
  return '<span class="pill ' + e.c + '">' + esc(e.t) + "</span>";
}

// ═══════════════════════════════════════════════════════════════
// PORTAL DEL CLIENTE
// ═══════════════════════════════════════════════════════════════
function vistaPortal() {
  var c = S.casoCliente;
  var paso = c ? S.pasoCliente : "acceso";
  var idx = { acceso: 0, captura: 1, revisar: 2, enviado: 2 }[paso];
  var pasos = ["Acceso", "Su información", "Revisar y enviar"].map(function (t, i) {
    return '<div class="step ' + (i === idx ? "on" : "") + " " + (i < idx ? "done" : "") + '">' +
      "<b>" + (i < idx ? "✓" : i + 1) + "</b>" + t + "</div>";
  }).join("");

  var cuerpo;
  if (!c) cuerpo = portalAcceso();
  else if (paso === "guardado") cuerpo = portalGuardado();
  else if (paso === "enviado") cuerpo = portalEnviado();
  else if (paso === "revisar") cuerpo = portalRevisar();
  else cuerpo = portalCaptura();

  return '<div class="wrap"><div class="tarjeta-portal">' +
    (c ? '<div class="steps">' + pasos + "</div>" : "") + cuerpo + "</div>" +
    '<p class="dim pie-portal">Sin cuenta, sin contraseña y sin instalar nada. ' +
    "Puede salir y volver con esta misma liga y clave.</p></div>";
}

function portalAcceso() {
  return '<div class="stack" style="gap:18px">' +
    '<div>' + logoGPA(52) +
    '<h1 style="font-size:23px; margin-top:14px">Alta de cliente</h1>' +
    '<p class="muted" style="margin:6px 0 0">General de Productos para el Agua le envió esta invitación. ' +
    "Entre con la clave que le dimos por teléfono o WhatsApp.</p></div>" +
    '<hr class="sep">' +
    '<div class="stack" style="gap:12px">' +
      '<div class="field"><label for="clave">Clave de acceso</label>' +
      '<input id="clave" class="mono clave-input" placeholder="XXXX-XXXX" autocomplete="off" ' +
      'maxlength="9" inputmode="text" autocapitalize="characters"></div>' +
      (S.errorClave ? '<div class="banner banner-stop"><span>' + esc(S.errorClave) + "</span></div>" : "") +
      bannerError() +
      '<button class="btn btn-primary" id="btn-entrar-portal"' + (S.cargando ? " disabled" : "") + ">" +
      (S.cargando ? "Entrando…" : "Entrar") + "</button>" +
      '<p class="dim" style="margin:0">Si no tiene su clave o ya no le sirve, comuníquese con GPA. ' +
      "Lo que escriba se guarda solo.</p>" +
    "</div></div>";
}

function bloqueFijos(c) {
  var r = regimen(c.regimen);
  return '<div class="stack" style="gap:8px">' +
    '<div class="spread"><div class="eyebrow">Datos registrados por GPA</div>' +
    '<span class="candado">No editable</span></div>' +
    '<div class="fijos">' +
      '<div class="fila"><span>Razón social</span><span>' + esc(c.razonSocial) + "</span></div>" +
      (c.nombreComercial ? '<div class="fila"><span>Nombre comercial</span><span>' + esc(c.nombreComercial) + "</span></div>" : "") +
      '<div class="fila"><span>RFC</span><span class="mono">' + esc(c.rfc) + "</span></div>" +
      '<div class="fila"><span>Régimen fiscal</span><span>' + (r ? esc(r.c + " — " + r.n) : esc(c.regimen)) + "</span></div>" +
      '<div class="fila"><span>Tipo de persona</span><span>' + esc(c.persona) + "</span></div>" +
    "</div>" +
    '<p class="dim" style="margin:0">Si algo de aquí está mal, avísele a GPA: solo ellos lo pueden corregir.</p></div>';
}

function campoHTML(f, c, editables) {
  var puede = !editables || editables.indexOf(f.k) !== -1;
  if (!puede) return "";
  var v = (c.valores || {})[f.k];
  var ancho = f.w === "full" ? "f-full" : f.w === "half" ? "f-half" : "f-third";
  var req = f.req ? ' <span class="req">*</span>' : "";
  var id = "f_" + f.k;

  // Campos que fija el sistema: el cliente los ve, no los cambia. (País = México)
  if (f.fijo) {
    return '<div class="field ' + ancho + '"><label for="' + id + '">' + esc(f.l) + "</label>" +
      '<input id="' + id + '" value="' + esc(f.fijo) + '" disabled class="fijo"></div>';
  }

  // Lo que GPA señaló al devolver, y lo que está mal escrito o falta.
  var marca = (c.marcas || {})["campo:" + f.k];
  var problema = (c.problemas || {})[f.k];
  var malo = marca ? marca.motivo : (S.mostrarFaltantes ? problema : "");
  var cls = "field " + ancho + (malo ? " flag" : "");
  var nota = malo ? '<span class="field-note">' + esc(malo) + "</span>" : "";

  if (f.tipo === "check") {
    return '<label class="check f-full" style="padding:4px 0">' +
      '<input type="checkbox" data-campo="' + f.k + '" ' + (v === true ? "checked" : "") + ">" +
      "<span>" + esc(f.l) + req + "</span></label>";
  }
  if (f.tipo === "area") {
    return '<div class="' + cls + '"><label for="' + id + '">' + esc(f.l) + req + "</label>" +
      '<textarea id="' + id + '" data-campo="' + f.k + '" rows="2" placeholder="' + esc(f.ph || "") + '">' +
      esc(v || "") + "</textarea>" + nota + "</div>";
  }
  if (f.opts) {
    return '<div class="' + cls + '"><label for="' + id + '">' + esc(f.l) + req + "</label>" +
      '<select id="' + id + '" data-campo="' + f.k + '"><option value="">Seleccione…</option>' +
      f.opts.map(function (o) { return "<option " + (v === o ? "selected" : "") + ">" + esc(o) + "</option>"; }).join("") +
      "</select>" + nota + "</div>";
  }
  // Las horas usan el selector del navegador: asi todos capturan igual (08:00, 17:30).
  var tipoInput = f.tipo === "hora" ? "time" : f.tipo === "email" ? "email" : f.tipo === "tel" ? "tel" : "text";
  var modo = (f.tipo === "tel" || f.tipo === "cp") ? ' inputmode="numeric"' : "";
  return '<div class="' + cls + '"><label for="' + id + '">' + esc(f.l) + req + "</label>" +
    '<input id="' + id + '" type="' + tipoInput + '"' + modo + ' data-campo="' + f.k + '" class="' +
    (f.mono ? "mono" : "") + '" value="' + esc(v || "") + '" placeholder="' + esc(f.ph || "") + '">' +
    nota + "</div>";
}

function tablaHTML(t, c, editables) {
  var filas = [];
  for (var r = 0; r < t.n; r++) {
    var celdas = t.cols.map(function (col, ci) {
      var k = t.k + "_" + r + "_" + ci;
      if (editables && editables.indexOf(k) === -1) return "";
      return '<td><input data-tabla="' + k + '" value="' + esc((c.tablasVal || {})[k] || "") +
        '" placeholder="' + esc(col) + '"></td>';
    }).join("");
    if (celdas) filas.push("<tr>" + celdas + "</tr>");
  }
  if (!filas.length) return "";
  return '<div class="stack f-full" style="gap:6px">' +
    '<div class="eyebrow">' + esc(t.l) + (t.req ? ' <span class="req">*</span>' : "") + "</div>" +
    '<div class="tablewrap"><table class="minitable">' + filas.join("") + "</table></div></div>";
}

/** Lo que falta o esta mal, calculado aqui mismo para poder avisar al instante.
 *  El servidor vuelve a revisarlo todo al enviar: esto es solo para la pantalla. */
function revisaLocal(c) {
  var out = {};
  modulosActivos(c).forEach(function (m) {
    camposDe(m).forEach(function (f) {
      if (f.fijo) return;
      var v = (c.valores || {})[f.k];
      var t = v === undefined || v === null ? "" : String(v).trim();
      if (f.tipo === "check") { if (f.req && v !== true) out[f.k] = "Falta marcar esta casilla."; return; }
      if (!t) { if (f.req) out[f.k] = "Falta llenar este dato."; return; }
      var d = t.replace(/\D/g, "");
      if (f.tipo === "tel" && d.length < 10) out[f.k] = "El teléfono va con 10 dígitos. Escribió " + d.length + ".";
      else if (f.tipo === "cp" && d.length !== 5) out[f.k] = "El código postal va con 5 dígitos. Escribió " + d.length + ".";
      else if (f.tipo === "email" && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(t)) out[f.k] = "Ese correo no parece válido.";
      else if (f.tipo === "hora" && !/^([01]?\d|2[0-3]):[0-5]\d$/.test(t)) out[f.k] = "La hora va como 08:00.";
    });
  });
  return out;
}

function faltantesLocal(c) {
  var lista = [];
  var probs = revisaLocal(c);
  var etiquetas = {};
  modulosActivos(c).forEach(function (m) {
    camposDe(m).forEach(function (f) { etiquetas[f.k] = limpia(f.l); });
  });
  Object.keys(probs).forEach(function (k) { lista.push(etiquetas[k] || k); });
  docsAplicables(c).forEach(function (d) {
    if (!(c.adjuntos || {})[d.id]) lista.push(d.n);
  });
  return lista;
}

/** Avance calculado aqui: la barra se mueve mientras se escribe, sin ir al servidor. */
function avanceLocal(c) {
  var total = 0, hechos = 0;
  modulosActivos(c).forEach(function (m) {
    camposDe(m).forEach(function (f) {
      if (!f.req || f.fijo) return;
      total++;
      var v = (c.valores || {})[f.k];
      if (f.tipo === "check" ? v === true : String(v == null ? "" : v).trim() !== "") hechos++;
    });
    (m.tablas || []).forEach(function (t) {
      if (!t.req) return;
      total++;
      if (String((c.tablasVal || {})[t.k + "_0_0"] || "").trim() !== "") hechos++;
    });
  });
  docsAplicables(c).forEach(function (d) {
    total++;
    if ((c.adjuntos || {})[d.id]) hechos++;
  });
  return { total: total, hechos: hechos, pct: total ? Math.round(hechos / total * 100) : 0 };
}

/** Pasa al estado lo que hay escrito en pantalla, antes de redibujar o guardar.
 *  Sin esto, cada redibujado (guardar, adjuntar) borraba lo tecleado. */
function sincronizaDesdeDOM() {
  var c = S.casoCliente;
  if (!c) return;
  c.valores = c.valores || {};
  c.tablasVal = c.tablasVal || {};
  document.querySelectorAll("[data-campo]").forEach(function (el) {
    c.valores[el.dataset.campo] = el.type === "checkbox" ? el.checked : el.value;
  });
  document.querySelectorAll("[data-tabla]").forEach(function (el) {
    c.tablasVal[el.dataset.tabla] = el.value;
  });
}

function portalCaptura() {
  var c = S.casoCliente;
  var devuelta = c.estado === "devuelta";
  // El servidor manda: si no está en camposEditables, no se dibuja.
  var editables = devuelta ? (c.camposEditables || []) : null;
  var aplic = docsAplicables(c);
  var visibles = devuelta
    ? aplic.filter(function (d) { return (c.marcas || {})[d.id]; })
    : aplic;

  var secciones = modulosActivos(c).map(function (m) {
    var campos = camposDe(m).map(function (f) { return campoHTML(f, c, editables); }).join("");
    var tablas = (m.tablas || []).map(function (t) { return tablaHTML(t, c, editables); }).join("");
    if (!campos && !tablas) return "";
    return '<div class="stack" style="gap:10px"><div><div class="eyebrow">' + esc(m.nombre) + "</div>" +
      '<p class="dim" style="margin:2px 0 0">' + esc(m.desc) + "</p></div>" +
      '<div class="grid">' + campos + tablas + '</div></div><hr class="sep">';
  }).join("");

  var docs = visibles.map(function (d) {
    var adj = (c.adjuntos || {})[d.id];
    var marca = (c.marcas || {})[d.id];
    return '<div class="doc ' + (marca ? "flag" : adj ? "attached" : "") + '">' +
      '<div class="doc-ic">' + esc(d.t) + "</div>" +
      '<div class="doc-body"><div class="doc-name">' + esc(d.n) + "</div>" +
      '<div class="doc-meta">' +
      (adj ? '<span class="mono">' + esc(adj.nombre) + "</span>" +
             (adj.url ? ' <a href="' + esc(adj.url) + '" target="_blank" rel="noopener">ver</a>' : "")
           : "<span>Archivo " + esc(d.t) + " o foto desde el celular</span>") +
      "</div>" +
      (marca ? '<div class="doc-motivo">GPA señaló: ' + esc(marca.motivo) + "</div>" : "") +
      '<div class="barra-subida" data-barra="' + d.id + '" hidden><i></i></div>' +
      "</div>" +
      '<label class="btn btn-sm ' + (adj ? "" : "btn-primary") + ' subir">' +
      (adj ? "Reemplazar" : "Adjuntar") +
      '<input type="file" data-subir="' + d.id + '" accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,image/*,application/pdf" hidden></label>' +
      "</div>";
  }).join("");

  var cabecera = devuelta
    ? '<div class="banner banner-stop"><span><b>Faltan unos ajustes.</b> Revisamos su expediente y ' +
      "solo necesitamos que corrija lo marcado abajo. Todo lo demás ya quedó guardado.</span></div>"
    : '<div><h1 style="font-size:21px">' + esc(c.tipoNombre) + "</h1>" +
      '<p class="dim" style="margin:3px 0 0">Complete lo que aplique. Puede salir y volver cuando quiera.</p></div>';

  var av = avanceLocal(c);
  return '<div class="stack" style="gap:18px">' + cabecera + bannerError() + bannerAviso() +
    (devuelta ? "" : bloqueFijos(c)) +
    '<div class="stack" style="gap:7px"><div class="spread"><span class="dim">Avance</span>' +
    '<span class="dim mono" id="pct">' + av.pct + '%</span></div>' +
    '<div class="progress"><i style="width:' + av.pct + '%"></i></div></div>' +
    '<hr class="sep">' + secciones +
    '<div class="stack" style="gap:10px"><div><div class="eyebrow">Documentos</div>' +
    '<p class="dim" style="margin:2px 0 0">' +
    (devuelta ? "Solo estos necesitan reemplazo." : "Puede tomarles foto con el celular. Hasta 15 MB cada uno.") +
    "</p></div>" +
    '<div class="doclist">' + (docs || '<p class="dim">No hay documentos por adjuntar.</p>') + "</div></div>" +
    '<hr class="sep">' +
    '<div class="row"><button class="btn btn-primary" id="btn-a-revisar">Revisar y enviar</button>' +
    '<button class="btn" id="btn-guardar-portal">Guardar y salir</button></div></div>';
}

function portalRevisar() {
  var c = S.casoCliente;
  var aplic = docsAplicables(c);
  var faltan = faltantesLocal(c);

  var resumen = modulosActivos(c).map(function (m) {
    var campos = camposDe(m).filter(function (f) { return f.tipo !== "check" && (c.valores || {})[f.k]; });
    if (!campos.length) return "";
    return '<div class="stack" style="gap:5px"><div class="eyebrow">' + esc(m.nombre) + "</div><div>" +
      campos.map(function (f) {
        return '<div class="kv"><span>' + esc(limpia(f.l)) + "</span><span" +
          (f.mono ? ' class="mono" style="font-size:13px"' : "") + ">" + esc(c.valores[f.k]) + "</span></div>";
      }).join("") + "</div></div>";
  }).join("");

  // Sin campos completos no se envia: la regla tambien esta en el servidor.
  var aviso = faltan.length
    ? '<div class="banner banner-stop"><span><b>Todavía no se puede enviar.</b> Faltan ' +
      faltan.length + " punto(s): " + esc(faltan.slice(0, 6).join(", ")) +
      (faltan.length > 6 ? " y " + (faltan.length - 6) + " más" : "") +
      '. Vuelva a su información: están marcados en rojo.</span></div>'
    : '<div class="banner banner-ok"><span><b>Su expediente está completo.</b> ' +
      aplic.length + " documentos adjuntos.</span></div>";

  return '<div class="stack" style="gap:18px">' +
    '<div><h1 style="font-size:21px">Revise antes de enviar</h1>' +
    '<p class="dim" style="margin:3px 0 0">Una vez enviado, GPA revisa su expediente. ' +
    "Si algo falta se lo devolvemos por esta misma liga.</p></div>" +
    bannerError() + aviso + bloqueFijos(c) + resumen +
    '<hr class="sep"><div class="stack" style="gap:8px"><div class="eyebrow">Documentos adjuntos</div>' +
    aplic.map(function (d) {
      var ok = !!(c.adjuntos || {})[d.id];
      return '<div class="row" style="gap:8px; font-size:13.5px"><span style="color:' +
        (ok ? "var(--ok)" : "var(--warn)") + '">' + (ok ? "✓" : "○") + "</span><span>" + esc(d.n) + "</span></div>";
    }).join("") + "</div><hr class=\"sep\">" +
    (faltan.length ? "" :
      '<label class="check"><input type="checkbox" id="privacidad">' +
      "<span>He leído el aviso de privacidad y autorizo a General de Productos para el Agua, S.A. de C.V. " +
      "a tratar estos datos y documentos para evaluar y registrar mi solicitud.</span></label>") +
    '<div class="row">' +
    (faltan.length
      ? '<button class="btn btn-primary" disabled>Enviar mi expediente</button>'
      : '<button class="btn btn-primary" id="btn-enviar-portal" disabled>Enviar mi expediente</button>') +
    '<button class="btn" id="btn-volver-captura">Volver a mi información</button></div></div>';
}

function portalGuardado() {
  var c = S.casoCliente;
  var av = avanceLocal(c);
  var faltan = faltantesLocal(c);
  return '<div class="stack" style="gap:18px">' +
    '<div class="banner banner-ok" style="font-size:15px"><span><b>Guardado.</b> ' +
    "Puede cerrar esta página y volver cuando quiera con su misma liga y clave.</span></div>" +
    '<div class="stack" style="gap:7px"><div class="spread"><span class="dim">Lleva</span>' +
    '<span class="dim mono">' + av.pct + '%</span></div>' +
    '<div class="progress"><i style="width:' + av.pct + '%"></i></div></div>' +
    (faltan.length
      ? '<div class="banner banner-warn"><span><b>Le faltan ' + faltan.length + " punto(s):</b> " +
        esc(faltan.slice(0, 5).join(", ")) + (faltan.length > 5 ? " y " + (faltan.length - 5) + " más" : "") +
        ". Su expediente no se envía hasta que estén completos.</span></div>"
      : '<div class="banner banner-ok"><span>Ya no le falta nada: puede enviarlo cuando guste.</span></div>') +
    '<div class="row"><button class="btn btn-primary" id="btn-seguir-llenando">Seguir llenando</button></div>' +
    '<p class="dim" style="margin:0">Folio <span class="mono">' + esc(c.folio) + "</span></p></div>";
}

function portalEnviado() {
  var c = S.casoCliente;
  return '<div class="stack" style="gap:18px">' +
    '<div class="banner banner-ok" style="font-size:15px"><span><b>Expediente enviado.</b> Gracias' +
    (c.contacto ? ", " + esc(c.contacto) : "") + ".</span></div>" +
    '<div class="stack" style="gap:6px"><div class="eyebrow">Su acuse</div>' +
    '<div class="liga" style="border-style:solid"><span>' + esc(c.folio) + "</span></div></div>" +
    '<p class="muted" style="margin:0">GPA revisará su información. Si algo necesita corrección, ' +
    "le avisaremos y podrá entrar con esta misma liga y clave a arreglar únicamente lo señalado.</p>" +
    '<p class="dim" style="margin:0">Puede cerrar esta página.</p></div>';
}

// ═══════════════════════════════════════════════════════════════
// PANEL INTERNO
// ═══════════════════════════════════════════════════════════════
function vistaLogin() {
  if (S.retoCognito) {
    return '<div class="wrap"><div class="tarjeta-login stack" style="gap:14px">' +
      '<div>' + logoGPA(52) + '<h1 style="font-size:21px; margin-top:12px">Elija su contraseña</h1>' +
      '<p class="dim" style="margin:4px 0 0">Es su primer ingreso. Al menos 10 caracteres, ' +
      "con mayúscula, minúscula y número.</p></div>" + bannerError() +
      '<div class="field"><label for="pw1">Contraseña nueva</label>' +
      '<input id="pw1" type="password" autocomplete="new-password"></div>' +
      '<div class="field"><label for="pw2">Repítala</label>' +
      '<input id="pw2" type="password" autocomplete="new-password"></div>' +
      '<button class="btn btn-primary" id="btn-fijar-pw"' + (S.cargando ? " disabled" : "") + ">" +
      (S.cargando ? "Guardando…" : "Guardar y entrar") + "</button></div></div>";
  }
  return '<div class="wrap"><div class="tarjeta-login stack" style="gap:14px">' +
    '<div>' + logoGPA(52) +
    '<h1 style="font-size:21px; margin-top:12px">Alta de Clientes</h1>' +
    '<p class="dim" style="margin:4px 0 0">Acceso para personal de GPA.</p></div>' + bannerError() +
    '<div class="field"><label for="correo">Correo</label>' +
    '<input id="correo" type="email" autocomplete="username" placeholder="nombre@gpa.com.mx"></div>' +
    '<div class="field"><label for="pw">Contraseña</label>' +
    '<input id="pw" type="password" autocomplete="current-password"></div>' +
    '<button class="btn btn-primary" id="btn-login"' + (S.cargando ? " disabled" : "") + ">" +
    (S.cargando ? "Entrando…" : "Entrar") + "</button>" +
    '<p class="dim" style="margin:0">¿Es un cliente de GPA? Usted no necesita cuenta: ' +
    "entre por la liga que le enviamos por correo.</p></div></div>";
}

function vistaBandeja() {
  var filas = S.bandeja.map(function (x) {
    var falta;
    if (x.estado === "autorizada") falta = '<span class="dim">Nada</span>';
    else if (x.estado === "rechazada") falta = '<span style="color:var(--stop)">Rechazada</span>';
    else if (x.marcados) falta = '<span style="color:var(--stop)">' + x.marcados + " señalado" + (x.marcados > 1 ? "s" : "") + "</span>";
    else if (x.estado === "por_autorizar") falta = '<span style="color:var(--warn)">' + x.firmas + " de " + x.firmasRequeridas + " firmas</span>";
    else if (x.pedidos - x.ok > 0) falta = (x.pedidos - x.ok) + " de " + x.pedidos + " documentos";
    else falta = "Listo para revisar";
    return '<tr class="clickable" data-folio="' + esc(x.folio) + '">' +
      '<td class="mono" style="font-size:13px">' + esc(x.folio) + "</td>" +
      "<td>" + etiquetaTipo(x.tipo) + "</td>" +
      '<td><div style="font-weight:600">' + esc(x.razonSocial) + "</div>" +
      '<div class="dim mono" style="font-size:12px">' + esc(x.rfc) + " · régimen " + esc(x.regimen) + "</div></td>" +
      "<td>" + esc(x.creadoPor || "—") + "</td>" +
      '<td><span class="tag">' + esc(x.sucursal || "—") + "</span></td>" +
      "<td>" + pill(x.estado) + "</td>" +
      '<td class="num mono">' + x.dias + "</td>" +
      '<td style="font-size:13.5px">' + falta + "</td></tr>";
  }).join("");

  function cuenta(e) { return S.bandeja.filter(function (x) { return x.estado === e; }).length; }
  var abiertos = S.bandeja.filter(function (x) { return x.estado !== "autorizada" && x.estado !== "rechazada"; }).length;
  var lentos = S.bandeja.filter(function (x) { return x.estado !== "autorizada" && x.estado !== "rechazada" && x.dias > 7; }).length;

  return '<div class="stack">' + bannerError() +
    '<div><h1 style="font-size:22px">Bandeja de expedientes</h1>' +
    '<p class="dim" style="margin:3px 0 0">Altas y créditos son solicitudes separadas, ' +
    "cada una con su liga y sus documentos.</p></div>" +
    '<div class="tiles">' +
      '<div class="tile"><div class="k">' + abiertos + '</div><div class="l">Abiertos</div></div>' +
      '<div class="tile"><div class="k">' + (cuenta("enviada") + cuenta("captura")) + '</div><div class="l">Esperando al cliente</div></div>' +
      '<div class="tile"><div class="k">' + cuenta("recibida") + '</div><div class="l">Por revisar</div></div>' +
      '<div class="tile"><div class="k" style="color:' + (cuenta("por_autorizar") ? "var(--warn)" : "inherit") + '">' + cuenta("por_autorizar") + '</div><div class="l">Por autorizar</div></div>' +
      '<div class="tile"><div class="k" style="color:' + (cuenta("devuelta") ? "var(--stop)" : "inherit") + '">' + cuenta("devuelta") + '</div><div class="l">Devueltos</div></div>' +
      '<div class="tile"><div class="k" style="color:' + (lentos ? "var(--warn)" : "inherit") + '">' + lentos + '</div><div class="l">Más de 7 días</div></div>' +
    "</div>" +
    '<div class="card pad"><div class="tablewrap"><table class="grid-t">' +
    "<thead><tr><th>Folio</th><th>Tipo</th><th>Cliente</th><th>Creó</th><th>Sucursal</th>" +
    '<th>Estado</th><th class="num">Días</th><th>Qué falta</th></tr></thead><tbody>' +
    (filas || '<tr><td colspan="8" class="dim">Todavía no hay expedientes. Empiece con una pre-solicitud.</td></tr>') +
    "</tbody></table></div></div></div>";
}

/** Secciones del formulario. No se eligen: el tipo de solicitud las trae todas. */
function listaModulos(T) {
  return T.modulos.map(function (id) {
    var m = modulo(id);
    return '<div class="modrow on"><span class="palomita">✓</span>' +
      '<span><span class="t">' + esc(m.nombre) + '</span>' +
      '<span class="d">' + esc(m.desc) + "</span></span></div>";
  }).join("");
}

/** Documentos del tipo. Los de persona moral se descuentan según el régimen. */
function listaDocumentos(T, persona) {
  return T.docs.map(function (id) {
    var d = doc(id);
    var noAplica = d.pm && persona === "Física";
    return '<div class="docpick ' + (noAplica ? "off" : "") + '">' +
      '<span class="palomita">' + (noAplica ? "—" : "✓") + "</span><span>" + esc(d.n) +
      (noAplica ? '<span class="dim"> · no aplica a persona física</span>' : "") + "</span></div>";
  }).join("");
}

/** Que le falta a la pre-solicitud para poder generar la liga.
 *  Las mismas reglas corren en el servidor; esto solo evita el viaje en balde. */
function problemasNueva(n) {
  var out = [];
  if (!String(n.razon_social || "").trim()) out.push("la razón social");
  var rfc = String(n.rfc || "").replace(/[^A-Za-z0-9]/g, "");
  if (rfc.length !== 12 && rfc.length !== 13) {
    out.push(rfc ? "el RFC completo (12 o 13 caracteres, lleva " + rfc.length + ")" : "el RFC");
  }
  var correo = String(n.correo || "").trim();
  if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(correo)) {
    out.push(correo ? "un correo válido del contacto" : "el correo del contacto");
  }
  var cel = String(n.celular || "").replace(/\D/g, "");
  if (cel.length < 10) {
    out.push(cel ? "el celular completo (10 dígitos, lleva " + cel.length + ")" : "el celular del contacto");
  }
  return out;
}

function textoPersona(n) {
  var r = regimen(n.regimen);
  return "Persona <b>" + esc(personaDe(n.regimen, n.rfc).toLowerCase()) + "</b>" +
    (r && r.t === "FM" ? ", determinada por la longitud del RFC" : "") + ".";
}

/** Refresca SOLO lo que depende del RFC y del régimen.
 *
 *  Nunca llama a render(): redibujar el formulario completo destruye el campo
 *  donde la persona está escribiendo y le quita el foco, obligando a hacer clic
 *  después de cada letra.
 */
function actualizaPorRfc() {
  var n = S.nueva;
  if (!n) return;
  var T = CAT.tipos[n.tipo];
  var persona = personaDe(n.regimen, n.rfc);

  var hint = $("#persona-hint");
  if (hint) hint.innerHTML = textoPersona(n);

  var caja = $("#conflicto-rfc");
  if (caja) {
    var texto = conflictoRfc(n.regimen, n.rfc);
    caja.innerHTML = texto
      ? '<div class="banner banner-warn"><span><b>Revise el régimen o el RFC.</b> ' + esc(texto) + "</span></div>"
      : "";
  }

  var lista = $("#lista-docs");
  if (lista) lista.innerHTML = listaDocumentos(T, persona);

  var conteo = $("#conteo-docs");
  if (conteo) {
    var cuantos = T.docs.filter(function (id) {
      var d = doc(id);
      return !(d.pm && persona === "Física");
    }).length;
    conteo.textContent = cuantos + " documento" + (cuantos === 1 ? "" : "s");
  }

  var faltan = problemasNueva(n);
  var boton = $("#btn-generar");
  if (boton) boton.disabled = faltan.length > 0;
  var aviso = $("#aviso-nueva");
  if (aviso) {
    aviso.innerHTML = faltan.length
      ? '<p class="dim" style="margin:0">Falta ' + esc(faltan.join(", ")) + ".</p>"
      : "";
  }
}

function vistaNueva() {
  var n = S.nueva;
  var T = CAT.tipos[n.tipo];
  var persona = personaDe(n.regimen, n.rfc);
  var conflicto = conflictoRfc(n.regimen, n.rfc);

  function campo(k, l, w, cls, ph) {
    return '<div class="field ' + w + '"><label for="n_' + k + '">' + l + "</label>" +
      '<input id="n_' + k + '" data-nueva="' + k + '" class="' + (cls || "") + '" value="' +
      esc(n[k] || "") + '" placeholder="' + esc(ph || "") + '"></div>';
  }
  function selec(k, l, w, opts) {
    return '<div class="field ' + w + '"><label for="n_' + k + '">' + l + '</label><select id="n_' + k + '" data-nueva="' + k + '">' +
      opts.map(function (o) { return "<option " + (n[k] === o ? "selected" : "") + ">" + esc(o) + "</option>"; }).join("") +
      "</select></div>";
  }

  var nDocs = T.docs.filter(function (id) {
    var d = doc(id);
    return !(d.pm && persona === "Física");
  }).length;
  var faltanNueva = problemasNueva(n);
  var listo = faltanNueva.length === 0;

  var panel;
  if (S.ligaNueva) {
    var L = S.ligaNueva;
    panel = '<div class="stack">' +
      '<div class="banner banner-ok"><span><b>Listo, folio ' + esc(L.folio) + ".</b> " +
      "La clave se muestra <b>una sola vez</b>: cópiela ahora.</span></div>" +
      '<div class="stack" style="gap:7px"><div class="eyebrow">1 · Liga, por correo</div>' +
      '<div class="liga"><span>' + esc(L.liga) + "</span></div>" +
      '<div class="row"><button class="btn btn-primary btn-sm" data-copiar="liga">Copiar liga</button>' +
      '<button class="btn btn-sm" data-borrador="correo">Borrador de correo</button></div>' +
      (S.borrador === "correo" ? '<div class="draft">' + esc(L.correo) + "</div>" : "") + "</div>" +
      '<hr class="sep"><div class="stack" style="gap:7px"><div class="eyebrow">2 · Clave, por otro canal</div>' +
      '<div class="clave">' + esc(L.clave) + "</div>" +
      '<div class="row"><button class="btn btn-primary btn-sm" data-copiar="clave">Copiar clave</button>' +
      '<button class="btn btn-sm" data-borrador="clave">Mensaje para WhatsApp</button></div>' +
      (S.borrador === "clave" ? '<div class="draft">' + esc(L.mensaje) + "</div>" : "") +
      '<p class="dim" style="margin:0">Nunca en el mismo correo que la liga: si el correo se reenvía, ' +
      "la liga sola no abre nada.</p></div>" +
      '<hr class="sep"><div class="row"><button class="btn" data-ir="bandeja">Ver la bandeja</button>' +
      '<button class="btn" data-abrir="' + esc(L.folio) + '">Abrir el expediente</button></div></div>';
  } else {
    panel = '<div class="stack">' +
      '<p class="dim" style="margin:0">Se generan dos cosas: la <b>liga</b>, que va por correo, ' +
      "y la <b>clave</b>, que va por otro canal.</p>" +
      '<button class="btn btn-primary" id="btn-generar"' + (listo && !S.cargando ? "" : " disabled") + ">" +
      (S.cargando ? "Generando…" : "Generar liga y clave") + "</button>" +
      '<div id="aviso-nueva">' +
      (listo ? "" : '<p class="dim" style="margin:0">Falta ' + esc(faltanNueva.join(", ")) + ".</p>") +
      "</div></div>";
  }

  return '<div class="stack">' + bannerError() +
    '<div><h1 style="font-size:22px">Nueva pre-solicitud</h1>' +
    '<p class="dim" style="margin:3px 0 0">Sin esta captura no existe liga. ' +
    "Nadie puede darse de alta por su cuenta.</p></div>" +
    '<div class="cols"><div class="stack">' +
      '<div class="card pad stack"><div class="eyebrow">1 · Qué se va a solicitar</div>' +
      '<div class="seg" style="width:fit-content">' +
      Object.keys(CAT.tipos).map(function (id) {
        return '<button data-tipo="' + id + '" aria-selected="' + (n.tipo === id) + '">' + esc(CAT.tipos[id].nombre) + "</button>";
      }).join("") + "</div>" +
      '<p class="dim" style="margin:0">' + esc(T.desc) + ' Formato <span class="mono">' + esc(T.formato) + "</span>. " +
      (T.autoriza === "simple" ? "La autoriza un miembro del Comité de Crédito." : "Necesita tres firmas: nivel 1 y dos de nivel 2.") + "</p></div>" +
      '<div class="card pad stack"><div class="eyebrow">2 · Quién es el cliente</div>' +
      '<p class="dim" style="margin:0">Razón social, RFC y nombre comercial quedan <b>fijos</b>: ' +
      "el cliente los ve, pero no los puede cambiar.</p><div class=\"grid\">" +
      campo("razon_social", 'Razón social <span class="req">*</span>', "f-full") +
      campo("nombre_comercial", "Nombre comercial", "f-half") +
      campo("rfc", 'RFC <span class="req">*</span>', "f-half", "mono", "12 o 13 caracteres") +
      '<div class="field f-full"><label for="n_regimen">Régimen fiscal (catálogo del SAT) <span class="req">*</span></label>' +
      '<select id="n_regimen" data-nueva="regimen">' +
      CAT.regimenes.map(function (r) {
        return '<option value="' + r.c + '" ' + (n.regimen === r.c ? "selected" : "") + ">" + r.c + " — " + esc(r.n) + "</option>";
      }).join("") + "</select>" +
      '<span class="dim" id="persona-hint">' + textoPersona(n) + "</span></div>" +
      selec("sucursal", "Sucursal que atiende", "f-third", CAT.cat.sucursal) +
      selec("giro", "Giro principal", "f-third", CAT.cat.giro) +
      selec("clasificacion", "Clasificación", "f-third", CAT.cat.clasificacion) +
      campo("contacto", "Persona de contacto", "f-third") +
      campo("correo", 'Correo del contacto <span class="req">*</span>', "f-half") +
      campo("celular", 'Celular del contacto <span class="req">*</span>', "f-half", "mono",
            "10 dígitos, p. ej. 33 1204 8871") + "</div>" +
      '<div id="conflicto-rfc">' +
      (conflicto ? '<div class="banner banner-warn"><span><b>Revise el régimen o el RFC.</b> ' + esc(conflicto) + "</span></div>" : "") +
      "</div></div>" +
      '<div class="card pad stack"><div class="spread"><div class="eyebrow">3 · Qué se le pide</div>' +
      '<span class="dim" id="conteo-docs">' + nDocs + " documento" + (nDocs === 1 ? "" : "s") + "</span></div>" +
      '<p class="dim" style="margin:0">Esto no se elige: cada tipo de solicitud trae sus secciones ' +
      "y sus documentos completos.</p>" +
      '<div class="stack" style="gap:8px">' + listaModulos(T) + "</div><hr class=\"sep\">" +
      '<div class="eyebrow">Documentos</div><div id="lista-docs">' + listaDocumentos(T, persona) + "</div>" +
      '<p class="dim" style="margin:0">Los de persona moral se descuentan solos según el régimen fiscal.</p></div>' +
    "</div>" +
    '<div class="card pad stack"><div class="eyebrow">4 · Envío al cliente</div>' + panel + "</div></div></div>";
}

function bloqueFirmas(c) {
  var T = tipoDe(c);
  var listo = c.estado === "por_autorizar";
  var puedo = api.sesion && (api.sesion.rol === "Comité de Crédito" || api.sesion.rol === "Administrador");
  var firmadas = c.autorizaciones || [];

  function slot(nivel, indice, titulo) {
    var deNivel = firmadas.filter(function (a) { return a.nivel === nivel; });
    var f = deNivel[indice];
    if (f) {
      return '<div class="firma lista"><div class="n">✓</div><div class="firma-body">' +
        '<div class="firma-t">' + esc(titulo) + "</div>" +
        '<div class="firma-d">' + esc(f.nombre || f.usuarioId) + " · " + esc(f.rol || "") + " · " + esc(f.fecha) + "</div>" +
        "</div></div>";
    }
    var faltaN1 = nivel === 2 && firmadas.filter(function (a) { return a.nivel === 1; }).length < 1;
    var yaFirmaron = firmadas.map(function (a) { return a.usuarioId; });
    var opciones = (nivel === 1 ? S.firmantes.nivel1 : S.firmantes.nivel2)
      .filter(function (u) { return yaFirmaron.indexOf(u.correo) === -1; });
    var clave = "n" + nivel + "_" + indice;
    var sel = S.firmaSel[clave] || (opciones[0] ? opciones[0].correo : "");
    var motivo = !listo ? "Falta que el expediente pase a autorización"
      : faltaN1 ? "Espera la firma de nivel 1"
      : !opciones.length ? "No hay usuarios habilitados disponibles"
      : !puedo ? "Su rol (" + (api.sesion ? api.sesion.rol : "") + ") no autoriza" : "";
    return '<div class="firma"><div class="n">' + (indice + 1) + "</div>" +
      '<div class="firma-body"><div class="firma-t">' + esc(titulo) + "</div>" +
      '<div class="firma-d">' + (motivo ? esc(motivo) : "Elija quién firma") + "</div></div>" +
      (motivo ? "" :
        '<select data-firmasel="' + clave + '">' +
        opciones.map(function (u) {
          return '<option value="' + esc(u.correo) + '" ' + (sel === u.correo ? "selected" : "") + ">" + esc(u.nombre) + "</option>";
        }).join("") + "</select>" +
        '<button class="btn btn-sm btn-primary" data-firmar="' + nivel + '" data-slot="' + indice + '">Firmar</button>') +
      "</div>";
  }

  var slots = T.autoriza === "simple"
    ? slot(1, 0, "Autorización del Comité de Crédito")
    : slot(1, 0, "Nivel 1 — una firma") + slot(2, 0, "Nivel 2 — primera de dos") + slot(2, 1, "Nivel 2 — segunda de dos");

  var cierre = "";
  if (c.estado === "autorizada") cierre = '<div class="banner banner-ok"><span><b>Expediente autorizado.</b> Ya puede darse de alta en SAP.</span></div>';
  else if (c.estado === "rechazada") cierre = '<div class="banner banner-stop"><span><b>Rechazado.</b> ' + esc(c.rechazo || "") + "</span></div>";

  return '<div class="card pad stack"><div class="spread"><div class="eyebrow">Autorización</div>' +
    '<span class="dim">' + (T.autoriza === "simple" ? "1 firma" : "3 firmas: 1 de nivel 1 y 2 de nivel 2") + "</span></div>" +
    cierre + '<div class="stack" style="gap:8px">' + slots + "</div>" +
    (listo && puedo ? '<div class="row"><button class="btn btn-stop btn-sm" id="btn-rechazar">Rechazar expediente</button></div>' : "") +
    "</div>";
}

function vistaExpediente() {
  var c = S.caso;
  if (!c) return '<div class="wrap">' + bannerError() + '<p class="dim">Cargando expediente…</p></div>';
  var T = tipoDe(c);
  var aplic = docsAplicables(c);
  var rol = api.sesion ? api.sesion.rol : "";
  var revisor = rol === "Administrador" || rol === "Ventas" || rol === "Comité de Crédito";
  var marcas = c.marcas || {};
  var señalados = Object.keys(marcas).filter(function (k) { return marcas[k] && marcas[k].motivo; });
  var recibidos = aplic.filter(function (d) { return (c.adjuntos || {})[d.id]; }).length;

  var docs = aplic.map(function (d) {
    var adj = (c.adjuntos || {})[d.id];
    var m = marcas[d.id];
    return '<div class="doc ' + (m && m.motivo ? "flag" : adj ? "attached" : "") + '">' +
      '<div class="doc-ic">' + esc(d.t) + "</div>" +
      '<div class="doc-body"><div class="doc-name">' + esc(d.n) + "</div>" +
      '<div class="doc-meta">' +
      (adj ? '<span class="mono">' + esc(adj.nombre) + "</span>" +
             (adj.url ? ' <a href="' + esc(adj.url) + '" target="_blank" rel="noopener">ver documento</a>' : "")
           : '<span style="color:var(--warn)">Sin adjuntar</span>') +
      (m && m.ok ? '<span style="color:var(--ok)">revisado</span>' : "") + "</div>" +
      (m && m.motivo ? '<div class="doc-motivo">Señalado: ' + esc(m.motivo) + "</div>" : "") + "</div>" +
      (adj && revisor && c.estado !== "autorizada" && c.estado !== "rechazada"
        ? '<div class="doc-acts">' +
          '<button class="btn btn-sm btn-ok" data-ok="' + d.id + '" aria-pressed="' + (m && m.ok ? "true" : "false") + '">Correcto</button>' +
          '<button class="btn btn-sm btn-stop" data-señalar="' + d.id + '" aria-pressed="' + (m && m.motivo ? "true" : "false") + '">Señalar</button></div>'
        : "") + "</div>";
  }).join("");

  var problemas = c.problemas || {};
  var puedeSenalar = revisor && c.estado !== "autorizada" && c.estado !== "rechazada";
  var datos = modulosActivos(c).map(function (m) {
    var campos = camposDe(m);
    return '<div class="stack" style="gap:6px"><div class="eyebrow">' + esc(m.nombre) + "</div><div>" +
      campos.map(function (f) {
        var v = (c.valores || {})[f.k];
        var texto = f.tipo === "check" ? (v === true ? "Sí" : "No") : v;
        var marcado = marcas["campo:" + f.k];
        var falta = problemas[f.k];
        return '<div class="campo-rev ' + (marcado ? "flag" : "") + '">' +
          '<div class="kv" style="border:0; padding:2px 0">' +
          "<span>" + esc(limpia(f.l)) + "</span>" +
          '<span class="row" style="gap:8px; justify-content:flex-end">' +
          "<span" + (f.mono ? ' class="mono" style="font-size:13px"' : "") + ">" +
          (texto ? esc(texto) : '<span class="dim">—</span>') + "</span>" +
          (puedeSenalar
            ? '<button class="btn btn-sm btn-stop senal" data-senalar-campo="' + f.k +
              '" title="Señalar este dato" aria-pressed="' + (marcado ? "true" : "false") + '">!</button>'
            : "") +
          "</span></div>" +
          (falta ? '<div class="doc-motivo" style="color:var(--warn)">' + esc(falta) + "</div>" : "") +
          (marcado ? '<div class="doc-motivo">Señalado: ' + esc(marcado.motivo) + "</div>" : "") +
          "</div>";
      }).join("") + "</div></div>";
  }).join("");

  var incompletos = Object.keys(problemas).length;

  var r = regimen(c.regimen);
  var av = c.avance || { pct: 0, hechos: 0, total: 0 };
  var pendientes = c.pendientesAutorizar || [];

  return '<div class="stack">' +
    '<div class="row"><button class="btn btn-sm" data-ir="bandeja">← Volver a la bandeja</button></div>' +
    bannerError() +
    '<div class="card pad stack"><div class="spread"><div>' +
      '<div class="row" style="gap:8px"><span class="mono dim" style="font-size:13px">' + esc(c.folio) + "</span>" +
      etiquetaTipo(c.tipo) + pill(c.estado) + "</div>" +
      '<h1 style="font-size:21px; margin-top:4px">' + esc(c.razonSocial) + "</h1>" +
      '<p class="dim" style="margin:2px 0 0"><span class="mono">' + esc(c.rfc) + "</span> · " +
      (r ? esc(r.c + " " + r.n) : "") + " · persona " + esc(String(c.persona || "").toLowerCase()) +
      " · " + esc(c.sucursal || "") + "</p></div>" +
      '<div style="text-align:right"><div style="font-size:26px; font-weight:700">' +
      av.pct + '%</div><div class="dim">' + av.hechos + " de " + av.total + " puntos</div></div></div>" +
      '<div class="progress"><i style="width:' + av.pct + '%"></i></div>' +
      (c.conflictoRfc ? '<div class="banner banner-warn"><span><b>Revise el régimen o el RFC.</b> ' + esc(c.conflictoRfc) + "</span></div>" : "") +
    "</div>" +
    '<div class="cols"><div class="stack">' +
      '<div class="card pad stack"><div class="spread"><div class="eyebrow">Documentos del expediente</div>' +
      '<span class="dim">' + recibidos + " de " + aplic.length + " recibidos</span></div>" +
      '<div class="doclist">' + (docs || '<p class="dim">En esta liga no se pidió ningún documento.</p>') + "</div>" +
      '<hr class="sep">' +
      (señalados.length ? '<div class="banner banner-stop"><span><b>' + señalados.length + " señalado" +
        (señalados.length > 1 ? "s" : "") + ".</b> Al devolver, el cliente entra con su misma liga y clave " +
        "y solo ve lo señalado.</span></div>" : "") +
      (!revisor ? '<div class="banner banner-warn"><span>Su rol (' + esc(rol) + ") solo permite consultar.</span></div>" : "") +
      (pendientes.length && c.estado === "recibida"
        ? '<div class="banner banner-info"><span><b>Para pasar a autorización falta:</b> ' +
          esc(pendientes.slice(0, 4).join("; ")) + (pendientes.length > 4 ? " y " + (pendientes.length - 4) + " más" : "") + "</span></div>"
        : "") +
      '<div class="row">' +
      '<button class="btn btn-primary" id="btn-devolver"' + (señalados.length && revisor ? "" : " disabled") + ">Devolver al cliente</button>" +
      '<button class="btn" id="btn-a-autorizacion"' + (!pendientes.length && c.estado === "recibida" && revisor ? "" : " disabled") + ">Pasar a autorización</button>" +
      '<button class="btn" id="btn-clave-nueva">Generar clave nueva</button>' +
      "</div>" +
      (S.ligaNueva && S.ligaNueva.folio === c.folio
        ? '<div class="banner banner-ok"><span><b>Clave nueva:</b> <span class="mono">' + esc(S.ligaNueva.clave) +
          "</span> — dígtela al cliente ahora, no se vuelve a mostrar.</span></div>" : "") +
      "</div>" + bloqueFirmas(c) + "</div>" +
      '<div class="card pad stack"><div class="spread"><div class="eyebrow">Lo que capturó el cliente</div>' +
      (incompletos
        ? '<span class="dim" style="color:var(--warn)">' + incompletos + " incompleto" + (incompletos > 1 ? "s" : "") + "</span>"
        : '<span class="dim">completo</span>') + "</div>" +
      (puedeSenalar ? '<p class="dim" style="margin:0">El botón <b>!</b> de cada dato lo señala como ' +
        "incorrecto o incompleto; al devolver, el cliente solo verá lo señalado.</p>" : "") +
      datos + "</div>" +
    "</div></div>";
}

function vistaUsuarios() {
  var filas = S.usuarios.map(function (u) {
    return "<tr>" +
      '<td><div style="font-weight:600">' + esc(u.nombre) + "</div>" +
      '<div class="dim" style="font-size:12.5px">' + esc(u.correo) + "</div></td>" +
      '<td><select data-urol="' + esc(u.correo) + '">' +
      CAT.roles.map(function (r) { return "<option " + (u.rol === r ? "selected" : "") + ">" + esc(r) + "</option>"; }).join("") +
      "</select></td>" +
      '<td><label class="switch"><input type="checkbox" data-un1="' + esc(u.correo) + '" ' + (u.n1 ? "checked" : "") + "> Nivel 1</label></td>" +
      '<td><label class="switch"><input type="checkbox" data-un2="' + esc(u.correo) + '" ' + (u.n2 ? "checked" : "") + "> Nivel 2</label></td>" +
      '<td><label class="switch"><input type="checkbox" data-uact="' + esc(u.correo) + '" ' + (u.activo ? "checked" : "") + "> Activo</label></td>" +
      '<td><span class="dim">' + esc(u.estatus === "FORCE_CHANGE_PASSWORD" ? "no ha entrado" : "") + "</span></td></tr>";
  }).join("");

  var problemas = (S.firmas && S.firmas.problemas) || [];
  return '<div class="stack">' + bannerError() +
    '<div><h1 style="font-size:22px">Usuarios</h1>' +
    '<p class="dim" style="margin:3px 0 0">Quién entra, con qué rol y quién puede firmar cada nivel.</p></div>' +
    problemas.map(function (p) { return '<div class="banner banner-stop"><span>' + esc(p) + "</span></div>"; }).join("") +
    '<div class="card pad"><div class="tablewrap"><table class="grid-t">' +
    "<thead><tr><th>Usuario</th><th>Rol</th><th>Firma nivel 1</th><th>Firma nivel 2</th><th>Estado</th><th></th></tr></thead>" +
    "<tbody>" + filas + "</tbody></table></div></div>" +
    '<div class="card pad stack"><div class="eyebrow">Agregar usuario</div>' +
    '<div class="grid">' +
      '<div class="field f-half"><label for="u_nombre">Nombre</label><input id="u_nombre"></div>' +
      '<div class="field f-half"><label for="u_correo">Correo</label><input id="u_correo" type="email" placeholder="nombre@gpa.com.mx"></div>' +
      '<div class="field f-third"><label for="u_rol">Rol</label><select id="u_rol">' +
      CAT.roles.map(function (r) { return "<option>" + esc(r) + "</option>"; }).join("") + "</select></div>" +
      '<div class="field f-third"><label for="u_pw">Contraseña temporal</label><input id="u_pw" placeholder="La cambiará al entrar"></div>' +
    "</div>" +
    '<div class="row"><label class="switch"><input type="checkbox" id="u_n1"> Firma nivel 1</label>' +
    '<label class="switch"><input type="checkbox" id="u_n2"> Firma nivel 2</label></div>' +
    '<button class="btn btn-primary" id="btn-nuevo-usuario">Crear cuenta</button>' +
    '<p class="dim" style="margin:0">El correo de bienvenida todavía no está configurado: ' +
    "entregue usted la contraseña temporal. Al entrar, la persona elige la suya.</p></div></div>";
}

// ═══════════════════════════════════════════════════════════════
// Render
// ═══════════════════════════════════════════════════════════════
function render() {
  var top = $("#topbar"), foot = $("#foot");

  if (S.modo === "portal") {
    top.hidden = true; foot.hidden = true;
    $("#app").innerHTML = vistaPortal();
    return;
  }
  if (!api.autenticado) {
    top.hidden = true; foot.hidden = true;
    $("#app").innerHTML = vistaLogin();
    return;
  }

  top.hidden = false; foot.hidden = false;
  var rol = api.sesion.rol;
  $("#subnav").innerHTML =
    '<button data-ir="bandeja" aria-current="' + (S.vista === "bandeja" || S.vista === "expediente") + '">Bandeja</button>' +
    '<button data-ir="nueva" aria-current="' + (S.vista === "nueva") + '"' +
      (rol === "Consulta" ? " disabled" : "") + ">Nueva pre-solicitud</button>" +
    '<button data-ir="usuarios" aria-current="' + (S.vista === "usuarios") + '"' +
      (rol !== "Administrador" ? " disabled" : "") + ">Usuarios</button>";
  $("#sesion-box").innerHTML =
    '<span class="dim">' + esc(api.sesion.nombre) + " · " + esc(rol) + "</span>" +
    '<button class="btn btn-sm" id="btn-salir">Salir</button>';

  var cuerpo =
    S.vista === "nueva" ? vistaNueva() :
    S.vista === "usuarios" ? vistaUsuarios() :
    S.vista === "expediente" ? vistaExpediente() : vistaBandeja();
  $("#app").innerHTML = '<div class="wrap">' + cuerpo + "</div>";
}

// ═══════════════════════════════════════════════════════════════
// Acciones
// ═══════════════════════════════════════════════════════════════
function nuevaVacia(tipo) {
  // Sin módulos ni documentos: los fija el servidor según el tipo de solicitud.
  var T = CAT.tipos[tipo || "alta"];
  return { tipo: T.id, razon_social: "", nombre_comercial: "", rfc: "", regimen: "601",
           contacto: "", correo: "", celular: "", sucursal: CAT.cat.sucursal[0],
           giro: CAT.cat.giro[0], clasificacion: CAT.cat.clasificacion[0] };
}

var irA = conError(function (vista, folio) {
  S.vista = vista;
  S.error = "";
  if (vista === "bandeja") {
    return api.bandeja().then(function (r) { S.bandeja = r.casos || []; });
  }
  if (vista === "nueva") { S.nueva = S.nueva || nuevaVacia(); S.ligaNueva = null; return; }
  if (vista === "usuarios") {
    return api.usuarios().then(function (r) { S.usuarios = r.usuarios || []; S.firmas = r.firmas; });
  }
  if (vista === "expediente") {
    S.folio = folio;
    return Promise.all([api.caso(folio), api.firmantes()]).then(function (res) {
      S.caso = res[0];
      S.firmantes = res[1];
    });
  }
});

function recargaCaso() {
  return api.caso(S.folio).then(function (c) { S.caso = c; });
}

function copiar(texto, aviso) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(texto).then(function () { toast(aviso); })
      .catch(function () { toast("No se pudo copiar. Selecciónelo con el dedo o el ratón."); });
  } else {
    toast("No se pudo copiar. Selecciónelo con el dedo o el ratón.");
  }
}

var guardaPortal = conError(function (siguiente) {
  // Se lee la pantalla ANTES de nada: conError redibuja, y sin esto se mandaba vacio.
  var c = S.casoCliente || {};
  return portal.guardar(c.valores || {}, c.tablasVal || {}).then(function (r) {
    // La respuesta del servidor manda, pero se conserva lo tecleado que aun no viaja.
    S.casoCliente = r;
    S.aviso = r.aviso || "";
    if (siguiente) S.pasoCliente = siguiente;
  });
});

// ── Clics ────────────────────────────────────────────────────────
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("button, tr[data-folio], a");
  if (!t || t.tagName === "A") return;
  var d = t.dataset || {};

  // ── portal ──
  if (t.id === "btn-entrar-portal") {
    var clave = ($("#clave").value || "").trim();
    S.errorClave = "";
    conError(function () {
      return portal.entrar(clave).then(function (c) {
        S.casoCliente = c;
        S.pasoCliente = c.estado === "recibida" ? "enviado" : "captura";
      });
    })();
    return;
  }
  if (t.id === "btn-guardar-portal") { sincronizaDesdeDOM(); guardaPortal("guardado"); return; }
  if (t.id === "btn-a-revisar") { sincronizaDesdeDOM(); S.mostrarFaltantes = true; guardaPortal("revisar"); return; }
  if (t.id === "btn-seguir-llenando") { S.pasoCliente = "captura"; render(); return; }
  if (t.id === "btn-volver-captura") { S.pasoCliente = "captura"; render(); return; }
  if (t.id === "btn-enviar-portal") {
    conError(function () {
      return portal.enviar().then(function (c) { S.casoCliente = c; S.pasoCliente = "enviado"; });
    })();
    return;
  }

  // ── login ──
  if (t.id === "btn-login") {
    var correo = ($("#correo").value || "").trim().toLowerCase();
    var pw = $("#pw").value || "";
    conError(function () {
      return api.entrar(correo, pw).then(function (r) {
        if (r.estado === "nueva-contrasena") { S.retoCognito = r; return; }
        return irA("bandeja");
      });
    })();
    return;
  }
  if (t.id === "btn-fijar-pw") {
    var p1 = $("#pw1").value || "", p2 = $("#pw2").value || "";
    if (p1 !== p2) { S.error = "Las dos contraseñas no son iguales."; render(); return; }
    conError(function () {
      return api.fijarContrasena(S.retoCognito.correo, S.retoCognito.sesionCognito, p1)
        .then(function () { S.retoCognito = null; return irA("bandeja"); });
    })();
    return;
  }
  if (t.id === "btn-salir") { api.salir(); S.vista = "bandeja"; render(); return; }

  // ── navegación ──
  if (d.ir) { irA(d.ir); return; }
  if (d.abrir) { irA("expediente", d.abrir); return; }
  if (t.matches("tr[data-folio]")) { irA("expediente", d.folio); return; }
  if (d.tipo) {
    // Cambiar de tipo NO debe borrar lo que ya se capturó del cliente.
    var previo = S.nueva || {};
    S.nueva = nuevaVacia(d.tipo);
    ["razon_social", "nombre_comercial", "rfc", "regimen", "contacto", "correo",
     "celular", "sucursal", "giro", "clasificacion"].forEach(function (k) {
      if (previo[k]) S.nueva[k] = previo[k];
    });
    S.ligaNueva = null;
    render();
    return;
  }
  if (d.borrador) { S.borrador = S.borrador === d.borrador ? "" : d.borrador; render(); return; }
  if (d.copiar) {
    copiar(d.copiar === "liga" ? S.ligaNueva.liga : S.ligaNueva.clave,
           d.copiar === "liga" ? "Liga copiada" : "Clave copiada");
    return;
  }

  // ── pre-solicitud ──
  if (t.id === "btn-generar") {
    var n = S.nueva;
    conError(function () {
      return api.crear({
        tipo: n.tipo, razonSocial: n.razon_social, nombreComercial: n.nombre_comercial,
        rfc: n.rfc, regimen: n.regimen, contacto: n.contacto, correo: n.correo,
        celular: n.celular, sucursal: n.sucursal, giro: n.giro, clasificacion: n.clasificacion,
        // No se mandan módulos ni documentos: los fija el servidor según el tipo.
      }).then(function (r) {
        var base = (window.GPA_CONFIG && window.GPA_CONFIG.portalUrl) || (location.origin + location.pathname.replace(/[^/]*$/, ""));
        var liga = base.replace(/\/$/, "") + "/?t=" + r.caso.token;
        var T = CAT.tipos[r.caso.tipo];
        S.ligaNueva = {
          folio: r.caso.folio, liga: liga, clave: r.clave,
          correo: "Para: " + r.caso.correo + "\nAsunto: " + T.nombre + " GPA — " + r.caso.razonSocial +
            "\n\nBuen día " + (r.caso.contacto || "") + ":\n\nPara completar su " + T.nombre.toLowerCase() +
            " con General de Productos para el Agua, entre en esta liga:\n\n" + liga +
            "\n\nLe llamaremos por separado para darle su clave de acceso. No necesita crear cuenta ni " +
            "contraseña, y puede entrar las veces que necesite.\n\nQuedo pendiente,\n" + api.sesion.nombre + " — GPA",
          mensaje: "Sr(a). " + (r.caso.contacto || "") + ", su clave de acceso para el portal de GPA es:\n\n" +
            r.clave + "\n\nNo la comparta. Sirve para entrar las veces que necesite.",
        };
        S.nueva = nuevaVacia(n.tipo);
      });
    })();
    return;
  }

  // ── expediente ──
  if (d.ok) { conError(function () { return api.marcarDoc(S.folio, d.ok, true, "").then(recargaCaso); })(); return; }
  if (d["señalar"]) {
    var motivo = window.prompt("¿Qué tiene mal este documento? El cliente verá este texto tal cual.", "");
    if (!motivo || !motivo.trim()) return;
    conError(function () { return api.marcarDoc(S.folio, d["señalar"], false, motivo.trim()).then(recargaCaso); })();
    return;
  }
  if (d.senalarCampo) {
    var previo = (S.caso.marcas || {})["campo:" + d.senalarCampo] || {};
    var sugerido = (S.caso.problemas || {})[d.senalarCampo] || "";
    var motivoCampo = window.prompt(
      "¿Qué tiene mal este dato? El cliente verá este texto tal cual.",
      previo.motivo || sugerido);
    if (!motivoCampo || !motivoCampo.trim()) return;
    conError(function () {
      return api["señalarCampo"](S.folio, d.senalarCampo, motivoCampo.trim()).then(recargaCaso);
    })();
    return;
  }
  if (t.id === "btn-devolver") { conError(function () { return api.devolver(S.folio).then(recargaCaso); })(); return; }
  if (t.id === "btn-a-autorizacion") { conError(function () { return api.aAutorizacion(S.folio).then(recargaCaso); })(); return; }
  if (t.id === "btn-clave-nueva") {
    conError(function () {
      return api.claveNueva(S.folio).then(function (r) {
        S.ligaNueva = { folio: S.folio, clave: r.clave, liga: "" };
      });
    })();
    return;
  }
  if (d.firmar) {
    var nivel = Number(d.firmar), slot = Number(d.slot);
    var sel = S.firmaSel["n" + nivel + "_" + slot];
    if (!sel) {
      var caja = document.querySelector('[data-firmasel="n' + nivel + "_" + slot + '"]');
      sel = caja ? caja.value : "";
    }
    conError(function () { return api.firmar(S.folio, nivel, sel).then(recargaCaso); })();
    return;
  }
  if (t.id === "btn-rechazar") {
    var mot = window.prompt("¿Por qué se rechaza este expediente?", "");
    if (!mot || !mot.trim()) return;
    conError(function () { return api.rechazar(S.folio, mot.trim()).then(recargaCaso); })();
    return;
  }

  // ── usuarios ──
  if (t.id === "btn-nuevo-usuario") {
    var datos = {
      nombre: $("#u_nombre").value, correo: ($("#u_correo").value || "").trim().toLowerCase(),
      rol: $("#u_rol").value, password: $("#u_pw").value,
      n1: $("#u_n1").checked, n2: $("#u_n2").checked, activo: true,
    };
    conError(function () {
      return api.guardarUsuario(datos).then(function () { return irA("usuarios"); })
        .then(function () { toast("Cuenta creada. Entréguele la contraseña temporal."); });
    })();
    return;
  }
});

// ── Cambios en formularios ───────────────────────────────────────
document.addEventListener("input", function (ev) {
  var el = ev.target, d = el.dataset || {};

  // Lo que se escribe entra al estado de inmediato. Antes solo vivia en el HTML,
  // asi que cualquier redibujado (guardar, adjuntar) lo borraba.
  if (d.campo || d.tabla) {
    var c = S.casoCliente;
    if (!c) return;
    if (d.campo) {
      c.valores = c.valores || {};
      c.valores[d.campo] = el.type === "checkbox" ? el.checked : el.value;
    } else {
      c.tablasVal = c.tablasVal || {};
      c.tablasVal[d.tabla] = el.value;
    }
    refrescaAvanceCliente();
    return;
  }

  if (d.nueva) {
    S.nueva[d.nueva] = el.value;
    // Aquí NO se llama a render(). Redibujar el formulario destruye el campo que
    // se está escribiendo y le quita el foco: obligaba a hacer clic tras cada letra.
    actualizaPorRfc();
  }
});

/** Mueve la barra y reevalua el boton de enviar sin redibujar el formulario. */
function refrescaAvanceCliente() {
  var c = S.casoCliente;
  if (!c) return;
  var av = avanceLocal(c);
  var barra = document.querySelector(".progress i");
  if (barra) barra.style.width = av.pct + "%";
  var pct = $("#pct");
  if (pct) pct.textContent = av.pct + "%";
}

document.addEventListener("change", function (ev) {
  var el = ev.target, d = el.dataset || {};

  // "El domicilio de entrega es el mismo que el fiscal": se copia solo.
  if (d.campo === "mismo_dom") {
    var c = S.casoCliente;
    if (c) {
      c.valores = c.valores || {};
      c.valores.mismo_dom = el.checked;
      if (el.checked) {
        var copia = { e_calle: "calle", e_colonia: "colonia", e_municipio: "municipio",
                      e_cp: "cp", e_ciudad: "ciudad", e_estado: "estado_dom" };
        Object.keys(copia).forEach(function (destino) {
          c.valores[destino] = c.valores[copia[destino]] || "";
        });
        toast("Copiamos su domicilio fiscal. Puede ajustarlo si hace falta.");
      }
      render();
    }
    return;
  }
  if (d.campo) {
    var cc = S.casoCliente;
    if (cc) {
      cc.valores = cc.valores || {};
      cc.valores[d.campo] = el.type === "checkbox" ? el.checked : el.value;
      refrescaAvanceCliente();
    }
    return;
  }
  if (d.nueva === "regimen") { S.nueva.regimen = el.value; actualizaPorRfc(); return; }
  if (d.firmasel) { S.firmaSel[d.firmasel] = el.value; return; }
  if (el.id === "privacidad") { var b = $("#btn-enviar-portal"); if (b) b.disabled = !el.checked; return; }

  if (d.subir) { subeArchivo(d.subir, el.files && el.files[0]); return; }

  // panel de usuarios: cada cambio se guarda de inmediato
  var correo = d.urol || d.un1 || d.un2 || d.uact;
  if (correo) {
    var u = S.usuarios.filter(function (x) { return x.correo === correo; })[0];
    if (!u) return;
    var datos = { correo: u.correo, nombre: u.nombre, rol: u.rol, n1: u.n1, n2: u.n2, activo: u.activo };
    if (d.urol) datos.rol = el.value;
    if (d.un1) datos.n1 = el.checked;
    if (d.un2) datos.n2 = el.checked;
    if (d.uact) datos.activo = el.checked;
    conError(function () {
      return api.guardarUsuario(datos).then(function () { return irA("usuarios"); });
    })();
  }
});

var subeArchivo = function (docId, archivo) {
  if (!archivo) return;
  // Se guarda antes de subir: la respuesta redibuja y se perderia lo capturado.
  sincronizaDesdeDOM();
  var capturado = JSON.parse(JSON.stringify({ v: S.casoCliente.valores || {},
                                              t: S.casoCliente.tablasVal || {} }));
  var barra = document.querySelector('[data-barra="' + docId + '"]');
  if (barra) { barra.hidden = false; barra.firstElementChild.style.width = "10%"; }
  S.error = "";
  portal.subir(docId, archivo, function (pct) {
    if (barra) barra.firstElementChild.style.width = pct + "%";
  }).then(function (c) {
    // El servidor aun no conoce lo que se acaba de teclear: se repone encima.
    c.valores = Object.assign({}, c.valores, capturado.v);
    c.tablasVal = Object.assign({}, c.tablasVal, capturado.t);
    S.casoCliente = c;
    render();
    toast("Documento recibido.");
  }).catch(function (e) {
    S.error = e.message || String(e);
    render();
  });
};

document.addEventListener("keydown", function (ev) {
  if (ev.key !== "Enter") return;
  if (ev.target.id === "clave") { ev.preventDefault(); $("#btn-entrar-portal").click(); }
  if (ev.target.id === "pw") { ev.preventDefault(); $("#btn-login").click(); }
});

// ═══════════════════════════════════════════════════════════════
// Arranque
// ═══════════════════════════════════════════════════════════════
function tokenDeUrl() {
  var q = new URLSearchParams(location.search).get("t");
  if (q) return q;
  var m = location.pathname.match(/\/alta\/([a-z0-9-]{8,})$/i);
  return m ? m[1] : "";
}

(function arranca() {
  if (!window.GPA_CONFIG || !window.GPA_CONFIG.apiUrl) {
    $("#app").innerHTML = '<div class="wrap"><div class="banner banner-stop" style="margin-top:40px">' +
      "<span><b>Falta la configuración.</b> No existe <span class=\"mono\">config.js</span> o no trae la " +
      "dirección de la API. En Amplify se genera solo; en local, copie " +
      "<span class=\"mono\">config.example.js</span> a <span class=\"mono\">config.js</span>.</span></div></div>";
    return;
  }
  var token = tokenDeUrl();
  cargarCatalogos().then(function (cat) {
    CAT = cat;
    if (token) {
      S.modo = "portal";
      portal = new PortalApi(token);
      if (portal.clave) {
        // La pestaña recuerda la clave: se entra solo, sin volver a teclearla.
        return portal.entrar(portal.clave).then(function (c) {
          S.casoCliente = c;
          S.pasoCliente = c.estado === "recibida" ? "enviado" : "captura";
        }).catch(function () { portal.olvida(); });
      }
      return;
    }
    if (api.autenticado) return irA("bandeja");
  }).catch(function (e) {
    S.error = e.message || String(e);
  }).then(render);
})();
