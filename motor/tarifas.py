# motor/tarifas.py
# Tarifas 2026 para dispersiones internas — solo desde GDL
# ─────────────────────────────────────────────────────────────────
# Estructura: RFC_fletera → tipo_vehiculo → destino_estado → tarifa_MXN
# Para PALLET: tarifa es por pallet unitario (se multiplica por numero_pallets)
# Para TORTON/TRAILER: tarifa es por viaje completo

TARIFAS_DISPERSIONES: dict[str, dict[str, dict[str, float]]] = {

    # ── Transportes Julián de Obregon (TJO680807GU2) ─────────────
    "TJO680807GU2": {
        "PALLET": {
            "Quintana Roo": 3732.0,   # CUN
        },
        "TORTON": {
            "Nayarit":    26000.0,    # PVR
            "Nuevo León": 28100.0,    # MTY
            "CDMX":       21500.0,
        },
        "TRAILER": {
            "Nayarit":    30000.0,    # PVR
            "Quintana Roo": 97026.0,  # CUN
            "Nuevo León": 36000.0,    # MTY
            "CDMX":       26000.0,
            "BCS":        117000.0,   # LC / Los Cabos
        },
    },

    # ── Fletes de Oriente (FOR630225561) ─────────────────────────
    "FOR630225561": {
        "TORTON": {
            "Nayarit":  20000.0,
            "CDMX":     23500.0,
        },
        "TRAILER": {
            "Nayarit":    24000.0,
            "Nuevo León": 33000.0,
            "CDMX":       26000.0,
        },
    },

    # ── Tres Guerras / Tresguerras (ACT68080665A) ─────────────────
    "ACT68080665A": {
        "PALLET": {
            "Nayarit":     1901.0,
            "Quintana Roo": 3947.0,
            "Nuevo León":  2339.0,
            "CDMX":        1901.0,
            "BCS":         4530.0,
        },
        "TORTON": {
            "Nayarit":  17207.0,
        },
        "TRAILER": {
            "Nayarit":    21595.0,
            "Nuevo León": 29124.0,
            "CDMX":       23156.0,
            "BCS":        122176.0,
        },
    },

    # ── Transportes de Carga Hormik (TCH170824TH2) ───────────────
    "TCH170824TH2": {
        "TRAILER": {
            "Nuevo León": 29900.0,
            "CDMX":       25031.0,
        },
    },

    # ── NT (pendiente de confirmar RFC) ──────────────────────────
    # "RFC_NT": {
    #     "TORTON": { "Nayarit": 17000, "Quintana Roo": 89000, ... }
    # },

    # ── Continental (pendiente RFC) ───────────────────────────────
    # "RFC_CONTINENTAL": {
    #     "PALLET": { "Nayarit": 1500 },
    #     "TORTON": { "Nayarit": 15000 },
    # },

    # ── Xpress MG (pendiente RFC) ─────────────────────────────────
    # "RFC_XPRESSMG": {
    #     "TRAILER": { "Quintana Roo": 95000, "Nuevo León": 32000 },
    # },
}


def obtener_tarifa(rfc_fletera: str, tipo_vehiculo: str,
                   destino_estado: str) -> float | None:
    """Retorna la tarifa de referencia en MXN, o None si no existe."""
    return (TARIFAS_DISPERSIONES
            .get(rfc_fletera, {})
            .get(tipo_vehiculo, {})
            .get(destino_estado))
