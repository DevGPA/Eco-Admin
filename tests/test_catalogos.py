# Tests de motor/catalogos.py — categorización, destinos, cargo envío, normalización.
import pytest

from motor.catalogos import (
    categoria_partida, evaluar_destino, es_cargo_envio, _normalizar,
    sucursal_de_origen, PESO_EXCLUIDO_KG, VOLUMEN_EXCLUIDO_L,
)


# ── categoria_partida: elegible (equipo) vs no elegible (restringido) ──
def test_equipo_pequeno_es_elegible():
    assert categoria_partida("Reflector LED", peso_kg=5) == "EQUIPO"


def test_excluido_por_tamano_25_inclusivo():
    # 25 exacto se EXCLUYE (límite inclusivo), peso o volumen
    assert categoria_partida("Bomba de calor", peso_kg=PESO_EXCLUIDO_KG) == "EXCLUIDO_GRANDE"
    assert categoria_partida("Cubeta", volumen_l=VOLUMEN_EXCLUIDO_L) == "EXCLUIDO_GRANDE"


def test_equipo_justo_debajo_de_25_es_elegible():
    assert categoria_partida("Filtro de arena", peso_kg=24.99) == "EQUIPO"


def test_equipo_grande_tambien_se_excluye_por_tamano():
    # Regla OR: un equipo ≥ 25 kg también se excluye por tamaño
    assert categoria_partida("Bomba para filtro 30 KGS") == "EXCLUIDO_GRANDE"


def test_restringido_por_tipo_aunque_sea_chico():
    # Restringidos por tipo aunque pesen < 25 kg/L
    assert categoria_partida("PEGA VENECIANO 5 KG") == "EXCLUIDO_RESTRINGIDO"
    assert categoria_partida("Adhesivo Imper Crest", peso_kg=2) == "EXCLUIDO_RESTRINGIDO"
    assert categoria_partida("Diamond Brite cubeta", peso_kg=10) == "EXCLUIDO_RESTRINGIDO"
    assert categoria_partida("River Rock", peso_kg=10) == "EXCLUIDO_RESTRINGIDO"
    assert categoria_partida("Quimico BlueQuim", peso_kg=1) == "EXCLUIDO_RESTRINGIDO"
    assert categoria_partida("SAL para alberca", peso_kg=10) == "EXCLUIDO_RESTRINGIDO"


def test_tamano_se_lee_de_la_descripcion():
    # Sin peso/volumen explícito, se extrae del texto
    assert categoria_partida("TRICLORO MAX GRANULAR 50 KGS") == "EXCLUIDO_GRANDE"
    assert categoria_partida("Producto generico 30 L") == "EXCLUIDO_GRANDE"


def test_equipo_sin_tamano_ni_keyword_es_elegible():
    assert categoria_partida("Equipo XYZ", peso_kg=5) == "EQUIPO"


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


# El OCR (y los usuarios) escriben el estado de muchas formas; la comparación
# debe ser insensible a acentos/mayúsculas y aceptar sinónimos oficiales.
@pytest.mark.parametrize("estado,esperado", [
    ("JALISCO", "OK"),                          # mayúsculas del OCR
    ("NUEVO LEON", "OK"),                       # sin acento
    ("Yucatan", "OK"),
    ("queretaro", "OK"),
    ("Estado de México", "OK"),                 # → Edo. México
    ("ESTADO DE MEXICO", "OK"),
    ("Ciudad de México", "OK"),                 # → CDMX
    ("Distrito Federal", "OK"),
    ("Veracruz de Ignacio de la Llave", "OK"),  # nombre constitucional
    ("Coahuila de Zaragoza", "OK"),
    ("Michoacán de Ocampo", "OK"),
    ("Baja California Sur", "OK"),              # → BCS
    ("OAXACA", "R-301"),                        # no cubierto, en mayúsculas
])
def test_evaluar_destino_variantes_ocr(estado, esperado):
    assert evaluar_destino(estado) == esperado


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
