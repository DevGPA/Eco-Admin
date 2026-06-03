# db/modelos.py
# Claves single-table y (de)serialización para DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Catálogos:  PK=CAT#VEHICLE  SK=VEH#{id}
#             PK=CAT#USER     SK=USR#{id}
#             PK=CAT#SUCURSAL SK=SUC#{nombre}
#             PK=CONFIG       SK=CONFIG
# Registros:  PK={TIPO}#{id}  SK=META   (TIPO ∈ {SOL, CL, MC})
#   GSI1 (todos por tipo):   GSI1PK={TIPO}             GSI1SK=fecha
#   GSI2 (por sucursal):     GSI2PK={TIPO}#{sucursal}  GSI2SK=fecha
#   GSI3 (por cuenta):       GSI3PK={TIPO}#{accountId} GSI3SK=fecha
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
from decimal import Decimal
from typing import Any

# Tipos de registro
SOL = "SOL"   # solicitud de combustible
CL  = "CL"    # checklist de reparto
MC  = "MC"    # checklist de montacargas

# ── Claves de catálogos ──────────────────────────────────────────
PK_VEHICLE  = "CAT#VEHICLE"
PK_USER     = "CAT#USER"
PK_SUCURSAL = "CAT#SUCURSAL"
PK_CONFIG   = "CONFIG"
SK_CONFIG   = "CONFIG"


def sk_vehicle(vid)  -> str: return f"VEH#{vid}"
def sk_user(uid)     -> str: return f"USR#{uid}"
def sk_sucursal(n)   -> str: return f"SUC#{n}"


# ── Claves de registros ──────────────────────────────────────────
def registro_keys(tipo: str, rid, sucursal: str, account_id: str, fecha: str) -> dict:
    """Devuelve PK/SK + las 3 GSIs para un registro de operación."""
    return {
        "PK": f"{tipo}#{rid}",
        "SK": "META",
        "GSI1PK": tipo,
        "GSI1SK": fecha,
        "GSI2PK": f"{tipo}#{sucursal}",
        "GSI2SK": fecha,
        "GSI3PK": f"{tipo}#{account_id}",
        "GSI3SK": fecha,
    }


# ── Conversión de tipos para DynamoDB ────────────────────────────
def to_dynamo(value: Any) -> Any:
    """floats → Decimal recursivamente; '' se conserva (DynamoDB sí acepta string vacío)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    """Decimal → int/float recursivamente para serializar a JSON."""
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value
