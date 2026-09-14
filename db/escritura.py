# db/escritura.py — escrituras y reglas de negocio de GPA Alta de Clientes.
# ─────────────────────────────────────────────────────────────────
# Todas las reglas viven aquí, del lado del servidor. El frontend solo avisa;
# nunca es la autoridad (error #1 del catálogo del protocolo GPA).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

from boto3.dynamodb.conditions import Attr

from catalogos import (TIPOS, FIRMAS_REQUERIDAS, ESTADOS, ESTADOS_CERRADOS,
                       ESTADOS_ABIERTOS_AL_CLIENTE, docs_aplicables, persona_de,
                       modulos_activos, campos_de, documento)
from . import tabla, sin_decimales
from .modelos import (SK_META, MAX_INTENTOS, pk_caso, sk_log, llaves_caso, iso_mx,
                      legible_mx, prefijo_folio, arma_folio, nuevo_token, nueva_clave,
                      hash_clave, clave_coincide, limpia_texto, limpia_mapa,
                      id_documento_valido)
from .queries import get_caso


class ReglaRota(Exception):
    """Una regla de negocio impidió la operación. El mensaje es para el usuario."""


# ── Bitácora ─────────────────────────────────────────────────────
def log(folio: str, accion: str, quien: str, detalle: str = "") -> None:
    tabla().put_item(Item={
        "PK": pk_caso(folio), "SK": sk_log(),
        "accion": accion, "quien": quien or "sistema",
        "detalle": limpia_texto(detalle, area=True),
        "cuando": iso_mx(), "cuandoLegible": legible_mx(),
    })


# ── Folio consecutivo por mes, sin huecos ni repetidos ───────────
def siguiente_folio() -> str:
    prefijo = prefijo_folio()
    r = tabla().update_item(
        Key={"PK": "CONFIG", "SK": f"CONTADOR#{prefijo}"},
        UpdateExpression="ADD #n :uno",
        ExpressionAttributeNames={"#n": "consecutivo"},
        ExpressionAttributeValues={":uno": 1},
        ReturnValues="UPDATED_NEW",
    )
    return arma_folio(prefijo, int(r["Attributes"]["consecutivo"]))


# ── Crear la pre-solicitud ───────────────────────────────────────
def crear_caso(datos: dict, usuario: dict) -> tuple[dict, str]:
    """Crea el expediente y devuelve (caso, clave_en_claro).

    La clave en claro se devuelve UNA sola vez: de la base solo queda su huella.
    """
    tipo_id = datos.get("tipo")
    if tipo_id not in TIPOS:
        raise ReglaRota("El tipo de solicitud debe ser «alta» o «credito».")
    tipo = TIPOS[tipo_id]

    razon = limpia_texto(datos.get("razonSocial"))
    rfc = limpia_texto(datos.get("rfc")).upper().replace(" ", "")
    correo = limpia_texto(datos.get("correo"))
    if not razon:
        raise ReglaRota("Falta la razón social.")
    if len(rfc) not in (12, 13):
        raise ReglaRota("El RFC debe tener 12 caracteres (persona moral) o 13 (persona física).")
    if "@" not in correo:
        raise ReglaRota("Falta un correo válido del contacto.")

    # Los módulos y documentos NO se eligen: cada tipo de solicitud trae los suyos
    # completos. Un alta pide sus 5 documentos y un crédito sus 13, siempre.
    # Lo único que se descuenta es lo que solo aplica a persona moral, y eso lo
    # decide el régimen fiscal, no quien captura. Se ignora lo que mande la pantalla.
    modulos = {mid: True for mid in tipo["modulos"]}
    docs = {did: True for did in tipo["docs"]}

    folio = siguiente_folio()
    token = nuevo_token()
    clave = nueva_clave()
    huella, sal = hash_clave(clave)
    creado = iso_mx()

    caso = {
        **llaves_caso(folio, creado, token, "enviada"),
        "folio": folio, "tipo": tipo_id, "token": token,
        "claveHash": huella, "claveSal": sal, "intentos": 0, "bloqueado": False,
        "razonSocial": razon,
        "nombreComercial": limpia_texto(datos.get("nombreComercial")),
        "rfc": rfc,
        "regimen": limpia_texto(datos.get("regimen")) or "601",
        "contacto": limpia_texto(datos.get("contacto")),
        "correo": correo,
        "celular": limpia_texto(datos.get("celular")),
        "sucursal": limpia_texto(datos.get("sucursal")),
        "giro": limpia_texto(datos.get("giro")),
        "clasificacion": limpia_texto(datos.get("clasificacion")),
        "modulos": modulos, "docs": docs,
        "valores": {}, "tablasVal": {}, "adjuntos": {}, "marcas": {},
        "autorizaciones": [], "rechazo": "",
        "estado": "enviada", "creado": creado, "creadoPor": usuario.get("correo", ""),
        "creadoPorNombre": usuario.get("nombre", ""),
        "actualizado": creado,
    }
    tabla().put_item(Item=caso, ConditionExpression=Attr("PK").not_exists())
    log(folio, "creada", usuario.get("correo", ""),
        f"{tipo['nombre']} · {razon} · liga y clave generadas")
    publico = {k: v for k, v in caso.items() if k not in ("claveHash", "claveSal")}
    return publico, clave


