# Tests de motor/catalogos.py — categorización, destinos, cargo envío, normalización.
import pytest

from motor.catalogos import (
    categoria_partida, evaluar_destino, es_cargo_envio, _normalizar,
    sucursal_de_origen, PESO_EXCLUIDO_KG, VOLUMEN_EXCLUIDO_L,
)


# ── categoria_partida: por presentación/tamaño (la clave SAT NO decide) ──
def test_categoria_elegible_si_menor_25():
    assert categoria_partida(peso_kg=10) == "EQUIPO"


def test_categoria_excluido_en_25_inclusivo():
    # 25 exacto se EXCLUYE (límite inclusivo)
    assert categoria_partida(peso_kg=PESO_EXCLUIDO_KG) == "EXCLUIDO_GRANDE"
    assert categoria_partida(volumen_l=VOLUMEN_EXCLUIDO_L) == "EXCLUIDO_GRANDE"


def test_categoria_excluido_si_mayor_25():
    assert categoria_partida(peso_kg=50) == "EXCLUIDO_GRANDE"


def test_categoria_justo_debajo_de_25_es_elegible():
    assert categoria_partida(peso_kg=24.99) == "EQUIPO"


def test_categoria_sin_tamano_es_elegible():
    assert categoria_partida() == "EQUIPO"


def test_clave_sat_no_determina_la_categoria():
    # Mismo producto/clave SAT; lo que decide es la presentación.
    assert categoria_partida("49241712", peso_kg=5) == "EQUIPO"            # chico → elegible
    assert categoria_partida("49241712", peso_kg=50) == "EXCLUIDO_GRANDE"  # grande → excluido


# ── sucursal_de_origen (origen real → código de sucursal) ─────────
def test_sucursal_por_ciudad():
    assert sucursal_de_origen("Guadalajara") == "GDL"
    assert sucursal_de_origen("Iztapalapa") == "CDMX"
    assert sucursal_de_origen("Cancún") == "CUN"


def test_sucursal_por_estado_fallback():
    assert sucursal_de_origen(ciudad="Ciudad X", estado="Nuevo León") == "MTY"


def test_sucursal_desconocida_vacia():
    assert sucursal_de_origen("Marte", "Marte") == ""


# ── evaluar_destino ───────────────────────────────────────────────
@pytest.mark.parametrize("estado,ciudad,esperado", [
    ("Jalisco", "", "OK"),
    ("Nuevo León", "", "OK"),
    ("Oaxaca", "", "R-301"),          # explícitamente no cubierto
    ("", "", "R-301"),                # estado vacío
    ("EstadoInventado", "", "R-301"), # fuera de catálogo
    ("Chiapas", "Tapachula", "OK"),
    ("Chiapas", "Tuxtla Gutiérrez", "OK"),   # con acento
    ("Chiapas", "San Cristóbal", "R-302"),   # ciudad no autorizada → borderline
])
def test_evaluar_destino(estado, ciudad, esperado):
    assert evaluar_destino(estado, ciudad) == esperado


# ── es_cargo_envio (Capa 1b) ──────────────────────────────────────
def test_cargo_envio_sku_y_desc_ok():
    assert es_cargo_envio("00400000000000", "CARGO POR ENVIO") is True


def test_cargo_envio_tolera_acentos_y_mayusculas():
    assert es_cargo_envio("00400000000000", "Cargo por Envío") is True


def test_cargo_envio_sku_incorrecto():
    assert es_cargo_envio("99999999999999", "CARGO POR ENVIO") is False


def test_cargo_envio_desc_sin_frase():
    assert es_cargo_envio("00400000000000", "FLETE NORMAL") is False


def test_cargo_envio_none_seguro():
    assert es_cargo_envio(None, None) is False


# ── _normalizar ───────────────────────────────────────────────────
def test_normalizar_quita_acentos_y_normaliza_espacios():
    assert _normalizar("  Cargo   por   Envío  ") == "CARGO POR ENVIO"


def test_normalizar_cadena_vacia():
    assert _normalizar("") == ""
