# db/queries.py
# Lecturas de DynamoDB — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from boto3.dynamodb.conditions import Key

from db import modelos as m

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_viaticos_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _items(resp) -> list:
    return [m.from_dynamo(i) for i in resp.get("Items", [])]


# ── Solicitudes, filtradas por rol ───────────────────────────────
def listar_solicitudes(rol: str, area: str, email: str) -> list:
    """
    Devuelve solicitudes según el alcance del rol:
      empleado                       → solo las suyas        (GSI2)
      supervisor                     → las de su área        (GSI3)
      compras/tesoreria/finanzas/
        direccion/admin              → todas                 (GSI1)
    Orden descendente por fecha.
    """
    t = _t()
    if rol == "empleado":
        resp = t.query(IndexName="solicitante-fecha-idx",
                       KeyConditionExpression=Key("GSI2PK").eq(f"{m.VIA}#{email}"),
                       ScanIndexForward=False)
    elif rol == "supervisor":
        resp = t.query(IndexName="area-fecha-idx",
                       KeyConditionExpression=Key("GSI3PK").eq(f"{m.VIA}#{area}"),
                       ScanIndexForward=False)
    else:  # compras, tesoreria, finanzas, direccion, admin
        resp = t.query(IndexName="tipo-fecha-idx",
                       KeyConditionExpression=Key("GSI1PK").eq(m.VIA),
                       ScanIndexForward=False)
    return [_limpiar(i) for i in _items(resp)]


def get_solicitud(rid: str) -> dict | None:
    resp = _t().get_item(Key={"PK": f"{m.VIA}#{rid}", "SK": "META"})
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
    emp = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_EMPLEADO)))
    are = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_AREA)))
    pol = t.get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_POLITICA}).get("Item") or {}
    tar = t.get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_TARIFAS}).get("Item") or {}
    cfg = t.get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG}).get("Item") or {}
    for lst in (emp, are):
        for it in lst:
            _limpiar(it)
    pol = _limpiar(m.from_dynamo(pol))
    tar = _limpiar(m.from_dynamo(tar))
    cfg = _limpiar(m.from_dynamo(cfg))
    return {
        "empleados": sorted(emp, key=lambda e: str(e.get("nombre", ""))),
        "areas":     sorted([a["nombre"] for a in are]),
        "politica":  pol,
        "tarifas":   tar,
        "config":    cfg,
    }
