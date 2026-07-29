# handler.py — GPA Operaciones
# Lambda — API Gateway HTTP API v2 (router por routeKey)
# ─────────────────────────────────────────────────────────────────
# Rutas:
#   GET   /health                       health check (sin auth)
#   GET   /catalogos                    vehículos, responsables, sucursales, config
#   POST  /combustible                  crear solicitud
#   GET   /combustible                  listar (según rol)
#   POST  /combustible/{id}/estado      aprobar / rechazar
#   POST  /checklist                    crear checklist de reparto
#   GET   /checklist                    listar
#   POST  /montacargas                  crear checklist de montacargas
#   GET   /montacargas                  listar
#   POST  /montacargas/{id}/estado      aprobar / rechazar
#   POST  /formulario                   crear registro de formulario dinámico
#   GET   /formulario?clave=...          listar registros de una plantilla
#   POST  /formulario/{id}/estado        aprobar / rechazar (?clave=...)
#   POST  /evidencias/url-subida         URL prefirmada para subir foto/firma
#   POST  /admin/vehiculo|responsable|sucursal|config|modulo|plantilla  (solo admin)
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json, os, re, logging, traceback, gzip, base64
from datetime import date, datetime, timedelta, timezone

from db import modelos as m
from db.escritura import (crear_registro, cambiar_estado, corregir_registro,
                          guardar_vehiculo, guardar_responsable,
                          guardar_sucursal, eliminar_sucursal, guardar_config,
                          actualizar_precio_por_combustible,
                          guardar_modulo, guardar_plantilla,
                          guardar_responsable_alerta, reasignar_registro_unidad)
from db.queries import (listar_registros, get_registro, cargar_catalogos,
                        get_plantilla, get_vehiculo, ultimo_medidor_por_vehiculo,
                        ultima_solicitud_vehiculo, solicitud_asignable_vehiculo)
from s3.evidencias import url_subida, url_lectura
from auth_cognito import listar_cuentas, guardar_cuenta

try:
    import boto3
    _sns = boto3.client("sns")
except Exception:           # pragma: no cover
    _sns = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ORIGIN       = os.environ.get("ALLOWED_ORIGIN", "*")
SNS_ARN      = os.environ.get("SNS_NOTIF_ARN", "")
EMAIL_LOGIS  = os.environ.get("EMAIL_LOGISTICA", "")
EMAIL_RIESGO = os.environ.get("EMAIL_RIESGOS", "")

# Patrón de una clave de evidencia en S3 (para resolver a URL prefirmada al leer)
_KEY_RE = re.compile(r"^(SOL|CL|MC|FRM)/[0-9a-f]{32}\.(jpg|png|webp)$")

# Ventana por defecto de los listados: solo los últimos N días salvo que se pida
# un rango explícito (?desde=&hasta=) o todo (?todo=1). A escala evita respuestas
# enormes (la base crece cada semana).
_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VENTANA_DIAS = int(os.environ.get("VENTANA_DIAS", "45"))
_MX = timezone(timedelta(hours=-6))   # Ciudad de México (UTC-6 fijo)


# ── Respuestas ───────────────────────────────────────────────────
def _resp(body, status=200):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": ORIGIN},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _resp_gz(body, event, status=200):
    """Como _resp pero comprime con gzip cuando el cliente lo acepta y la respuesta
    es grande (>50 KB). API Gateway HTTP API v2 no comprime solo; el navegador
    descomprime transparente (fetch no requiere cambios). Solo para listados."""
    data = json.dumps(body, ensure_ascii=False, default=str)
    ae = ((event.get("headers") or {}).get("accept-encoding") or "").lower()
    if "gzip" in ae and len(data) > 50_000:
        return {"statusCode": status,
                "headers": {"Content-Type": "application/json",
                            "Content-Encoding": "gzip",
                            "Access-Control-Allow-Origin": ORIGIN},
                "isBase64Encoded": True,
                "body": base64.b64encode(gzip.compress(data.encode())).decode()}
    return _resp(body, status)


def _err(msg, status=400):
    return _resp({"error": msg}, status)


