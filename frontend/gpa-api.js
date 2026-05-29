// gpa-api.js
// SDK Frontend — Motor de Fletes GPA v2.4
// ─────────────────────────────────────────────────────────────────
// Conecta el monitor HTML con API Gateway + Cognito JWT
//
// Uso:
//   const api = new GpaApi({ env: 'prod' });
//   await api.login('usuario@gpa.com.mx', 'password');
//   const res = await api.evaluar({ folioCP: '116873635', ... });
//   const kanban = await api.monitor({ estado: 'EN_REVISION' });
// ─────────────────────────────────────────────────────────────────

class GpaApi {

  // ── Constructor ────────────────────────────────────────────────
  constructor(config = {}) {
    // Guardar referencia (no copia) para que cambios posteriores a
    // GPA_CONFIG se reflejen sin tener que re-asignar la instancia.
    this._config = config;

    this._token      = null;
    this._tokenExp   = 0;
    this._refreshTkn = null;
    this._userId     = null;

    // Intentar recuperar sesión guardada
    this._loadSession();
  }

  // ── Config (lectura dinámica desde GPA_CONFIG) ─────────────────
  get env()      { return this._config.env      || 'dev'; }
  set env(v)     { this._config.env = v; }
  get region()   { return this._config.region   || 'us-east-1'; }
  set region(v)  { this._config.region = v; }
  get apiUrl()   { return this._config.apiUrl   || ''; }
  set apiUrl(v)  { this._config.apiUrl = v; }
  get poolId()   { return this._config.poolId   || ''; }
  set poolId(v)  { this._config.poolId = v; }
  get clientId() { return this._config.clientId || ''; }
  set clientId(v){ this._config.clientId = v; }

  // ═══════════════════════════════════════════════════════════════
  // AUTH — Cognito JWT
  // ═══════════════════════════════════════════════════════════════

  /**
   * Login con email + password → obtiene JWT de Cognito
   * @returns {{ token, userId, groups, expiresAt }}
   */
  async login(email, password) {
    const res = await fetch(
      `https://cognito-idp.${this.region}.amazonaws.com/`,
      {
        method: 'POST',
        headers: {
          'Content-Type':  'application/x-amz-json-1.1',
          'X-Amz-Target':  'AWSCognitoIdentityProviderService.InitiateAuth',
        },
        body: JSON.stringify({
          AuthFlow:       'USER_PASSWORD_AUTH',
          ClientId:       this.clientId,
          AuthParameters: { USERNAME: email, PASSWORD: password },
        }),
      }
    );

    const data = await res.json();

    if (data.ChallengeName === 'NEW_PASSWORD_REQUIRED') {
      throw new GpaAuthError(
        'CAMBIO_PASSWORD_REQUERIDO',
        'Debes cambiar tu contraseña temporal.',
        data.Session
      );
    }

    if (!res.ok || !data.AuthenticationResult) {
      throw new GpaAuthError(
        'AUTH_FALLIDA',
        data.message || 'Credenciales inválidas'
      );
    }

    const auth = data.AuthenticationResult;
    this._token      = auth.IdToken;
    this._refreshTkn = auth.RefreshToken;
    this._tokenExp   = Date.now() + (auth.ExpiresIn * 1000);

    // Decodificar JWT para obtener claims
    const claims    = this._decodeJwt(auth.IdToken);
    this._userId    = claims.email || claims['cognito:username'];

    this._saveSession();

    return {
      token:     this._token,
      userId:    this._userId,
      groups:    claims['cognito:groups'] || [],
      expiresAt: new Date(this._tokenExp).toISOString(),
    };
  }

