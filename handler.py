# handler.py — GPA Alta de Clientes
# Lambda única detrás de API Gateway HTTP API v2. Router por routeKey.
# ─────────────────────────────────────────────────────────────────
# SIN AUTENTICACIÓN (el cliente externo: liga + clave, nunca una cuenta)
#   GET   /health                  vivo
#   GET   /catalogos               régimen SAT, tipos, módulos, documentos
#   POST  /portal/entrar           {token, clave} → su expediente
#   POST  /portal/guardar          {token, clave, valores, tablas}
#   POST  /portal/url-subida       {token, clave, docId, contentType, tam}
#   POST  /portal/adjuntar         {token, clave, docId, nombre, key}
#   POST  /portal/enviar           {token, clave}
#
# CON COGNITO (usuarios de GPA)
#   GET   /casos                          bandeja
#   POST  /casos                          crear pre-solicitud → liga + clave
#   GET   /casos/{folio}                  expediente completo
#   GET   /casos/{folio}/bitacora         quién hizo qué
#   POST  /casos/{folio}/clave            generar clave nueva
#   POST  /casos/{folio}/revision         marcar documento o señalar campo
#   POST  /casos/{folio}/devolver         regresárselo al cliente
#   POST  /casos/{folio}/autorizacion     pasar a firmas
#   POST  /casos/{folio}/firmar           {nivel, correoFirmante}
#   POST  /casos/{folio}/rechazar         {motivo}
#   GET   /usuarios · POST /usuarios      panel de usuarios (solo Administrador)
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import logging
import os
import traceback

from catalogos import (TIPOS, ESTADOS, catalogos_publicos, puede, avance,
                       docs_aplicables, persona_de, conflicto_regimen_rfc)
from db.escritura import (ReglaRota, crear_caso, regenerar_clave, verificar_clave,
                          guardar_captura, registrar_adjunto, enviar_expediente,
                          marcar_documento, señalar_campo, devolver,
                          pasar_a_autorizacion, pendientes_para_autorizar,
                          firmar, rechazar, campos_permitidos)
from db.queries import get_caso, listar_casos, bitacora, resumen_bandeja
from db.modelos import dias_desde
from s3.documentos import DocumentoInvalido, url_subida, resuelve_urls
import auth_cognito

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


# ── Respuestas ───────────────────────────────────────────────────
def _resp(body, status: int = 200):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _err(mensaje: str, status: int = 400):
    """El mensaje es para leerse tal cual en pantalla, no un código técnico."""
    return _resp({"error": mensaje}, status)


def _body(event) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return {}


def _claims(event) -> dict:
    return ((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt", {}).get("claims", {}) or {}


def _param(event, nombre: str, defecto: str = "") -> str:
    return (event.get("pathParameters") or {}).get(nombre) or defecto


def _query(event, nombre: str, defecto: str = "") -> str:
    return (event.get("queryStringParameters") or {}).get(nombre) or defecto


# ── Proyección para el cliente externo ───────────────────────────
def _vista_cliente(caso: dict) -> dict:
    """Lo que el cliente puede ver de su propio expediente.

    Se arma por lista blanca: así un campo interno nuevo no se filtra solo.
    """
    persona = persona_de(caso.get("regimen"), caso.get("rfc"))
    con_urls = resuelve_urls(caso)
    marcas_publicas = {}
    for k, v in (caso.get("marcas") or {}).items():
        if isinstance(v, dict) and v.get("motivo"):
            marcas_publicas[k] = {"motivo": v["motivo"]}       # sin quién ni cuándo
    return {
        "folio": caso.get("folio"),
        "tipo": caso.get("tipo"),
        "tipoNombre": (TIPOS.get(caso.get("tipo")) or TIPOS["alta"])["nombre"],
        "estado": caso.get("estado"),
        "razonSocial": caso.get("razonSocial"),
        "nombreComercial": caso.get("nombreComercial"),
        "rfc": caso.get("rfc"),
        "regimen": caso.get("regimen"),
        "persona": persona,
        "contacto": caso.get("contacto"),
        "modulos": caso.get("modulos") or {},
        "docs": caso.get("docs") or {},
        "docsAplicables": [d["id"] for d in
                           docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona)],
        "valores": caso.get("valores") or {},
        "tablasVal": caso.get("tablasVal") or {},
        "adjuntos": con_urls.get("adjuntos") or {},
        "marcas": marcas_publicas,
        # El servidor dice qué puede escribir: la pantalla obedece, no decide.
        "camposEditables": sorted(campos_permitidos(caso)),
        "avance": avance(caso),
    }


def _vista_interna(caso: dict) -> dict:
    persona = persona_de(caso.get("regimen"), caso.get("rfc"))
    return {
        **resuelve_urls(caso),
        "persona": persona,
        "avance": avance(caso),
        "dias": dias_desde(caso.get("creado")),
        "docsAplicables": [d["id"] for d in
                           docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona)],
        "pendientesAutorizar": pendientes_para_autorizar(caso),
        "conflictoRfc": conflicto_regimen_rfc(caso.get("regimen"), caso.get("rfc")),
    }