def _rango_listado(event):
    """Lee ?desde=&hasta=&todo= y devuelve (desde, hasta_excl) para listar_registros.
    Sin desde ni todo → ventana por defecto (últimos VENTANA_DIAS días)."""
    qs = event.get("queryStringParameters") or {}
    desde = qs.get("desde") or ""
    hasta = qs.get("hasta") or ""
    todo = (qs.get("todo") or "") in ("1", "true")
    if not _YMD_RE.match(desde):
        desde = ""
    if not _YMD_RE.match(hasta):
        hasta = ""
    if not desde and not todo:
        desde = (datetime.now(_MX) - timedelta(days=VENTANA_DIAS)).strftime("%Y-%m-%d")
    hasta_excl = (date.fromisoformat(hasta) + timedelta(days=1)).isoformat() if hasta else None
    return (desde or None), hasta_excl


# ── Claims del JWT de Cognito ────────────────────────────────────
def _csv(x):
    return [s.strip() for s in (x or "").split(",") if s.strip()]


# Mapa tipo de registro → módulo(s) que conceden acceso (control de acceso).
# CL/MC aceptan "mtto" (nueva navegación unificada) o las claves antiguas.
MODULO = {m.SOL: ("combustible",),
          m.CL:  ("mtto", "checklist"),
          m.MC:  ("mtto", "montacargas")}


def _claims(event) -> dict:
    c = (event.get("requestContext", {}).get("authorizer", {})
              .get("jwt", {}).get("claims", {})) or {}
    sucursales = _csv(c.get("custom:sucursales"))
    if not sucursales and c.get("custom:sucursal"):
        sucursales = [c.get("custom:sucursal")]
    return {
        "email":      c.get("email") or c.get("cognito:username") or "desconocido",
        "rol":        c.get("custom:rol", "operador"),
        "sucursal":   c.get("custom:sucursal") or None,
        "sucursales": sucursales,                 # [] = todas
        "modulos":    _csv(c.get("custom:modulos")),  # [] = todos
        "nombre":     c.get("custom:nombre") or c.get("email") or "",
    }


def _modulo_ok(cl, modulo) -> bool:
    """`modulo` puede ser una clave (str) o varias (tuple/list); basta una coincidencia.
    Lista de módulos vacía en la cuenta = acceso a todos."""
    mods = cl.get("modulos") or []
    if not mods:
        return True
    acept = (modulo,) if isinstance(modulo, str) else tuple(modulo)
    return any(x in mods for x in acept)


# La sub-pestaña "Sucursales" vive DENTRO de Mtto en la app, así que el acceso a
# Mtto (o sus claves antiguas) también concede sus formularios. Los demás módulos
# dinámicos se conceden por su propia clave.
_MODULO_FORM_ALIAS = {"sucursales": ("sucursales", "mtto", "checklist", "montacargas")}


def _acepta_modulo(modulo):
    return _MODULO_FORM_ALIAS.get(modulo, (modulo,))


def _body(event) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except Exception:
        raise ValueError("Body debe ser JSON válido")


def _req_meta(event) -> dict:
    """Metadatos de la petición sellados por el servidor (el usuario NO los puede
    tocar): IP de origen, user-agent y hora de recepción. Sirven de contraste
    independiente contra el GPS del dispositivo en el reporte de carga."""
    from datetime import datetime, timezone
    http = (event.get("requestContext", {}) or {}).get("http", {}) or {}
    return {
        "sourceIp":   http.get("sourceIp"),
        "userAgent":  http.get("userAgent"),
        "recibidoEn": datetime.now(timezone.utc).isoformat(),
    }


# ── Resolver claves de evidencia → URLs prefirmadas ──────────────
def _resolver_urls(obj):
    if isinstance(obj, str):
        return url_lectura(obj) if _KEY_RE.match(obj) else obj
    if isinstance(obj, dict):
        return {k: _resolver_urls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolver_urls(v) for v in obj]
    return obj


# ── Notificaciones ───────────────────────────────────────────────
def _notificar(asunto: str, mensaje: str):
    if _sns and SNS_ARN:
        try:
            _sns.publish(TopicArn=SNS_ARN, Subject=asunto[:100], Message=mensaje)
        except Exception:
            logger.warning("No se pudo publicar SNS:\n%s", traceback.format_exc())


