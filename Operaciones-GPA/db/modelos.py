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
import calendar
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

# Tipos de registro
SOL = "SOL"   # solicitud de combustible
CL  = "CL"    # checklist de reparto
MC  = "MC"    # checklist de montacargas
EPP = "EPP"   # movimiento de equipo de protección personal (entrada o salida)

# Movimientos de EPP. Un solo tipo de registro con dos caras, como SOL guarda la
# solicitud y el reporte: así el saldo se calcula de UNA sola lista.
EPP_ENTRADA = "entrada"   # compra: la respalda una factura
EPP_SALIDA  = "salida"    # entrega a un empleado: la respalda el vale firmado

# ── Claves de catálogos ──────────────────────────────────────────
PK_VEHICLE  = "CAT#VEHICLE"
PK_USER     = "CAT#USER"
PK_SUCURSAL = "CAT#SUCURSAL"
PK_MODULO   = "CAT#MODULO"     # módulos dinámicos (motor de formularios)
PK_PLANTILLA= "CAT#PLANTILLA"  # plantillas de formularios dinámicos
PK_RESPONSABLE = "CAT#RESPONSABLE"  # responsables de alertas del Tablero de Seguimiento
PK_EPP_ART  = "CAT#EPPART"     # catálogo de artículos de EPP y uniforme
PK_CONFIG   = "CONFIG"
SK_CONFIG   = "CONFIG"


def sk_vehicle(vid)  -> str: return f"VEH#{vid}"
def sk_user(uid)     -> str: return f"USR#{uid}"
def sk_sucursal(n)   -> str: return f"SUC#{n}"
def sk_modulo(clave) -> str: return f"MOD#{clave}"
def sk_plantilla(clave) -> str: return f"PLT#{clave}"
def sk_responsable(email) -> str: return f"RESP#{email}"
def sk_epp_art(aid)  -> str: return f"ART#{aid}"


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
# Tope de avance permitido desde el último km de la unidad: UNO SOLO para toda
# la flota, sin importar el combustible ni el módulo. Antes había topes
# especiales (Gas LP 100 km, Eléctrico 300 km) que trababan capturas legítimas;
# por decisión del área todas las unidades se controlan igual que gasolina y
# diésel.
KM_MAX_DELTA = 1000              # km máximos de avance entre dos lecturas
KM_MAX_DELTA_DEFAULT = KM_MAX_DELTA   # compat. con el nombre anterior


def evaluar_km(km_nuevo, km_ultimo, combustible: str | None = None) -> str | None:
    """Valida el km de una nueva captura contra el último de la unidad.
    Devuelve un mensaje de error, o None si es válido.
    `km_ultimo` None = primer registro de la unidad → se permite cualquier km.
    `combustible` ya NO altera el tope; se acepta por compatibilidad."""
    if km_nuevo is None or km_ultimo is None:
        return None
    try:
        nuevo, ult = float(km_nuevo), float(km_ultimo)
    except (TypeError, ValueError):
        return "Kilometraje inválido"
    max_delta = KM_MAX_DELTA
    if nuevo < ult:
        return f"El kilometraje ({nuevo:g}) no puede ser menor al último de la unidad ({ult:g})."
    if nuevo - ult > max_delta:
        return f"El kilometraje ({nuevo:g}) excede {max_delta:,} km del último de la unidad ({ult:g}). Verifica la lectura."
    return None


# ── Saldo de EPP (puro, sin dependencias) ────────────────────────
# El inventario se lleva POR ARTÍCULO (no por talla): la talla se registra en la
# entrega para que quede en el vale, pero no parte el saldo.

def saldo_epp(movimientos) -> dict:
    """Existencia por sucursal y artículo a partir de los movimientos.

        {sucursal: {articuloId: {"entradas": n, "salidas": n, "saldo": n}}}

    Una salida sin existencia deja el saldo en NEGATIVO a propósito: la entrega
    al trabajador no se frena, y el negativo señala la factura que falta capturar.
    """
    out: dict = {}
    for mv in movimientos or []:
        if str(mv.get("status") or "") in ("Anulado", "Rechazado", "Rechazada"):
            continue
        mov = str(mv.get("movimiento") or "")
        if mov not in (EPP_ENTRADA, EPP_SALIDA):
            continue
        suc = str(mv.get("sucursal") or "SIN_SUCURSAL")
        for r in mv.get("renglones") or []:
            aid = str(r.get("articuloId") or "").strip()
            if not aid:
                continue
            try:
                cant = float(r.get("cantidad") or 0)
            except (TypeError, ValueError):
                continue
            if cant <= 0:
                continue
            a = out.setdefault(suc, {}).setdefault(aid, {"entradas": 0, "salidas": 0, "saldo": 0})
            if mov == EPP_ENTRADA:
                a["entradas"] += cant
            else:
                a["salidas"] += cant
            a["saldo"] = a["entradas"] - a["salidas"]
    # Enteros cuando no hay fracción, para que la app no muestre «3.0»
    for suc in out.values():
        for a in suc.values():
            for k in ("entradas", "salidas", "saldo"):
                if float(a[k]).is_integer():
                    a[k] = int(a[k])
    return out


