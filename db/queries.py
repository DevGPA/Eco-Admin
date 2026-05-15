# db/queries.py
# Consultas del monitor GPA — DynamoDB GSI queries
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from boto3.dynamodb.conditions import Key, Attr

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_fletes_dev")

_table_cache = None

def _table():
    global _table_cache
    if not _table_cache:
        _table_cache = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table_cache


ESTADOS_KANBAN = [
    "AUTO_APROBADA",
    "APROBADA_MANUAL",
    "EN_REVISION",
    "ESCALADA",
    "AUTO_RECHAZADA",
    "RECHAZADA_MANUAL",
    "BLOQUEADA",
]


def get_cola_revision(fecha_desde: str = None) -> list:
    """
    Solicitudes EN_REVISION para columna del kanban.
    GSI: estado-fecha-idx
    """
    kce = Key("estado").eq("EN_REVISION")
    if fecha_desde:
        kce = kce & Key("fechaEmision").gte(fecha_desde)

    resp = _table().query(
        IndexName="estado-fecha-idx",
        KeyConditionExpression=kce,
        ScanIndexForward=False,   # más recientes primero
    )
    return resp.get("Items", [])


def get_por_rango_fecha(
    estado: str,
    desde: str,
    hasta: str,
) -> list:
    """
    Filtro del selector de fechas del dashboard.
    GSI: estado-fecha-idx · SK BETWEEN desde AND hasta
    """
    resp = _table().query(
        IndexName="estado-fecha-idx",
        KeyConditionExpression=(
            Key("estado").eq(estado) &
            Key("fechaEmision").between(desde, hasta)
        ),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def get_kpis_mes(anio: int, mes: int) -> dict:
    """
    KPIs para el header del monitor.
    Retorna conteo por estado para el mes indicado.
    """
    desde = f"{anio}-{mes:02d}-01"
    hasta = f"{anio}-{mes:02d}-31"

    totales: dict = {}
    monto_total_usd = 0.0
    flete_total_usd = 0.0

    for estado in ESTADOS_KANBAN:
        items = get_por_rango_fecha(estado, desde, hasta)
        totales[estado] = len(items)
        for item in items:
            monto_total_usd += float(item.get("montoBaseUSD", 0) or 0)
            flete_total_usd += float(item.get("fleteBaseUSD", 0) or 0)

    total = sum(totales.values())
    aprobadas = totales.get("AUTO_APROBADA", 0) + totales.get("APROBADA_MANUAL", 0)
    rechazadas = totales.get("AUTO_RECHAZADA", 0) + totales.get("RECHAZADA_MANUAL", 0)

    return {
        "anio":           anio,
        "mes":            mes,
        "total":          total,
        "por_estado":     totales,
        "aprobadas":      aprobadas,
        "rechazadas":     rechazadas,
        "en_revision":    totales.get("EN_REVISION", 0),
        "pct_aprobacion": round(aprobadas / total * 100, 1) if total else 0,
        "monto_total_usd":round(monto_total_usd, 2),
        "flete_total_usd":round(flete_total_usd, 2),
        "pct_flete_global":round(
            flete_total_usd / monto_total_usd * 100, 2
        ) if monto_total_usd else 0,
    }


def get_solicitud_completa(sol_id: str) -> dict | None:
    """
    Solicitud principal + historial completo.
    Query: PK = SOL#uuid, SK begins_with #META | HIST#
    """
    resp = _table().query(
        KeyConditionExpression=Key("PK").eq(f"SOL#{sol_id}"),
        ScanIndexForward=True,
    )
    items = resp.get("Items", [])
    if not items:
        return None

    meta     = next((i for i in items if i["SK"] == "#META"), None)
    historial = [i for i in items if i["SK"].startswith("HIST#")]

    if meta:
        meta["historial"] = sorted(historial, key=lambda x: x["SK"], reverse=True)
    return meta


def get_por_fletera(
    fleta_rfc: str,
    desde: str,
    hasta: str,
) -> list:
    """
    Historial de solicitudes por RFC de fletera.
    GSI: fletera-fecha-idx
    """
    resp = _table().query(
        IndexName="fletera-fecha-idx",
        KeyConditionExpression=(
            Key("fletaRFC").eq(fleta_rfc) &
            Key("fechaEmision").between(desde, hasta)
        ),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def get_por_sucursal(
    sucursal: str,
    desde: str,
    hasta: str,
) -> list:
    """
    Fletes originados en una sucursal.
    GSI: origen-fecha-idx
    """
    resp = _table().query(
        IndexName="origen-fecha-idx",
        KeyConditionExpression=(
            Key("origenSucursal").eq(sucursal) &
            Key("fechaEmision").between(desde, hasta)
        ),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def get_por_destino(
    estado_dest: str,
    desde: str,
    hasta: str,
) -> list:
    """
    Fletes hacia un estado destino.
    GSI: destino-fecha-idx
    """
    resp = _table().query(
        IndexName="destino-fecha-idx",
        KeyConditionExpression=(
            Key("destinoEstado").eq(estado_dest) &
            Key("fechaEmision").between(desde, hasta)
        ),
        ScanIndexForward=False,
    )
    return resp.get("Items", [])
