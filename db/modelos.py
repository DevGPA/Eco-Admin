# db/modelos.py
# Claves single-table y (de)serialización para DynamoDB — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────
# Catálogos:  PK=CAT#EMPLEADO SK=EMP#{id}
#             PK=CAT#AREA     SK=AREA#{nombre}
#             PK=CONFIG       SK=POLITICA   (límites POL-TE01)
#             PK=CONFIG       SK=TARIFAS    (vuelos/autobús/hospedaje)
#             PK=CONFIG       SK=CONFIG     (correos / banderas)
# Solicitudes: PK=VIA#{id}  SK=META
#   GSI1 (todas por fecha):   GSI1PK=VIA            GSI1SK=fecha
#   GSI2 (por solicitante):   GSI2PK=VIA#{email}    GSI2SK=fecha
#   GSI3 (por área):          GSI3PK=VIA#{area}     GSI3SK=fecha
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
from decimal import Decimal
from typing import Any

# Tipo de registro (solicitud de viáticos)
VIA = "VIA"

# ── Claves de catálogos ──────────────────────────────────────────
PK_EMPLEADO = "CAT#EMPLEADO"
PK_AREA     = "CAT#AREA"
PK_CONFIG   = "CONFIG"
SK_POLITICA = "POLITICA"
SK_TARIFAS  = "TARIFAS"
SK_CONFIG   = "CONFIG"


def sk_empleado(eid) -> str: return f"EMP#{eid}"
def sk_area(n)       -> str: return f"AREA#{n}"


# ── Claves de solicitudes ────────────────────────────────────────
def solicitud_keys(rid, email: str, area: str, fecha: str) -> dict:
    """Devuelve PK/SK + las 3 GSIs para una solicitud de viáticos."""
    return {
        "PK": f"{VIA}#{rid}",
        "SK": "META",
        "GSI1PK": VIA,
        "GSI1SK": fecha,
        "GSI2PK": f"{VIA}#{email}",
        "GSI2SK": fecha,
        "GSI3PK": f"{VIA}#{area}",
        "GSI3SK": fecha,
    }


# ── Conversión de tipos para DynamoDB ────────────────────────────
def to_dynamo(value: Any) -> Any:
    """floats → Decimal recursivamente; '' se conserva (DynamoDB acepta string vacío)."""
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