# ── Router ───────────────────────────────────────────────────────
def lambda_handler(event, context):
    route = event.get("routeKey", "")
    try:
        if route == "GET /health":
            return _resp({"ok": True, "servicio": "gpa-operaciones"})

        cl = _claims(event)

        if route == "GET /catalogos":
            cat = cargar_catalogos()
            # Config de despliegue (NO se persiste en el item CONFIG): viaja inyectada
            # para que el frontend sepa la ventana por defecto de los listados.
            cat.setdefault("config", {})["ventanaDias"] = VENTANA_DIAS
            return _resp(cat)

        # ── Combustible ──
        if route == "POST /combustible":
            return _crear(m.SOL, _body(event), cl,
                          notif=(EMAIL_LOGIS, "Nueva solicitud de combustible"),
                          req_meta=_req_meta(event))
        if route == "GET /combustible":
            return _listar(m.SOL, event, cl)
        if route == "POST /combustible/{id}/estado":
            return _estado(m.SOL, event, cl)
        if route == "POST /combustible/{id}/corregir":
            return _corregir(event, cl)

        # ── Checklist de reparto ──
        if route == "POST /checklist":
            return _crear(m.CL, _body(event), cl,
                          notif=(EMAIL_RIESGO, "Nuevo checklist de reparto"))
        if route == "GET /checklist":
            return _listar(m.CL, event, cl)

        # ── Montacargas ──
        if route == "POST /montacargas":
            return _crear(m.MC, _body(event), cl,
                          notif=(EMAIL_RIESGO, "Nuevo checklist de montacargas"))
        if route == "GET /montacargas":
            return _listar(m.MC, event, cl)
        if route == "POST /montacargas/{id}/estado":
            return _estado(m.MC, event, cl)

        # ── Formularios dinámicos (motor de plantillas) ──
        if route == "POST /formulario":
            return _crear_form(_body(event), cl)
        if route == "GET /formulario":
            return _listar_form(event, cl)
        if route == "POST /formulario/{id}/estado":
            return _estado_form(event, cl)

        # ── Evidencias ──
        if route == "POST /evidencias/url-subida":
            b = _body(event)
            tipo = b.get("tipo", "SOL")
            if tipo not in (m.SOL, m.CL, m.MC, "FRM"):
                return _err("tipo inválido")
            return _resp(url_subida(tipo, b.get("contentType", "image/jpeg")))

        # ── Admin (solo rol admin) ──
        if route.startswith("POST /admin/") or route == "GET /admin/cuentas":
            if cl["rol"] != "admin":
                return _err("Requiere rol admin", 403)
            if route == "GET /admin/cuentas":
                return _resp({"items": listar_cuentas()})
            if route == "POST /admin/cuenta":
                b = _body(event)
                res = guardar_cuenta(b)
                # Responsable de alertas (catálogo CAT#RESPONSABLE). Solo se toca si
                # el panel envía el campo (p. ej. no lo manda el toggle activo/inactivo).
                if "responsableAlerta" in b:
                    guardar_responsable_alerta(res.get("email") or b.get("email", ""),
                                               b.get("responsableAlerta"))
                return _resp(res)
            if route == "POST /admin/reasignar-unidad":
                return _reasignar_unidad(_body(event), cl)
            return _admin(route, _body(event))

        return _err(f"Ruta no encontrada: {route}", 404)

    except ValueError as e:
        return _err(str(e), 400)
    except Exception as exc:
        logger.error("Error:\n%s", traceback.format_exc())
        return _err(f"Error interno: {exc}", 500)


