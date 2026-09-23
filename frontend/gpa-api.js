// gpa-api.js — cliente de API de GPA Alta de Clientes
// ─────────────────────────────────────────────────────────────────
// Dos clientes distintos, a propósito:
//
//   GpaApi     usuarios internos de GPA. Cognito + JWT.
//   PortalApi  el cliente externo. Liga con token + clave. SIN cuenta.
//
// La configuración llega en window.GPA_CONFIG (config.js, generado en el
// despliegue de Amplify a partir de los Outputs de SAM).
// ─────────────────────────────────────────────────────────────────

const SESION_KEY = "gpa_alta_sesion";
const PORTAL_KEY = "gpa_alta_portal";

function _cfg() { return window.GPA_CONFIG || {}; }
function _region() { return _cfg().region || "us-east-1"; }
function _apiUrl() { return String(_cfg().apiUrl || "").replace(/\/$/, ""); }

/** Mensaje legible a partir de una respuesta fallida. */
async function _falla(res) {
  let data = {};
  try { data = await res.json(); } catch { /* respuesta sin cuerpo */ }
  if (data.error) return new Error(data.error);
  if (res.status === 429) return new Error("Demasiados intentos seguidos. Espere un minuto y vuelva a probar.");
  if (res.status >= 500) return new Error("El servidor de GPA no respondió bien. Vuelva a intentar en un momento.");
  return new Error(`No se pudo completar la operación (error ${res.status}).`);
}

/** fetch con aviso claro cuando no hay red, en vez del críptico «Failed to fetch». */
async function _pide(url, opciones) {
  try {
    return await fetch(url, opciones);
  } catch {
    throw new Error("No hay conexión con el servidor. Revise su internet y vuelva a intentar.");
  }
}

// ═══════════════════════════════════════════════════════════════
// Usuarios internos de GPA
// ═══════════════════════════════════════════════════════════════
class GpaApi {
  constructor() { this.sesion = this._carga(); }

  get clientId() { return _cfg().clientId || ""; }
  get autenticado() { return !!(this.sesion && this.sesion.token && this.sesion.exp > Date.now()); }

  _carga() { try { return JSON.parse(localStorage.getItem(SESION_KEY)); } catch { return null; } }
  _guarda(s) {
    this.sesion = s;
    try { s ? localStorage.setItem(SESION_KEY, JSON.stringify(s)) : localStorage.removeItem(SESION_KEY); } catch { /* modo privado */ }
  }

