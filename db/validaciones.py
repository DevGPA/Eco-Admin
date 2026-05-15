# db/validaciones.py
# Capa 0 del motor: pre-validación documental contra DynamoDB
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_fletes_dev")

_table_cache = None

def _table():
    global _table_cache
    if not _table_cache:
        _table_cache = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table_cache


ESTADOS_APROBADOS = {"AUTO_APROBADA", "APROBADA_MANUAL"}


def verificar_unicidad(folio_cp: str, folios_fv: list[str]) -> dict:
    """
    Capa 0 — Verifica R-091 y R-092 antes de evaluar.

    R-092: Una CP no puede existir en NINGUNA solicitud (cualquier estado).
    R-091: Una FV no puede estar en una solicitud APROBADA.

    Returns:
        {
          "valido": True | False,
          "codigo": "R-091" | "R-092" | None,
          "concepto": str,
          "detalle": str
        }
    """
    # ── R-092: CP duplicada ──────────────────────────────────────
    resp_cp = _table().query(
        KeyConditionExpression=Key("PK").eq(f"CP#{folio_cp}"),
        Limit=1,
        ProjectionExpression="SK, estado",
    )
    if resp_cp["Count"] > 0:
        sol_ref = resp_cp["Items"][0]["SK"].replace("SOL#", "")
        estado_ref = resp_cp["Items"][0].get("estado", "DESCONOCIDO")
        return {
            "valido":   False,
            "codigo":   "R-092",
            "concepto": "CP duplicada",
            "detalle":  (
                f"La carta porte {folio_cp} ya fue registrada "
                f"en la solicitud {sol_ref} (estado: {estado_ref}). "
                f"Una CP no puede usarse más de una vez."
            ),
        }

    # ── R-091: FV en solicitud aprobada ─────────────────────────
    for folio_fv in folios_fv:
        resp_fv = _table().query(
            KeyConditionExpression=Key("PK").eq(f"FV#{folio_fv}"),
            ProjectionExpression="SK, estado",
        )
        for item in resp_fv.get("Items", []):
            if item.get("estado") in ESTADOS_APROBADOS:
                sol_ref = item["SK"].replace("SOL#", "")
                return {
                    "valido":   False,
                    "codigo":   "R-091",
                    "concepto": "FV duplicada",
                    "detalle":  (
                        f"La factura de venta {folio_fv} ya fue usada "
                        f"en la solicitud aprobada {sol_ref}. "
                        f"No se puede reutilizar una FV ya aprobada."
                    ),
                }

    return {"valido": True}


def existe_solicitud(sol_id: str) -> bool:
    """Verifica si una solicitud existe en la tabla."""
    resp = _table().get_item(
        Key={"PK": f"SOL#{sol_id}", "SK": "#META"},
        ProjectionExpression="PK",
    )
    return "Item" in resp