# ── Operaciones de registro ──────────────────────────────────────
def _validar_medidor(tipo, datos, cl):
    """Bloqueo AUTORITATIVO de odómetro/horómetro, comparando contra la lectura
    REAL de la unidad (todo el historial, no solo lo del operador):
      · combustible (SOL) y checklist (CL) → km vs último km (historial SOL+CL,
        odómetro compartido entre ambos módulos).
      · montacargas (MC) → horas vs últimas horas (solo si el equipo está Activo).
    Un admin puede saltarlo con datos['forzar']=True (corrección).
    Devuelve mensaje de error o None."""
    if datos.get("forzar") and cl["rol"] == "admin":
        return None                       # override explícito de admin
    vid = str(datos.get("vehicleId") or "")
    if not vid:
        return None
    if tipo in (m.SOL, m.CL):
        if datos.get("km") in (None, ""):
            return None
        ult = ultimo_medidor_por_vehiculo([m.SOL, m.CL], "km").get(vid)
        if not ult:
            return None                   # primera lectura de la unidad
        comb = datos.get("combustible") or (get_vehiculo(vid) or {}).get("combustible")
        return m.evaluar_km(datos.get("km"), ult["valor"], comb)
    if tipo == m.MC:
        if datos.get("estatus") not in (None, "Activo"):
            return None                   # equipo inactivo: no se exige horómetro
        if datos.get("horas") in (None, "", 0):
            return None
        ult = ultimo_medidor_por_vehiculo([m.MC], "horas").get(vid)
        if not ult:
            return None
        return m.evaluar_horas(datos.get("horas"), ult["valor"])
    return None


def _crear(tipo, datos, cl, notif=None, req_meta=None):
    if cl["rol"] == "analista":
        return _err("El analista no captura registros", 403)
    if not _modulo_ok(cl, MODULO[tipo]):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    # Reporte de carga SOLO con asignación: debe existir una solicitud de la
    # unidad APROBADA y SIN reporte previo (relación 1 a 1). Se vincula por folio
    # (regla autoritativa; el cliente solo avisa).
    if tipo == m.SOL and datos.get("formato") == "reporte":
        asignable = solicitud_asignable_vehiculo(datos.get("vehicleId"))
        if not asignable:
            ult = ultima_solicitud_vehiculo(datos.get("vehicleId"))
            if not ult:
                motivo = "no existe una solicitud de combustible para esta unidad"
            elif ult.get("status") == "Rechazada":
                motivo = "la solicitud está RECHAZADA"
            elif ult.get("status") != "Aprobada":
                motivo = "la solicitud sigue PENDIENTE de autorización"
            else:
                motivo = "la solicitud aprobada de esta unidad ya tiene un reporte de carga"
            return _err(f"No se puede enviar el reporte: {motivo}. Se requiere una "
                        "solicitud APROBADA y sin reporte (asignación).", 422)
        # Vínculo 1 a 1: el reporte guarda el id y el folio de la solicitud aprobada.
        datos["solicitudId"] = asignable.get("id")
        datos["folioSolicitud"] = ("SOL-" + str(asignable.get("id"))).upper()
        # Candados de la carga: litros ≤ capacidad del tanque; precio/L en (0, 100].
        try:
            litros = float(datos.get("litros") or 0)
            precio_l = float(datos.get("precioLitro") or 0)
        except (TypeError, ValueError):
            return _err("Litros o precio por litro inválidos.", 422)
        if litros <= 0:
            return _err("Los litros cargados deben ser mayores a 0.", 422)
        cap = float((get_vehiculo(str(datos.get("vehicleId") or "")) or {}).get("tanque") or 0)
        if cap > 0 and litros > cap:
            return _err(f"Los litros cargados ({litros:g} L) exceden la capacidad del tanque "
                        f"de la unidad ({cap:g} L).", 422)
        if precio_l <= 0 or precio_l > 100:
            return _err("El precio por litro debe ser mayor a $0 y no exceder $100.", 422)
    err_medidor = _validar_medidor(tipo, datos, cl)
    if err_medidor:
        return _err(err_medidor, 422)
    # Si un admin forzó la captura fuera de rango, se deja rastro y no se
    # persiste la bandera cruda.
    if datos.pop("forzar", None) and cl["rol"] == "admin":
        datos["kmForzadoPor"] = cl["email"]
    sucursal = datos.get("sucursal") or cl["sucursal"] or "SIN_SUCURSAL"
    # Reporte de carga: sella los metadatos del servidor bajo _auditoria.servidor.
    # Se pone al final para que el cliente NO pueda sobrescribir el bloque servidor.
    if tipo == m.SOL and datos.get("formato") == "reporte" and req_meta:
        aud = dict(datos.get("_auditoria") or {})
        aud["servidor"] = req_meta
        datos = {**datos, "_auditoria": aud}
    # Análisis de foto puede llegar después; lo separamos del cuerpo principal
    res = crear_registro(tipo, datos, sucursal, cl["email"])
    if notif:
        email_dest, asunto = notif
        _notificar(asunto, _texto_notif(tipo, datos, sucursal, cl, res["id"], email_dest))
    return _resp({**res, "ok": True})