  _lee(jwt) {
    try {
      const cuerpo = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(cuerpo))));
    } catch { return {}; }
  }

  _cognito(target, cuerpo) {
    return _pide(`https://cognito-idp.${_region()}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(cuerpo),
    });
  }

  _rolDeGrupos(claims) {
    const mapa = (window.GPA_CATALOGOS && window.GPA_CATALOGOS.grupoARol) || {
      admin: "Administrador", comite: "Comité de Crédito", ventas: "Ventas", consulta: "Consulta",
    };
    const grupos = claims["cognito:groups"] || [];
    const lista = Array.isArray(grupos) ? grupos : String(grupos).split(/[\s,[\]]+/).filter(Boolean);
    for (const g of ["admin", "comite", "ventas", "consulta"]) if (lista.includes(g)) return mapa[g];
    return "Consulta";
  }

  _sesionDe(resultado, correo) {
    const claims = this._lee(resultado.IdToken);
    return {
      token: resultado.IdToken,
      refresh: resultado.RefreshToken,
      exp: Date.now() + (resultado.ExpiresIn - 60) * 1000,
      correo: claims.email || correo,
      nombre: claims["custom:nombre"] || claims.email || correo,
      rol: this._rolDeGrupos(claims),
      n1: String(claims["custom:n1"] || "0") === "1",
      n2: String(claims["custom:n2"] || "0") === "1",
    };
  }

  /** Devuelve {estado:"listo"} o {estado:"nueva-contrasena", sesionCognito} para el primer ingreso. */
  async entrar(correo, contrasena) {
    const res = await this._cognito("InitiateAuth", {
      AuthFlow: "USER_PASSWORD_AUTH", ClientId: this.clientId,
      AuthParameters: { USERNAME: correo, PASSWORD: contrasena },
    });
    const data = await res.json().catch(() => ({}));

    // Primer ingreso: Cognito exige cambiar la contraseña temporal.
    // Se resuelve aquí mismo para no depender del correo, que todavía no está configurado.
    if (data.ChallengeName === "NEW_PASSWORD_REQUIRED") {
      return { estado: "nueva-contrasena", sesionCognito: data.Session, correo };
    }
    if (!res.ok || !data.AuthenticationResult) {
      throw new Error(data.message && /incorrect|not authorized/i.test(data.message)
        ? "Correo o contraseña incorrectos."
        : (data.message || "No se pudo entrar. Revise sus datos."));
    }
    this._guarda(this._sesionDe(data.AuthenticationResult, correo));
    return { estado: "listo", sesion: this.sesion };
  }

  async fijarContrasena(correo, sesionCognito, nueva) {
    const res = await this._cognito("RespondToAuthChallenge", {
      ChallengeName: "NEW_PASSWORD_REQUIRED", ClientId: this.clientId,
      Session: sesionCognito,
      ChallengeResponses: { USERNAME: correo, NEW_PASSWORD: nueva },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.AuthenticationResult) {
      throw new Error(data.message ||
        "La contraseña no cumple: al menos 10 caracteres, con mayúscula, minúscula y número.");
    }
    this._guarda(this._sesionDe(data.AuthenticationResult, correo));
    return this.sesion;
  }

  async _renueva() {
    if (!this.sesion || !this.sesion.refresh) return false;
    const res = await this._cognito("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: this.clientId,
      AuthParameters: { REFRESH_TOKEN: this.sesion.refresh },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.AuthenticationResult) { this.salir(); return false; }
    const a = data.AuthenticationResult;
    this._guarda({ ...this.sesion, token: a.IdToken, exp: Date.now() + (a.ExpiresIn - 60) * 1000 });
    return true;
  }

  salir() { this._guarda(null); }

  async _http(metodo, ruta, cuerpo) {
    if (this.sesion && this.sesion.exp <= Date.now()) await this._renueva();
    const res = await _pide(_apiUrl() + ruta, {
      method: metodo,
      headers: {
        "Content-Type": "application/json",
        Authorization: this.sesion && this.sesion.token ? `Bearer ${this.sesion.token}` : "",
      },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
    if (res.status === 401) { this.salir(); throw new Error("Su sesión venció. Vuelva a entrar."); }
    if (!res.ok) throw await _falla(res);
    return res.json();
  }

  // ── Expedientes ──
  bandeja(estado) { return this._http("GET", "/casos" + (estado ? `?estado=${encodeURIComponent(estado)}` : "")); }
  caso(folio) { return this._http("GET", `/casos/${encodeURIComponent(folio)}`); }
  bitacora(folio) { return this._http("GET", `/casos/${encodeURIComponent(folio)}/bitacora`); }
  crear(datos) { return this._http("POST", "/casos", datos); }
  claveNueva(folio) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/clave`); }
  marcarDoc(folio, docId, ok, motivo) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/revision`, { docId, ok, motivo }); }
  señalarCampo(folio, campo, motivo) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/revision`, { campo, motivo }); }
  devolver(folio) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/devolver`); }
  aAutorizacion(folio) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/autorizacion`); }
  /** Firma quien tiene la sesión abierta: el servidor lo toma del token, no de aquí. */
  firmar(folio, nivel, comentario) {
    return this._http("POST", `/casos/${encodeURIComponent(folio)}/firmar`,
                      { nivel, comentario });
  }

  // ── Análisis interno: comentarios y anexos. El cliente nunca ve nada de esto. ──
  analisis(folio) { return this._http("GET", `/casos/${encodeURIComponent(folio)}/analisis`); }
  comentar(folio, texto) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/comentario`, { texto }); }
  quitarAnexo(folio, quitar) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/anexo`, { quitar }); }

  /** Sube un anexo interno directo a S3 y lo registra con su descripción. */
  async subirAnexo(folio, archivo, descripcion) {
    const permiso = await this._http("POST", `/casos/${encodeURIComponent(folio)}/anexo-url`,
                                     { contentType: archivo.type, tam: archivo.size });
    const puesto = await _pide(permiso.url, {
      method: "PUT", headers: permiso.headers, body: archivo,
    });
    if (!puesto.ok) {
      throw new Error("El anexo no se pudo guardar. Revise su conexión e inténtelo otra vez.");
    }
    return this._http("POST", `/casos/${encodeURIComponent(folio)}/anexo`, {
      nombre: archivo.name, key: permiso.key, tam: archivo.size, descripcion,
    });
  }
  rechazar(folio, motivo) { return this._http("POST", `/casos/${encodeURIComponent(folio)}/rechazar`, { motivo }); }

  // ── Clientes vetados: a quiénes NO se les da de alta ──
  veto() { return this._http("GET", "/veto"); }
  vetoAgregar(datos) { return this._http("POST", "/veto", datos); }
  vetoQuitar(id, motivo) { return this._http("POST", "/veto/quitar", { id, motivo }); }
  vetoRevisar(datos) { return this._http("POST", "/veto/revisar", datos); }

  // ── Usuarios ──
  usuarios() { return this._http("GET", "/usuarios"); }
  guardarUsuario(datos) { return this._http("POST", "/usuarios", datos); }
  firmantes() { return this._http("GET", "/firmantes"); }
}