# ── Router ───────────────────────────────────────────────────────
def lambda_handler(event, context):
    ruta = (event.get("routeKey") or "").strip()
    try:
        # ── públicas ──
        if ruta == "GET /health":
            return _resp({"ok": True, "servicio": "gpa-alta-clientes",
                          "env": os.environ.get("ENV", "")})
        if ruta == "GET /catalogos":
            return _resp(catalogos_publicos())
        if ruta.startswith("POST /portal/"):
            return _portal(ruta, _body(event))

        # ── internas ──
        usuario = auth_cognito.usuario_de_claims(_claims(event))
        if not usuario.get("correo"):
            return _err("Su sesión venció. Vuelva a entrar.", 401)
        return _interno(ruta, event, usuario)

    except ReglaRota as e:
        return _err(str(e), 409)
    except DocumentoInvalido as e:
        return _err(str(e), 400)
    except auth_cognito.CuentaInvalida as e:
        return _err(str(e), 400)
    except Exception:
        logger.error("Fallo en %s\n%s", ruta, traceback.format_exc())
        return _err("Algo falló del lado de GPA. Vuelva a intentar; si sigue, "
                    "avise a Administración con el folio a la mano.", 500)


# ── Portal del cliente (liga + clave, sin cuenta) ────────────────
def _portal(ruta: str, datos: dict):
    token = str(datos.get("token") or "").strip()
    clave = str(datos.get("clave") or "")
    if not token:
        return _err("La liga está incompleta. Pida a GPA que se la reenvíe.", 400)
    if not clave:
        return _err("Escriba la clave que le dio GPA.", 400)

    if ruta == "POST /portal/entrar":
        return _resp(_vista_cliente(verificar_clave(token, clave)))

    if ruta == "POST /portal/guardar":
        caso = guardar_captura(token, clave, datos.get("valores") or {},
                               datos.get("tablas") or {})
        vista = _vista_cliente(caso)
        # Si algo no se guardó, se dice aquí mismo, no en silencio.
        if caso.get("descartados"):
            vista["aviso"] = ("Algunos datos no se guardaron porque no forman parte de "
                              "lo que GPA le pidió corregir.")
        return _resp(vista)

    if ruta == "POST /portal/url-subida":
        caso = verificar_clave(token, clave)
        doc_id = str(datos.get("docId") or "")
        persona = persona_de(caso.get("regimen"), caso.get("rfc"))
        pedidos = {d["id"] for d in
                   docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona)}
        if doc_id not in pedidos:
            return _err("Ese documento no se le pidió en esta solicitud.", 400)
        return _resp(url_subida(caso["folio"], doc_id,
                                str(datos.get("contentType") or ""),
                                int(datos.get("tam") or 0)))

    if ruta == "POST /portal/adjuntar":
        return _resp(_vista_cliente(registrar_adjunto(
            token, clave, str(datos.get("docId") or ""),
            str(datos.get("nombre") or ""), str(datos.get("key") or ""))))

    if ruta == "POST /portal/enviar":
        return _resp(_vista_cliente(enviar_expediente(token, clave)))

    return _err("Esa dirección no existe.", 404)