  /**
   * Cambiar contraseña temporal (primer login)
   */
  async cambiarPassword(session, email, newPassword) {
    const res = await fetch(
      `https://cognito-idp.${this.region}.amazonaws.com/`,
      {
        method: 'POST',
        headers: {
          'Content-Type':  'application/x-amz-json-1.1',
          'X-Amz-Target':  'AWSCognitoIdentityProviderService.RespondToAuthChallenge',
        },
        body: JSON.stringify({
          ChallengeName:  'NEW_PASSWORD_REQUIRED',
          ClientId:       this.clientId,
          Session:        session,
          ChallengeResponses: {
            USERNAME:     email,
            NEW_PASSWORD: newPassword,
          },
        }),
      }
    );
    const data = await res.json();
    if (!res.ok) throw new GpaAuthError('CAMBIO_FALLIDO', data.message);

    // Cognito puede encadenar otro desafío (MFA, etc.) en lugar de autenticar.
    if (data.ChallengeName) {
      throw new GpaAuthError('CHALLENGE_PENDIENTE',
        `Desafío adicional requerido: ${data.ChallengeName}`, data.Session);
    }
    if (!data.AuthenticationResult) {
      throw new GpaAuthError('CAMBIO_FALLIDO',
        data.message || 'No se recibió la sesión tras el cambio de contraseña.');
    }

    // Login exitoso después del cambio
    const auth = data.AuthenticationResult;
    this._token      = auth.IdToken;
    this._refreshTkn = auth.RefreshToken;
    this._tokenExp   = Date.now() + (auth.ExpiresIn * 1000);
    const claims     = this._decodeJwt(auth.IdToken);
    this._userId     = claims.email || claims['cognito:username'];
    this._saveSession();
    return { token: this._token, userId: this._userId };
  }

  /**
   * Refrescar token automáticamente si está por expirar
   */
  async _ensureToken() {
    if (!this._token) throw new GpaAuthError('NO_SESION', 'Inicia sesión primero.');

    // Refrescar 5 min antes de expirar
    if (Date.now() > this._tokenExp - 300000) {
      if (this._refreshTkn) {
        try {
          const res = await fetch(
            `https://cognito-idp.${this.region}.amazonaws.com/`,
            {
              method: 'POST',
              headers: {
                'Content-Type':  'application/x-amz-json-1.1',
                'X-Amz-Target':  'AWSCognitoIdentityProviderService.InitiateAuth',
              },
              body: JSON.stringify({
                AuthFlow:       'REFRESH_TOKEN_AUTH',
                ClientId:       this.clientId,
                AuthParameters: { REFRESH_TOKEN: this._refreshTkn },
              }),
            }
          );
          const data = await res.json();
          // fetch no lanza ante 4xx/5xx: validar explícitamente el refresh.
          if (!res.ok || !data.AuthenticationResult) {
            this.logout();
            throw new GpaAuthError('SESION_EXPIRADA', 'Tu sesión expiró. Inicia sesión de nuevo.');
          }
          this._token    = data.AuthenticationResult.IdToken;
          this._tokenExp = Date.now() + (data.AuthenticationResult.ExpiresIn * 1000);
          this._saveSession();
        } catch (e) {
          this.logout();
          if (e instanceof GpaAuthError) throw e;
          throw new GpaAuthError('SESION_EXPIRADA', 'Tu sesión expiró. Inicia sesión de nuevo.');
        }
      } else {
        this.logout();
        throw new GpaAuthError('SESION_EXPIRADA', 'Tu sesión expiró.');
      }
    }
  }

  /** Cerrar sesión */
  logout() {
    this._token = null;
    this._refreshTkn = null;
    this._tokenExp = 0;
    this._userId = null;
    try { sessionStorage.removeItem('gpa_session'); } catch(e) {}
  }

  /** ¿Está autenticado? */
  get isAuthenticated() { return !!this._token && Date.now() < this._tokenExp; }

  /** Email del usuario actual */
  get userId() { return this._userId; }

  // ═══════════════════════════════════════════════════════════════
  // ENDPOINTS — Evaluación
  // ═══════════════════════════════════════════════════════════════

  /**
   * POST /evaluar — enviar solicitud al motor v2.4
   * @param {Object} solicitud
   * @returns {Object} { id, folioCP, codigoMotor, concepto, estado, pctFlete, criterios }
   */
  async evaluar(solicitud) {
    return this._post('/evaluar', solicitud);
  }

  // ═══════════════════════════════════════════════════════════════
  // ENDPOINTS — Aprobación
  // ═══════════════════════════════════════════════════════════════

  /**
   * POST /aprobar — aprobador 1 aprueba
   * @param {string} id - UUID de la solicitud
   * @param {string} comentario
   */
  async aprobar(id, comentario = '') {
    return this._post('/aprobar', { id, comentario });
  }

  /**
   * POST /rechazar — aprobador 1 rechaza
   */
  async rechazar(id, comentario = '') {
    return this._post('/rechazar', { id, comentario });
  }

