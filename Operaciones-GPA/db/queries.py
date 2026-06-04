# db/queries.py
# Lecturas de DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from boto3.dynamodb.conditions import Key

from db import modelos as m

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_operaciones_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _items(resp) -> list:
    return [m.from_dynamo(i) for i in resp.get("Items", [])]


# ── Registros, filtrados por rol ─────────────────────────────────
def listar_registros(tipo: str, rol: str, sucursales, account_id: str) -> list:
    """
    Devuelve registros de un tipo según el alcance del usuario:
      admin / analista    → todos                          (GSI1)
      supervisor          → unión de sus sucursales        (GSI2 por cada una)
      operador            → solo lo que él capturó          (GSI3 por cuenta)
    `sucursales` es una lista; vacía para admin/analista = todas.
    Orden descendente por fecha.
    """
    t = _t()
    if rol in ("admin", "analista"):
        resp = t.query(IndexName="tipo-fecha-idx",
                       KeyConditionExpression=Key("GSI1PK").eq(tipo),
                       ScanIndexForward=False)
        return [_limpiar(i) for i in _items(resp)]

    if rol == "operador":
        # El operador solo ve su propio historial de cargas
        resp = t.query(IndexName="cuenta-fecha-idx",
                       KeyConditionExpression=Key("GSI3PK").eq(f"{tipo}#{account_id}"),
                       ScanIndexForward=False)
        return [_limpiar(i) for i in _items(resp)]

    # supervisor: registros de las sucursales asignadas
    out = []
    for suc in (sucursales or []):
        resp = t.query(IndexName="sucursal-fecha-idx",
                       KeyConditionExpression=Key("GSI2PK").eq(f"{tipo}#{suc}"),
                       ScanIndexForward=False)
        out.extend(_items(resp))
    out.sort(key=lambda r: r.get("fecha", ""), reverse=True)
    return [_limpiar(i) for i in out]


def get_registro(tipo: str, rid: str) -> dict | None:
    resp = _t().get_item(Key={"PK": f"{tipo}#{rid}", "SK": "META"})
    item = resp.get("Item")
    return _limpiar(m.from_dynamo(item)) if item else None


def _limpiar(item: dict) -> dict:
    """Quita las claves internas de Dynamo antes de mandar al cliente."""
    for k in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"):
        item.pop(k, None)
    return item


# ── Catálogos ────────────────────────────────────────────────────
def cargar_catalogos() -> dict:
    t = _t()
    veh = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_VEHICLE)))
    usr = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_USER)))
    suc = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_SUCURSAL)))
    cfg = t.get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG}).get("Item") or {}
    for lst in (veh, usr, suc):
        for it in lst:
            _limpiar(it)
    cfg = _limpiar(m.from_dynamo(cfg))
    return {
        "vehicles":   sorted(veh, key=lambda v: str(v.get("economico", ""))),
        "users":      sorted(usr, key=lambda u: str(u.get("nombre", ""))),
        "sucursales": sorted([s["nombre"] for s in suc]),
        "config":     cfg,
    }