def regenerar_clave(folio: str, usuario: dict) -> str:
    """Nueva clave para el mismo expediente. La anterior deja de servir."""
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    if caso["estado"] in ESTADOS_CERRADOS:
        raise ReglaRota("El expediente ya está cerrado; no necesita clave.")
    clave = nueva_clave()
    huella, sal = hash_clave(clave)
    tabla().update_item(
        Key={"PK": pk_caso(folio), "SK": SK_META},
        UpdateExpression=("SET claveHash=:h, claveSal=:s, intentos=:cero, "
                          "bloqueado=:no, actualizado=:t"),
        ExpressionAttributeValues={":h": huella, ":s": sal, ":cero": 0,
                                   ":no": False, ":t": iso_mx()},
    )
    log(folio, "clave-nueva", usuario.get("correo", ""), "Se generó una clave de acceso nueva")
    return clave


# ── Entrada del cliente ──────────────────────────────────────────
def verificar_clave(token: str, clave: str) -> dict:
    """Valida la clave contra la liga. Cuenta intentos y bloquea a los 5 fallos."""
    from .queries import caso_por_token
    caso = caso_por_token(token, con_secretos=True)
    if not caso:
        raise ReglaRota("Esta liga no existe o ya venció.")
    if caso.get("bloqueado"):
        raise ReglaRota("Esta liga quedó bloqueada por intentos fallidos. "
                        "Comuníquese con GPA para que le den una clave nueva.")
    if caso["estado"] in ESTADOS_CERRADOS:
        raise ReglaRota("Este expediente ya se cerró. Comuníquese con GPA.")

    if clave_coincide(clave, caso.get("claveHash", ""), caso.get("claveSal", "")):
        actualiza = {"intentos": 0}
        if caso["estado"] == "enviada":
            actualiza["estado"] = "captura"
        _fija_campos(caso["folio"], actualiza, caso)
        log(caso["folio"], "acceso", "cliente", "El cliente entró con su clave")
        return get_caso(caso["folio"])

    intentos = int(caso.get("intentos") or 0) + 1
    bloqueado = intentos >= MAX_INTENTOS
    _fija_campos(caso["folio"], {"intentos": intentos, "bloqueado": bloqueado}, caso)
    log(caso["folio"], "acceso-fallido", "cliente", f"Intento {intentos} de {MAX_INTENTOS}")
    if bloqueado:
        raise ReglaRota("Quinto intento fallido: la liga quedó bloqueada. "
                        "Comuníquese con GPA para que le den una clave nueva.")
    restantes = MAX_INTENTOS - intentos
    raise ReglaRota(f"Esa clave no corresponde a esta invitación. "
                    f"Le quedan {restantes} intento{'s' if restantes != 1 else ''}.")


