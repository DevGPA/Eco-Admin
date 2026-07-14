# Tests de db/validaciones.py — política de unicidad y re-evaluación (sin AWS).
import db.validaciones as validaciones


class FakeTable:
    """Devuelve items canned por PK ('CP#...' / 'FV#...')."""
    def __init__(self, items_por_pk=None):
        self.items_por_pk = items_por_pk or {}

    def query(self, KeyConditionExpression=None, **kw):
        # boto3 Key("PK").eq(valor) → extraer el valor del condition expression
        valor = KeyConditionExpression._values[1]
        items = self.items_por_pk.get(valor, [])
        return {"Items": items, "Count": len(items)}


def _con_tabla(monkeypatch, items_por_pk):
    fake = FakeTable(items_por_pk)
    monkeypatch.setattr(validaciones, "_table", lambda: fake)


def test_sin_previos_es_valido(monkeypatch):
    _con_tabla(monkeypatch, {})
    res = validaciones.verificar_unicidad("CP1", ["FV1"])
    assert res["valido"] is True
    assert "reemplaza" not in res


def test_cp_en_revision_bloquea_r092(monkeypatch):
    _con_tabla(monkeypatch, {"CP#CP1": [{"SK": "SOL#abc", "estado": "EN_REVISION"}]})
    res = validaciones.verificar_unicidad("CP1", [])
    assert res["valido"] is False and res["codigo"] == "R-092"


def test_cp_aprobada_bloquea_r092(monkeypatch):
    _con_tabla(monkeypatch, {"CP#CP1": [{"SK": "SOL#abc", "estado": "AUTO_APROBADA"}]})
    res = validaciones.verificar_unicidad("CP1", [])
    assert res["valido"] is False and res["codigo"] == "R-092"


def test_rechazo_manual_bloquea_r092(monkeypatch):
    # Un humano ya rechazó este folio: re-subirlo no debe re-abrirlo solo.
    _con_tabla(monkeypatch, {"CP#CP1": [{"SK": "SOL#abc", "estado": "RECHAZADA_MANUAL"}]})
    res = validaciones.verificar_unicidad("CP1", [])
    assert res["valido"] is False and res["codigo"] == "R-092"


def test_auto_rechazada_permite_reevaluar_y_reemplaza(monkeypatch):
    # Veredicto de máquina (p.ej. por OCR mal extraído): re-subir el PDF debe
    # re-evaluar y sustituir el registro, no quedar sellado por R-092.
    _con_tabla(monkeypatch, {"CP#CP1": [{"SK": "SOL#viejo1", "estado": "AUTO_RECHAZADA"}]})
    res = validaciones.verificar_unicidad("CP1", ["FV1"])
    assert res["valido"] is True
    assert res["reemplaza"] == ["viejo1"]


def test_rechazo_aceptado_permite_reevaluar(monkeypatch):
    # El humano ACEPTÓ el rechazo del motor (RECHAZO_ACEPTADO, fuera del
    # tablero). Es un acuse, no un sello: re-subir el PDF corregido debe
    # re-evaluar y reemplazar, igual que un AUTO_RECHAZADA.
    _con_tabla(monkeypatch, {"CP#CP1": [{"SK": "SOL#v1", "estado": "RECHAZO_ACEPTADO"}]})
    res = validaciones.verificar_unicidad("CP1", ["FV1"])
    assert res["valido"] is True
    assert res["reemplaza"] == ["v1"]


def test_mezcla_rechazada_y_activa_bloquea(monkeypatch):
    # Si además del rechazo viejo hay una solicitud ACTIVA → sigue bloqueado.
    _con_tabla(monkeypatch, {"CP#CP1": [
        {"SK": "SOL#viejo1", "estado": "AUTO_RECHAZADA"},
        {"SK": "SOL#activa", "estado": "EN_REVISION"},
    ]})
    res = validaciones.verificar_unicidad("CP1", [])
    assert res["valido"] is False and res["codigo"] == "R-092"


def test_fv_en_aprobada_bloquea_r091(monkeypatch):
    _con_tabla(monkeypatch, {"FV#FV1": [{"SK": "SOL#ap", "estado": "APROBADA_MANUAL"}]})
    res = validaciones.verificar_unicidad("CPNUEVA", ["FV1"])
    assert res["valido"] is False and res["codigo"] == "R-091"


def test_fv_en_rechazada_no_bloquea(monkeypatch):
    _con_tabla(monkeypatch, {"FV#FV1": [{"SK": "SOL#rj", "estado": "AUTO_RECHAZADA"}]})
    res = validaciones.verificar_unicidad("CPNUEVA", ["FV1"])
    assert res["valido"] is True


def test_folio_fv_vacio_no_participa_en_unicidad(monkeypatch):
    # Caso prod: una solicitud APROBADA guardada con folio de FV vacío
    # bloqueaba (R-091) TODAS las facturas futuras sin folio.
    _con_tabla(monkeypatch, {"FV#": [{"SK": "SOL#aprobada", "estado": "AUTO_APROBADA"}]})
    res = validaciones.verificar_unicidad("CPNUEVA", ["", "   "])
    assert res["valido"] is True
