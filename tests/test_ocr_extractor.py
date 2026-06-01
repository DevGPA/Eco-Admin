# Tests de s3/ocr_extractor.py — clasificación por RFC y armado de caso.
# No requieren AWS/Bedrock ni PyMuPDF (se prueba la lógica pura con páginas mock).
import pytest

from s3.ocr_extractor import clasificar_por_rfc, armar_caso, _parse_json
from motor.catalogos import RFC_GPA

CARRIER = "ACT680806665A"
CLIENTE = "PEA230227FL6"


def pag(emisor=None, receptor=None, subtotal=None, moneda=None, tc=None, folio=None):
    return {"rfcEmisor": emisor, "rfcReceptor": receptor, "subtotal": subtotal,
            "moneda": moneda, "tipoCambio": tc, "folio": folio}


def cp(subtotal, folio="116162584"):
    # Carta porte: la emite la fletera, GPA es receptor
    return pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=subtotal, moneda="MXN", folio=folio)


def fv(subtotal, folio="FA10314168", tc=17.77):
    # Factura de venta: la emite GPA
    return pag(emisor=RFC_GPA, receptor=CLIENTE, subtotal=subtotal, moneda="USD", tc=tc, folio=folio)


# ── clasificar_por_rfc ────────────────────────────────────────────
def test_gpa_emisor_es_fv():
    assert clasificar_por_rfc(RFC_GPA, CLIENTE) == "FV"


def test_gpa_receptor_es_cp():
    assert clasificar_por_rfc(CARRIER, RFC_GPA) == "CP"


def test_gpa_en_ninguno_es_error():
    assert clasificar_por_rfc(CARRIER, CLIENTE) == "ERROR"


def test_clasificacion_ignora_mayusculas_y_espacios():
    assert clasificar_por_rfc("  gpa8402219y1  ", CLIENTE) == "FV"


def test_clasificacion_ambos_none_es_error():
    assert clasificar_por_rfc(None, None) == "ERROR"


# ── armar_caso ────────────────────────────────────────────────────
def test_caso_cp_mas_fv_ok():
    res = armar_caso([cp(132.00), fv(4.41)], folio_archivo="116162584")
    assert res["status"] == "OK"
    assert res["fleteSinIvaMXN"] == pytest.approx(132.00)
    assert res["montoVentaFV"] == pytest.approx(4.41)
    assert res["monedaFV"] == "USD"
    assert res["tipoCambioRef"] == pytest.approx(17.77)
    assert res["foliosFV"] == ["FA10314168"]


def test_caso_suma_varias_fv():
    res = armar_caso([cp(200.0), fv(4.41, folio="FA1"), fv(5.59, folio="FA2")])
    assert res["status"] == "OK"
    assert res["montoVentaFV"] == pytest.approx(10.00)
    assert res["paginasFV"] == 2
    assert res["foliosFV"] == ["FA1", "FA2"]


def test_caso_suma_varios_cp_para_flete():
    res = armar_caso([cp(100.0), cp(32.0), fv(4.41)])
    assert res["fleteSinIvaMXN"] == pytest.approx(132.0)
    assert res["paginasCP"] == 2


def test_caso_sin_cp_es_error():
    res = armar_caso([fv(4.41)])
    assert res["status"] == "ERROR"
    assert res["error"] == "SIN_CARTA_PORTE"


def test_caso_sin_fv_es_error():
    res = armar_caso([cp(132.0)])
    assert res["status"] == "ERROR"
    assert res["error"] == "SIN_FACTURA_GPA"


def test_caso_cuenta_paginas_ajenas():
    ajena = pag(emisor=CARRIER, receptor=CLIENTE, subtotal=999)  # GPA no aparece
    res = armar_caso([cp(132.0), fv(4.41), ajena])
    assert res["status"] == "OK"
    assert res["paginasError"] == 1
    # la página ajena no contamina los montos
    assert res["fleteSinIvaMXN"] == pytest.approx(132.0)
    assert res["montoVentaFV"] == pytest.approx(4.41)


def test_caso_vacio_es_error():
    res = armar_caso([])
    assert res["status"] == "ERROR"


# ── _parse_json ───────────────────────────────────────────────────
def test_parse_json_extrae_objeto_con_prosa():
    txt = 'Claro, aquí está:\n{"rfcEmisor": "GPA8402219Y1", "subtotal": 4.41}\nEspero ayude.'
    d = _parse_json(txt)
    assert d["rfcEmisor"] == "GPA8402219Y1"
    assert d["subtotal"] == 4.41


def test_parse_json_sin_json_lanza():
    with pytest.raises(ValueError):
        _parse_json("no hay json aquí")
