# Tests de db/escritura.py — manejo de claves de GSI vacías (sin AWS real).
import db.escritura as escritura
from motor.evaluador import ResultadoMotor


class FakeDynamo:
    def __init__(self):
        self.transact = None

    def transact_write_items(self, TransactItems):
        self.transact = TransactItems
        return {}


def _guardar(monkeypatch, **campos):
    fake = FakeDynamo()
    monkeypatch.setattr(escritura, "_dynamo_client", lambda: fake)
    res = ResultadoMotor(
        codigo_motor="R-402", concepto_motor="Fletera no autorizada",
        estado="AUTO_RECHAZADA", tipo_operacion="VENTA_CLIENTE",
        folio_cp="117551580", folios_fv=["FA1"],
        **campos,
    )
    escritura.guardar_solicitud(res)
    item_meta = fake.transact[0]["Put"]["Item"]
    return item_meta


def test_gsi_keys_vacias_se_omiten(monkeypatch):
    # Sin fletera/origen/destino → esas claves de GSI NO deben escribirse
    item = _guardar(monkeypatch, fleta_rfc="", origen_sucursal="",
                    destino_estado="", fecha_emision="")
    assert "fletaRFC" not in item
    assert "origenSucursal" not in item
    assert "destinoEstado" not in item
    # fechaEmision (clave RANGE de los GSI) nunca vacía → respaldo fecha de evaluación
    assert item["fechaEmision"]["S"]            # no vacío
    assert len(item["fechaEmision"]["S"]) == 10  # YYYY-MM-DD


def test_gsi_keys_presentes_si_tienen_valor(monkeypatch):
    item = _guardar(monkeypatch, fleta_rfc="TCH170824TH2", origen_sucursal="GDL",
                    destino_estado="Jalisco", fecha_emision="2026-05-07")
    assert item["fletaRFC"]["S"] == "TCH170824TH2"
    assert item["origenSucursal"]["S"] == "GDL"
    assert item["destinoEstado"]["S"] == "Jalisco"
    assert item["fechaEmision"]["S"] == "2026-05-07"