  /**
   * POST /escalar — escalar a aprobador 2
   */
  async escalar(id, comentario = '') {
    return this._post('/escalar', { id, comentario });
  }

  // ═══════════════════════════════════════════════════════════════
  // ENDPOINTS — Monitor y consultas
  // ═══════════════════════════════════════════════════════════════

  /**
   * GET /monitor — kanban del dashboard
   * @param {Object} params { estado?, desde?, hasta? }
   * @returns {{ items, estado, total }}
   */
  async monitor(params = {}) {
    return this._get('/monitor', params);
  }

  /**
   * GET /kpis — indicadores del mes
   * @param {number} anio
   * @param {number} mes
   */
  async kpis(anio, mes) {
    return this._get('/kpis', { anio, mes });
  }

  /**
   * GET /solicitud/{id} — detalle + historial completo
   */
  async solicitud(id) {
    return this._get(`/solicitud/${id}`);
  }

  /**
   * GET /solicitudes — listado paginado
   * @param {Object} params { estado?, desde, hasta, limit? }
   */
  async solicitudes(params) {
    return this._get('/solicitudes', params);
  }

  // ═══════════════════════════════════════════════════════════════
  // ENDPOINTS — Auditoría
  // ═══════════════════════════════════════════════════════════════

  /**
   * GET /auditor/fletera — historial por RFC
   * @param {string} rfc
   * @param {string} desde - YYYY-MM-DD
   * @param {string} hasta - YYYY-MM-DD
   */
  async auditorFletera(rfc, desde, hasta) {
    return this._get('/auditor/fletera', { rfc, desde, hasta });
  }

  /**
   * GET /auditor/sucursal — historial por sucursal
   */
  async auditorSucursal(sucursal, desde, hasta) {
    return this._get('/auditor/sucursal', { sucursal, desde, hasta });
  }

  /**
   * GET /auditor/destino — historial por estado destino
   */
  async auditorDestino(estado, desde, hasta) {
    return this._get('/auditor/destino', { estado, desde, hasta });
  }

  // ═══════════════════════════════════════════════════════════════
  // ENDPOINTS — Sistema
  // ═══════════════════════════════════════════════════════════════

  /**
   * GET /health — sin autenticación
   */
  async health() {
    const res = await fetch(`${this.apiUrl}/health`);
    return res.json();
  }

  // ═══════════════════════════════════════════════════════════════
  // KANBAN — carga completa de las 4 columnas
  // ═══════════════════════════════════════════════════════════════

  /**
   * Carga las 4 columnas del kanban en paralelo.
   * @param {string} desde - YYYY-MM-DD
   * @param {string} hasta - YYYY-MM-DD
   * @returns {{ EN_REVISION, ESCALADA, aprobadas, rechazadas, kpis }}
   */
  async cargarKanban(desde, hasta) {
    const [revision, escaladas, autoAprob, manualAprob, autoRech, manualRech, kpisData] =
      await Promise.all([
        this.monitor({ estado: 'EN_REVISION', desde, hasta }),
        this.monitor({ estado: 'ESCALADA',    desde, hasta }),
        this.monitor({ estado: 'AUTO_APROBADA',    desde, hasta }),
        this.monitor({ estado: 'APROBADA_MANUAL',  desde, hasta }),
        this.monitor({ estado: 'AUTO_RECHAZADA',   desde, hasta }),
        this.monitor({ estado: 'RECHAZADA_MANUAL', desde, hasta }),
        this.kpis(
          parseInt(desde.slice(0, 4)),
          parseInt(desde.slice(5, 7))
        ),
      ]);

    return {
      EN_REVISION: revision.items    || [],
      ESCALADA:    escaladas.items   || [],
      aprobadas:   [...(autoAprob.items || []), ...(manualAprob.items || [])],
      rechazadas:  [...(autoRech.items || []),  ...(manualRech.items || [])],
      kpis:        kpisData,
    };
  }

  // ═══════════════════════════════════════════════════════════════
  // HTTP — métodos internos
  // ═══════════════════════════════════════════════════════════════

  async _get(path, params = {}) {
    await this._ensureToken();
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    const url = `${this.apiUrl}${path}${qs ? '?' + qs : ''}`;

    const res = await fetch(url, {
      method: 'GET',
      headers: this._headers(),
    });

    return this._handleResponse(res);
  }

