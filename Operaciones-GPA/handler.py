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
#   POST  /evidencias/url-subida        URL prefirmada para subir foto/firma
#   POST  /admin/vehiculo|responsable|sucursal|config   (solo admin)
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json, os, re, logging, traceback

from db import modelos as m
from db.escritura import (crear_registro, cambiar_estado,
                          guardar_vehiculo, guardar_responsable,
                          guardar_sucursal, eliminar_sucursal, guardar_config,
                          actualizar_precio_por_combustible)
from db.queries import listar_registros, get_registro, cargar_catalogos
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
_KEY_RE = re.compile(r"^(SOL|CL|MC)/[0-9a-f]{32}\.(jpg|png|webp)$")


# ── Respuestas ───────────────────────────────────────────────────
def _resp(body, status=200):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": ORIGIN},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _err(msg, status=400):
    return _resp({"error": msg}, status)


# ── Claims del JWT de Cognito ────────────────────────────────────
def _csv(x):
    return [s.strip() for s in (x or "").split(",") if s.strip()]


# Mapa tipo de registro → nombre de módulo (para el control de acceso)
MODULO = {m.SOL: "combustible", m.CL: "checklist", m.MC: "montacargas"}


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
    mods = cl.get("modulos") or []
    return (not mods) or (modulo in mods)


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
            return _resp({"ok": True, "servicio": "gpa-operaciones"})

        cl = _claims(event)

        if route == "GET /catalogos":
            return _resp(cargar_catalogos())

        # ── Combustible ──
        if route == "POST /combustible":
            return _crear(m.SOL, _body(event), cl,
                          notif=(EMAIL_LOGIS, "Nueva solicitud de combustible"))
        if route == "GET /combustible":
            return _listar(m.SOL, cl)
        if route == "POST /combustible/{id}/estado":
            return _estado(m.SOL, event, cl)

        # ── Checklist de reparto ──
        if route == "POST /checklist":
            return _crear(m.CL, _body(event), cl,
                          notif=(EMAIL_RIESGO, "Nuevo checklist de reparto"))
        if route == "GET /checklist":
            return _listar(m.CL, cl)

        # ── Montacargas ──
        if route == "POST /montacargas":
            return _crear(m.MC, _body(event), cl,
                          notif=(EMAIL_RIESGO, "Nuevo checklist de montacargas"))
        if route == "GET /montacargas":
            return _listar(m.MC, cl)
        if route == "POST /montacargas/{id}/estado":
            return _estado(m.MC, event, cl)

        # ── Evidencias ──
        if route == "POST /evidencias/url-subida":
            b = _body(event)
            tipo = b.get("tipo", "SOL")
            if tipo not in (m.SOL, m.CL, m.MC):
                return _err("tipo inválido")
            return _resp(url_subida(tipo, b.get("contentType", "image/jpeg")))

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


# ── Operaciones de registro ──────────────────────────────────────
def _crear(tipo, datos, cl, notif=None):
    if cl["rol"] == "analista":
        return _err("El analista no captura registros", 403)
    if not _modulo_ok(cl, MODULO[tipo]):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    sucursal = datos.get("sucursal") or cl["sucursal"] or "SIN_SUCURSAL"
    # Análisis de foto puede llegar después; lo separamos del cuerpo principal
    res = crear_registro(tipo, datos, sucursal, cl["email"])
    if notif:
        email_dest, asunto = notif
        _notificar(asunto, _texto_notif(tipo, datos, sucursal, cl, res["id"], email_dest))
    return _resp({**res, "ok": True})


def _listar(tipo, cl):
    if not _modulo_ok(cl, MODULO[tipo]):
        return _err("Tu cuenta no tiene acceso a este módulo", 403)
    regs = listar_registros(tipo, cl["rol"], cl["sucursales"], cl["email"])
    return _resp({"items": [_resolver_urls(r) for r in regs]})


def _estado(tipo, event, cl):
    if cl["rol"] not in ("admin", "analista", "supervisor"):
        return _err("No autorizado para cambiar estado", 403)
    rid = (event.get("pathParameters") or {}).get("id")
    if not rid:
        return _err("Falta id")
    nuevo = _body(event).get("status")
    if not nuevo:
        return _err("Falta status")
    if not get_registro(tipo, rid):
        return _err("Registro no encontrado", 404)
    cambiar_estado(tipo, rid, nuevo, cl["nombre"] or cl["email"])
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
    else:
        return _err("Ruta admin no encontrada", 404)
    return _resp({"ok": True})
