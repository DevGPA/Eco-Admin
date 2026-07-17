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
PK_MODULO   = "CAT#MODULO"     # módulos dinámicos (motor de formularios)
PK_PLANTILLA= "CAT#PLANTILLA"  # plantillas de formularios dinámicos
PK_RESPONSABLE = "CAT#RESPONSABLE"  # responsables de alertas del Tablero de Seguimiento
PK_CONFIG   = "CONFIG"
SK_CONFIG   = "CONFIG"


def sk_vehicle(vid)  -> str: return f"VEH#{vid}"
def sk_user(uid)     -> str: return f"USR#{uid}"
def sk_sucursal(n)   -> str: return f"SUC#{n}"
def sk_modulo(clave) -> str: return f"MOD#{clave}"
def sk_plantilla(clave) -> str: return f"PLT#{clave}"
def sk_responsable(email) -> str: return f"RESP#{email}"


def tipo_formulario(clave) -> str:
    """Tipo de registro para una plantilla dinámica (un stream por formulario)."""
    return f"FRM#{clave}"


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


# ── Regla de kilometraje (pura, sin dependencias) ────────────────
# Tope de avance permitido desde el último km de la unidad, por combustible.
KM_MAX_DELTA_ESPECIAL = 100      # Gas LP / Eléctrico (montacargas, etc.)
KM_MAX_DELTA_DEFAULT  = 1000     # resto


def evaluar_km(km_nuevo, km_ultimo, combustible: str | None = None) -> str | None:
    """Valida el km de una nueva captura contra el último de la unidad.
    Devuelve un mensaje de error, o None si es válido.
    `km_ultimo` None = primer registro de la unidad → se permite cualquier km."""
    if km_nuevo is None or km_ultimo is None:
        return None
    try:
        nuevo, ult = float(km_nuevo), float(km_ultimo)
    except (TypeError, ValueError):
        return "Kilometraje inválido"
    max_delta = KM_MAX_DELTA_ESPECIAL if combustible in ("Gas LP", "Electrico") else KM_MAX_DELTA_DEFAULT
    if nuevo < ult:
        return f"El kilometraje ({nuevo:g}) no puede ser menor al último de la unidad ({ult:g})."
    if nuevo - ult > max_delta:
        return f"El kilometraje ({nuevo:g}) excede {max_delta:,} km del último de la unidad ({ult:g}). Verifica la lectura."
    return None