def _fija_campos(folio: str, campos: dict, caso_actual: dict | None = None) -> None:
    """UpdateItem genérico. Si cambia el estado, mueve también el índice GSI3."""
    campos = dict(campos)
    campos["actualizado"] = iso_mx()
    if "estado" in campos:
        creado = (caso_actual or {}).get("creado") or iso_mx()
        campos["GSI3PK"] = f"EST#{campos['estado']}"
        campos["GSI3SK"] = creado
    nombres = {f"#c{i}": k for i, k in enumerate(campos)}
    valores = {f":v{i}": v for i, v in enumerate(campos.values())}
    expr = "SET " + ", ".join(f"#c{i} = :v{i}" for i in range(len(campos)))
    tabla().update_item(
        Key={"PK": pk_caso(folio), "SK": SK_META},
        UpdateExpression=expr,
        ExpressionAttributeNames=nombres,
        ExpressionAttributeValues=valores,
    )


def _exige_abierto_al_cliente(caso: dict) -> None:
    if caso["estado"] not in ESTADOS_ABIERTOS_AL_CLIENTE:
        raise ReglaRota("Este expediente ya no admite cambios. Comuníquese con GPA.")


def campos_permitidos(caso: dict) -> set:
    """Qué campos puede escribir el cliente ahora mismo.

    Con el expediente devuelto, solo los que GPA señaló: lo demás ya quedó revisado.
    """
    permitidos = set()
    for m in modulos_activos(caso.get("tipo"), caso.get("modulos") or {}):
        for f in campos_de(m):
            permitidos.add(f["k"])
        for t in m.get("tablas", []):
            for fila in range(t.get("n", 1)):
                for col in range(len(t.get("cols", []))):
                    permitidos.add(f"{t['k']}_{fila}_{col}")
    if caso["estado"] != "devuelta":
        return permitidos
    marcas = caso.get("marcas") or {}
    señalados = {k.split("campo:", 1)[1] for k in marcas
                 if k.startswith("campo:") and (marcas[k] or {}).get("motivo")}
    return permitidos & señalados


def guardar_captura(token: str, clave: str, valores: dict, tablas: dict) -> dict:
    """Guarda lo que escribió el cliente. Descarta cualquier campo que no le toca."""
    caso = verificar_clave(token, clave)
    _exige_abierto_al_cliente(caso)
    permitidos = campos_permitidos(caso)

    nuevos_valores = dict(caso.get("valores") or {})
    descartados = []
    for k, v in limpia_mapa(valores).items():
        if k in permitidos:
            nuevos_valores[k] = v
        else:
            descartados.append(k)

    nuevas_tablas = dict(caso.get("tablasVal") or {})
    for k, v in limpia_mapa(tablas).items():
        if k in permitidos:
            nuevas_tablas[k] = v
        else:
            descartados.append(k)

    _fija_campos(caso["folio"], {"valores": nuevos_valores, "tablasVal": nuevas_tablas}, caso)
    if descartados:
        # No se calla: queda en la bitácora para poder explicarlo después.
        log(caso["folio"], "captura-parcial", "cliente",
            "Campos descartados por no corresponder: " + ", ".join(descartados[:20]))
    resultado = get_caso(caso["folio"])
    resultado["descartados"] = descartados
    return resultado


def registrar_adjunto(token: str, clave: str, doc_id: str, nombre: str, key: str) -> dict:
    """Deja constancia de un documento ya subido a S3 con URL prefirmada."""
    caso = verificar_clave(token, clave)
    _exige_abierto_al_cliente(caso)
    if not id_documento_valido(doc_id):
        raise ReglaRota("Identificador de documento inválido.")
    persona = persona_de(caso.get("regimen"), caso.get("rfc"))
    pedidos = {d["id"] for d in docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona)}
    if doc_id not in pedidos:
        raise ReglaRota("Ese documento no se le pidió en esta solicitud.")
    if caso["estado"] == "devuelta":
        marca = (caso.get("marcas") or {}).get(doc_id) or {}
        if not marca.get("motivo"):
            raise ReglaRota("Ese documento ya fue aceptado; no hace falta reemplazarlo.")

    adjuntos = dict(caso.get("adjuntos") or {})
    adjuntos[doc_id] = {"nombre": limpia_texto(nombre), "key": limpia_texto(key),
                        "cuando": iso_mx()}
    marcas = dict(caso.get("marcas") or {})
    marcas.pop(doc_id, None)          # un documento nuevo borra el señalamiento anterior
    _fija_campos(caso["folio"], {"adjuntos": adjuntos, "marcas": marcas}, caso)
    log(caso["folio"], "adjunto", "cliente", f"{doc_id}: {nombre}")
    return get_caso(caso["folio"])