# ── Cumplimiento del checklist de reparto (puro, sin dependencias) ──
# Espejo EXACTO de lo que ya calcula el Tablero de Seguimiento en el front
# (segLunes / segHabil / estIni). Si aquí y allá no dieran lo mismo, el operador
# vería «cumplido» en el tablero y el servidor le bloquearía la solicitud.
#
#   · Semanal → la semana corre de LUNES a domingo; el límite es el LUNES.
#     Desde el martes sin checklist de esa semana, está VENCIDO.
#   · Mensual → el mes natural; el límite es el DÍA 5, recorrido al siguiente
#     día hábil si cae sábado o domingo.

MX_TZ = timezone(timedelta(hours=-6))    # Ciudad de México (UTC-6 fijo)


def hoy_mx() -> date:
    """Fecha de HOY en hora de México (no la del servidor, que va en UTC)."""
    return datetime.now(MX_TZ).date()


def lunes_de(d: date) -> date:
    """Lunes de la semana de `d` (lunes = inicio de semana)."""
    return d - timedelta(days=d.weekday())


def dia_habil(d: date) -> date:
    """Si cae sábado o domingo, se recorre al lunes siguiente."""
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def periodo_checklist(tipo: str, hoy: date) -> tuple[str, str, str]:
    """(inicio, fin, límite) del período vigente, en texto YYYY-MM-DD."""
    if tipo == "semanal":
        lun = lunes_de(hoy)
        return lun.isoformat(), (lun + timedelta(days=6)).isoformat(), lun.isoformat()
    ini = date(hoy.year, hoy.month, 1)
    fin = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])
    return ini.isoformat(), fin.isoformat(), dia_habil(date(hoy.year, hoy.month, 5)).isoformat()


def estado_cumplimiento(hay: bool, limite: str, fin: str, hoy: str,
                        inicio: str | None = None) -> str:
    """cumplido · pendiente · vencido · na — igual que estIni() del tablero.
    `inicio` es el día de arranque (go-live): antes de él nada se reclama."""
    if hay:
        return "cumplido"
    if inicio and limite < inicio:
        return "pendiente" if hoy <= fin else "na"
    return "vencido" if hoy > limite else "pendiente"


def norm_texto(valor) -> str:
    """Sin acentos, minúsculas y sin espacios — para comparar textos capturados."""
    txt = unicodedata.normalize("NFD", str(valor or ""))
    txt = "".join(c for c in txt if not unicodedata.combining(c)).lower()
    return "".join(txt.split())


def categoria_vehiculo(v: dict) -> str:
    """'reparto' o 'montacargas'. Espejo de catVeh() del front: manda la
    categoría explícita; si no hay, el área ALMACEN o el Gas LP son montacargas."""
    cat = str((v or {}).get("categoria") or "").strip()
    if cat:
        return cat
    if "ALMACEN" in str((v or {}).get("responsable") or "").upper():
        return "montacargas"
    if "gaslp" in norm_texto((v or {}).get("combustible")):
        return "montacargas"
    return "reparto"


HORAS_MAX_DELTA = 100            # tope de avance de horas por captura (montacargas)


def evaluar_horas(horas_nueva, horas_ultima) -> str | None:
    """Valida las horas de un montacargas contra la última lectura de la unidad.
    Devuelve un mensaje de error, o None si es válido.
    `horas_ultima` None = primera lectura → se permite cualquier valor."""
    if horas_nueva is None or horas_ultima is None:
        return None
    try:
        nueva, ult = float(horas_nueva), float(horas_ultima)
    except (TypeError, ValueError):
        return "Horas inválidas"
    if nueva < ult:
        return f"Las horas ({nueva:g}) no pueden ser menores a las últimas de la unidad ({ult:g})."
    if nueva - ult > HORAS_MAX_DELTA:
        return f"Las horas ({nueva:g}) exceden {HORAS_MAX_DELTA} h de las últimas de la unidad ({ult:g}). Verifica la lectura."
    return None