  async _post(path, body) {
    await this._ensureToken();
    const res = await fetch(`${this.apiUrl}${path}`, {
      method:  'POST',
      headers: this._headers(),
      body:    JSON.stringify(body),
    });
    return this._handleResponse(res);
  }

  _headers() {
    return {
      'Content-Type':   'application/json',
      'Authorization':  `Bearer ${this._token}`,
      'X-GPA-UserId':   this._userId || '',
      'X-GPA-Source':    'monitor-v24',
    };
  }

  async _handleResponse(res) {
    // Parseo defensivo: API Gateway/Cognito devuelven a veces cuerpos vacíos o
    // no-JSON (401 sin body, 403, 502/504). Evita que res.json() lance antes de
    // poder evaluar el status real.
    let data = {};
    try {
      const txt = await res.text();
      data = txt ? JSON.parse(txt) : {};
    } catch (_) {
      data = {};
    }

    if (res.status === 401) {
      this.logout();
      throw new GpaAuthError('SESION_EXPIRADA', 'Tu sesión expiró.');
    }

    if (res.status === 409) {
      throw new GpaMotorError(
        data.codigoMotor,
        data.concepto,
        data.error
      );
    }

    if (!res.ok) {
      throw new GpaApiError(res.status, data.error || 'Error del servidor');
    }

    return data;
  }

  // ═══════════════════════════════════════════════════════════════
  // SESIÓN — persistencia en sessionStorage
  // ═══════════════════════════════════════════════════════════════

  _saveSession() {
    try {
      sessionStorage.setItem('gpa_session', JSON.stringify({
        token:      this._token,
        refreshTkn: this._refreshTkn,
        tokenExp:   this._tokenExp,
        userId:     this._userId,
      }));
    } catch(e) { /* sessionStorage no disponible */ }
  }

  _loadSession() {
    try {
      const s = sessionStorage.getItem('gpa_session');
      if (!s) return;
      const d = JSON.parse(s);
      if (d.tokenExp > Date.now()) {
        this._token      = d.token;
        this._refreshTkn = d.refreshTkn;
        this._tokenExp   = d.tokenExp;
        this._userId     = d.userId;
      }
    } catch(e) { /* sessionStorage no disponible */ }
  }

  /** Decodificar JWT (sin verificar — solo para leer claims en el frontend) */
  _decodeJwt(token) {
    try {
      const payload = token.split('.')[1];
      return JSON.parse(atob(payload.replace(/-/g,'+').replace(/_/g,'/')));
    } catch(e) { return {}; }
  }
}


// ═══════════════════════════════════════════════════════════════════
// ERRORES TIPADOS
// ═══════════════════════════════════════════════════════════════════

class GpaAuthError extends Error {
  constructor(code, message, session) {
    super(message);
    this.name    = 'GpaAuthError';
    this.code    = code;
    this.session = session;
  }
}

class GpaMotorError extends Error {
  constructor(codigoMotor, concepto, detalle) {
    super(detalle || concepto);
    this.name        = 'GpaMotorError';
    this.codigoMotor = codigoMotor;
    this.concepto    = concepto;
  }
}

class GpaApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name   = 'GpaApiError';
    this.status = status;
  }
}


// ═══════════════════════════════════════════════════════════════════
// UTILIDADES DE SEGURIDAD
// ═══════════════════════════════════════════════════════════════════

/**
 * Escapa texto para insertarlo de forma segura en HTML (previene XSS).
 * Cubre contextos de texto y de atributo (comillas simples y dobles).
 */
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}


// ═══════════════════════════════════════════════════════════════════
// INTEGRACIÓN CON EL MONITOR HTML
// ═══════════════════════════════════════════════════════════════════

/**
 * GpaMonitorBridge — conecta el SDK con el DOM del monitor v2.4.
 * Maneja: login modal, carga de kanban, filtros de fecha,
 * acciones de aprobación y actualización de KPIs.
 */
class GpaMonitorBridge {

  constructor(api) {
    this.api = api;
  }

  // ── Inicializar el monitor ─────────────────────────────────────
  async init() {
    // Si no hay sesión, mostrar login
    if (!this.api.isAuthenticated) {
      this.showLoginUI();
      return;
    }

    this.showUserBadge();
    await this.refreshKanban();
  }

