// gpa-api.js — SDK Frontend de GPA Operaciones
// ─────────────────────────────────────────────────────────────────
// Conecta la PWA con API Gateway + Cognito (JWT).
// Lee la configuración de window.GPA_CONFIG (ver config.js, generado en deploy).
//
//   const api = new GpaApi();
//   await api.login('chofer@gpa.com.mx', 'Gpa2026!');
//   const cat = await api.catalogos();
//   const sols = await api.listar('combustible');
//   const key = await api.subirEvidencia('combustible', dataUrl);
//   await api.crear('combustible', { ...datos, photo: key });
// ─────────────────────────────────────────────────────────────────

const TIPO_PATH = { combustible: "combustible", checklist: "checklist", montacargas: "montacargas" };
const TIPO_EVID = { combustible: "SOL", checklist: "CL", montacargas: "MC", formulario: "FRM" };
const SES_KEY = "gpa_ops_session";
const MAX_SUBIDAS = 4;   // evidencias subiendo a la vez (cola; evita ráfagas → throttle)

class GpaApi {
  constructor() {
    this.cfg = window.GPA_CONFIG || {};
    this._sess = this._load();
    this._pendingChallenge = null;
    // Cola de subidas: máximo N evidencias a la vez (evita ráfagas que disparen el throttle)
    this._subiendo = 0; this._espera = [];
  }

  // ── Resiliencia ante picos: reintento con backoff + límite de concurrencia ──
  // Reintenta (hasta 3 intentos) SOLO errores transitorios: red caída, 429 (throttle)
  // y 5xx. Espera creciente con jitter para desincronizar a los clientes.
  async _retry(fn, intentos = 4) {
    let espera = 400;
    for (let i = 0; ; i++) {
      try { return await fn(); }
      catch (e) {
        if (!e || !e._reintentable || i >= intentos - 1) throw e;
        await new Promise(r => setTimeout(r, espera + Math.random() * 300));
        espera *= 3;
      }
    }
  }
  async _turno() {
    while (this._subiendo >= MAX_SUBIDAS) await new Promise(r => this._espera.push(r));
    this._subiendo++;
  }
  _libera() {
    this._subiendo--;
    const sig = this._espera.shift(); if (sig) sig();
  }

  get region()   { return this.cfg.region   || "us-east-1"; }
  get apiUrl()   { return (this.cfg.apiUrl   || "").replace(/\/$/, ""); }
  get clientId() { return this.cfg.clientId  || ""; }
  get session()  { return this._sess; }
  get isAuth()   { return !!(this._sess && this._sess.token && this._sess.exp > Date.now()); }

  _load() { try { return JSON.parse(localStorage.getItem(SES_KEY)); } catch { return null; } }
  _save(s) { this._sess = s; try { s ? localStorage.setItem(SES_KEY, JSON.stringify(s)) : localStorage.removeItem(SES_KEY); } catch {} }

