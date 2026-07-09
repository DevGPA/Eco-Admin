// gpa-api.js — SDK Frontend de GPA ViaticOS
// ─────────────────────────────────────────────────────────────────
// Conecta la PWA con API Gateway + Cognito (JWT).
// Lee la configuración de window.GPA_CONFIG (ver config.js, generado en deploy).
//
//   const api = new GpaApi();
//   await api.login('empleado@gpa.com.mx', 'Gpa2026!');
//   const cat  = await api.catalogos();
//   const sols = await api.listar();
//   const { id, folio } = await api.crear({ destino:'Monterrey', ... });
//   await api.estado(id, 'Aprobada');                 // supervisor
//   await api.paso(id, { estado:'TransporteCotizado', datos:{ transporte:{...} } });
//   const key = await api.subirEvidencia('CFDI', dataUrl);
// ─────────────────────────────────────────────────────────────────

const SES_KEY = "gpa_via_session";

class GpaApi {
  constructor() {
    this.cfg = window.GPA_CONFIG || {};
    this._sess = this._load();
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
    if (data.ChallengeName === "NEW_PASSWORD_REQUIRED")
      throw new Error("Debes establecer una nueva contraseña. Contacta al administrador.");
    if (!res.ok || !data.AuthenticationResult)
      throw new Error(data.message || "Usuario o contraseña incorrectos");

    const a = data.AuthenticationResult;
    const c = this._decode(a.IdToken);
    this._save({
      token: a.IdToken,
      refresh: a.RefreshToken,
      exp: Date.now() + (a.ExpiresIn - 60) * 1000,
      email: c.email || email,
      rol: c["custom:rol"] || "empleado",
      area: c["custom:area"] || null,
      nombre: c["custom:nombre"] || c.email || email,
    });
    return this._sess;
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
    const res = await fetch(this.apiUrl + path, {
      method,
      headers: { "Content-Type": "application/json", "Authorization": this._sess?.token ? `Bearer ${this._sess.token}` : "" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) { this.logout(); throw new Error("Sesión expirada, vuelve a entrar"); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  }

  // ── API de negocio ─────────────────────────────────────────────
  catalogos()              { return this._fetch("GET", "/catalogos"); }
  async listar()           { return (await this._fetch("GET", "/solicitudes")).items || []; }
  detalle(id)              { return this._fetch("GET", `/solicitudes/${id}`); }
  crear(datos)             { return this._fetch("POST", "/solicitudes", datos); }
  estado(id, estado)       { return this._fetch("POST", `/solicitudes/${id}/estado`, { estado }); }
  paso(id, body)           { return this._fetch("POST", `/solicitudes/${id}/paso`, body); }

  adminEmpleado(e)  { return this._fetch("POST", "/admin/empleado", e); }
  adminArea(a)      { return this._fetch("POST", "/admin/area", a); }
  adminPolitica(p)  { return this._fetch("POST", "/admin/politica", p); }
  adminTarifas(t)   { return this._fetch("POST", "/admin/tarifas", t); }
  adminConfig(c)    { return this._fetch("POST", "/admin/config", c); }
  async adminCuentas() { return (await this._fetch("GET", "/admin/cuentas")).items || []; }
  adminCuenta(c)    { return this._fetch("POST", "/admin/cuenta", c); }

  // ── Evidencias: sube un data-URL a S3 y devuelve la clave ──────
  // carpeta ∈ FIRMA | CFDI | TICKET | VIA
  async subirEvidencia(carpeta, dataUrl) {
    if (!dataUrl || !dataUrl.startsWith("data:")) return dataUrl;
    const contentType = dataUrl.substring(5, dataUrl.indexOf(";"));
    const { key, uploadUrl } = await this._fetch("POST", "/evidencias/url-subida",
      { carpeta, contentType });
    const blob = await (await fetch(dataUrl)).blob();
    const put = await fetch(uploadUrl, { method: "PUT", headers: { "Content-Type": contentType }, body: blob });
    if (!put.ok) throw new Error("No se pudo subir la evidencia");
    return key;
  }
}

window.GpaApi = GpaApi;
