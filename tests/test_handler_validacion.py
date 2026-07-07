# Tests de validación de entrada del handler (rutas que retornan 400 sin tocar AWS).
import json
import boto3
from handler import _route_evaluar, _route_upload_url


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


# ── /upload-url (URL prefirmada de S3) ────────────────────────────────
class _FakeS3:
    def __init__(self):
        self.llamada = None

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.llamada = {"op": op, "Params": Params, "ExpiresIn": ExpiresIn}
        return "https://s3.amazonaws.com/gpa-docs/presigned?X-Amz-Signature=abc"


def test_upload_url_genera_presigned(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    monkeypatch.setenv("S3_BUCKET", "gpa-docs-test")
    resp = _route_upload_url(_evento({"filename": "116873635.pdf", "fecha": "2026-05-07"}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["url"].startswith("https://s3.amazonaws.com/")
    assert body["key"] == "pendientes/2026-05-07/116873635.pdf"
    assert body["bucket"] == "gpa-docs-test"
    assert fake.llamada["op"] == "put_object"
    assert fake.llamada["Params"]["Bucket"] == "gpa-docs-test"


def test_upload_url_rechaza_extension_invalida(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "gpa-docs-test")
    assert _route_upload_url(_evento({"filename": "factura.docx"}))["statusCode"] == 400
    # XML también se rechaza: el OCR solo procesa PDF (evita falla silenciosa).
    assert _route_upload_url(_evento({"filename": "cfdi.xml"}))["statusCode"] == 400


def test_upload_url_sin_bucket_500(monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    resp = _route_upload_url(_evento({"filename": "116.pdf"}))
    assert resp["statusCode"] == 500


def test_upload_url_sanitiza_nombre(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    monkeypatch.setenv("S3_BUCKET", "gpa-docs-test")
    resp = _route_upload_url(_evento({"filename": "fac tura/../raro.pdf", "fecha": "2026-05-07"}))
    assert resp["statusCode"] == 200
    key = json.loads(resp["body"])["key"]
    assert ".." not in key and " " not in key and key.startswith("pendientes/2026-05-07/")


def test_upload_url_extension_a_minusculas(monkeypatch):
    # El filtro de sufijo de S3 (.pdf) es sensible a mayúsculas: la key debe
    # terminar en minúsculas para que el objeto dispare el OCR.
    fake = _FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    monkeypatch.setenv("S3_BUCKET", "gpa-docs-test")
    resp = _route_upload_url(_evento({"filename": "FACTURA.PDF", "fecha": "2026-05-07"}))
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["key"].endswith(".pdf")


# ── Re-evaluación: el previo AUTO_RECHAZADA se marca REEMPLAZADA ──────
def test_evaluar_reemplaza_rechazo_previo(monkeypatch):
    import handler as h

    marcados = []
    monkeypatch.setattr(h, "verificar_unicidad",
                        lambda cp, fvs: {"valido": True, "reemplaza": ["viejo1", "viejo2"]})
    monkeypatch.setattr(h, "guardar_solicitud",
                        lambda res: {"id": "nuevo123", "fechaEvaluacion": "2026-06-12T00:00:00"})
    monkeypatch.setattr(h, "cambiar_estado",
                        lambda sid, estado, uid, com="": marcados.append((sid, estado)))

    resp = h._route_evaluar(_evento(_body_valido()))
    assert resp["statusCode"] == 201
    assert ("viejo1", "REEMPLAZADA") in marcados
    assert ("viejo2", "REEMPLAZADA") in marcados


def test_evaluar_no_truena_si_reemplazo_falla(monkeypatch):
    # Un previo corrupto no debe tumbar la evaluación nueva (ya guardada).
    import handler as h

    monkeypatch.setattr(h, "verificar_unicidad",
                        lambda cp, fvs: {"valido": True, "reemplaza": ["fantasma"]})
    monkeypatch.setattr(h, "guardar_solicitud",
                        lambda res: {"id": "nuevo123", "fechaEvaluacion": "2026-06-12T00:00:00"})
    def _boom(*a, **k): raise ValueError("Solicitud fantasma no encontrada")
    monkeypatch.setattr(h, "cambiar_estado", _boom)

    resp = h._route_evaluar(_evento(_body_valido()))
    assert resp["statusCode"] == 201


# ── R-093 (sin factura anexa) + dedupe de tarjetas de error ──────────
def _fake_ddb(monkeypatch, existentes=None):
    import handler as h
    import db.escritura as esc
    escritos = []
    class DDB:
        def put_item(self, TableName=None, Item=None): escritos.append(Item)
    monkeypatch.setattr(esc, "_dynamo_client", lambda: DDB())
    monkeypatch.setattr(h, "get_por_rango_fecha", lambda e, d, hs: existentes or [])
    return escritos


def test_sin_fv_anexa_es_rechazo_r093(monkeypatch):
    import handler as h
    escritos = _fake_ddb(monkeypatch)
    h._guardar_caso_error({"error": "SIN_FV_VINCULADA", "folioCP": "119480566",
                           "detalle": "CP sin factura"}, "pendientes/x.pdf")
    metas = [i for i in escritos if i["SK"]["S"] == "#META"]
    assert metas[0]["estado"]["S"] == "AUTO_RECHAZADA"
    assert metas[0]["codigoMotor"]["S"] == "R-093"
    # y deja item CP# para que la re-subida con factura lo REEMPLACE sola
    cps = [i for i in escritos if i["PK"]["S"] == "CP#119480566"]
    assert len(cps) == 1 and cps[0]["estado"]["S"] == "AUTO_RECHAZADA"


def test_error_ocr_duplicado_no_crea_otra_tarjeta(monkeypatch):
    import handler as h
    escritos = _fake_ddb(monkeypatch,
        existentes=[{"folioCP": "TPQ1A-955", "codigoMotor": "R-093"}])
    h._guardar_caso_error({"error": "SIN_FV_VINCULADA", "folioCP": "TPQ1A-955"}, "k.pdf")
    assert escritos == []      # reintento de S3 → no duplica
