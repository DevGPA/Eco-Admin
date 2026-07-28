# db/escritura.py
# Escritura en DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone, timedelta

from db import modelos as m

# Ciudad de México = UTC-6 fijo (sin horario de verano desde 2023). Todos los
# registros se marcan con la hora del centro de México.
_MX_TZ = timezone(timedelta(hours=-6))

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_operaciones_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _now_iso() -> str:
    return datetime.now(_MX_TZ).isoformat()


# ── Registros de operación ───────────────────────────────────────
def crear_registro(tipo: str, datos: dict, sucursal: str, account_id: str) -> dict:
    """
    Crea un registro (SOL/CL/MC). Genera id y fecha en el servidor.
    `datos` son los campos de negocio (sin claves de Dynamo).
    """
    rid   = uuid.uuid4().hex[:12]
    fecha = _now_iso()
    item = {
        **m.registro_keys(tipo, rid, sucursal or "SIN_SUCURSAL", account_id, fecha),
        **m.to_dynamo(datos),
        "id":        rid,
        "tipo_reg":  tipo,
        "fecha":     fecha,
        "sucursal":  sucursal,
        "accountId": account_id,
    }
    _t().put_item(Item=item)
    return {"id": rid, "fecha": fecha}


def cambiar_estado(tipo: str, rid: str, nuevo_estado: str, por: str,
                   comentario: str = "", campos_corregir=None) -> None:
    """Actualiza el estado de un registro (combustible o montacargas). El
    comentario del autorizador es opcional; si viene, se guarda en comentarioAut.
    `campos_corregir` (lista) solo se usa con el estado «Por corregir»: se guarda
    en `camposCorregir`. En cualquier otro cambio de estado esa marca se ELIMINA
    (el registro deja de estar en corrección)."""
    names = {"#s": "status", "#cc": "camposCorregir"}
    values = {":s": nuevo_estado, ":p": por, ":f": _now_iso(), ":c": comentario or ""}
    sets = ["#s = :s", "autorizadoPor = :p", "fechaAut = :f", "comentarioAut = :c"]
    if campos_corregir:
        values[":cc"] = m.to_dynamo(list(campos_corregir))
        sets.append("#cc = :cc")
        expr = "SET " + ", ".join(sets)
    else:
        expr = "SET " + ", ".join(sets) + " REMOVE #cc"
    _t().update_item(
        Key={"PK": f"{tipo}#{rid}", "SK": "META"},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def corregir_registro(tipo: str, rid: str, parche: dict, por: str) -> None:
    """Aplica la corrección de un registro «Por corregir»: fusiona los campos
    corregidos, borra la marca de corrección y la autorización previa, y regresa
    el registro a «Pendiente» para re-autorización, dejando rastro en `correccion`."""
    datos = {**(parche or {}), "status": "Pendiente",
             "correccion": {"por": por, "en": _now_iso()}}
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(datos.items()):
        names[f"#k{i}"] = k
        values[f":v{i}"] = m.to_dynamo(v)
        sets.append(f"#k{i} = :v{i}")
    # Reset de la marca de corrección y de la autorización previa.
    names.update({"#cc": "camposCorregir", "#ap": "autorizadoPor",
                  "#fa": "fechaAut", "#ca": "comentarioAut"})
    expr = "SET " + ", ".join(sets) + " REMOVE #cc, #ap, #fa, #ca"
    _t().update_item(
        Key={"PK": f"{tipo}#{rid}", "SK": "META"},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def merge_registro(tipo: str, rid: str, parche: dict) -> None:
    """Aplica un parche parcial a un registro (p. ej. análisis de foto)."""
    if not parche:
        return
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(parche.items()):
        names[f"#k{i}"] = k
        values[f":v{i}"] = m.to_dynamo(v)
        sets.append(f"#k{i} = :v{i}")
    _t().update_item(
        Key={"PK": f"{tipo}#{rid}", "SK": "META"},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


# ── Catálogos ────────────────────────────────────────────────────
# Campos que SÍ se pueden modificar en un vehículo existente.
# (economico = número económico personalizado de GPA; el id sí es inmutable/consecutivo)
EDITABLES_VEH = ("economico", "responsable", "combustible", "precio", "producto", "activo", "categoria", "sucursal", "tanque")
# 'sucursal' es editable para permitir reasignaciones de unidad entre sucursales.
# 'tanque' es editable para corregir la capacidad (afecta litros/monto estimados).
# Campos inmutables (no se alteran aunque vengan distintos): placas,
# subMarca (+ id, que es la clave).


def _economico_duplicado(t, economico, vid) -> bool:
    """True si OTRA unidad ya usa ese número económico (mezclaría los reportes)."""
    if economico in (None, ""):
        return False
    eco = str(economico).strip()
    resp = t.query(KeyConditionExpression=Key("PK").eq(m.PK_VEHICLE))
    return any(str(it.get("economico") or "") == eco and str(it.get("id")) != str(vid)
               for it in resp.get("Items", []))


def guardar_vehiculo(v: dict) -> dict:
    """
    Reglas (autoritativas en servidor):
      • NO borra vehículos (no hay borrado; el alta/edición nunca elimina).
      • Vehículo EXISTENTE: solo se actualizan los campos editables
        (responsable, combustible, precio, producto, activo); el resto se conserva.
      • Vehículo NUEVO: el id debe ser numérico y CONSECUTIVO INCREMENTAL
        (mayor al id más alto existente). Si no, se rechaza.
      • El número ECONÓMICO no puede repetirse entre unidades.
    """
    vid = str(v.get("id", "")).strip()
    if not vid:
        raise ValueError("Falta el id del vehículo")
    t = _t()
    sk = m.sk_vehicle(vid)
    existente = t.get_item(Key={"PK": m.PK_VEHICLE, "SK": sk}).get("Item")

    if v.get("economico") not in (None, "") and _economico_duplicado(t, v["economico"], vid):
        raise ValueError(f"El número económico '{v['economico']}' ya lo usa otra unidad. "
                         f"Cada unidad debe tener un económico distinto.")

    if existente:
        item = dict(existente)
        for k in EDITABLES_VEH:
            if k == "activo":
                if "activo" in v:
                    item["activo"] = bool(v["activo"])
            elif k in v and v[k] not in (None, ""):
                item[k] = v[k]
        t.put_item(Item=m.to_dynamo(item))
        return {"accion": "actualizado", "id": vid}

    # Nuevo: validar consecutivo incremental
    try:
        nid = int(vid)
    except ValueError:
        raise ValueError(f"El id del vehículo debe ser numérico (recibido: '{vid}')")
    maxid = 0
    resp = t.query(KeyConditionExpression=Key("PK").eq(m.PK_VEHICLE))
    for it in resp.get("Items", []):
        try:
            maxid = max(maxid, int(str(it.get("id", "0"))))
        except ValueError:
            pass
    if nid <= maxid:
        raise ValueError(f"El id #{vid} no es incremental (último #{maxid}). "
                         f"No se permite reusar ni retroceder ids para conservar el histórico.")
    nuevo = {
        "id": vid,
        "economico": str(v.get("economico") or vid),
        "placas": v.get("placas", ""),
        "subMarca": v.get("subMarca", ""),
        "sucursal": v.get("sucursal", ""),
        "tanque": v.get("tanque", 0),
        "responsable": v.get("responsable", ""),
        "combustible": v.get("combustible", "Gasolina"),
        "producto": v.get("producto", ""),
        "precio": v.get("precio", 0),
        "categoria": v.get("categoria") or "reparto",
        "activo": v.get("activo", True),
    }
    t.put_item(Item={"PK": m.PK_VEHICLE, "SK": sk, **m.to_dynamo(nuevo)})
    return {"accion": "creado", "id": vid}


def guardar_responsable(u: dict) -> None:
    _t().put_item(Item={"PK": m.PK_USER, "SK": m.sk_user(u["id"]), **m.to_dynamo(u)})


def guardar_sucursal(nombre: str) -> None:
    _t().put_item(Item={"PK": m.PK_SUCURSAL, "SK": m.sk_sucursal(nombre), "nombre": nombre})


def eliminar_sucursal(nombre: str) -> None:
    _t().delete_item(Key={"PK": m.PK_SUCURSAL, "SK": m.sk_sucursal(nombre)})


def guardar_config(cfg: dict) -> None:
    _t().put_item(Item={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG, **m.to_dynamo(cfg)})


# ── Motor de formularios dinámicos ───────────────────────────────
def guardar_modulo(mod: dict) -> dict:
    """Crea/edita un módulo dinámico. Requiere 'clave' y 'nombre'."""
    clave = str(mod.get("clave") or "").strip().lower()
    if not clave:
        raise ValueError("Falta la clave del módulo")
    item = {
        "clave": clave,
        "nombre": mod.get("nombre") or clave,
        "icono": mod.get("icono") or "",
        "orden": mod.get("orden", 100),
        "activo": mod.get("activo", True),
    }
    _t().put_item(Item={"PK": m.PK_MODULO, "SK": m.sk_modulo(clave), **m.to_dynamo(item)})
    return {"ok": True, "clave": clave}


def guardar_plantilla(p: dict) -> dict:
    """Crea/edita una plantilla de formulario. Requiere 'clave', 'modulo', 'nombre', 'secciones'."""
    clave = str(p.get("clave") or "").strip().lower()
    if not clave:
        raise ValueError("Falta la clave del formulario")
    if not p.get("modulo"):
        raise ValueError("Falta el módulo del formulario")
    item = {
        "clave": clave,
        "modulo": p["modulo"],
        "nombre": p.get("nombre") or clave,
        "secciones": p.get("secciones") or [],
        "requiereFirma": bool(p.get("requiereFirma", True)),
        "requiereAutorizacion": bool(p.get("requiereAutorizacion", False)),
        # Periodicidad para el Tablero de Seguimiento (mensual por defecto).
        "periodicidad": p.get("periodicidad") or "mensual",
        # Metas de seguimiento: cuántos se esperan por sucursal {sucursal: cantidad}.
        # Vacío = 1 por sucursal (comportamiento por defecto del tablero).
        "metas": p.get("metas") or {},
        "activo": p.get("activo", True),
    }
    _t().put_item(Item={"PK": m.PK_PLANTILLA, "SK": m.sk_plantilla(clave), **m.to_dynamo(item)})
    return {"ok": True, "clave": clave}


# ── Reasignación de unidad (corrección de admin) ─────────────────
# Identidad desnormalizada de la unidad dentro de un registro.
_IDENT_REG_A_VEH = {"economico": "economico", "placas": "placas", "subMarca": "subMarca",
                    "sucursal": "sucursal", "areaResponsable": "responsable"}
# Claves internas / campos de identidad del registro que NO se copian al nuevo.
_KEYS_DYNAMO = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"}
_NO_COPIAR = _KEYS_DYNAMO | {"id", "tipo_reg", "fecha", "sucursal", "accountId",
                             "reasignacion", "reasignadoA", "reasignadoDe"}


def reasignar_registro_unidad(tipo: str, rid: str, destino: dict, por: str) -> dict:
    """Corrección de admin de la unidad de un registro (SOL/CL/MC).

    Reasignar = tratar la corrección como registro NUEVO en TODAS las bases:
      1) crea un registro NUEVO en la unidad correcta, copiando los datos
         capturados y PRESERVANDO la fecha, el estado y la autorización del
         original (id/folio nuevos; rastro en `reasignadoDe`);
      2) deja el registro VIEJO en estatus «Anulado» (rastro en `reasignadoA`).
    Ambas escrituras cruzan el stream de DynamoDB → el puente a Fleet Command
    propaga automáticamente el alta del nuevo (`creacion`) y el cambio de estado
    del viejo (`cambio_estado`), sin tocar el contrato. NO se borra el viejo
    (producción tiene protección de borrado / PITR)."""
    t = _t()
    item = t.get_item(Key={"PK": f"{tipo}#{rid}", "SK": "META"}).get("Item")
    if not item:
        raise ValueError("Registro no encontrado")
    if str(item.get("vehicleId")) == str(destino.get("id")):
        raise ValueError("El registro ya pertenece a esa unidad")
    if str(item.get("status") or "") == "Anulado":
        raise ValueError("El registro ya está anulado")

    # 1) Registro NUEVO en la unidad correcta (datos capturados + fecha/estado/auth).
    negocio = {k: v for k, v in item.items() if k not in _NO_COPIAR}
    negocio["vehicleId"] = destino["id"]
    for campo_reg, campo_veh in _IDENT_REG_A_VEH.items():
        val = destino.get(campo_veh)
        if val is not None:
            negocio[campo_reg] = val
    fecha      = item.get("fecha") or _now_iso()
    sucursal   = destino.get("sucursal") or item.get("sucursal") or "SIN_SUCURSAL"
    account_id = item.get("accountId") or ""
    new_id     = uuid.uuid4().hex[:12]
    negocio["reasignadoDe"] = {
        "id": rid, "folio": f"{tipo}-{rid}".upper(),
        "vehicleId": item.get("vehicleId"), "economico": item.get("economico"),
        "placas": item.get("placas"), "sucursal": item.get("sucursal"),
        "por": por, "en": _now_iso(),
    }
    nuevo_item = {
        **m.registro_keys(tipo, new_id, sucursal, account_id, fecha),
        **m.to_dynamo(negocio),
        "id": new_id, "tipo_reg": tipo, "fecha": fecha,
        "sucursal": sucursal, "accountId": account_id,
    }
    t.put_item(Item=nuevo_item)

    # 2) Anular el registro VIEJO (cambio de status → el puente lo propaga).
    merge_registro(tipo, rid, {
        "status": "Anulado",
        "reasignadoA": {"id": new_id, "folio": f"{tipo}-{new_id}".upper(),
                        "vehicleId": destino["id"], "economico": destino.get("economico"),
                        "sucursal": sucursal, "por": por, "en": _now_iso()},
    })
    return {"ok": True, "id": new_id, "anuladoId": rid, "vehicleId": destino["id"]}


# ── Responsables de alertas del Tablero de Seguimiento ───────────
def guardar_responsable_alerta(email: str, tipo) -> None:
    """Marca (o quita) una cuenta como responsable de alertas de cumplimiento.
    tipo ∈ {'sucursal','corporativo'}; cualquier otro valor (o vacío) = quitar."""
    email = (email or "").strip().lower()
    if not email:
        return
    t = _t()
    if tipo in ("sucursal", "corporativo"):
        t.put_item(Item={"PK": m.PK_RESPONSABLE, "SK": m.sk_responsable(email),
                         "email": email, "tipo": tipo})
    else:
        t.delete_item(Key={"PK": m.PK_RESPONSABLE, "SK": m.sk_responsable(email)})


def actualizar_precio_por_combustible(combustible: str, precio) -> int:
    """Cambio masivo: fija el precio/L de TODOS los vehículos de un tipo de
    combustible. Devuelve cuántos vehículos se actualizaron."""
    t = _t()
    precio_dec = m.to_dynamo(float(precio))
    n = 0
    resp = t.query(KeyConditionExpression=Key("PK").eq(m.PK_VEHICLE))
    for it in resp.get("Items", []):
        if it.get("combustible") == combustible:
            t.update_item(
                Key={"PK": m.PK_VEHICLE, "SK": it["SK"]},
                UpdateExpression="SET precio = :p",
                ExpressionAttributeValues={":p": precio_dec},
            )
            n += 1
    return n