  // ── Login UI ───────────────────────────────────────────────────
  showLoginUI() {
    const overlay = document.createElement('div');
    overlay.id = 'login-overlay';
    overlay.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(28,37,53,.85);z-index:9999;
                  display:grid;place-items:center;">
        <div style="background:var(--p);border:1px solid var(--ln);border-radius:16px;
                    padding:32px;width:360px;max-width:90vw;">
          <div style="text-align:center;margin-bottom:20px;">
            <div style="font-family:'Nunito',sans-serif;font-size:18px;font-weight:800;
                        color:var(--navy);">GPA Motor de Fletes</div>
            <div style="font-size:12px;color:var(--ink3);margin-top:4px;">
              Inicia sesión para continuar</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:12px;">
            <input type="email" id="login-email" placeholder="Email"
              style="border:1px solid var(--ln);background:var(--p2);color:var(--navy);
                     padding:10px 12px;border-radius:8px;font-size:14px;
                     font-family:'Nunito Sans',sans-serif;outline:none;width:100%;">
            <input type="password" id="login-pass" placeholder="Contraseña"
              style="border:1px solid var(--ln);background:var(--p2);color:var(--navy);
                     padding:10px 12px;border-radius:8px;font-size:14px;
                     font-family:'Nunito Sans',sans-serif;outline:none;width:100%;">
            <div id="login-error" style="display:none;font-size:12px;color:var(--stop);
                 padding:6px 8px;background:var(--stop-bg);border-radius:6px;"></div>
            <button id="login-btn" onclick="window._gpaLoginAction()" 
              style="background:var(--navy);color:#fff;border:none;padding:12px;
                     border-radius:8px;font-family:'Nunito',sans-serif;font-size:14px;
                     font-weight:800;cursor:pointer;width:100%;">
              Iniciar sesión
            </button>
          </div>
          <div style="text-align:center;margin-top:14px;">
            <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;
                         color:var(--ink3);letter-spacing:.05em;">
              spec v2.4 · API Gateway · Cognito JWT
            </span>
          </div>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    // Enter key
    document.getElementById('login-pass').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') window._gpaLoginAction();
    });
  }

  // ── Badge de usuario en el topbar ──────────────────────────────
  showUserBadge() {
    const badge = document.getElementById('user-badge');
    if (badge) {
      badge.textContent = this.api.userId || 'conectado';
      badge.style.display = 'flex';
    }
    // Quitar login overlay si existe
    const ov = document.getElementById('login-overlay');
    if (ov) ov.remove();
  }

  // ── Cargar kanban completo ─────────────────────────────────────
  async refreshKanban() {
    // Rango por defecto: mes actual (no fechas fijas que quedan desfasadas).
    const now   = new Date();
    const fmt   = (d) => d.toISOString().slice(0, 10);
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const last  = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    const desde = document.getElementById('dfFrom')?.value || fmt(first);
    const hasta = document.getElementById('dfTo')?.value   || fmt(last);

    try {
      const data = await this.api.cargarKanban(desde, hasta);

      this.renderColumn('col-revision',  data.EN_REVISION);
      this.renderColumn('col-escaladas', data.ESCALADA);
      this.renderColumn('col-aprobadas', data.aprobadas);
      this.renderColumn('col-rechazadas',data.rechazadas);
      this.renderKpis(data.kpis);
      this.updateCounts(data);

    } catch (err) {
      if (err instanceof GpaAuthError) {
        this.showLoginUI();
      } else {
        console.error('Error cargando kanban:', err);
        this.showError('Error al cargar el monitor: ' + err.message);
      }
    }
  }

  // ── Render tarjeta de solicitud ────────────────────────────────
  renderCard(item) {
    // Código sin escapar SOLO para decisiones de clase (no se inserta en el DOM)
    const codigoRaw = item.codigoMotor || '';
    const estado    = item.estado || '';
    // Todo lo que se inserta como HTML va escapado (anti-XSS)
    const codigo    = escapeHtml(codigoRaw);
    const concepto  = escapeHtml(item.conceptoMotor || '');
    const folio     = escapeHtml(item.folioCP || '');
    const destino   = escapeHtml(`${item.origenSucursal || ''} → ${item.destinoEstado || ''}`);
    const pct       = item.pctFlete ? (parseFloat(item.pctFlete) * 100).toFixed(1) : '—';
    const fecha     = escapeHtml(item.fechaEmision || '');
    // ID usado dentro de onclick/atributos: limitar a charset seguro (UUID-like).
    // Esto neutraliza la inyección de JS al romper la cadena del onclick.
    const solId     = String(item.PK || '').replace('SOL#', '').replace(/[^a-zA-Z0-9_-]/g, '');

    // Color de la tarjeta basado en el estado/código
    let cardClass = 'go';
    if (codigoRaw.startsWith('R-1') || codigoRaw.startsWith('R-2') || codigoRaw.startsWith('R-3'))
      cardClass = 'stop';
    else if (codigoRaw === 'R-501' || codigoRaw === 'R-502' || codigoRaw === 'R-801')
      cardClass = 'warn';
    else if (codigoRaw === 'R-800' || estado.includes('DISPERSION'))
      cardClass = 'navy';
    else if (codigoRaw === 'R-060')
      cardClass = 'gold';

    // Clase del badge
    let cuClass = 'a'; // aprobada por default
    if (estado === 'EN_REVISION') cuClass = 'w';
    else if (estado === 'ESCALADA') cuClass = 'w';
    else if (estado.includes('RECHAZADA')) cuClass = 's';

    // Botones según estado
    let btns = `<button class="btn" onclick="gpaVerDetalle('${solId}')">Ver</button>`;
    if (estado === 'EN_REVISION' || estado === 'ESCALADA') {
      btns = `<button class="btn btnd" onclick="gpaRechazar('${solId}')">✕</button>` +
             `<button class="btn btnp" onclick="gpaAprobar('${solId}')">✓ Aprobar</button>`;
    }

    return `
      <div class="card ${cardClass}" data-id="${solId}" data-fecha="${fecha}">
        <div class="ch">
          <div class="chk" onclick="ck(this,event)"></div>
          <div class="cm">
            <div class="cn">${folio}</div>
            <div class="cf">${codigo} · ${concepto} · ${fecha}</div>
          </div>
          <span class="cu ${cuClass}">${codigo} · ${concepto}</span>
        </div>
        <div class="cmeta">
          <span>${destino}</span>
          <span class="ms">·</span>
          <span>Flete: ${pct}%</span>
          <span class="ms">·</span>
          <span>$${parseFloat(item.montoBaseUSD || 0).toFixed(0)} USD</span>
        </div>
        <div class="cft">
          <div class="dps">
            <span class="dp" onclick="gpaVerDetalle('${solId}')">${folio}</span>
          </div>
          <div class="bs">${btns}</div>
        </div>
      </div>`;
  }

  // ── Render columna del kanban ──────────────────────────────────
  renderColumn(containerId, items) {
    const el = document.getElementById(containerId);
    if (!el) return;

    if (!items.length) {
      el.innerHTML = '<div class="empty">Sin solicitudes en este rango.</div>';
      return;
    }

    el.innerHTML = items.map(item => this.renderCard(item)).join('');
  }

  // ── Render KPIs ────────────────────────────────────────────────
  renderKpis(kpis) {
    if (!kpis) return;
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set('kpi-total',     kpis.total || 0);
    set('kpi-aprobadas', kpis.aprobadas || 0);
    set('kpi-rechazadas',kpis.rechazadas || 0);
    set('kpi-revision',  kpis.en_revision || 0);
    set('kpi-pct',       (kpis.pct_aprobacion || 0) + '%');
    set('kpi-flete-pct', (kpis.pct_flete_global || 0) + '%');
  }

  updateCounts(data) {
    const set = (id, n) => {
      const el = document.getElementById(id);
      if (el) el.textContent = n;
    };
    set('count-revision',  data.EN_REVISION.length);
    set('count-escaladas', data.ESCALADA.length);
    set('count-aprobadas', data.aprobadas.length);
    set('count-rechazadas',data.rechazadas.length);
  }

  showError(msg) {
    console.error(msg);
    // Mostrar en el UI si hay un elemento para ello
    const el = document.getElementById('api-error-msg');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  }
}