def enviar_expediente(token: str, clave: str) -> dict:
    caso = verificar_clave(token, clave)
    _exige_abierto_al_cliente(caso)
    _fija_campos(caso["folio"], {"estado": "recibida", "marcas": {},
                                 "enviado": iso_mx()}, caso)
    log(caso["folio"], "enviado", "cliente", "El cliente envió su expediente")
    return get_caso(caso["folio"])


# ── Revisión interna ─────────────────────────────────────────────
def marcar_documento(folio: str, doc_id: str, ok: bool, motivo: str, usuario: dict) -> dict:
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    if caso["estado"] in ESTADOS_CERRADOS:
        raise ReglaRota("El expediente ya está cerrado.")
    if not (caso.get("adjuntos") or {}).get(doc_id):
        raise ReglaRota("Ese documento todavía no llega; no se puede revisar.")
    marcas = dict(caso.get("marcas") or {})
    if ok:
        marcas[doc_id] = {"ok": True, "quien": usuario.get("correo", ""), "cuando": iso_mx()}
        detalle = f"{doc_id}: correcto"
    else:
        motivo = limpia_texto(motivo, area=True)
        if not motivo:
            raise ReglaRota("Escriba el motivo: el cliente lo va a leer tal cual.")
        marcas[doc_id] = {"motivo": motivo, "quien": usuario.get("correo", ""), "cuando": iso_mx()}
        detalle = f"{doc_id} señalado: {motivo}"
    _fija_campos(folio, {"marcas": marcas}, caso)
    log(folio, "revision", usuario.get("correo", ""), detalle)
    return get_caso(folio)


def señalar_campo(folio: str, campo: str, motivo: str, usuario: dict) -> dict:
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    motivo = limpia_texto(motivo, area=True)
    if not motivo:
        raise ReglaRota("Escriba el motivo: el cliente lo va a leer tal cual.")
    marcas = dict(caso.get("marcas") or {})
    marcas[f"campo:{campo}"] = {"motivo": motivo, "quien": usuario.get("correo", ""),
                                "cuando": iso_mx()}
    _fija_campos(folio, {"marcas": marcas}, caso)
    log(folio, "revision", usuario.get("correo", ""), f"campo {campo} señalado: {motivo}")
    return get_caso(folio)


def devolver(folio: str, usuario: dict) -> dict:
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    marcas = caso.get("marcas") or {}
    señalados = [k for k, v in marcas.items() if isinstance(v, dict) and v.get("motivo")]
    if not señalados:
        raise ReglaRota("Señale al menos un documento o campo antes de devolver.")
    _fija_campos(folio, {"estado": "devuelta"}, caso)
    log(folio, "devuelta", usuario.get("correo", ""),
        f"{len(señalados)} punto(s) señalado(s): " + ", ".join(señalados[:10]))
    return get_caso(folio)


def pendientes_para_autorizar(caso: dict) -> list:
    """Qué falta para poder firmar. Lista vacía = listo."""
    faltas = []
    persona = persona_de(caso.get("regimen"), caso.get("rfc"))
    aplic = docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona)
    adjuntos = caso.get("adjuntos") or {}
    marcas = caso.get("marcas") or {}
    for d in aplic:
        if not adjuntos.get(d["id"]):
            faltas.append(f"falta {d['n']}")
        elif not (marcas.get(d["id"]) or {}).get("ok"):
            faltas.append(f"sin revisar: {d['n']}")
    señalados = [k for k, v in marcas.items() if isinstance(v, dict) and v.get("motivo")]
    if señalados:
        faltas.append(f"{len(señalados)} punto(s) señalado(s) sin resolver")
    return faltas


