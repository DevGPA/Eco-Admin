# Tests de motor/catalogos.py — categorización, destinos, cargo envío, normalización.
import pytest

from motor.catalogos import (
    categoria_partida, evaluar_destino, es_cargo_envio, _normalizar,
    PESO_MAX_EXCLUIDO_P,
)


# ── categoria_partida ─────────────────────────────────────────────
@pytest.mark.parametrize("sku,esperado", [
    ("39111611", "EQUIPO"),
    ("40151510", "EQUIPO"),
    ("30131704", "RECUBRIMIENTO"),
    ("30111601", "MATERIAL_INSTALACION"),
    ("49241712", "EXCLUIDO_GRANDE"),
    ("11111607", "EXCLUIDO_PEQUENO"),
])
def test_categoria_por_sku_catalogo(sku, esperado):
    assert categoria_partida(sku) == esperado


def test_categoria_por_peso_grande():
    assert categoria_partida("SKU-DESCONOCIDO", peso_kg=30) == "EXCLUIDO_GRANDE"


def test_categoria_por_volumen_grande():
    assert categoria_partida("SKU-DESCONOCIDO", volumen_l=60) == "EXCLUIDO_GRANDE"


def test_categoria_por_peso_pequeno():
    assert categoria_partida("SKU-DESCONOCIDO", peso_kg=10) == "EXCLUIDO_PEQUENO"


def test_categoria_fallback_equipo_sin_datos():
    # SKU desconocido sin peso ni volumen → fallback elegible (EQUIPO)
    assert categoria_partida("SKU-DESCONOCIDO") == "EQUIPO"


def test_categoria_limite_25kg_es_pequeno_inclusivo():
    # El límite 25 kg es inclusivo hacia PEQUEÑO (spec v2.3)
    assert categoria_partida("X", peso_kg=PESO_MAX_EXCLUIDO_P) == "EXCLUIDO_PEQUENO"


def test_categoria_limite_25kg_mas_uno_es_grande():
    assert categoria_partida("X", peso_kg=PESO_MAX_EXCLUIDO_P + 0.01) == "EXCLUIDO_GRANDE"


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
