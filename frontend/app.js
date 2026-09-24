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
  tipoBandeja: "alta",        // qué pestaña de la bandeja se está viendo
  nueva: null,
  ligaNueva: null,          // { liga, clave, folio } — la clave se ve una sola vez
  borrador: "",
  firmando: null,        // {nivel, slot} mientras se escribe el motivo
  analisis: { comentarios: [], anexos: [] },
  veto: [],
  vetoHits: null,        // resultado de revisar al prospecto contra la lista
  vetoTimer: null,
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
    "Puede salir y volver con esta misma liga y clave." +
    (c && c.venceLegible ? " Esta invitación vence el <b>" + esc(c.venceLegible) + "</b>." : "") +
    "</p></div>";
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
      (c.montoRequerido
        ? '<div class="fila"><span>Monto de crédito requerido</span>' +
          '<span class="mono">' + esc(c.montoRequerido) + "</span></div>"
        : "") +
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

function grupoDoc(id) {
  return (CAT.gruposDoc || {})[id] || { n: "Documentos", c: "#185FA5", d: "" };
}

/** Parte los documentos por a quién pertenecen, en el orden del catálogo. */
function docsPorGrupo(lista) {
  var orden = CAT.ordenGrupos || ["empresa", "representante", "aval"];
  var out = [];
  orden.forEach(function (g) {
    var dd = lista.filter(function (d) { return (d.de || "empresa") === g; });
    if (dd.length) out.push({ grupo: g, docs: dd });
  });
  return out;
}

/** Un renglón de documento en la vista del cliente. */
function docRenglonCliente(d, c) {
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
}

/** Documentos agrupados por dueño, cada grupo con su nombre y su color.
 *  El nombre va escrito: el color solo refuerza, nunca es la única señal. */
function seccionDocumentos(c, visibles) {
  return docsPorGrupo(visibles).map(function (bloque) {
    var g = grupoDoc(bloque.grupo);
    return '<div class="grupo-doc" style="--g:' + g.c + '">' +
      '<div class="grupo-cab"><div><div class="grupo-n">' + esc(g.n) + "</div>" +
      (g.d ? '<div class="grupo-d">' + esc(g.d) + "</div>" : "") + "</div>" +
      '<span class="grupo-cuenta">' + bloque.docs.length + "</span></div>" +
      '<div class="doclist">' +
      bloque.docs.map(function (d) { return docRenglonCliente(d, c); }).join("") +
      "</div></div>";
  }).join("");
}