def _listar(tipo, event, cl):
    if not _modulo_ok(cl, MODULO[tipo]):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    desde, hasta_excl = _rango_listado(event)
    regs = listar_registros(tipo, cl["rol"], cl["sucursales"], cl["email"], desde, hasta_excl)
    # El bloque _auditoria es solo para el back office (y Fleet Command vía el
    # puente, que lo lee del stream): el operador que capturó no lo recibe.
    oculta_aud = cl["rol"] == "operador"
    items = []
    for r in regs:
        if oculta_aud and isinstance(r, dict) and "_auditoria" in r:
            r = {k: v for k, v in r.items() if k != "_auditoria"}
        items.append(_resolver_urls(r))
    return _resp_gz({"items": items}, event)


# Estados permitidos al autorizar (whitelist; femenino=combustible, masculino=MC/FRM).
# "Por corregir" solo aplica a combustible (SOL); "Anulado" lo fija la reasignación
# internamente (no por esta vía).
_ESTADOS_OK = ("Pendiente", "Aprobada", "Rechazada", "Aprobado", "Rechazado", "Por corregir")


def _veto_estado(cl, reg) -> str | None:
    """Reglas de autorización sobre UN registro (además del rol):
    · supervisor restringido → solo registros de SUS sucursales;
    · nadie (salvo admin) autoriza sus PROPIAS capturas."""
    if cl["rol"] == "supervisor" and cl["sucursales"] and \
            reg.get("sucursal") not in cl["sucursales"]:
        return "Este registro es de otra sucursal (fuera de tu alcance)."
    if cl["rol"] != "admin" and reg.get("accountId") == cl["email"]:
        return "No puedes autorizar tus propias capturas; pide a otro autorizador (solo un administrador puede)."
    return None


def _estado(tipo, event, cl):
    if cl["rol"] not in ("admin", "analista", "supervisor"):
        return _err("No autorizado para cambiar estado", 403)
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    b = _body(event)
    nuevo = b.get("status")
    if not nuevo:
        return _err("Falta status")
    if nuevo not in _ESTADOS_OK:
        return _err("Estado inválido", 400)
    reg = get_registro(tipo, rid)
    if not reg:
        return _err("Registro no encontrado", 404)
    veto = _veto_estado(cl, reg)
    if veto:
        return _err(veto, 403)
    campos = None
    if nuevo == "Por corregir":
        # Solo combustible; solo registros NO autorizados (ni anulados).
        if tipo != m.SOL:
            return _err("El estado «Por corregir» solo aplica a combustible.", 400)
        est_actual = str(reg.get("status") or "")
        if est_actual == "Aprobada":
            return _err("No se puede marcar «Por corregir» un registro ya autorizado.", 409)
        if est_actual == "Anulado":
            return _err("El registro está anulado.", 409)
        campos = [str(c) for c in (b.get("campos") or b.get("camposCorregir") or [])
                  if str(c).strip()]
        if not campos:
            return _err("Indica al menos un campo a corregir.", 400)
    cambiar_estado(tipo, rid, nuevo, cl["nombre"] or cl["email"],
                   (b.get("comentario") or "").strip(), campos)
    return _resp({"ok": True, "status": nuevo})


# Campos derivados que acompañan a un campo corregible (se recalculan en servidor).
_CORREGIR_DERIVADOS = {
    "tankBefore":  ("litros", "monto", "necesidad", "tankAfter"),
    "litros":      ("monto",),
    "precioLitro": ("monto",),
}


