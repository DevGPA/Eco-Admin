# handler.py — GPA ViaticOS
# Lambda — API Gateway HTTP API v2 (router por routeKey)
# ─────────────────────────────────────────────────────────────────
# Rutas:
#   GET   /health                      health check (sin auth)
#   GET   /catalogos                   empleados, áreas, política POL-TE01, tarifas
#   POST  /solicitudes                 crear solicitud de viáticos (empleado)
#   GET   /solicitudes                 listar (según rol)
#   GET   /solicitudes/{id}            detalle
#   POST  /solicitudes/{id}/estado     aprobar / rechazar (supervisor)
#   POST  /solicitudes/{id}/paso       avanzar etapa del flujo (datos + estado)
#   GET   /cotizador/vuelos            opciones de vuelo rankeadas (compras)
#   POST  /cotizador/rankear           ordenar opciones capturadas a mano (compras)
#   POST  /evidencias/url-subida       URL prefirmada para subir CFDI/ticket/firma
#   POST  /admin/empleado|area|politica|tarifas|config   (solo admin)
#   GET   /admin/cuentas · POST /admin/cuenta            (solo admin)
#
# Flujo POL-TE01 (estado → etapa → rol que lo fija):
#   Solicitada(1) empleado · Aprobada/Rechazada(2) supervisor ·
#   TransporteCotizado(3) compras · AnticipoLiberado(4) tesorería ·
#   EnComprobacion(5) empleado · Validada(6) finanzas ·
#   Revisada(7) supervisor · Cerrada(8) finanzas · Reembolsada(9) finanzas
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json, os, re, logging, traceback

from db.escritura import (crear_solicitud, cambiar_estado, aplicar_paso,
                          guardar_empleado, guardar_area, eliminar_area,
                          guardar_politica, guardar_tarifas, guardar_config)
from db.queries import listar_solicitudes, get_solicitud, cargar_catalogos
from s3.evidencias import url_subida, url_lectura
from auth_cognito import listar_cuentas, guardar_cuenta
from cotizador import buscar_vuelos, rankear

try:
    import boto3
    _sns = boto3.client("sns")
except Exception:           # pragma: no cover
    _sns = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ORIGIN        = os.environ.get("ALLOWED_ORIGIN", "*")
SNS_ARN       = os.environ.get("SNS_NOTIF_ARN", "")
EMAIL_FINANZAS  = os.environ.get("EMAIL_FINANZAS", "")
EMAIL_TESORERIA = os.environ.get("EMAIL_TESORERIA", "")

# Patrón de una clave de evidencia en S3 (para resolver a URL prefirmada al leer)
_KEY_RE = re.compile(r"^(FIRMA|CFDI|TICKET|VIA)/[0-9a-f]{32}\.(jpg|png|webp|pdf|xml)$")

# ── Máquina de estados ───────────────────────────────────────────
# estado destino → (etapa, roles autorizados, ¿notificar?)
FLUJO = {
    "Aprobada":           (2, {"supervisor", "admin"}),
    "Rechazada":          (2, {"supervisor", "finanzas", "admin"}),
    "TransporteCotizado": (3, {"compras", "admin"}),
    "AnticipoLiberado":   (4, {"tesoreria", "admin"}),
    "EnComprobacion":     (5, {"empleado", "admin"}),
    "Validada":           (6, {"finanzas", "admin"}),
    "Revisada":           (7, {"supervisor", "admin"}),
    "Cerrada":            (8, {"finanzas", "admin"}),
    "Reembolsada":        (9, {"finanzas", "admin"}),
}


# ── Respuestas ───────────────────────────────────────────────────
def _resp(body, status=200):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": ORIGIN},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _err(msg, status=400):
    return _resp({"error": msg}, status)


# ── Claims del JWT de Cognito ────────────────────────────────────
def _claims(event) -> dict:
    c = (event.get("requestContext", {}).get("authorizer", {})
              .get("jwt", {}).get("claims", {})) or {}
    return {
        "email":  c.get("email") or c.get("cognito:username") or "desconocido",
        "rol":    c.get("custom:rol", "empleado"),
        "area":   c.get("custom:area") or None,
        "nombre": c.get("custom:nombre") or c.get("email") or "",
    }


def _body(event) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except Exception:
        raise ValueError("Body debe ser JSON válido")


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
            return _resp({"ok": True, "servicio": "gpa-viaticos"})

        cl = _claims(event)

        if route == "GET /catalogos":
            return _resp(cargar_catalogos())

        # ── Solicitudes ──
        if route == "POST /solicitudes":
            return _crear(_body(event), cl)
        if route == "GET /solicitudes":
            return _listar(cl)
        if route == "GET /solicitudes/{id}":
            return _detalle(event)
        if route == "POST /solicitudes/{id}/estado":
            return _estado(event, cl)
        if route == "POST /solicitudes/{id}/paso":
            return _paso(event, cl)

        # ── Cotizador de vuelos (compras) ──
        if route == "GET /cotizador/vuelos":
            return _cotizar_vuelos(event, cl)
        if route == "POST /cotizador/rankear":
            return _rankear_manual(event, cl)

        # ── Evidencias ──
        if route == "POST /evidencias/url-subida":
            b = _body(event)
            return _resp(url_subida(b.get("carpeta", "VIA"),
                                    b.get("contentType", "image/jpeg")))

        # ── Admin (solo rol admin) ──
        if route.startswith("POST /admin/") or route == "GET /admin/cuentas":
            if cl["rol"] != "admin":
                return _err("Requiere rol admin", 403)
            if route == "GET /admin/cuentas":
                return _resp({"items": listar_cuentas()})
            if route == "POST /admin/cuenta":
                return _resp(guardar_cuenta(_body(event)))
            return _admin(route, _body(event))

        return _err(f"Ruta no encontrada: {route}", 404)

    except ValueError as e:
        return _err(str(e), 400)
    except Exception as exc:
        logger.error("Error:\n%s", traceback.format_exc())
        return _err(f"Error interno: {exc}", 500)


