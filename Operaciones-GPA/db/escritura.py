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


def cambiar_estado(tipo: str, rid: str, nuevo_estado: str, por: str) -> None:
    """Actualiza el estado de un registro (combustible o montacargas)."""
    _t().update_item(
        Key={"PK": f"{tipo}#{rid}", "SK": "META"},
        UpdateExpression="SET #s = :s, autorizadoPor = :p, fechaAut = :f",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": nuevo_estado, ":p": por, ":f": _now_iso()},
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
EDITABLES_VEH = ("economico", "responsable", "combustible", "precio", "producto", "activo", "categoria", "sucursal")
# 'sucursal' es editable para permitir reasignaciones de unidad entre sucursales.
# Campos inmutables (no se alteran aunque vengan distintos): placas,
# subMarca, tanque (+ id, que es la clave).


def guardar_vehiculo(v: dict) -> dict:
    """
    Reglas (autoritativas en servidor):
      • NO borra vehículos (no hay borrado; el alta/edición nunca elimina).
      • Vehículo EXISTENTE: solo se actualizan los campos editables
        (responsable, combustible, precio, producto, activo); el resto se conserva.
      • Vehículo NUEVO: el id debe ser numérico y CONSECUTIVO INCREMENTAL
        (mayor al id más alto existente). Si no, se rechaza.
    """
    vid = str(v.get("id", "")).strip()
    if not vid:
        raise ValueError("Falta el id del vehículo")
    t = _t()
    sk = m.sk_vehicle(vid)
    existente = t.get_item(Key={"PK": m.PK_VEHICLE, "SK": sk}).get("Item")

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
        "activo": p.get("activo", True),
    }
    _t().put_item(Item={"PK": m.PK_PLANTILLA, "SK": m.sk_plantilla(clave), **m.to_dynamo(item)})
    return {"ok": True, "clave": clave}


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
