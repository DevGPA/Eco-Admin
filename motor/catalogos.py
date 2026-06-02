# motor/catalogos.py
# Catálogos y parámetros configurables del motor v2.4
# ─────────────────────────────────────────────────────────────────
# EDIT: Para actualizar sin redespliegue usar Parameter Store.
# Las constantes aquí son el fallback si SSM no está disponible.

import os
import re
import unicodedata
from typing import Optional


def _normalizar(texto: str) -> str:
    """Mayúsculas, sin acentos ni espacios redundantes — para comparar texto libre."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_acentos.upper().split())


# ── Parámetros de monto ──────────────────────────────────────────
MONTO_MIN_GENERAL       = float(os.environ.get("MONTO_MIN_GENERAL", "350"))
MONTO_MIN_COSTAL        = float(os.environ.get("MONTO_MIN_COSTAL", "1000"))
MONTO_MIN_EQUIPO_COSTAL = float(os.environ.get("MONTO_MIN_EQUIPO_COSTAL", "500"))
MONTO_MIN_ACCESORIOS    = float(os.environ.get("MONTO_MIN_ACCESORIOS", "1000"))
PROP_MIN_ELEGIBLE       = float(os.environ.get("PROP_MIN_ELEGIBLE", "0.50"))

# ── Umbral de elegibilidad por presentación/tamaño ───────────────
# Regla de negocio (GPA): se EXCLUYE si el peso es ≥ 25 kg O el volumen es ≥ 25 L
# (dos dimensiones independientes, lógica OR; NO es una unidad "kg/L"). El 25 es
# inclusivo al excluido. La clave SAT NO es determinante; lo define la presentación.
PESO_EXCLUIDO_KG    = float(os.environ.get("PESO_EXCLUIDO_KG", "25"))    # ≥ 25 kg → excluido
VOLUMEN_EXCLUIDO_L  = float(os.environ.get("VOLUMEN_EXCLUIDO_L", "25"))  # ≥ 25 L  → excluido

# ── Parámetros de proporción ─────────────────────────────────────
UMBRAL_FLETE_WARN      = float(os.environ.get("UMBRAL_FLETE_WARN", "0.15"))
UMBRAL_FLETE_CRIT      = float(os.environ.get("UMBRAL_FLETE_CRIT", "0.30"))
UMBRAL_FLETE_BORDERLINE= float(os.environ.get("UMBRAL_FLETE_BORDERLINE", "0.13"))  # R-302 + C5
UMBRAL_TARIFA_DISP     = float(os.environ.get("UMBRAL_TARIFA_DISP", "0.10"))
UMBRAL_CARGO_ENVIO     = float(os.environ.get("UMBRAL_CARGO_ENVIO", "0.01"))

# ── Tipo de cambio de respaldo (solo fallback; la fuente real es la FV/CP) ──
TIPO_CAMBIO_DEFAULT = float(os.environ.get("TIPO_CAMBIO_DEFAULT", "17.35"))

# ── Back Order ───────────────────────────────────────────────────
BACKORDER_ENABLED = os.environ.get("BACKORDER_ENABLED", "true").lower() == "true"

# ── Códigos SAP que dirigen las capas del motor ──────────────────
SAP_DISPERSION   = os.environ.get("SAP_DISPERSION", "GS0231")    # Capa 1a
SAP_CARGO_ENVIO  = os.environ.get("SAP_CARGO_ENVIO", "GS0248")   # Capa 1b
SAP_BACKORDER    = os.environ.get("SAP_BACKORDER", "GS0229")     # Capa 2

# ── Detección de "Cargo por envío" (Capa 1b / GS0248) ────────────
SKU_CARGO_ENVIO  = os.environ.get("SKU_CARGO_ENVIO", "00400000000000")
# Frases (sin acentos, mayúsculas) que identifican el concepto en la descripción
DESC_CARGO_ENVIO = tuple(
    s.strip() for s in os.environ.get("DESC_CARGO_ENVIO", "CARGO POR ENVIO").split("|") if s.strip()
)

# ── Identidad fiscal de GPA ──────────────────────────────────────
# RFC de General de Productos para el Agua. Define el rol en cada CFDI:
#   GPA emisor   → Factura de Venta (FV)
#   GPA receptor → Carta Porte / documento del proveedor (CP)
#   GPA en ninguno → documento ajeno → ERROR
RFC_GPA = os.environ.get("RFC_GPA", "GPA8402219Y1").strip().upper()

# ── Sucursales válidas ───────────────────────────────────────────
SUCURSALES_VALIDAS       = {"GDL", "CDMX", "MTY", "CUN", "PVR", "SJD"}
SUCURSAL_ORIGEN_DISPERSION = "GDL"

# RFCs internos GPA que disparan DISPERSIÓN_INTERNA (Capa 1a) por igualdad exacta.
# Configurable vía env RECEPTORES_INTERNOS_GPA="RFC1,RFC2". Vacío por defecto:
# la dispersión se detecta entonces solo por el código SAP (SAP_DISPERSION).
RECEPTORES_INTERNOS_GPA = {
    r.strip().upper()
    for r in os.environ.get("RECEPTORES_INTERNOS_GPA", "").split(",")
    if r.strip()
}

# Mapeo código postal SAP → sucursal
MAPEO_CP_SUCURSAL = {
    "44930": "GDL", "44190": "GDL",
    "09040": "CDMX", "09230": "CDMX",
    "64820": "MTY",
    "77510": "CUN",
    "46291": "PVR",
    "23473": "SJD",
}

# ── Destinos ─────────────────────────────────────────────────────
DESTINOS_CATALOGO = {
    "Jalisco", "Nuevo León", "Tamaulipas", "Coahuila",
    "Yucatán", "Quintana Roo", "Guerrero", "Veracruz",
    "Puebla", "Guanajuato", "Querétaro", "Michoacán",
    "Nayarit", "Sinaloa", "Sonora", "CDMX",
    "Edo. México", "Morelos", "San Luis Potosí", "Aguascalientes",
    "Chihuahua", "Durango", "Zacatecas", "Hidalgo",
    "Campeche", "Tabasco", "BCS", "BCN", "Colima",
}

# Chiapas: solo ciudades específicas
CHIAPAS_CIUDADES_OK = {"tapachula", "tuxtla gutiérrez", "tuxtla gutierrez"}

# Oaxaca: NO cubierto → R-301

def evaluar_destino(estado: str, ciudad: str = "") -> str:
    """
    Retorna 'OK', 'R-301' o 'R-302' según el destino.
    R-302 = ciudad borderline (requiere revisión del aprobador).
    """
    if not estado:
        return "R-301"
    if estado == "Oaxaca":
        return "R-301"
    if estado == "Chiapas":
        ciudad_norm = ciudad.strip().lower()
        if any(c in ciudad_norm for c in CHIAPAS_CIUDADES_OK):
            return "OK"
        return "R-302"  # Otra ciudad de Chiapas → borderline
    if estado in DESTINOS_CATALOGO:
        return "OK"
    return "R-301"


def es_cargo_envio(sku_id: Optional[str], descripcion: Optional[str]) -> bool:
    """Capa 1b (GS0248): detecta 'cargo por envío' tolerando acentos/espacios/sinónimos."""
    if sku_id != SKU_CARGO_ENVIO:
        return False
    desc = _normalizar(descripcion or "")
    return any(frase in desc for frase in DESC_CARGO_ENVIO)


# ── Fleteras autorizadas (RFC) ───────────────────────────────────
FLETERAS_AUTORIZADAS = {
    "ACT68080665A",  # Tres Guerras (Tresguerras)
    "TEE070612ITA",  # Transportes y Envíos Estrella
    "TOS0407087T2",  # Transportadora Osorio
    "FOR630225561",  # Fletes de Oriente
    "TJO680807GU2",  # Transportes Julián de Obregon
    "EME880309SK5",  # Estafeta Mexicana
    "ACA170911HY7",  # Autotransportes y Carga PTX
    "TCH170824TH2",  # Transportes de Carga Hormik
    "FASG781207JM9", # Gerardo Franco Sánchez (persona física)
    "CAAE970704V91", # Evelyn M. Camacho Aviña (persona física)
}

# ── Categorías de producto ────────────────────────────────────────
# Productos RESTRINGIDOS (no elegibles) por TIPO — palabras clave que aparecen
# en la descripción. Lista del negocio (configurable con env PALABRAS_RESTRINGIDAS):
#   químicos BlueQuim, cuñetes de cloro, material filtrante, sal, adhesivos/morteros
#   (Pega Veneciano, Imper Crest y similares), Diamond Brite, River Rock.
PALABRAS_RESTRINGIDAS = tuple(s.strip() for s in os.environ.get(
    "PALABRAS_RESTRINGIDAS",
    "BLUEQUIM|QUIMICO|CLORO|CUÑETE|CUNETE|MATERIAL FILTRANTE|ADHESIVO|MORTERO|"
    "PEGA|IMPER CREST|IMPERCREST|DIAMOND BRITE|RIVER ROCK"
).split("|") if s.strip())

_RE_PESO_DESC = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:KGS?|KILOS?)\b")
_RE_VOL_DESC  = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:LTS?|LITROS?|L)\b")


def tamano_de_descripcion(descripcion: str):
    """Extrae (peso_kg, volumen_l) del texto de la descripción (siempre trae el tamaño)."""
    d = _normalizar(descripcion)
    pesos = [float(m.group(1).replace(",", ".")) for m in _RE_PESO_DESC.finditer(d)]
    vols  = [float(m.group(1).replace(",", ".")) for m in _RE_VOL_DESC.finditer(d)]
    return (max(pesos) if pesos else 0.0), (max(vols) if vols else 0.0)


def es_restringido_por_tipo(descripcion: str) -> bool:
    """True si la descripción corresponde a un producto restringido por tipo."""
    d = _normalizar(descripcion)
    if any(k in d for k in PALABRAS_RESTRINGIDAS):
        return True
    return "SAL" in d.split()   # 'sal' como palabra completa (evita 'salida', etc.)


def categoria_partida(descripcion: str = "", peso_kg: float = 0,
                      volumen_l: float = 0) -> str:
    """
    Categoriza una partida para decidir elegibilidad (regla de negocio GPA).
    NO elegible (restringido) si CUALQUIERA:
      - peso ≥ 25 kg  O  volumen ≥ 25 L  (por tamaño)        → EXCLUIDO_GRANDE
      - es producto restringido por tipo (químicos, cuñetes de cloro, material
        filtrante, sal, adhesivos/morteros, Diamond Brite, River Rock) → EXCLUIDO_RESTRINGIDO
    En otro caso es elegible → EQUIPO.
    El tamaño se toma de los argumentos; si no vienen, se lee de la descripción
    (la presentación siempre aparece en el texto, p.ej. "50 KGS").
    """
    if not peso_kg and not volumen_l:
        peso_kg, volumen_l = tamano_de_descripcion(descripcion)
    if peso_kg >= PESO_EXCLUIDO_KG or volumen_l >= VOLUMEN_EXCLUIDO_L:
        return "EXCLUIDO_GRANDE"        # restringido por tamaño (costal)
    if es_restringido_por_tipo(descripcion):
        return "EXCLUIDO_RESTRINGIDO"   # restringido por tipo (no elegible)
    return "EQUIPO"                     # elegible


# ── Mapeo ciudad/municipio de ORIGEN → código de sucursal ─────────
# El envío debe originarse en una de las 6 plazas-sucursal (se valida por el
# ORIGEN real de la carta porte, no por la sucursal de facturación).
SUCURSAL_POR_CIUDAD = {
    "GUADALAJARA": "GDL", "ZAPOPAN": "GDL", "TLAQUEPAQUE": "GDL", "TLAJOMULCO": "GDL",
    "CIUDAD DE MEXICO": "CDMX", "MEXICO": "CDMX", "CDMX": "CDMX",
    "IZTAPALAPA": "CDMX", "DISTRITO FEDERAL": "CDMX",
    "MONTERREY": "MTY", "GUADALUPE": "MTY", "SAN NICOLAS": "MTY", "APODACA": "MTY",
    "CANCUN": "CUN", "BENITO JUAREZ": "CUN",
    "PUERTO VALLARTA": "PVR",
    "LOS CABOS": "SJD", "SAN JOSE DEL CABO": "SJD", "CABO SAN LUCAS": "SJD",
}


def sucursal_de_origen(ciudad: Optional[str] = None,
                       estado: Optional[str] = None) -> str:
    """Mapea la ciudad (o estado) de origen a un código de sucursal GPA, o '' si no aplica."""
    c = _normalizar(ciudad)
    if c in SUCURSAL_POR_CIUDAD:
        return SUCURSAL_POR_CIUDAD[c]
    for ciu, suc in SUCURSAL_POR_CIUDAD.items():   # coincidencia parcial
        if ciu in c:
            return suc
    # Fallback por estado (solo estados con una única sucursal inequívoca)
    e = _normalizar(estado)
    return {"NUEVO LEON": "MTY", "QUINTANA ROO": "CUN",
            "BAJA CALIFORNIA SUR": "SJD"}.get(e, "")


# ── Códigos R-xxx → concepto ──────────────────────────────────────
R_CONCEPTOS: dict[str, str] = {
    "R-000": "Apoyo completo",
    "R-050": "Back Order",
    "R-060": "Cargo envío OK",
    "R-061": "Cargo envío con diferencia",
    "R-091": "FV duplicada",
    "R-092": "CP duplicada",
    "R-101": "Monto insuficiente",
    "R-102": "Costal sin equipo mínimo",
    "R-103": "Costal sin mínimo $1,000",
    "R-104": "Accesorios sin mínimo",
    "R-105": "Elegible < 50% con accesorios",
    "R-201": "Producto excluido sin elegible",
    "R-202": "Sin producto elegible",
    "R-301": "Destino no cubierto",
    "R-302": "Ciudad borderline",
    "R-401": "No es entrega a domicilio",
    "R-401-S": "Sucursal no autorizada",
    "R-401-D": "Dispersión desde no-GDL",
    "R-402": "Fletera no autorizada",
    "R-501": "Flete alto > 15%",
    "R-502": "Flete crítico > 30%",
    "R-601": "Remoto + flete alto",
    "R-602": "Borderline + flete alto",
    "R-701": "En negociación",
    "R-702": "Negociación OK",
    "R-703": "Negociación fallida",
    "R-800": "Dispersión OK",
    "R-801": "Dispersión sin tarifa",
    "R-802": "Dispersión excede tarifa",
    "R-901": "Escalado por aprobador",
    "R-902": "Escalado por SLA",
}

# ── Estados finales de las solicitudes ───────────────────────────
ESTADOS_APROBADOS = {"AUTO_APROBADA", "APROBADA_MANUAL"}
ESTADOS_RECHAZADOS = {"AUTO_RECHAZADA", "RECHAZADA_MANUAL"}
ESTADOS_ACTIVOS = {"EN_REVISION", "EN_ESCALAMIENTO", "EN_NEGOCIACION"}

ESTADO_POR_CODIGO: dict[str, str] = {
    "R-000": "AUTO_APROBADA",
    "R-050": "AUTO_APROBADA",
    "R-060": "AUTO_APROBADA",
    "R-061": "EN_REVISION",
    "R-091": "BLOQUEADA",
    "R-092": "BLOQUEADA",
    "R-101": "AUTO_RECHAZADA",
    "R-102": "AUTO_RECHAZADA",
    "R-103": "AUTO_RECHAZADA",
    "R-104": "AUTO_RECHAZADA",
    "R-105": "AUTO_RECHAZADA",
    "R-201": "AUTO_RECHAZADA",
    "R-202": "AUTO_RECHAZADA",
    "R-301": "AUTO_RECHAZADA",
    "R-302": "EN_REVISION",
    "R-401": "AUTO_RECHAZADA",
    "R-401-S": "AUTO_RECHAZADA",
    "R-401-D": "AUTO_RECHAZADA",
    "R-402": "AUTO_RECHAZADA",
    "R-501": "EN_REVISION",
    "R-502": "EN_REVISION",
    "R-601": "EN_REVISION",
    "R-602": "EN_REVISION",
    "R-800": "AUTO_APROBADA",
    "R-801": "EN_REVISION",
    "R-802": "EN_REVISION",
}
