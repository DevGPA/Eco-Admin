# motor/tarifas.py
# Tarifas 2026 para dispersiones internas — solo desde GDL
# ─────────────────────────────────────────────────────────────────
# Fuente OFICIAL: "tarifas dispersiones 2026.xlsx" (hoja "Tarifas maestras
# 2026", actualizada mayo 2026) — cargada el 2026-07-20 por indicación del
# usuario considerando ÚNICAMENTE Tórtón y Cajas (25 y 50 kg); pallet y
# trailer de esa tabla se cargarán más adelante.
#
# Estructura: RFC_fletera → tipo_vehiculo → destino_estado → tarifa_MXN
#   CAJA   = "Caja 25kg" · CAJA50 = "Caja 50kg" (por caja)
#   TORTON = viaje completo
# Destinos de la tabla → estado canónico del catálogo:
#   PVR (Puerto Vallarta) → "Jalisco" y "Nayarit" (misma tarifa: el destino
#   real puede caer en Bahía de Banderas, lado Nayarit)
#   CUN → "Quintana Roo" · MTY → "Nuevo León" · CDMX → "CDMX"
#   LC (La Paz / Los Cabos, B.C.S.) → "BCS"
# Una ruta SIN tarifa cae a la regla del tope ($33,000 + IVA, catalogos.py).

TARIFAS_DISPERSIONES: dict[str, dict[str, dict[str, float]]] = {

    # ── Transportes Julián de Obregón (TJO680807GU2) ─────────────
    "TJO680807GU2": {
        "CAJA": {
            "Quintana Roo": 535.8,
            "Nuevo León":   392.0,
            "CDMX":         483.5,
            "BCS":         1437.5,
        },
        "TORTON": {
            "Jalisco": 26000.0,
            "Nayarit": 26000.0,
        },
    },

    # ── Fletes de Oriente (FOR630225561) ─────────────────────────
    "FOR630225561": {
        "CAJA": {
            "Jalisco": 197.0,
            "Nayarit": 197.0,
        },
        "TORTON": {
            "Jalisco": 20000.0,
            "Nayarit": 20000.0,
            "CDMX":   23500.0,
        },
    },

    # ── Estafeta Mexicana (EME880309SK5) ─────────────────────────
    "EME880309SK5": {
        "CAJA": {
            "Jalisco":      210.0,
            "Nayarit":      210.0,
            "Quintana Roo": 351.0,
            "Nuevo León":   267.0,
            "CDMX":         252.9,
            "BCS":          446.0,
        },
        "CAJA50": {
            "Jalisco":      396.49,
            "Nayarit":      396.49,
            "Quintana Roo": 855.4,
            "Nuevo León":   671.0,
            "CDMX":         580.1,
            "BCS":          977.77,
        },
    },

    # ── Tres Guerras / Tresguerras (ACT68080665A) ─────────────────
    "ACT68080665A": {
        "CAJA": {
            "Jalisco":      132.0,
            "Nayarit":      132.0,
            "Quintana Roo": 165.0,
            "Nuevo León":   143.0,
            "CDMX":         132.0,
            "BCS":          214.0,
        },
        "CAJA50": {
            "Jalisco":      240.0,
            "Nayarit":      240.0,
            "Quintana Roo": 330.0,
            "Nuevo León":   286.0,
            "CDMX":         264.0,
            "BCS":          483.58,
        },
        "TORTON": {
            "Jalisco": 17207.0,
            "Nayarit": 17207.0,
        },
    },

    # ── Pendientes de RFC (tienen tórtón/caja en la tabla 2026 pero su
    #    RFC no está en el catálogo de fleteras; activar cuando el usuario
    #    lo confirme) ────────────────────────────────────────────────
    # ENTREGA:              Caja 25kg → MTY 630, CDMX 630
    # CONTINENTAL:          Caja 25kg → PVR 100 · Caja 50kg → PVR 200 · Tórtón → PVR 15,000
    # TNT:                  Tórtón → PVR 17,000, CUN 89,000, MTY 27,000, CDMX 22,500
    # EDGAR GUTIÉRREZ:      Tórtón → PVR 17,000, CDMX 21,000
    # LÍNEAS INTERNACIONALES: Tórtón → PVR 9,000, CDMX 9,000
}


def obtener_tarifa(rfc_fletera: str, tipo_vehiculo: str,
                   destino_estado: str) -> float | None:
    """Retorna la tarifa de referencia en MXN, o None si no existe."""
    return (TARIFAS_DISPERSIONES
            .get(rfc_fletera, {})
            .get(tipo_vehiculo, {})
            .get(destino_estado))