/** Documentos adicionales: lo que el cliente crea útil y no esté en la lista. */
function seccionOtros(c) {
  var otros = c.otros || [];
  var lista = otros.map(function (o) {
    return '<div class="doc attached">' +
      '<div class="doc-ic">+</div>' +
      '<div class="doc-body"><div class="doc-name">' + esc(o.descripcion || "Documento adicional") + "</div>" +
      '<div class="doc-meta"><span class="mono">' + esc(o.nombre) + "</span>" +
      (o.url ? ' <a href="' + esc(o.url) + '" target="_blank" rel="noopener">ver</a>' : "") + "</div></div>" +
      '<button class="btn btn-sm btn-stop" data-quitar="' + esc(o.id) + '">Quitar</button></div>';
  }).join("");

  return '<div class="grupo-doc" style="--g:#7A8A9A">' +
    '<div class="grupo-cab"><div><div class="grupo-n">Otros documentos</div>' +
    '<div class="grupo-d">Opcional. Si tiene algo más que crea útil, súbalo aquí.</div></div>' +
    '<span class="grupo-cuenta">' + otros.length + "</span></div>" +
    (lista ? '<div class="doclist">' + lista + "</div>" : "") +
    '<div class="grid" style="margin-top:8px">' +
    '<div class="field f-full"><label for="otro-desc">¿De qué se trata?</label>' +
    '<input id="otro-desc" placeholder="Ej. Carta de recomendación de mi banco"></div>' +
    '<div class="f-full row"><label class="btn btn-sm subir">Elegir archivo y subir' +
    '<input type="file" data-subir="otro" accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,image/*,application/pdf" hidden></label>' +
    '<span class="dim">Hasta 10 archivos, 15 MB cada uno.</span></div>' +
    "</div></div>";
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

  var docs = seccionDocumentos(c, visibles);

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
    (docs || '<p class="dim">No hay documentos por adjuntar.</p>') +
    (devuelta ? "" : seccionOtros(c)) + "</div>" +
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
  // Altas y créditos son dos bandejas, no una. Son solicitudes distintas, con
  // documentos y autorización distintos, y quien revisa altas rara vez es quien
  // autoriza créditos. Mezcladas, el atraso de una se escondía detrás de la otra.
  var tipo = S.tipoBandeja === "credito" ? "credito" : "alta";
  function delTipo(t) { return S.bandeja.filter(function (x) { return x.tipo === t; }); }
  function vivos(lista) {
    return lista.filter(function (x) { return x.estado !== "autorizada" && x.estado !== "rechazada"; });
  }

  var lista = delTipo(tipo);
  var filas = lista.map(function (x) {
    var falta;
    if (x.estado === "autorizada") falta = '<span class="dim">Nada</span>';
    else if (x.estado === "rechazada") falta = '<span style="color:var(--stop)">Rechazada</span>';
    else if (x.marcados) falta = '<span style="color:var(--stop)">' + x.marcados + " señalado" + (x.marcados > 1 ? "s" : "") + "</span>";
    else if (x.estado === "por_autorizar") falta = '<span style="color:var(--warn)">' + x.firmas + " de " + x.firmasRequeridas + " firmas</span>";
    else if (x.pedidos - x.ok > 0) falta = (x.pedidos - x.ok) + " de " + x.pedidos + " documentos";
    else falta = "Listo para revisar";
    // Sin columna «Tipo»: la pestaña ya lo dice, y en el celular cada columna
    // que sobra empuja a las demás fuera de la pantalla.
    return '<tr class="clickable" data-folio="' + esc(x.folio) + '">' +
      '<td class="mono" style="font-size:13px">' + esc(x.folio) + "</td>" +
      '<td><div style="font-weight:600">' + esc(x.razonSocial) + "</div>" +
      '<div class="dim mono" style="font-size:12px">' + esc(x.rfc) + " · régimen " + esc(x.regimen) + "</div></td>" +
      "<td>" + esc(x.creadoPor || "—") + "</td>" +
      '<td><span class="tag">' + esc(x.sucursal || "—") + "</span></td>" +
      "<td>" + pill(x.estado) + "</td>" +
      '<td class="num mono">' + x.dias + "</td>" +
      '<td style="font-size:13.5px">' + falta + "</td></tr>";
  }).join("");

  function ficha(n, etiqueta, color) {
    return '<div class="tile"><div class="k"' +
      (color && n ? ' style="color:var(--' + color + ')"' : "") + ">" + n + "</div>" +
      '<div class="l">' + etiqueta + "</div></div>";
  }
  function cuenta(e) { return lista.filter(function (x) { return x.estado === e; }).length; }
  var lentos = vivos(lista).filter(function (x) { return x.dias > 7; }).length;

  // La pestaña trae su pendiente al lado: se ve dónde está el trabajo sin entrar.
  function pestaña(t, etiqueta) {
    var pend = vivos(delTipo(t)).length;
    return '<button data-bandeja="' + t + '" aria-current="' + (tipo === t) + '">' +
      etiqueta + (pend ? " · " + pend : "") + "</button>";
  }

  var T = (CAT.tipos && CAT.tipos[tipo]) || {};
  return '<div class="stack">' + bannerError() +
    '<div><h1 style="font-size:22px">Bandeja de expedientes</h1>' +
    '<p class="dim" style="margin:3px 0 0">Altas y créditos son solicitudes separadas, ' +
    "cada una con su liga, sus documentos y su autorización.</p></div>" +
    '<div class="subnav" role="tablist" style="margin-bottom:0">' +
      pestaña("alta", "Altas de cliente") +
      pestaña("credito", "Solicitudes de crédito") +
    "</div>" +
    '<div class="tiles">' +
      ficha(cuenta("enviada") + cuenta("captura"), "Esperando al cliente") +
      ficha(cuenta("recibida"), "Por revisar") +
      ficha(cuenta("por_autorizar"), "Por autorizar", "warn") +
      ficha(cuenta("devuelta"), "Devueltos", "stop") +
      ficha(lentos, "Más de 7 días", "warn") +
      ficha(cuenta("autorizada"), "Autorizados") +
    "</div>" +
    '<div class="card pad"><div class="tablewrap"><table class="grid-t">' +
    "<thead><tr><th>Folio</th><th>Cliente</th><th>Creó</th><th>Sucursal</th>" +
    '<th>Estado</th><th class="num">Días</th><th>Qué falta</th></tr></thead><tbody>' +
    (filas || '<tr><td colspan="7" class="dim">No hay ' +
      esc(String(T.nombre || "").toLowerCase() || "expedientes") +
      ' todavía. Empiece con una pre-solicitud.</td></tr>') +
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
  // El monto lo fija GPA, no el cliente: sin el no hay credito que evaluar.
  if (n.tipo === "credito" && !String(n.montoRequerido || "").replace(/\D/g, "")) {
    out.push("el monto de crédito requerido");
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

/** Pinta el resultado de revisar al prospecto contra la lista de vetados. */
function bloqueVeto(n) {
  var h = S.vetoHits;
  if (!h || (!h.bloqueos.length && !h.avisos.length)) return "";
  var esAdmin = api.sesion && api.sesion.rol === "Administrador";

  var detalle = function (x, parecido) {
    return "<li>El <b>" + esc(x.etiqueta) + "</b> " +
      (parecido ? "se parece " + x.similitud + "% a" : "coincide con") +
      " <b>" + esc(x.vetado) + "</b> — " + esc(x.motivo) +
      (x.desde ? ' <span class="dim">(en la lista desde ' + esc(x.desde) + ")</span>" : "") + "</li>";
  };

  var salida = "";
  if (h.bloqueos.length) {
    salida += '<div class="banner banner-stop"><span>' +
      "<b>No se le puede dar de alta a este cliente.</b>" +
      '<ul class="lista-veto">' + h.bloqueos.map(function (b) { return detalle(b, false); }).join("") + "</ul>" +
      (esAdmin
        ? "Como Administrador puede continuar, pero tiene que escribir por qué. "
          + "Su justificación queda en el expediente para siempre."
        : "Si cree que es un error, pídale a un Administrador que lo revise.") +
      "</span></div>";
    if (esAdmin) {
      salida += '<div class="field"><label for="motivo-veto">Motivo para darlo de alta de todos modos ' +
        '<span class="req">*</span></label>' +
        '<textarea id="motivo-veto" rows="2" placeholder="Ej. Es un homónimo: RFC distinto y otro domicilio. ' +
        'Confirmado con Crédito el 22/09.">' + esc(n.motivoVeto || "") + "</textarea></div>";
    }
  }
  if (h.avisos.length) {
    salida += '<div class="banner banner-warn"><span><b>Se parece a un cliente vetado.</b> ' +
      "No lo detiene, pero revíselo antes de seguir." +
      '<ul class="lista-veto">' + h.avisos.map(function (a) { return detalle(a, true); }).join("") + "</ul>" +
      "</span></div>";
  }
  return salida;
}

/** Revisa contra la lista mientras se captura, sin castigar cada tecla. */
function revisaVeto() {
  var n = S.nueva;
  if (!n) return;
  if (S.vetoTimer) clearTimeout(S.vetoTimer);
  S.vetoTimer = setTimeout(function () {
    var datos = { rfc: n.rfc, razonSocial: n.razon_social, nombreComercial: n.nombre_comercial,
                  correo: n.correo, celular: n.celular };
    if (!datos.rfc && !datos.razonSocial) { S.vetoHits = null; return; }
    api.vetoRevisar(datos).then(function (r) {
      var antes = JSON.stringify(S.vetoHits);
      S.vetoHits = r;
      if (JSON.stringify(r) !== antes) render();
    }).catch(function () { /* si falla la revisión previa, el servidor bloquea igual al crear */ });
  }, 500);
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
            "10 dígitos, p. ej. 33 1204 8871") +
      (n.tipo === "credito"
        ? campo("montoRequerido", 'Monto de crédito requerido <span class="req">*</span>',
                "f-half", "mono", "250,000")
        : "") + "</div>" +
      (n.tipo === "credito"
        ? '<p class="dim" style="margin:0">El monto lo captura GPA. El cliente lo verá en su ' +
          "formulario, pero no lo puede cambiar.</p>"
        : "") +
      '<div id="conflicto-rfc">' +
      (conflicto ? '<div class="banner banner-warn"><span><b>Revise el régimen o el RFC.</b> ' + esc(conflicto) + "</span></div>" : "") +
      bloqueVeto(n) +
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

/** Análisis y autorización: comentarios y anexos internos. NO lo ve el cliente. */
function bloqueAnalisis(c) {
  var rol = api.sesion ? api.sesion.rol : "";
  var puedeComentar = ["Administrador", "Comité de Crédito", "Ventas"].indexOf(rol) !== -1;
  var comentarios = S.analisis.comentarios || [];
  var anexos = S.analisis.anexos || [];

  var hilo = comentarios.map(function (m) {
    var esFirma = String(m.tipo || "").indexOf("firma") === 0;
    var esRechazo = m.tipo === "rechazo";
    var etiqueta = esFirma ? "Firma " + m.tipo.replace("firma-n", "nivel ")
                 : esRechazo ? "Rechazo" : "";
    return '<div class="coment ' + (esFirma ? "es-firma" : esRechazo ? "es-rechazo" : "") + '">' +
      '<div class="coment-cab"><b>' + esc(m.nombre || m.quien) + "</b>" +
      '<span class="dim">' + esc(m.rol || "") + " · " + esc(m.cuandoLegible || "") + "</span>" +
      (etiqueta ? '<span class="tag">' + esc(etiqueta) + "</span>" : "") + "</div>" +
      '<div class="coment-txt">' + esc(m.texto) + "</div></div>";
  }).join("");

  var listaAnexos = anexos.map(function (a) {
    return '<div class="doc attached"><div class="doc-ic">int</div>' +
      '<div class="doc-body"><div class="doc-name">' + esc(a.descripcion) + "</div>" +
      '<div class="doc-meta"><span class="mono">' + esc(a.nombre) + "</span>" +
      (a.url ? ' <a href="' + esc(a.url) + '" target="_blank" rel="noopener">ver</a>' : "") +
      '<span>' + esc(a.nombre_quien || a.quien) + " · " + esc(a.cuandoLegible || "") + "</span>" +
      "</div></div>" +
      (puedeComentar ? '<button class="btn btn-sm btn-stop" data-quitar-anexo="' + esc(a.id) + '">Quitar</button>' : "") +
      "</div>";
  }).join("");

  return '<div class="card pad stack">' +
    '<div class="spread"><div class="eyebrow">Análisis y autorización</div>' +
    '<span class="tag tag-credito">Solo GPA</span></div>' +
    '<p class="dim" style="margin:0">Nada de esto lo ve el cliente: ni los comentarios ' +
    "ni los anexos.</p>" +
    (hilo ? '<div class="stack" style="gap:8px">' + hilo + "</div>"
          : '<p class="dim" style="margin:0">Todavía no hay comentarios.</p>') +
    (puedeComentar
      ? '<hr class="sep"><div class="field"><label for="nuevo-coment">Agregar un comentario</label>' +
        '<textarea id="nuevo-coment" rows="2" placeholder="Ej. Hablé con dos referencias, ' +
        'ambas confirman 3 años de relación sin atrasos."></textarea></div>' +
        '<div class="row"><button class="btn btn-sm btn-primary" id="btn-comentar">Guardar comentario</button>' +
        '<span class="dim">No se puede borrar: es registro de autorización.</span></div>'
      : "") +
    '<hr class="sep">' +
    '<div class="spread"><div class="eyebrow">Anexos internos</div>' +
    '<span class="dim">' + anexos.length + "</span></div>" +
    (listaAnexos ? '<div class="doclist">' + listaAnexos + "</div>" : "") +
    (puedeComentar
      ? '<div class="field"><label for="anexo-desc">¿Qué es el anexo?</label>' +
        '<input id="anexo-desc" placeholder="Ej. Reporte de buró, análisis financiero, cédula de referencias"></div>' +
        '<div class="row"><label class="btn btn-sm subir">Elegir archivo y subir' +
        '<input type="file" id="anexo-file" accept=".pdf,.jpg,.jpeg,.png,.webp,image/*,application/pdf" hidden></label>' +
        '<span class="dim">Hasta 20 anexos, 15 MB cada uno.</span></div>'
      : "") +
    "</div>";
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
    var yo = api.sesion || {};
    var abierto = !!(S.firmando && S.firmando.nivel === nivel && S.firmando.slot === indice);

    // Firma quien está con la sesión abierta. Ya no se elige a nadie: una firma
    // puesta por otro no valdria como acta. El servidor lo vuelve a comprobar.
    var habilitados = (nivel === 1 ? S.firmantes.nivel1 : S.firmantes.nivel2)
      .filter(function (u) { return yaFirmaron.indexOf(u.correo) === -1; });
    var motivo = !listo ? "Falta que el expediente pase a autorización"
      : faltaN1 ? "Espera la firma de nivel 1"
      : !puedo ? "Su rol (" + (yo.rol || "") + ") no autoriza"
      : yaFirmaron.indexOf(yo.correo) !== -1 ? "Usted ya firmó este expediente"
      : !yo["n" + nivel] ? "Usted no está habilitado para firmar el nivel " + nivel
      : "";
    // Cuando usted no puede firmar, decir quién sí puede ahorra media hora de preguntas.
    var quienes = motivo && habilitados.length
      ? " · pueden firmarlo: " + habilitados.map(function (u) { return u.nombre; }).join(", ")
      : "";
    return '<div class="firma"><div class="n">' + (indice + 1) + "</div>" +
      '<div class="firma-body"><div class="firma-t">' + esc(titulo) + "</div>" +
      '<div class="firma-d">' + (motivo ? esc(motivo + quienes)
        : "Firma usted: " + esc(yo.nombre || yo.correo || "")) + "</div></div>" +
      (motivo ? "" :
        '<button class="btn btn-sm btn-primary" data-firmar="' + nivel + '" data-slot="' + indice + '">Firmar</button>') +
      // El motivo de la firma va en el acta y no se puede cambiar: por eso un
      // cuadro de texto de verdad y no una ventanita del navegador.
      (abierto
        ? '<div class="f-full" style="flex-basis:100%; margin-top:8px">' +
          '<div class="field"><label for="motivo-firma">Motivo de su firma <span class="req">*</span></label>' +
          '<textarea id="motivo-firma" rows="2" placeholder="Ej. Línea de 250,000 autorizada ' +
          'contra pagaré firmado; revisar a los 6 meses."></textarea></div>' +
          '<div class="row" style="margin-top:8px">' +
          '<button class="btn btn-sm btn-primary" data-confirmar-firma="' + nivel + '" data-slot="' + indice + '">Confirmar firma</button>' +
          '<button class="btn btn-sm" id="btn-cancelar-firma">Cancelar</button>' +
          '<span class="dim">Queda en el acta; no se puede editar después.</span></div></div>'
        : "") +
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

  function docRenglonInterno(d) {
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
  }

  // Agrupados por dueño, igual que los ve el cliente: así se revisa sin confundir
  // el INE del representante con el del aval.
  var docs = docsPorGrupo(aplic).map(function (bloque) {
    var g = grupoDoc(bloque.grupo);
    return '<div class="grupo-doc" style="--g:' + g.c + '">' +
      '<div class="grupo-cab"><div class="grupo-n">' + esc(g.n) + "</div>" +
      '<span class="grupo-cuenta">' + bloque.docs.length + "</span></div>" +
      '<div class="doclist">' + bloque.docs.map(docRenglonInterno).join("") + "</div></div>";
  }).join("");

  var otrosInt = (c.otros || []).map(function (o) {
    return '<div class="doc attached"><div class="doc-ic">+</div>' +
      '<div class="doc-body"><div class="doc-name">' + esc(o.descripcion || "Documento adicional") + "</div>" +
      '<div class="doc-meta"><span class="mono">' + esc(o.nombre) + "</span>" +
      (o.url ? ' <a href="' + esc(o.url) + '" target="_blank" rel="noopener">ver documento</a>' : "") +
      "</div></div></div>";
  }).join("");
  if (otrosInt) {
    docs += '<div class="grupo-doc" style="--g:#7A8A9A">' +
      '<div class="grupo-cab"><div class="grupo-n">Otros documentos que subió el cliente</div>' +
      '<span class="grupo-cuenta">' + (c.otros || []).length + "</span></div>" +
      '<div class="doclist">' + otrosInt + "</div></div>";
  }

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
      (c.vetoOmitido
        ? '<div class="banner banner-stop"><span><b>Este cliente estaba en la lista de vetados ' +
          "y se dio de alta de todos modos.</b><br>" + esc(c.vetoOmitido.motivo) +
          '<br><span class="dim">Lo autorizó ' + esc(c.vetoOmitido.nombreQuien || c.vetoOmitido.quien) +
          " el " + esc(c.vetoOmitido.cuandoLegible || "") + ".</span></span></div>"
        : "") +
      ((c.avisosVeto || []).length
        ? '<div class="banner banner-warn"><span><b>Se parece a un cliente vetado.</b> ' +
          esc(c.avisosVeto.map(function (a) {
            return a.similitud + "% a «" + a.vetado + "» (" + a.motivo + ")";
          }).join(" · ")) + "</span></div>"
        : "") +
      // El aval también entra por la lista de veto. Esto solo lo ve GPA: al
      // cliente no se le dice nada, ni se le rechaza el envío por este motivo.
      ((c.avisosObligados || []).length
        ? '<div class="banner banner-stop"><span><b>Un obligado solidario está en la ' +
          "lista de vetados.</b><br>" +
          c.avisosObligados.map(function (a) {
            return esc(a.obligado) + " — coincidencia " + esc(a.coincide) +
              (a.similitud ? " (" + a.similitud + "%)" : "") +
              " por " + esc(a.etiqueta) + " con «" + esc(a.vetado) + "»: " + esc(a.motivo);
          }).join("<br>") +
          '<br><span class="dim">El cliente no fue avisado de esto.</span></span></div>'
        : "") +
      (c.vencida
        ? '<div class="banner banner-stop"><span><b>La liga venció el ' + esc(c.venceLegible) +
          ".</b> El cliente ya no puede entrar. Genere una clave nueva: eso reinicia los 15 días.</span></div>"
        : c.venceLegible
          ? '<p class="dim" style="margin:0">La liga del cliente vence el <b>' + esc(c.venceLegible) + "</b>.</p>"
          : "") +
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
      bloqueAnalisis(c) +
      '<div class="card pad stack"><div class="spread"><div class="eyebrow">Lo que capturó el cliente</div>' +
      (incompletos
        ? '<span class="dim" style="color:var(--warn)">' + incompletos + " incompleto" + (incompletos > 1 ? "s" : "") + "</span>"
        : '<span class="dim">completo</span>') + "</div>" +
      (puedeSenalar ? '<p class="dim" style="margin:0">El botón <b>!</b> de cada dato lo señala como ' +
        "incorrecto o incompleto; al devolver, el cliente solo verá lo señalado.</p>" : "") +
      datos + "</div>" +
    "</div></div>";
}

function vistaVeto() {
  var activos = S.veto.filter(function (v) { return v.activo !== false; });
  var bajas = S.veto.filter(function (v) { return v.activo === false; });

  function fila(v) {
    return "<tr>" +
      '<td><div style="font-weight:600">' + esc(v.razonSocial || "—") + "</div>" +
      (v.nombreComercial ? '<div class="dim" style="font-size:12.5px">' + esc(v.nombreComercial) + "</div>" : "") +
      '<div class="dim mono" style="font-size:12px">' + esc(v.rfc || "sin RFC") + "</div></td>" +
      '<td style="font-size:13.5px">' + esc(v.motivo) + "</td>" +
      '<td class="dim" style="font-size:12.5px">' + esc(v.nombreQuien || v.quien) + "<br>" + esc(v.cuandoLegible || "") + "</td>" +
      "<td>" + (v.activo === false
        ? '<span class="dim">Quitado' + (v.motivoBaja ? ": " + esc(v.motivoBaja) : "") + "</span>"
        : '<button class="btn btn-sm" data-quitar-veto="' + esc(v.id) + '">Quitar de la lista</button>') +
      "</td></tr>";
  }

  return '<div class="stack">' + bannerError() +
    '<div><h1 style="font-size:22px">Clientes vetados</h1>' +
    '<p class="dim" style="margin:3px 0 0">A estos no se les da de alta, sean empresas o ' +
    "personas físicas. Al capturar una pre-solicitud se comparan RFC, nombre, nombre " +
    "comercial, correo y celular contra esta lista; y al recibir un expediente de crédito, " +
    "también los obligados solidarios.</p></div>" +
    '<div class="card pad"><div class="tablewrap"><table class="grid-t">' +
    "<thead><tr><th>Cliente</th><th>Por qué</th><th>Lo puso</th><th></th></tr></thead><tbody>" +
    (activos.map(fila).join("") || '<tr><td colspan="4" class="dim">La lista está vacía.</td></tr>') +
    "</tbody></table></div></div>" +
    '<div class="card pad stack"><div class="eyebrow">Agregar a la lista</div>' +
    '<p class="dim" style="margin:0">Puede ser una empresa o una persona física. ' +
    "Basta el nombre o el RFC; entre más datos ponga, más difícil será que se " +
    "cuele con otro nombre. También se revisa contra los obligados solidarios " +
    "de las solicitudes de crédito.</p>" +
    '<div class="grid">' +
      '<div class="field f-full"><label for="v_razon">Razón social o nombre de la persona</label>' +
      '<input id="v_razon" placeholder="Albercas del Valle S.A. de C.V.  ·  o  ·  Juan Pérez García"></div>' +
      '<div class="field f-half"><label for="v_comercial">Nombre comercial</label><input id="v_comercial"></div>' +
      '<div class="field f-half"><label for="v_rfc">RFC</label><input id="v_rfc" class="mono"></div>' +
      '<div class="field f-half"><label for="v_correo">Correo</label><input id="v_correo"></div>' +
      '<div class="field f-half"><label for="v_celular">Celular</label><input id="v_celular" class="mono"></div>' +
      '<div class="field f-full"><label for="v_motivo">¿Por qué no se le puede dar de alta? ' +
      '<span class="req">*</span></label>' +
      '<textarea id="v_motivo" rows="2" placeholder="Ej. Cartera incobrable desde 2024, pasó a jurídico."></textarea></div>' +
    "</div>" +
    '<button class="btn btn-primary" id="btn-veto-agregar">Agregar</button></div>' +
    (bajas.length
      ? '<div class="card pad stack"><div class="eyebrow">Salieron de la lista (' + bajas.length + ")</div>" +
        '<div class="tablewrap"><table class="grid-t"><tbody>' + bajas.map(fila).join("") + "</tbody></table></div></div>"
      : "") +
    "</div>";
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
      (rol !== "Administrador" ? " disabled" : "") + ">Usuarios</button>" +
    '<button data-ir="veto" aria-current="' + (S.vista === "veto") + '"' +
      (rol !== "Administrador" ? " disabled" : "") + ">Clientes vetados</button>";
  $("#sesion-box").innerHTML =
    '<span class="dim">' + esc(api.sesion.nombre) + " · " + esc(rol) + "</span>" +
    '<button class="btn btn-sm" id="btn-salir">Salir</button>';

  var cuerpo =
    S.vista === "nueva" ? vistaNueva() :
    S.vista === "usuarios" ? vistaUsuarios() :
    S.vista === "veto" ? vistaVeto() :
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
           contacto: "", correo: "", celular: "", montoRequerido: "",
           sucursal: CAT.cat.sucursal[0],
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
  if (vista === "veto") {
    return api.veto().then(function (r) { S.veto = r.veto || []; });
  }
  if (vista === "expediente") {
    S.folio = folio;
    return Promise.all([api.caso(folio), api.firmantes(), api.analisis(folio)])
      .then(function (res) {
        S.caso = res[0];
        S.firmantes = res[1];
        S.analisis = res[2];
      });
  }
});

function recargaCaso() {
  return Promise.all([api.caso(S.folio), api.analisis(S.folio)]).then(function (r) {
    S.caso = r[0];
    S.analisis = r[1];
  });
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
  if (d.quitar) {
    sincronizaDesdeDOM();
    var guardado = JSON.parse(JSON.stringify({ v: S.casoCliente.valores || {},
                                               t: S.casoCliente.tablasVal || {} }));
    conError(function () {
      return portal.quitar(d.quitar).then(function (c) {
        c.valores = Object.assign({}, c.valores, guardado.v);
        c.tablasVal = Object.assign({}, c.tablasVal, guardado.t);
        S.casoCliente = c;
        toast("Documento quitado.");
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
  if (d.bandeja) { S.tipoBandeja = d.bandeja; render(); return; }
  if (d.abrir) { irA("expediente", d.abrir); return; }
  if (t.matches("tr[data-folio]")) { irA("expediente", d.folio); return; }
  if (d.tipo) {
    // Cambiar de tipo NO debe borrar lo que ya se capturó del cliente.
    var previo = S.nueva || {};
    S.nueva = nuevaVacia(d.tipo);
    ["razon_social", "nombre_comercial", "rfc", "regimen", "contacto", "correo",
     "celular", "montoRequerido", "sucursal", "giro", "clasificacion"].forEach(function (k) {
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
        montoRequerido: n.montoRequerido,
        // Si el prospecto está vetado, un Administrador puede levantarlo con motivo.
        omitirVeto: !!(S.vetoHits && S.vetoHits.bloqueos.length),
        motivoVeto: (($("#motivo-veto") || {}).value || "").trim(),
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
        S.vetoHits = null;
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
    // Primero se pide el motivo; la firma se confirma en el siguiente paso.
    S.firmando = { nivel: Number(d.firmar), slot: Number(d.slot) };
    render();
    var ta = $("#motivo-firma");
    if (ta) ta.focus();
    return;
  }
  if (t.id === "btn-cancelar-firma") { S.firmando = null; render(); return; }
  if (d.confirmarFirma) {
    var niv = Number(d.confirmarFirma);
    var motivoFirma = ($("#motivo-firma") || {}).value || "";
    if (!motivoFirma.trim()) {
      S.error = "Escriba el motivo de su firma. Queda en el acta y no se puede cambiar después.";
      render();
      return;
    }
    conError(function () {
      return api.firmar(S.folio, niv, motivoFirma.trim()).then(function () {
        S.firmando = null;
        return recargaCaso();
      });
    })();
    return;
  }
  if (t.id === "btn-comentar") {
    var texto = ($("#nuevo-coment") || {}).value || "";
    if (!texto.trim()) { S.error = "Escriba el comentario."; render(); return; }
    conError(function () {
      return api.comentar(S.folio, texto.trim()).then(recargaCaso);
    })();
    return;
  }
  if (d.quitarAnexo) {
    conError(function () { return api.quitarAnexo(S.folio, d.quitarAnexo).then(recargaCaso); })();
    return;
  }
  if (t.id === "btn-rechazar") {
    var mot = window.prompt("¿Por qué se rechaza este expediente?", "");
    if (!mot || !mot.trim()) return;
    conError(function () { return api.rechazar(S.folio, mot.trim()).then(recargaCaso); })();
    return;
  }

  // ── usuarios ──
  if (t.id === "btn-veto-agregar") {
    var nuevoVeto = {
      razonSocial: ($("#v_razon") || {}).value || "",
      nombreComercial: ($("#v_comercial") || {}).value || "",
      rfc: ($("#v_rfc") || {}).value || "",
      correo: ($("#v_correo") || {}).value || "",
      celular: ($("#v_celular") || {}).value || "",
      motivo: ($("#v_motivo") || {}).value || "",
    };
    conError(function () {
      return api.vetoAgregar(nuevoVeto).then(function (r) {
        S.veto = r.veto || [];
        toast("Agregado a la lista.");
      });
    })();
    return;
  }
  if (d.quitarVeto) {
    var motivoBaja = window.prompt("¿Por qué se saca de la lista? Queda registrado.", "");
    if (!motivoBaja || !motivoBaja.trim()) return;
    conError(function () {
      return api.vetoQuitar(d.quitarVeto, motivoBaja.trim()).then(function (r) {
        S.veto = r.veto || [];
        toast("Salió de la lista.");
      });
    })();
    return;
  }
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
    if (["rfc", "razon_social", "nombre_comercial", "correo", "celular"].indexOf(d.nueva) !== -1) {
      revisaVeto();
    }
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
  if (el.id === "privacidad") { var b = $("#btn-enviar-portal"); if (b) b.disabled = !el.checked; return; }

  if (el.id === "anexo-file") {
    var cajaDesc = $("#anexo-desc");
    var descAnexo = cajaDesc ? cajaDesc.value.trim() : "";
    var arch = el.files && el.files[0];
    el.value = "";
    if (!descAnexo) { S.error = "Antes de subirlo, escriba qué es el anexo."; render(); return; }
    if (!arch) return;
    conError(function () {
      return api.subirAnexo(S.folio, arch, descAnexo).then(recargaCaso)
        .then(function () { toast("Anexo guardado."); });
    })();
    return;
  }
  if (d.subir) {
    var desc = "";
    if (d.subir === "otro") {
      var caja = $("#otro-desc");
      desc = caja ? caja.value.trim() : "";
      if (!desc) {
        S.error = "Antes de subirlo, escriba de qué se trata el documento.";
        el.value = "";
        render();
        return;
      }
    }
    subeArchivo(d.subir, el.files && el.files[0], desc);
    return;
  }

  // panel de usuarios: cada cambio se guarda de inmediato
  var correo = d.urol || d.un1 || d.un2 || d.uact;
  if (correo) {
    var u = S.usuarios.filter(function (x) { return x.correo === correo; })[0];
    if (!u) return;
    var datos = { correo: u.correo, nombre: u.nombre, rol: u.rol, n1: u.n1, n2: u.n2, activo: u.activo };
    var quecambio = "";
    if (d.urol) { datos.rol = el.value; quecambio = "rol " + el.value; }
    if (d.un1) { datos.n1 = el.checked; quecambio = (el.checked ? "con" : "sin") + " firma de nivel 1"; }
    if (d.un2) { datos.n2 = el.checked; quecambio = (el.checked ? "con" : "sin") + " firma de nivel 2"; }
    if (d.uact) { datos.activo = el.checked; quecambio = el.checked ? "activo" : "dado de baja"; }
    conError(function () {
      return api.guardarUsuario(datos).then(function (r) {
        // Se usa lo que DEVUELVE el servidor, que lo lee con admin_get_user.
        // Antes se volvía a pedir la lista completa, y list_users de Cognito tarda
        // en reflejar un cambio recién hecho: pintaba el valor viejo y parecía
        // que no se había guardado nada.
        if (r && r.usuario) {
          S.usuarios = S.usuarios.map(function (x) {
            return x.correo === r.usuario.correo ? r.usuario : x;
          });
        }
        if (r && r.firmas) S.firmas = r.firmas;
        render();
        toast((datos.nombre || datos.correo) + ": " + quecambio);
      });
    })();
  }
});

var subeArchivo = function (docId, archivo, descripcion) {
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
  }, descripcion).then(function (c) {
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