// ═══════════════════════════════════════════════════════════════════
// INICIALIZACIÓN GLOBAL
// ═══════════════════════════════════════════════════════════════════

// Configuración — actualizar después del deploy con los outputs de CloudFormation
const GPA_CONFIG = {
  env:      'prod',
  region:   'us-east-1',
  apiUrl:   '',   // ← pegar: https://{id}.execute-api.us-east-1.amazonaws.com/prod
  poolId:   '',   // ← pegar: us-east-1_XXXXXXXXX
  clientId: '',   // ← pegar: abc123def456...
};

// Instancia global
const gpaApi    = new GpaApi(GPA_CONFIG);
const gpaBridge = new GpaMonitorBridge(gpaApi);

// ── Acción de login (llamada desde el botón del modal) ───────────
window._gpaLoginAction = async function() {
  const email = document.getElementById('login-email')?.value;
  const pass  = document.getElementById('login-pass')?.value;
  const err   = document.getElementById('login-error');
  const btn   = document.getElementById('login-btn');

  if (!email || !pass) {
    err.textContent = 'Ingresa email y contraseña';
    err.style.display = 'block';
    return;
  }

  btn.textContent = 'Conectando...';
  btn.disabled = true;

  try {
    await gpaApi.login(email, pass);
    gpaBridge.showUserBadge();
    await gpaBridge.refreshKanban();
  } catch (e) {
    if (e.code === 'CAMBIO_PASSWORD_REQUERIDO') {
      err.textContent = 'Debes cambiar tu contraseña temporal.';
      err.style.display = 'block';
      // TODO: mostrar form de cambio de contraseña
    } else {
      err.textContent = e.message || 'Error de autenticación';
      err.style.display = 'block';
    }
  } finally {
    btn.textContent = 'Iniciar sesión';
    btn.disabled = false;
  }
};

