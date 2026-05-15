# db/escritura.py
# Escritura transaccional en DynamoDB — Motor GPA v2.4
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import uuid
import boto3
from datetime import datetime, timezone
from decimal  import Decimal

from motor.catalogos import R_CONCEPTOS

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_fletes_dev")

_table_cache  = None
_client_cache = None


def _dynamo_table():
    global _table_cache
    if not _table_cache:
        _table_cache = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table_cache


def _dynamo_client():
    global _client_cache
    if not _client_cache:
        _client_cache = boto3.client("dynamodb")
    return _client_cache


def _to_dec(v) -> Decimal:
    """Convierte float a Decimal para DynamoDB (no acepta float nativo)."""
    return Decimal(str(round(float(v), 6)))


def guardar_solicitud(resultado) -> dict:
    """
    Escribe la solicitud evaluada en DynamoDB de forma transaccional.
    Garantiza unicidad de CP (R-092) a nivel de base de datos.

    Args:
        resultado: ResultadoMotor del evaluador.py

    Returns:
        {"id": str, "fechaEvaluacion": str}
    """
    sol_id   = str(uuid.uuid4())
    ahora    = datetime.now(timezone.utc).isoformat()
    fecha_iso= ahora[:10]
    ts_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl      = ts_epoch + (7 * 365 * 24 * 3600)   # 7 años

    codigo   = resultado.codigo_motor
    concepto = R_CONCEPTOS.get(codigo, codigo)

    # ── Item principal Solicitud ─────────────────────────────────
    item_meta = {
        "PK":              {"S": f"SOL#{sol_id}"},
        "SK":              {"S": "#META"},
        "estado":          {"S": resultado.estado},
        "codigoMotor":     {"S": codigo},
        "conceptoMotor":   {"S": concepto},
        "tipoOperacion":   {"S": resultado.tipo_operacion},
        "folioCP":         {"S": resultado.folio_cp},
        "foliosFV":        {"SS": list(resultado.folios_fv)} if resultado.folios_fv else {"NULL": True},
        "origenSucursal":  {"S": resultado.origen_sucursal},
        "fletaRFC":        {"S": resultado.fleta_rfc},
        "destinoEstado":   {"S": resultado.destino_estado},
        "destinoCiudad":   {"S": resultado.destino_ciudad or ""},
        "montoBaseUSD":    {"N": str(_to_dec(resultado.monto_base_usd))},
        "fleteBaseUSD":    {"N": str(_to_dec(resultado.flete_base_usd))},
        "pctFlete":        {"N": str(_to_dec(resultado.pct_flete))},
        "tipoCambioRef":   {"N": str(_to_dec(resultado.tipo_cambio_ref))},
        "incluyeFerry":    {"BOOL": resultado.incluye_ferry},
        "fechaEmision":    {"S": resultado.fecha_emision},
        "fechaEvaluacion": {"S": ahora},
        "criteriosDetalle":{"S": str(resultado.criterios_detalle)},
        "ttl":             {"N": str(ttl)},
    }

    # ── Item índice CP ───────────────────────────────────────────
    item_cp = {
        "PK":          {"S": f"CP#{resultado.folio_cp}"},
        "SK":          {"S": f"SOL#{sol_id}"},
        "estado":      {"S": resultado.estado},
        "fechaEmision":{"S": resultado.fecha_emision},
        "ttl":         {"N": str(ttl)},
    }

    # ── Item historial inicial ───────────────────────────────────
    item_hist = {
        "PK":           {"S": f"SOL#{sol_id}"},
        "SK":           {"S": f"HIST#{ahora}"},
        "accion":       {"S": "EVALUAR"},
        "codigoMotor":  {"S": codigo},
        "conceptoMotor":{"S": concepto},
        "estadoAntes":  {"S": "NUEVA"},
        "estadoDespues":{"S": resultado.estado},
        "usuarioId":    {"S": "MOTOR_V24"},
    }

    # ── Construir transacción ────────────────────────────────────
    items_transact = [
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": item_meta,
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": item_cp,
                # Garantía R-092 a nivel DB — falla si CP ya existe
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": item_hist,
            }
        },
    ]

    # ── Items por cada FV ────────────────────────────────────────
    for folio_fv in resultado.folios_fv:
        items_transact.append({
            "Put": {
                "TableName": TABLE_NAME,
                "Item": {
                    "PK":          {"S": f"FV#{folio_fv}"},
                    "SK":          {"S": f"SOL#{sol_id}"},
                    "estado":      {"S": resultado.estado},
                    "fechaEmision":{"S": resultado.fecha_emision},
                    "ttl":         {"N": str(ttl)},
                },
            }
        })

    # DynamoDB TransactWriteItems (máx 100 items por transacción)
    _dynamo_client().transact_write_items(TransactItems=items_transact)

    return {"id": sol_id, "fechaEvaluacion": ahora}


def cambiar_estado(
    sol_id: str,
    nuevo_estado: str,
    usuario_id: str,
    comentario: str = "",
) -> dict:
    """
    Actualiza el estado de una solicitud y registra en historial.
    Usa TransactWriteItems para garantizar consistencia.
    """
    ahora = datetime.now(timezone.utc).isoformat()
    tabla = _dynamo_table()

    # Obtener estado y folios actuales
    item = tabla.get_item(
        Key={"PK": f"SOL#{sol_id}", "SK": "#META"},
    ).get("Item", {})

    if not item:
        raise ValueError(f"Solicitud {sol_id} no encontrada")

    estado_antes = item.get("estado", "DESCONOCIDO")
    folios_fv    = list(item.get("foliosFV") or [])
    codigo       = item.get("codigoMotor", "")

    items_transact = [
        # 1. Actualizar solicitud
        {
            "Update": {
                "TableName": TABLE_NAME,
                "Key": {
                    "PK": {"S": f"SOL#{sol_id}"},
                    "SK": {"S": "#META"},
                },
                "UpdateExpression":
                    "SET estado = :e, aprobador1Id = :u, comentario = :c",
                "ExpressionAttributeValues": {
                    ":e": {"S": nuevo_estado},
                    ":u": {"S": usuario_id},
                    ":c": {"S": comentario},
                },
            }
        },
        # 2. Registrar en historial
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": {
                    "PK":           {"S": f"SOL#{sol_id}"},
                    "SK":           {"S": f"HIST#{ahora}"},
                    "accion":       {"S": nuevo_estado},
                    "codigoMotor":  {"S": codigo},
                    "estadoAntes":  {"S": estado_antes},
                    "estadoDespues":{"S": nuevo_estado},
                    "usuarioId":    {"S": usuario_id},
                    "comentario":   {"S": comentario},
                },
            }
        },
    ]

    # 3. Actualizar índices FV si aprobado
    if nuevo_estado in {"AUTO_APROBADA", "APROBADA_MANUAL"}:
        for fv in folios_fv:
            items_transact.append({
                "Update": {
                    "TableName": TABLE_NAME,
                    "Key": {
                        "PK": {"S": f"FV#{fv}"},
                        "SK": {"S": f"SOL#{sol_id}"},
                    },
                    "UpdateExpression": "SET estado = :e",
                    "ExpressionAttributeValues": {
                        ":e": {"S": nuevo_estado},
                    },
                }
            })

    _dynamo_client().transact_write_items(TransactItems=items_transact)

    return {
        "id":          sol_id,
        "estado":      nuevo_estado,
        "estadoAntes": estado_antes,
        "aprobador":   usuario_id,
        "timestamp":   ahora,
    }