# ── Panel interno ────────────────────────────────────────────────
def _interno(ruta: str, event, usuario: dict):
    rol = usuario["rol"]

    if ruta == "GET /casos":
        casos = listar_casos(_query(event, "estado"), int(_query(event, "limite", "200")))
        return _resp({"casos": resumen_bandeja(casos), "yo": usuario})

    if ruta == "POST /casos":
        if not puede(rol, "crear"):
            return _err(f"Su rol ({rol}) no puede crear pre-solicitudes.", 403)
        caso, clave = crear_caso(_body(event), usuario)
        # La clave viaja UNA sola vez: después solo queda su huella en la base.
        return _resp({"caso": _vista_interna(caso), "clave": clave,
                      "aviso": "Anote o copie la clave ahora: no se vuelve a mostrar."})

    folio = _param(event, "folio")
    if folio:
        caso = get_caso(folio)
        if not caso:
            return _err("No existe ese expediente.", 404)

        if ruta == "GET /casos/{folio}":
            return _resp(_vista_interna(caso))
        if ruta == "GET /casos/{folio}/bitacora":
            return _resp({"bitacora": bitacora(folio)})

        cuerpo = _body(event)

        if ruta == "POST /casos/{folio}/clave":
            if not puede(rol, "crear"):
                return _err(f"Su rol ({rol}) no puede generar claves.", 403)
            return _resp({"clave": regenerar_clave(folio, usuario),
                          "aviso": "Anote o copie la clave ahora: no se vuelve a mostrar."})

        if ruta == "POST /casos/{folio}/revision":
            if not puede(rol, "revisar"):
                return _err(f"Su rol ({rol}) solo permite consultar.", 403)
            if cuerpo.get("campo"):
                return _resp(_vista_interna(
                    señalar_campo(folio, str(cuerpo["campo"]), cuerpo.get("motivo", ""), usuario)))
            return _resp(_vista_interna(marcar_documento(
                folio, str(cuerpo.get("docId") or ""), bool(cuerpo.get("ok")),
                cuerpo.get("motivo", ""), usuario)))

        if ruta == "POST /casos/{folio}/devolver":
            if not puede(rol, "revisar"):
                return _err(f"Su rol ({rol}) solo permite consultar.", 403)
            return _resp(_vista_interna(devolver(folio, usuario)))

        if ruta == "POST /casos/{folio}/autorizacion":
            if not puede(rol, "revisar"):
                return _err(f"Su rol ({rol}) solo permite consultar.", 403)
            return _resp(_vista_interna(pasar_a_autorizacion(folio, usuario)))

        if ruta == "POST /casos/{folio}/firmar":
            if not puede(rol, "autorizar"):
                return _err(f"Su rol ({rol}) no autoriza expedientes.", 403)
            nivel = int(cuerpo.get("nivel") or 0)
            correo = str(cuerpo.get("correoFirmante") or usuario["correo"])
            firmante = auth_cognito.get_usuario(correo)
            if not firmante:
                return _err("Ese usuario ya no existe en el sistema.", 404)
            if not firmante["activo"]:
                return _err(f"{firmante['nombre']} está dado de baja y no puede firmar.", 409)
            return _resp(_vista_interna(firmar(folio, nivel, firmante, usuario)))

        if ruta == "POST /casos/{folio}/rechazar":
            if not puede(rol, "autorizar"):
                return _err(f"Su rol ({rol}) no autoriza expedientes.", 403)
            return _resp(_vista_interna(rechazar(folio, cuerpo.get("motivo", ""), usuario)))

    if ruta == "GET /usuarios":
        if not puede(rol, "usuarios"):
            return _err(f"Su rol ({rol}) no puede administrar usuarios.", 403)
        return _resp({"usuarios": auth_cognito.listar_usuarios(),
                      "firmas": auth_cognito.salud_firmas()})

    if ruta == "POST /usuarios":
        if not puede(rol, "usuarios"):
            return _err(f"Su rol ({rol}) no puede administrar usuarios.", 403)
        guardado = auth_cognito.guardar_usuario(_body(event))
        return _resp({"usuario": guardado, "firmas": auth_cognito.salud_firmas()})

    if ruta == "GET /firmantes":
        return _resp({"nivel1": auth_cognito.elegibles(1), "nivel2": auth_cognito.elegibles(2)})

    return _err("Esa dirección no existe.", 404)
