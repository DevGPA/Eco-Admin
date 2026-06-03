# db/escritura.py
# Escritura en DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import uuid
import boto3
from datetime import datetime, timezone

from db import modelos as m

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_operaciones_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
def guardar_vehiculo(v: dict) -> None:
    _t().put_item(Item={"PK": m.PK_VEHICLE, "SK": m.sk_vehicle(v["id"]), **m.to_dynamo(v)})


def guardar_responsable(u: dict) -> None:
    _t().put_item(Item={"PK": m.PK_USER, "SK": m.sk_user(u["id"]), **m.to_dynamo(u)})


def guardar_sucursal(nombre: str) -> None:
    _t().put_item(Item={"PK": m.PK_SUCURSAL, "SK": m.sk_sucursal(nombre), "nombre": nombre})


def eliminar_sucursal(nombre: str) -> None:
    _t().delete_item(Key={"PK": m.PK_SUCURSAL, "SK": m.sk_sucursal(nombre)})


def guardar_config(cfg: dict) -> None:
    _t().put_item(Item={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG, **m.to_dynamo(cfg)})