  _decode(jwt) {
    try {
      const p = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(p))));
    } catch { return {}; }
  }

  // ── Auth (Cognito USER_PASSWORD_AUTH) ──────────────────────────
  async login(email, password) {
    const res = await fetch(`https://cognito-idp.${this.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth" },
      body: JSON.stringify({
        AuthFlow: "USER_PASSWORD_AUTH", ClientId: this.clientId,
        AuthParameters: { USERNAME: email, PASSWORD: password },
      }),
    });
    const data = await res.json();
    if (data.ChallengeName === "NEW_PASSWORD_REQUIRED") {
      // Primer ingreso: Cognito exige fijar contraseña. Guardamos el reto;
      // la UI pide la nueva contraseña y llama a completeNewPassword().
      this._pendingChallenge = {
        name: "NEW_PASSWORD_REQUIRED",
        session: data.Session,
        username: (data.ChallengeParameters && data.ChallengeParameters.USER_ID_FOR_SRP) || email,
      };
      return { challenge: "NEW_PASSWORD_REQUIRED" };
    }
    // El administrador restableció la contraseña (estado RESET_REQUIRED): el usuario
    // debe crear una nueva con un código que le llega por correo.
    if (/PasswordResetRequired/i.test(data.__type || ""))
      return { challenge: "PASSWORD_RESET_REQUIRED" };
    if (!res.ok || !data.AuthenticationResult)
      throw new Error(data.message || "Usuario o contraseña incorrectos");
    return this._finishAuth(data.AuthenticationResult, email);
  }

  // Completa el reto NEW_PASSWORD_REQUIRED del primer ingreso.
  async completeNewPassword(newPassword) {
    const ch = this._pendingChallenge;
    if (!ch || ch.name !== "NEW_PASSWORD_REQUIRED")
      throw new Error("No hay un cambio de contraseña pendiente. Vuelve a iniciar sesión.");
    const res = await fetch(`https://cognito-idp.${this.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.RespondToAuthChallenge" },
      body: JSON.stringify({
        ChallengeName: "NEW_PASSWORD_REQUIRED", ClientId: this.clientId, Session: ch.session,
        ChallengeResponses: { USERNAME: ch.username, NEW_PASSWORD: newPassword },
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.AuthenticationResult)
      throw new Error(data.message || "No se pudo establecer la nueva contraseña");
    this._pendingChallenge = null;
    return this._finishAuth(data.AuthenticationResult, ch.username);
  }

  _finishAuth(a, email) {
    const c = this._decode(a.IdToken);
    const csv = s => (s || "").split(",").map(x => x.trim()).filter(Boolean);
    const sucursales = csv(c["custom:sucursales"]);
    if (!sucursales.length && c["custom:sucursal"]) sucursales.push(c["custom:sucursal"]);
    this._save({
      token: a.IdToken,
      refresh: a.RefreshToken,
      exp: Date.now() + (a.ExpiresIn - 60) * 1000,
      email: c.email || email,
      rol: c["custom:rol"] || "operador",
      sucursal: c["custom:sucursal"] || null,
      sucursales,                          // [] = todas
      modulos: csv(c["custom:modulos"]),   // [] = todos
      nombre: c["custom:nombre"] || c.email || email,
    });
    return this._sess;
  }

  // ── Recuperar contraseña (olvido) ──────────────────────────────
  async forgotPassword(email) {
    const res = await fetch(`https://cognito-idp.${this.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.ForgotPassword" },
      body: JSON.stringify({ ClientId: this.clientId, Username: (email || "").trim().toLowerCase() }),
    });
    const data = await res.json();
    if (!res.ok) {
      const t = (data.__type || "") + " " + (data.message || "");
      // Cuenta nueva que nunca fijó su contraseña (FORCE_CHANGE_PASSWORD): Cognito no
      // puede enviar código hasta el primer ingreso. Guiamos al usuario a activarla.
      if (/NotAuthorized/i.test(t) || /current state/i.test(t))
        throw new Error("Tu cuenta aún no está activada. Ingresa con la contraseña temporal que te dio el administrador; al entrar te pedirá crear tu propia contraseña.");
      if (/UserNotFound/i.test(t))
        throw new Error("No encontramos una cuenta con ese correo.");
      if (/LimitExceeded|TooManyRequests/i.test(t))
        throw new Error("Demasiados intentos. Espera unos minutos e inténtalo de nuevo.");
      throw new Error(data.message || "No se pudo enviar el código");
    }
    return data.CodeDeliveryDetails || {};
  }

  async confirmForgotPassword(email, code, newPassword) {
    const res = await fetch(`https://cognito-idp.${this.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.ConfirmForgotPassword" },
      body: JSON.stringify({ ClientId: this.clientId, Username: (email || "").trim().toLowerCase(),
                             ConfirmationCode: (code || "").trim(), Password: newPassword }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || "No se pudo cambiar la contraseña");
    return true;
  }

  async _refresh() {
    if (!this._sess?.refresh) return false;
    const res = await fetch(`https://cognito-idp.${this.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth" },
      body: JSON.stringify({
        AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: this.clientId,
        AuthParameters: { REFRESH_TOKEN: this._sess.refresh },
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.AuthenticationResult) { this.logout(); return false; }
    const a = data.AuthenticationResult;
    this._save({ ...this._sess, token: a.IdToken, exp: Date.now() + (a.ExpiresIn - 60) * 1000 });
    return true;
  }

  logout() { this._save(null); }

  // ── HTTP ───────────────────────────────────────────────────────
  async _fetch(method, path, body) {
    if (this._sess && this._sess.exp <= Date.now()) await this._refresh();
    const res = await this._retry(async () => {
      let r;
      try {
        r = await fetch(this.apiUrl + path, {
          method,
          headers: { "Content-Type": "application/json", "Authorization": this._sess?.token ? `Bearer ${this._sess.token}` : "" },
          body: body ? JSON.stringify(body) : undefined,
        });
      } catch (e) { e._reintentable = true; throw e; }        // red intermitente
      if (r.status === 429 || r.status >= 500) {              // throttle o error del servidor
        const err = new Error("El servidor está ocupado, intenta de nuevo en un momento.");
        err._reintentable = true; throw err;
      }
      return r;
    });
    if (res.status === 401) { this.logout(); throw new Error("Sesión expirada, vuelve a entrar"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  }

  // ── API de negocio ─────────────────────────────────────────────
  catalogos()                 { return this._fetch("GET", "/catalogos"); }
  async listar(tipo)          { return (await this._fetch("GET", `/${TIPO_PATH[tipo]}`)).items || []; }
  crear(tipo, datos)          { return this._fetch("POST", `/${TIPO_PATH[tipo]}`, datos); }
  cambiarEstado(tipo, id, st) { return this._fetch("POST", `/${TIPO_PATH[tipo]}/${id}/estado`, { status: st }); }

  adminVehiculo(v)    { return this._fetch("POST", "/admin/vehiculo", v); }
  adminResponsable(u) { return this._fetch("POST", "/admin/responsable", u); }
  adminSucursal(b)    { return this._fetch("POST", "/admin/sucursal", b); }
  adminConfig(c)      { return this._fetch("POST", "/admin/config", c); }
  adminPrecioCombustible(combustible, precio) { return this._fetch("POST", "/admin/precio-combustible", { combustible, precio }); }
  async adminCuentas() { return (await this._fetch("GET", "/admin/cuentas")).items || []; }
  adminCuenta(c)      { return this._fetch("POST", "/admin/cuenta", c); }

  // ── Motor de formularios dinámicos ─────────────────────────────
  adminModulo(mod)    { return this._fetch("POST", "/admin/modulo", mod); }
  adminPlantilla(p)   { return this._fetch("POST", "/admin/plantilla", p); }
  async listarFormulario(clave) {
    return (await this._fetch("GET", `/formulario?clave=${encodeURIComponent(clave)}`)).items || [];
  }
  crearFormulario(plantillaClave, datos) {
    return this._fetch("POST", "/formulario", { plantillaClave, datos });
  }
  cambiarEstadoFormulario(clave, id, st) {
    return this._fetch("POST", `/formulario/${id}/estado?clave=${encodeURIComponent(clave)}`, { status: st });
  }

  // ── Evidencias: sube un data-URL a S3 y devuelve la clave ──────
  // Pasa por la cola (máx 4 a la vez) y reintenta el PUT si S3/red fallan temporalmente.
  async subirEvidencia(tipo, dataUrl) {
    if (!dataUrl || !dataUrl.startsWith("data:")) return dataUrl;
    await this._turno();
    try {
      const contentType = dataUrl.substring(5, dataUrl.indexOf(";"));
      const { key, uploadUrl } = await this._fetch("POST", "/evidencias/url-subida",
        { tipo: TIPO_EVID[tipo], contentType });
      const blob = await (await fetch(dataUrl)).blob();
      const put = await this._retry(async () => {
        let r;
        try { r = await fetch(uploadUrl, { method: "PUT", headers: { "Content-Type": contentType }, body: blob }); }
        catch (e) { e._reintentable = true; throw e; }
        if (r.status === 429 || r.status >= 500) { const err = new Error("S3 ocupado"); err._reintentable = true; throw err; }
        return r;
      });
      if (!put.ok) throw new Error("No se pudo subir la evidencia");
      return key;
    } finally { this._libera(); }
  }

  // Recorre un objeto y sube todas las imágenes base64, reemplazándolas por su clave S3.
  // Las subidas se hacen EN PARALELO (varias fotos a la vez) para que sea más rápido.
  async subirEvidencias(tipo, obj) {
    if (typeof obj === "string") return obj.startsWith("data:image") ? this.subirEvidencia(tipo, obj) : obj;
    if (Array.isArray(obj)) return Promise.all(obj.map(v => this.subirEvidencias(tipo, v)));
    if (obj && typeof obj === "object") {
      const entries = await Promise.all(Object.keys(obj).map(async k => [k, await this.subirEvidencias(tipo, obj[k])]));
      return Object.fromEntries(entries);
    }
    return obj;
  }
}

window.GpaApi = GpaApi;
