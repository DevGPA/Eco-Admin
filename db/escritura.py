# db/escritura.py
# Escritura en DynamoDB — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import uuid
import boto3
from datetime import datetime, timezone

from db import modelos as m

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_viaticos_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _folio(fecha: str, rid: str) -> str:
    """Folio legible tipo VIA-2025-AB12CD."""
    anio = fecha[:4]
    return f"VIA-{anio}-{rid[:6].upper()}"


# ── Solicitudes de viáticos ──────────────────────────────────────
def crear_solicitud(datos: dict, email: str, area: str, nombre: str) -> dict:
    """
    Crea una solicitud de viáticos en estado 'Solicitada'.
    Genera id, folio, fecha e historial en el servidor.
    """
    rid   = uuid.uuid4().hex[:12]
    fecha = _now_iso()
    folio = _folio(fecha, rid)
    item = {
        **m.solicitud_keys(rid, email, area or "SIN_AREA", fecha),
        **m.to_dynamo(datos),
        "id":          rid,
        "folio":       folio,
        "tipo_reg":    m.VIA,
        "fecha":       fecha,
        "solicitante": nombre or email,
        "email":       email,
        "area":        area,
        "estado":      "Solicitada",
        "etapa":       1,
        "historial":   [{"estado": "Solicitada", "por": nombre or email, "fecha": fecha}],
    }
    _t().put_item(Item=item)
    return {"id": rid, "folio": folio, "fecha": fecha, "estado": "Solicitada"}


def cambiar_estado(rid: str, nuevo_estado: str, etapa: int | None, por: str) -> None:
    """Cambia el estado de una solicitud y agrega una entrada al historial."""
    fecha = _now_iso()
    sets = ["#s = :s", "fechaAct = :f",
            "historial = list_append(if_not_exists(historial, :empty), :h)"]
    names = {"#s": "estado"}
    values = {
        ":s": nuevo_estado,
        ":f": fecha,
        ":empty": [],
        ":h": [{"estado": nuevo_estado, "por": por, "fecha": fecha}],
    }
    if etapa is not None:
        sets.append("etapa = :e")
        values[":e"] = etapa
    _t().update_item(
        Key={"PK": f"{m.VIA}#{rid}", "SK": "META"},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def aplicar_paso(rid: str, parche: dict, nuevo_estado: str | None,
                 etapa: int | None, por: str) -> None:
    """
    Aplica los datos de una etapa del flujo (transporte, anticipo, comprobantes,
    validación, revisión, cierre, reembolso), opcionalmente avanza el estado y
    deja constancia en el historial.
    """
    fecha = _now_iso()
    names, values, sets = {}, {":f": fecha}, ["fechaAct = :f"]
    for i, (k, v) in enumerate(parche.items()):
        names[f"#k{i}"] = k
        values[f":v{i}"] = m.to_dynamo(v)
        sets.append(f"#k{i} = :v{i}")
    if nuevo_estado:
        names["#s"] = "estado"
        values[":s"] = nuevo_estado
        values[":empty"] = []
        values[":h"] = [{"estado": nuevo_estado, "por": por, "fecha": fecha}]
        sets.append("#s = :s")
        sets.append("historial = list_append(if_not_exists(historial, :empty), :h)")
    if etapa is not None:
        values[":e"] = etapa
        sets.append("etapa = :e")
    _t().update_item(
        Key={"PK": f"{m.VIA}#{rid}", "SK": "META"},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names or None,
        ExpressionAttributeValues=values,
    )


# ── Catálogos ────────────────────────────────────────────────────
def guardar_empleado(e: dict) -> None:
    _t().put_item(Item={"PK": m.PK_EMPLEADO, "SK": m.sk_empleado(e["id"]), **m.to_dynamo(e)})


def guardar_area(nombre: str, datos: dict | None = None) -> None:
    item = {"PK": m.PK_AREA, "SK": m.sk_area(nombre), "nombre": nombre}
    if datos:
        item.update(m.to_dynamo(datos))
    _t().put_item(Item=item)


def eliminar_area(nombre: str) -> None:
    _t().delete_item(Key={"PK": m.PK_AREA, "SK": m.sk_area(nombre)})


def guardar_politica(pol: dict) -> None:
    _t().put_item(Item={"PK": m.PK_CONFIG, "SK": m.SK_POLITICA, **m.to_dynamo(pol)})


def guardar_tarifas(tar: dict) -> None:
    _t().put_item(Item={"PK": m.PK_CONFIG, "SK": m.SK_TARIFAS, **m.to_dynamo(tar)})


def guardar_config(cfg: dict) -> None:
    _t().put_item(Item={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG, **m.to_dynamo(cfg)})