def _corregir(event, cl):
    """Aplica la corrección de un registro de combustible marcado «Por corregir».
    La hace quien lo capturó (o un admin); solo edita los campos que el autorizador
    marcó en `camposCorregir`; al enviar el registro vuelve a «Pendiente»."""
    if cl["rol"] == "analista":
        return _err("El analista no captura registros", 403)
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    reg = get_registro(m.SOL, rid)
    if not reg:
        return _err("Registro no encontrado", 404)
    if str(reg.get("status") or "") != "Por corregir":
        return _err("El registro no está en estado «Por corregir».", 409)
    if cl["rol"] != "admin" and reg.get("accountId") != cl["email"]:
        return _err("Solo quien capturó el registro (o un admin) puede corregirlo.", 403)
    permitidos = {str(c) for c in (reg.get("camposCorregir") or [])}
    if not permitidos:
        return _err("El registro no tiene campos marcados para corregir.", 409)
    for base, comps in _CORREGIR_DERIVADOS.items():
        if base in permitidos:
            permitidos.update(comps)
    b = _body(event)
    entrada = dict(b.get("datos") or {})
    parche = {k: v for k, v in entrada.items() if k in permitidos}
    if not parche:
        return _err("No se enviaron cambios en los campos marcados.", 400)
    es_reporte = reg.get("formato") == "reporte"
    # Revalidación de candados (km / litros ≤ tanque / precio ≤ 100) sobre el combinado.
    if "km" in parche:
        combinado = {**reg, **parche, "forzar": b.get("forzar")}
        err = _validar_medidor(m.SOL, combinado, cl)
        if err:
            return _err(err, 422)
    if es_reporte and ("litros" in parche or "precioLitro" in parche):
        try:
            litros = float(parche.get("litros", reg.get("litros")) or 0)
            precio = float(parche.get("precioLitro", reg.get("precioLitro")) or 0)
        except (TypeError, ValueError):
            return _err("Litros o precio por litro inválidos.", 422)
        if litros <= 0:
            return _err("Los litros cargados deben ser mayores a 0.", 422)
        cap = float((get_vehiculo(str(reg.get("vehicleId") or "")) or {}).get("tanque") or 0)
        if cap > 0 and litros > cap:
            return _err(f"Los litros cargados ({litros:g} L) exceden la capacidad del "
                        f"tanque de la unidad ({cap:g} L).", 422)
        if precio <= 0 or precio > 100:
            return _err("El precio por litro debe ser mayor a $0 y no exceder $100.", 422)
        parche["monto"] = round(litros * precio, 2)
    elif (not es_reporte) and "tankBefore" in parche:
        try:
            tank = float(parche.get("tankBefore") or 0)
        except (TypeError, ValueError):
            return _err("Nivel de tanque inválido.", 422)
        cap = float(reg.get("tanque") or 0)
        precio = float(reg.get("precio") or 0)
        need = max(0.0, 1 - tank)
        litros = round(cap * need)
        parche.update({"litros": litros, "monto": round(litros * precio),
                       "necesidad": need, "tankAfter": 1})
    corregir_registro(m.SOL, rid, parche, cl["nombre"] or cl["email"])
    return _resp({"ok": True, "status": "Pendiente"})


# ── Formularios dinámicos (motor de plantillas) ──────────────────
def _plantilla_activa(clave):
    """Devuelve la plantilla activa o lanza ValueError si no existe / inactiva."""
    if not clave:
        raise ValueError("Falta la clave del formulario")
    plt = get_plantilla(str(clave).strip().lower())
    if not plt:
        raise ValueError("Formulario no encontrado")
    if not plt.get("activo", True):
        raise ValueError("Formulario inactivo")
    return plt


def _crear_form(body, cl):
    if cl["rol"] == "analista":
        return _err("El analista no captura registros", 403)
    plt = _plantilla_activa(body.get("plantillaClave"))
    if not _modulo_ok(cl, _acepta_modulo(plt.get("modulo"))):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    datos = dict(body.get("datos") or {})
    datos["plantillaClave"] = plt["clave"]
    datos["plantillaNombre"] = plt.get("nombre") or plt["clave"]
    datos["modulo"] = plt.get("modulo")
    datos["solicitante"] = cl["nombre"] or cl["email"]
    datos["status"] = "Pendiente" if plt.get("requiereAutorizacion") else "Aprobado"
    sucursal = datos.get("sucursal") or cl["sucursal"] or "SIN_SUCURSAL"
    res = crear_registro(m.tipo_formulario(plt["clave"]), datos, sucursal, cl["email"])
    return _resp({**res, "ok": True, "status": datos["status"]})