// ═══════════════════════════════════════════════════════════════
// Portal del cliente externo — liga + clave, nunca una cuenta
// ═══════════════════════════════════════════════════════════════
class PortalApi {
  constructor(token) {
    this.token = token || "";
    this.clave = "";
    // Se recuerda en la pestaña para que recargar no obligue a teclear la clave
    // otra vez. Al cerrar la pestaña se borra: no queda nada en el dispositivo.
    try {
      const g = JSON.parse(sessionStorage.getItem(PORTAL_KEY) || "null");
      if (g && g.token === this.token) this.clave = g.clave || "";
    } catch { /* modo privado */ }
  }

  _recuerda() {
    try { sessionStorage.setItem(PORTAL_KEY, JSON.stringify({ token: this.token, clave: this.clave })); } catch { /* modo privado */ }
  }

  olvida() {
    this.clave = "";
    try { sessionStorage.removeItem(PORTAL_KEY); } catch { /* modo privado */ }
  }

  async _http(ruta, cuerpo) {
    const res = await _pide(_apiUrl() + ruta, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: this.token, clave: this.clave, ...(cuerpo || {}) }),
    });
    if (!res.ok) throw await _falla(res);
    return res.json();
  }

  async entrar(clave) {
    this.clave = clave;
    const caso = await this._http("/portal/entrar");
    this._recuerda();
    return caso;
  }

  guardar(valores, tablas) { return this._http("/portal/guardar", { valores, tablas }); }
  enviar() { return this._http("/portal/enviar"); }

  /** Sube el archivo directo a S3 con URL prefirmada; nunca pasa por la Lambda.
   *  Para el documento libre (docId "otro") se manda también de qué se trata. */
  async subir(docId, archivo, alAvanzar, descripcion) {
    const permiso = await this._http("/portal/url-subida", {
      docId, contentType: archivo.type, tam: archivo.size,
    });
    if (alAvanzar) alAvanzar(30);
    const puesto = await _pide(permiso.url, {
      method: "PUT", headers: permiso.headers, body: archivo,
    });
    if (!puesto.ok) {
      throw new Error("El archivo no se pudo guardar. Revise su conexión e inténtelo otra vez.");
    }
    if (alAvanzar) alAvanzar(80);
    return this._http("/portal/adjuntar", {
      docId, nombre: archivo.name, key: permiso.key,
      tam: archivo.size, descripcion: descripcion || "",
    });
  }

  /** Quita un documento adicional subido por error. Los de la lista se reemplazan. */
  quitar(docId) { return this._http("/portal/quitar", { docId }); }
}

/** Catálogos: públicos, los necesita también el cliente que no tiene cuenta. */
async function cargarCatalogos() {
  const res = await _pide(_apiUrl() + "/catalogos", { headers: { "Content-Type": "application/json" } });
  if (!res.ok) throw await _falla(res);
  window.GPA_CATALOGOS = await res.json();
  return window.GPA_CATALOGOS;
}

window.GpaApi = GpaApi;
window.PortalApi = PortalApi;
window.cargarCatalogos = cargarCatalogos;
