# db/modelos.py — GPA Alta de Clientes
# Claves de DynamoDB, folios, hora de México y manejo de la clave de acceso.
# ─────────────────────────────────────────────────────────────────
# Modelo single-table:
#   Caso:      PK=CASO#{folio}   SK=META
#     GSI1 (todos por fecha):     GSI1PK=CASO            GSI1SK={creado}
#     GSI2 (búsqueda por liga):   GSI2PK=TOKEN#{token}   GSI2SK=META
#     GSI3 (por estado):          GSI3PK=EST#{estado}    GSI3SK={creado}
#   Bitácora:  PK=CASO#{folio}   SK=LOG#{ts}#{n}
#   Config:    PK=CONFIG         SK=CONTADOR#{aaaamm}
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

# Hora de México fija en UTC-6, sin horario de verano (regla del protocolo GPA).
TZ_MX = timezone(timedelta(hours=-6))

# Alfabeto sin caracteres que se confunden al dictarlos por teléfono:
# sin I, L, O, 0, 1. Se usa para la clave que el cliente teclea.
ALFABETO_CLAVE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# El token vive en la URL: minúsculas, también sin ambiguos.
ALFABETO_TOKEN = "abcdefghjkmnpqrstuvwxyz23456789"

PBKDF2_VUELTAS = 210_000
MAX_INTENTOS = 5


def ahora_mx() -> datetime:
    return datetime.now(TZ_MX)


def iso_mx() -> str:
    """Marca de tiempo ISO con offset de México. Ordenable como texto."""
    return ahora_mx().isoformat(timespec="seconds")


def legible_mx(iso: str | None = None) -> str:
    """dd/mm/aaaa hh:mm en hora de México."""
    d = ahora_mx() if not iso else datetime.fromisoformat(iso).astimezone(TZ_MX)
    return d.strftime("%d/%m/%Y %H:%M")


def dias_desde(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        d = datetime.fromisoformat(iso).astimezone(TZ_MX)
    except (ValueError, TypeError):
        return 0
    return max(0, (ahora_mx() - d).days)


# ── Claves de la tabla ───────────────────────────────────────────
def pk_caso(folio: str) -> str:
    return f"CASO#{folio}"


SK_META = "META"


def sk_log() -> str:
    """Clave de un renglón de bitácora.

    Lleva microsegundos y un sufijo al azar porque varios eventos caen en el mismo
    segundo (crear → registrar → notificar). Con precisión de segundos, el segundo
    evento sobrescribía al primero y el rastro se perdía sin avisar.
    """
    marca = ahora_mx().isoformat(timespec="microseconds")
    return f"LOG#{marca}#{secrets.token_hex(3)}"


def llaves_caso(folio: str, creado: str, token: str, estado: str) -> dict:
    return {
        "PK": pk_caso(folio),
        "SK": SK_META,
        "GSI1PK": "CASO",
        "GSI1SK": creado,
        "GSI2PK": f"TOKEN#{token}",
        "GSI2SK": SK_META,
        "GSI3PK": f"EST#{estado}",
        "GSI3SK": creado,
    }


# ── Folio: GS-AAMM-NNN ───────────────────────────────────────────
def prefijo_folio(cuando: datetime | None = None) -> str:
    d = cuando or ahora_mx()
    return f"GS-{d.strftime('%y%m')}"


def arma_folio(prefijo: str, consecutivo: int) -> str:
    return f"{prefijo}-{consecutivo:03d}"


# ── Token de la liga ─────────────────────────────────────────────
def nuevo_token() -> str:
    """3 grupos de 4: k7m2-9fqx-4tz8. ~60 bits, imposible de adivinar."""
    grupos = ["".join(secrets.choice(ALFABETO_TOKEN) for _ in range(4)) for _ in range(3)]
    return "-".join(grupos)


# ── Clave de acceso del cliente ──────────────────────────────────
def nueva_clave() -> str:
    """XXXX-XXXX en mayúsculas, dictable por teléfono."""
    grupos = ["".join(secrets.choice(ALFABETO_CLAVE) for _ in range(4)) for _ in range(2)]
    return "-".join(grupos)


def normaliza_clave(valor: str) -> str:
    """Quita guiones, espacios y acentos de teclado; sube a mayúsculas."""
    return "".join(ch for ch in str(valor or "").upper() if ch.isalnum())


def hash_clave(clave: str, sal: str | None = None) -> tuple[str, str]:
    """Devuelve (huella_hex, sal_hex). La clave en claro NUNCA se guarda."""
    sal = sal or secrets.token_hex(16)
    huella = hashlib.pbkdf2_hmac(
        "sha256", normaliza_clave(clave).encode(), bytes.fromhex(sal), PBKDF2_VUELTAS
    )
    return huella.hex(), sal


def clave_coincide(clave: str, huella: str, sal: str) -> bool:
    """Comparación en tiempo constante: no filtra información por el tiempo de respuesta."""
    if not huella or not sal:
        return False
    intento, _ = hash_clave(clave, sal)
    return hmac.compare_digest(intento, huella)


# ── Saneado de lo que escribe el cliente ─────────────────────────
LARGO_MAX_CAMPO = 300
LARGO_MAX_AREA = 2000


def limpia_texto(valor, area: bool = False):
    """Recorta y acota. El escapado de HTML es del frontend; aquí se limita el tamaño."""
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return ""
    s = str(valor).strip()
    return s[: (LARGO_MAX_AREA if area else LARGO_MAX_CAMPO)]


def limpia_mapa(datos: dict, maximo: int = 400) -> dict:
    """Sanea un diccionario de campo→valor que viene del cliente."""
    if not isinstance(datos, dict):
        return {}
    out = {}
    for i, (k, v) in enumerate(datos.items()):
        if i >= maximo:
            break
        clave = limpia_texto(k)[:80]
        if not clave:
            continue
        out[clave] = v if isinstance(v, bool) else limpia_texto(v, area=True)
    return out


def id_documento_valido(did: str) -> bool:
    return bool(did) and all(ch.isalnum() or ch == "_" for ch in str(did)) and len(str(did)) <= 40


def env_bucket() -> str:
    return os.environ.get("DOCS_BUCKET", "")