def _listar_form(event, cl):
    clave = (event.get("queryStringParameters") or {}).get("clave")
    plt = _plantilla_activa(clave)
    if not _modulo_ok(cl, _acepta_modulo(plt.get("modulo"))):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    desde, hasta_excl = _rango_listado(event)
    regs = listar_registros(m.tipo_formulario(plt["clave"]),
                            cl["rol"], cl["sucursales"], cl["email"], desde, hasta_excl)
    return _resp_gz({"items": [_resolver_urls(r) for r in regs]}, event)


def _estado_form(event, cl):
    if cl["rol"] not in ("admin", "analista", "supervisor"):
        return _err("No autorizado para cambiar estado", 403)
    clave = (event.get("queryStringParameters") or {}).get("clave")
    plt = _plantilla_activa(clave)
    tipo = m.tipo_formulario(plt["clave"])
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    b = _body(event)
    nuevo = b.get("status")
    if not nuevo:
        return _err("Falta status")
    if nuevo not in _ESTADOS_OK:
        return _err("Estado inválido", 400)
    reg = get_registro(tipo, rid)
    if not reg:
        return _err("Registro no encontrado", 404)
    veto = _veto_estado(cl, reg)
    if veto:
        return _err(veto, 403)
    cambiar_estado(tipo, rid, nuevo, cl["nombre"] or cl["email"], (b.get("comentario") or "").strip())
    return _resp({"ok": True, "status": nuevo})


def _texto_notif(tipo, datos, sucursal, cl, rid, email_dest):
    etiqueta = {m.SOL: "Solicitud de combustible",
                m.CL:  "Checklist de reparto",
                m.MC:  "Checklist de montacargas"}[tipo]
    lineas = [
        f"{etiqueta} nueva (#{rid})",
        f"Sucursal: {sucursal}",
        f"Vehículo: {datos.get('placas','—')}  #{datos.get('economico','—')}",
        f"Capturó: {cl['nombre']} ({cl['email']})",
    ]
    if tipo == m.SOL:
        lineas.append(f"Litros: {datos.get('litros','—')}  ·  Monto: ${datos.get('monto','—')}")
    lineas.append(f"\nAviso dirigido a: {email_dest}")
    return "\n".join(lineas)


# ── Admin ────────────────────────────────────────────────────────
def _reasignar_unidad(b, cl):
    """Corrección de admin: mueve un registro (SOL/CL/MC) a otra unidad.
    Solo cambia la identidad de la unidad en el registro (+ índice por sucursal);
    los datos capturados no se alteran y queda rastro en `reasignacion`."""
    tipo = b.get("tipo")
    if tipo not in (m.SOL, m.CL, m.MC):
        return _err("tipo inválido (SOL/CL/MC)")
    rid = str(b.get("id") or "").strip()
    if not rid:
        return _err("Falta el id del registro")
    veh = get_vehiculo(str(b.get("vehicleId") or "").strip())
    if not veh:
        return _err("Unidad destino no encontrada", 404)
    res = reasignar_registro_unidad(tipo, rid, veh, cl["email"])
    return _resp(res)


def _admin(route, body):
    if route == "POST /admin/vehiculo":
        guardar_vehiculo(body)
    elif route == "POST /admin/responsable":
        guardar_responsable(body)
    elif route == "POST /admin/sucursal":
        if body.get("eliminar"):
            eliminar_sucursal(body["nombre"])
        else:
            guardar_sucursal(body["nombre"])
    elif route == "POST /admin/config":
        guardar_config(body)
    elif route == "POST /admin/precio-combustible":
        comb = body.get("combustible")
        precio = body.get("precio")
        if not comb or precio is None:
            return _err("Faltan 'combustible' y 'precio'")
        n = actualizar_precio_por_combustible(comb, precio)
        return _resp({"ok": True, "actualizados": n})
    elif route == "POST /admin/modulo":
        return _resp(guardar_modulo(body))
    elif route == "POST /admin/plantilla":
        return _resp(guardar_plantilla(body))
    else:
        return _err("Ruta admin no encontrada", 404)
    return _resp({"ok": True})
