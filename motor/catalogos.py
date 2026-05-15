# motor/catalogos.py
# Catálogos y parámetros configurables del motor v2.4
# ─────────────────────────────────────────────────────────────────
# EDIT: Para actualizar sin redespliegue usar Parameter Store.
# Las constantes aquí son el fallback si SSM no está disponible.

import os

# ── Parámetros de monto ──────────────────────────────────────────
MONTO_MIN_GENERAL       = float(os.environ.get("MONTO_MIN_GENERAL", "350"))
MONTO_MIN_COSTAL        = float(os.environ.get("MONTO_MIN_COSTAL", "1000"))
MONTO_MIN_EQUIPO_COSTAL = float(os.environ.get("MONTO_MIN_EQUIPO_COSTAL", "500"))
MONTO_MIN_ACCESORIOS    = float(os.environ.get("MONTO_MIN_ACCESORIOS", "1000"))
PROP_MIN_ELEGIBLE       = float(os.environ.get("PROP_MIN_ELEGIBLE", "0.50"))

# ── Parámetros de excluidos ──────────────────────────────────────
PESO_MAX_EXCLUIDO_P   = float(os.environ.get("PESO_MAX_EXCLUIDO_P", "25"))   # ≤ 25kg
VOLUMEN_MAX_EXCLUIDO_P= float(os.environ.get("VOLUMEN_MAX_EXCLUIDO_P", "50")) # ≤ 50L

# ── Parámetros de proporción ─────────────────────────────────────
UMBRAL_FLETE_WARN  = float(os.environ.get("UMBRAL_FLETE_WARN", "0.15"))
UMBRAL_FLETE_CRIT  = float(os.environ.get("UMBRAL_FLETE_CRIT", "0.30"))
UMBRAL_TARIFA_DISP = float(os.environ.get("UMBRAL_TARIFA_DISP", "0.10"))
UMBRAL_CARGO_ENVIO = float(os.environ.get("UMBRAL_CARGO_ENVIO", "0.01"))

# ── Back Order ───────────────────────────────────────────────────
BACKORDER_ENABLED = os.environ.get("BACKORDER_ENABLED", "true").lower() == "true"

# ── Sucursales válidas ───────────────────────────────────────────
SUCURSALES_VALIDAS       = {"GDL", "CDMX", "MTY", "CUN", "PVR", "SJD"}
SUCURSAL_ORIGEN_DISPERSION = "GDL"

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
# Asignación por SKU. La fuente de verdad es siempre la FV.
SKU_CATEGORIAS: dict[str, str] = {
    # EQUIPO
    "40151510": "EQUIPO",   # Motobomba
    "40161528": "EQUIPO",   # Filtro IW Pacific
    "39111611": "EQUIPO",   # Reflector LED Nova
    "40101806": "EQUIPO",   # Bomba de calor Inter Heat
    "40101807": "EQUIPO",   # Calefactor solar
    "49241711": "EQUIPO",   # Cubierta solar spa
    "40141731": "EQUIPO",   # Boquilla
    "41112501": "EQUIPO",   # Flujómetro
    "40161527": "EQUIPO",   # Filtro
    "40141607": "EQUIPO",   # Valvula bola
    # RECUBRIMIENTO
    "30131704": "RECUBRIMIENTO",  # Vetro Venezia / azulejo pool
    # MATERIAL_INSTALACION
    "30111601": "MATERIAL_INSTALACION",  # Pega Veneciana
    # EXCLUIDO_GRANDE (≥25kg / ≥50L)
    "49241712": "EXCLUIDO_GRANDE",  # Tricloro/Dicloro 50kg
    "62815740": "EXCLUIDO_GRANDE",  # Cloro en polvo CILI
    "62815880": "EXCLUIDO_GRANDE",  # Cloro (Z)
    # EXCLUIDO_PEQUEÑO (≤25kg / ≤50L)
    "11111607": "EXCLUIDO_PEQUENO",  # Zeolita 25kg
    "12161503": "EXCLUIDO_PEQUENO",  # Kit reactivos
}


def categoria_partida(sku: str, peso_kg: float = 0,
                      volumen_l: float = 0) -> str:
    """
    Categoriza una partida de la FV.
    Prioridad: SKU fijo → peso/volumen → fallback EQUIPO.
    """
    cat = SKU_CATEGORIAS.get(sku)
    if cat:
        return cat
    # Por peso/volumen
    if peso_kg > PESO_MAX_EXCLUIDO_P or volumen_l > VOLUMEN_MAX_EXCLUIDO_P:
        return "EXCLUIDO_GRANDE"
    if 0 < peso_kg <= PESO_MAX_EXCLUIDO_P or 0 < volumen_l <= VOLUMEN_MAX_EXCLUIDO_P:
        return "EXCLUIDO_PEQUENO"
    return "EQUIPO"  # fallback: asumir elegible


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
