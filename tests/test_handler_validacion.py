# Tests de validación de entrada del handler (rutas que retornan 400 sin tocar AWS).
import json
from handler import _route_evaluar


def _evento(body: dict) -> dict:
    return {"requestContext": {}, "body": json.dumps(body)}


def _body_valido(**overrides) -> dict:
    b = {
        "folioCP": "116873635",
        "foliosFV": ["FA10315862"],
        "origenSucursal": "GDL",
        "destinoEstado": "Jalisco",
        "fletaRFC": "ACT68080665A",
        "partidas": [{"sku": "39111611", "cantidad": 1, "precioUnitarioUSD": 1000}],
        "fleteBaseMXN": 1000.0,
        "tipoCambioRef": 17.35,
        "fechaEmision": "2026-04-22",
    }
    b.update(overrides)
    return b


def test_faltan_campos_requeridos_400():
    resp = _route_evaluar(_evento({"folioCP": "1"}))
    assert resp["statusCode"] == 400
    assert "requeridos" in resp["body"].lower()


def test_tipo_cambio_cero_400():
    resp = _route_evaluar(_evento(_body_valido(tipoCambioRef=0)))
    assert resp["statusCode"] == 400
    assert "tipoCambioRef" in resp["body"]


def test_tipo_cambio_negativo_400():
    resp = _route_evaluar(_evento(_body_valido(tipoCambioRef=-5)))
    assert resp["statusCode"] == 400


def test_tipo_cambio_no_numerico_400():
    resp = _route_evaluar(_evento(_body_valido(tipoCambioRef="abc")))
    assert resp["statusCode"] == 400


def test_chiapas_sin_ciudad_400():
    resp = _route_evaluar(_evento(_body_valido(destinoEstado="Chiapas")))
    assert resp["statusCode"] == 400
    assert "Chiapas" in resp["body"]