# ── Operaciones de solicitud ─────────────────────────────────────
def _crear(datos, cl):
    if cl["rol"] not in ("empleado", "supervisor", "admin"):
        return _err("Este rol no captura solicitudes", 403)
    area = datos.get("area") or cl["area"] or "SIN_AREA"
    res = crear_solicitud(datos, cl["email"], area, cl["nombre"])
    _notificar("Nueva solicitud de viáticos",
               f"Solicitud {res['folio']} creada por {cl['nombre']} ({cl['email']}).\n"
               f"Área: {area}. Destino: {datos.get('destino','—')}.\n"
               f"Requiere aprobación del supervisor.")
    return _resp({**res, "ok": True})


def _listar(cl):
    regs = listar_solicitudes(cl["rol"], cl["area"], cl["email"])
    return _resp({"items": [_resolver_urls(r) for r in regs]})


def _detalle(event):
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    sol = get_solicitud(rid)
    if not sol:
        return _err("Solicitud no encontrada", 404)
    return _resp(_resolver_urls(sol))


def _estado(event, cl):
    """Aprobar / rechazar (atajo). El estado debe existir en FLUJO."""
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    nuevo = _body(event).get("estado")
    if nuevo not in FLUJO:
        return _err("Estado inválido")
    etapa, roles = FLUJO[nuevo]
    if cl["rol"] not in roles:
        return _err(f"El rol '{cl['rol']}' no puede fijar el estado '{nuevo}'", 403)
    if not get_solicitud(rid):
        return _err("Solicitud no encontrada", 404)
    cambiar_estado(rid, nuevo, etapa, cl["nombre"] or cl["email"])
    _notif_estado(rid, nuevo, cl)
    return _resp({"ok": True, "estado": nuevo, "etapa": etapa})


def _paso(event, cl):
    """
    Avanza una etapa del flujo guardando sus datos.
    Body: { estado?: str, datos?: {...} }
      - estado: estado destino (debe estar en FLUJO y el rol debe poder fijarlo)
      - datos:  campos de la etapa (transporte elegido, anticipo, comprobantes, etc.)
    """
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    if not get_solicitud(rid):
        return _err("Solicitud no encontrada", 404)
    b = _body(event)
    nuevo = b.get("estado")
    datos = b.get("datos") or {}
    etapa = None
    if nuevo:
        if nuevo not in FLUJO:
            return _err("Estado inválido")
        etapa, roles = FLUJO[nuevo]
        if cl["rol"] not in roles:
            return _err(f"El rol '{cl['rol']}' no puede fijar el estado '{nuevo}'", 403)
    elif not datos:
        return _err("Nada que actualizar (faltan estado y datos)")
    aplicar_paso(rid, datos, nuevo, etapa, cl["nombre"] or cl["email"])
    if nuevo:
        _notif_estado(rid, nuevo, cl)
    return _resp({"ok": True, "estado": nuevo, "etapa": etapa})


# ── Cotizador de vuelos ──────────────────────────────────────────
_ROLES_COTIZA = {"compras", "admin"}


def _cotizar_vuelos(event, cl):
    """Busca vuelos con el proveedor activo (Duffel si hay token; si no, manual)."""
    if cl["rol"] not in _ROLES_COTIZA:
        return _err("Solo Compras puede cotizar transporte", 403)
    q = event.get("queryStringParameters") or {}
    return _resp(buscar_vuelos(q.get("origen", "GDL"), q.get("destino", ""),
                               q.get("fecha", ""), q.get("regreso", "")))


def _rankear_manual(event, cl):
    """Ordena opciones capturadas a mano con el mismo criterio del sistema."""
    if cl["rol"] not in _ROLES_COTIZA:
        return _err("Solo Compras puede cotizar transporte", 403)
    ops = _body(event).get("opciones")
    if not isinstance(ops, list) or not ops:
        return _err("Manda al menos una opción en 'opciones'")
    return _resp({"opciones": rankear(ops)})


def _notif_estado(rid, estado, cl):
    destinos = {
        "AnticipoLiberado": EMAIL_TESORERIA,
        "Cerrada":          EMAIL_FINANZAS,
        "Reembolsada":      EMAIL_FINANZAS,
    }
    if estado in destinos:
        _notificar(f"ViaticOS: solicitud {estado}",
                   f"La solicitud {rid} pasó a estado '{estado}' "
                   f"(por {cl['nombre'] or cl['email']}).")


# ── Admin ────────────────────────────────────────────────────────
def _admin(route, body):
    if route == "POST /admin/empleado":
        guardar_empleado(body)
    elif route == "POST /admin/area":
        if body.get("eliminar"):
            eliminar_area(body["nombre"])
        else:
            guardar_area(body["nombre"], {k: v for k, v in body.items() if k != "nombre"})
    elif route == "POST /admin/politica":
        guardar_politica(body)
    elif route == "POST /admin/tarifas":
        guardar_tarifas(body)
    elif route == "POST /admin/config":
        guardar_config(body)
    else:
        return _err("Ruta admin no encontrada", 404)
    return _resp({"ok": True})