// ── Acciones globales del kanban ─────────────────────────────────

window.gpaAprobar = async function(solId) {
  if (!confirm('¿Aprobar esta solicitud?')) return;
  const comentario = prompt('Comentario (opcional):') || '';
  try {
    await gpaApi.aprobar(solId, comentario);
    await gpaBridge.refreshKanban();
  } catch(e) {
    alert('Error al aprobar: ' + e.message);
  }
};

window.gpaRechazar = async function(solId) {
  const comentario = prompt('Motivo del rechazo:');
  if (comentario === null) return;  // canceló
  try {
    await gpaApi.rechazar(solId, comentario);
    await gpaBridge.refreshKanban();
  } catch(e) {
    alert('Error al rechazar: ' + e.message);
  }
};

window.gpaEscalar = async function(solId) {
  const comentario = prompt('Motivo del escalamiento:');
  if (comentario === null) return;
  try {
    await gpaApi.escalar(solId, comentario);
    await gpaBridge.refreshKanban();
  } catch(e) {
    alert('Error al escalar: ' + e.message);
  }
};

window.gpaVerDetalle = async function(solId) {
  try {
    const data = await gpaApi.solicitud(solId);
    console.log('Solicitud:', data);
    // TODO: mostrar panel lateral con detalle + historial
    alert(
      `Solicitud: ${data.folioCP}\n` +
      `Estado: ${data.estado}\n` +
      `Código: ${data.codigoMotor} · ${data.conceptoMotor}\n` +
      `Historial: ${(data.historial || []).length} entradas`
    );
  } catch(e) {
    alert('Error: ' + e.message);
  }
};

// ── Conectar filtro de fechas con la API ─────────────────────────
window.gpaApplyFilter = async function() {
  if (!gpaApi.isAuthenticated) return;
  await gpaBridge.refreshKanban();
};

// ── Evaluar solicitud desde el simulador ─────────────────────────
window.gpaEvaluarAPI = async function(solicitud) {
  try {
    const res = await gpaApi.evaluar(solicitud);
    return res;
  } catch(e) {
    if (e instanceof GpaMotorError) {
      return {
        error:       true,
        codigoMotor: e.codigoMotor,
        concepto:    e.concepto,
        detalle:     e.message,
      };
    }
    throw e;
  }
};

// ── Auto-init cuando el DOM esté listo ───────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Solo inicializar si la API está configurada
  if (GPA_CONFIG.apiUrl) {
    gpaBridge.init();
  } else {
    console.info(
      '%c[GPA API] %cNo configurada — usando modo offline (datos de demostración)',
      'color:#3AADAD;font-weight:bold', 'color:#8A96B0'
    );
  }
});