def pasar_a_autorizacion(folio: str, usuario: dict) -> dict:
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    if caso["estado"] != "recibida":
        raise ReglaRota(f"El expediente está «{ESTADOS[caso['estado']]['t']}»; "
                        "solo pasa a autorización cuando está «Recibida».")
    faltas = pendientes_para_autorizar(caso)
    if faltas:
        raise ReglaRota("Todavía no: " + "; ".join(faltas[:5]))
    _fija_campos(folio, {"estado": "por_autorizar"}, caso)
    log(folio, "a-autorizacion", usuario.get("correo", ""), "Expediente completo y revisado")
    return get_caso(folio)


# ── Autorización ─────────────────────────────────────────────────
def firmar(folio: str, nivel: int, firmante: dict, usuario: dict) -> dict:
    """Registra una firma. Las reglas se validan aquí, no en la pantalla."""
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    if caso["estado"] != "por_autorizar":
        raise ReglaRota("El expediente no está en autorización.")
    tipo = TIPOS.get(caso.get("tipo")) or TIPOS["alta"]

    if tipo["autoriza"] == "simple" and nivel != 1:
        raise ReglaRota("Un alta lleva una sola firma.")
    if nivel not in (1, 2):
        raise ReglaRota("El nivel de firma debe ser 1 o 2.")

    firmas = list(caso.get("autorizaciones") or [])
    n1 = [a for a in firmas if a.get("nivel") == 1]
    n2 = [a for a in firmas if a.get("nivel") == 2]

    if nivel == 1 and n1:
        raise ReglaRota("El nivel 1 ya está firmado.")
    if nivel == 2:
        if tipo["autoriza"] != "dosNiveles":
            raise ReglaRota("Este tipo de solicitud no tiene nivel 2.")
        if not n1:
            raise ReglaRota("Falta la firma de nivel 1.")
        if len(n2) >= 2:
            raise ReglaRota("El nivel 2 ya tiene sus dos firmas.")

    fid = firmante.get("correo", "")
    if any(a.get("usuarioId") == fid for a in firmas):
        raise ReglaRota(f"{firmante.get('nombre') or fid} ya firmó este expediente.")
    if not firmante.get(f"n{nivel}"):
        raise ReglaRota(f"{firmante.get('nombre') or fid} no está habilitado "
                        f"para firmar nivel {nivel}.")

    firmas.append({"nivel": nivel, "usuarioId": fid,
                   "nombre": firmante.get("nombre", ""), "rol": firmante.get("rol", ""),
                   "fecha": legible_mx(), "cuando": iso_mx(),
                   "registradaPor": usuario.get("correo", "")})

    completa = len([a for a in firmas if a["nivel"] == 1]) >= 1 and (
        tipo["autoriza"] == "simple" or len([a for a in firmas if a["nivel"] == 2]) >= 2)
    campos = {"autorizaciones": firmas}
    if completa:
        campos["estado"] = "autorizada"
        campos["autorizado"] = iso_mx()
    _fija_campos(folio, campos, caso)
    log(folio, "firma", usuario.get("correo", ""),
        f"Nivel {nivel} firmado por {firmante.get('nombre') or fid}"
        + (" · expediente AUTORIZADO" if completa else ""))
    return get_caso(folio)


def rechazar(folio: str, motivo: str, usuario: dict) -> dict:
    caso = get_caso(folio)
    if not caso:
        raise ReglaRota("No existe ese expediente.")
    if caso["estado"] in ESTADOS_CERRADOS:
        raise ReglaRota("El expediente ya está cerrado.")
    motivo = limpia_texto(motivo, area=True)
    if not motivo:
        raise ReglaRota("Escriba el motivo del rechazo.")
    _fija_campos(folio, {"estado": "rechazada", "rechazo": motivo,
                         "rechazadoPor": usuario.get("correo", "")}, caso)
    log(folio, "rechazo", usuario.get("correo", ""), motivo)
    return get_caso(folio)
