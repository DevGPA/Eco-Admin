# tests/test_puente.py
# Pruebas del publisher del puente (bridge/publisher.py) — sin AWS.
#   python -m unittest tests.test_puente -v
# Además genera los payloads golden en tests/golden/ para las pruebas
# de contrato del receptor en Fleet Command.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import publisher  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden"


# ── Imágenes de stream de ejemplo (DynamoDB JSON) ─────────────────
def _img_sol(status="Pendiente"):
    return {
        "PK": {"S": "SOL#a1b2c3d4e5f6"}, "SK": {"S": "META"},
        "GSI1PK": {"S": "SOL"}, "GSI1SK": {"S": "2026-07-09T18:30:00+00:00"},
        "GSI2PK": {"S": "SOL#Culiacán"}, "GSI2SK": {"S": "2026-07-09T18:30:00+00:00"},
        "GSI3PK": {"S": "SOL#juan@gpa.com.mx"}, "GSI3SK": {"S": "2026-07-09T18:30:00+00:00"},
        "id": {"S": "a1b2c3d4e5f6"}, "tipo_reg": {"S": "SOL"},
        "fecha": {"S": "2026-07-09T18:30:00+00:00"},
        "sucursal": {"S": "Culiacán"}, "accountId": {"S": "juan@gpa.com.mx"},
        "vehicleId": {"S": "V-0042"}, "economico": {"S": "42"},
        "placas": {"S": "ABC123D"}, "subMarca": {"S": "NP300"},
        "userId": {"S": "U-17"}, "responsable": {"S": "Juan Pérez"},
        "km": {"N": "123456"}, "tankBefore": {"N": "0.25"}, "tankAfter": {"N": "1"},
        "necesidad": {"S": "Ruta foránea"}, "litros": {"N": "48.3"},
        "monto": {"N": "1286.31"}, "combustible": {"S": "Gasolina"},
        "producto": {"S": "Magna"}, "precio": {"N": "26.63"}, "tanque": {"N": "60"},
        "obs": {"S": ""}, "status": {"S": status},
        "photo": {"S": "SOL/" + "3f" * 16 + ".jpg"},
        "firma": {"S": "SOL/" + "9e" * 16 + ".png"},
    }


def _img_cl():
    return {
        "PK": {"S": "CL#f6e5d4c3b2a1"}, "SK": {"S": "META"},
        "id": {"S": "f6e5d4c3b2a1"}, "tipo_reg": {"S": "CL"},
        "tipo": {"S": "semanal"},
        "fecha": {"S": "2026-07-09T12:00:00+00:00"},
        "sucursal": {"S": "Guadalajara"}, "accountId": {"S": "ana@gpa.com.mx"},
        "vehicleId": {"S": "V-0007"}, "economico": {"S": "7"}, "placas": {"S": "XYZ987A"},
        "userId": {"S": "U-22"}, "responsable": {"S": "Ana López"},
        "km": {"N": "98765"},
        "fotoKm": {"S": "CL/" + "77" * 16 + ".jpg"},
        "answers": {"M": {
            "llantas": {"S": "Bien"},
            "carroceria": {"S": "Con Raspaduras/Golpes"},
            "nivelAceite": {"S": "OK"},
            "fotoLlanta": {"S": "CL/" + "ab" * 16 + ".webp"},
        }},
        "obs": {"S": "sin novedades"},
        "firma": {"S": "CL/" + "cd" * 16 + ".png"},
    }


def _record(event_name, new_img, old_img=None, seq="111"):
    d = {"SequenceNumber": seq, "NewImage": new_img}
    if old_img:
        d["OldImage"] = old_img
    return {"eventName": event_name, "dynamodb": d}


class TestFiltro(unittest.TestCase):
    def test_insert_sol_emite_creacion(self):
        item, evento = publisher.filtrar_record(_record("INSERT", _img_sol()))
        self.assertEqual(evento, "creacion")
        self.assertEqual(item["id"], "a1b2c3d4e5f6")

    def test_modify_con_cambio_de_status_emite(self):
        r = _record("MODIFY", _img_sol("Aprobada"), _img_sol("Pendiente"))
        item, evento = publisher.filtrar_record(r)
        self.assertEqual(evento, "cambio_estado")
        self.assertEqual(item["status"], "Aprobada")

    def test_modify_sin_cambio_de_status_no_emite(self):
        r = _record("MODIFY", _img_sol(), _img_sol())
        self.assertIsNone(publisher.filtrar_record(r))

    def test_mc_no_cruza_el_puente(self):
        img = _img_sol()
        img["PK"] = {"S": "MC#000000000001"}
        img["tipo_reg"] = {"S": "MC"}
        self.assertIsNone(publisher.filtrar_record(_record("INSERT", img)))

    def test_catalogos_no_cruzan(self):
        img = {"PK": {"S": "CAT#VEHICLE"}, "SK": {"S": "VEH#V-1"}}
        self.assertIsNone(publisher.filtrar_record(_record("INSERT", img)))

    def test_remove_no_emite(self):
        self.assertIsNone(publisher.filtrar_record(_record("REMOVE", _img_sol())))


class TestEvento(unittest.TestCase):
    def test_evento_sol(self):
        item, _ = publisher.filtrar_record(_record("INSERT", _img_sol()))
        ev = publisher.construir_evento(item, "creacion")
        self.assertEqual(ev["contrato"], "gpa.ops.v1")
        self.assertEqual(ev["version"], 1)
        self.assertEqual(ev["tipo"], "SOL")
        self.assertIsNone(ev["subtipo"])
        self.assertEqual(ev["folio"], "OPS-a1b2c3d4e5f6")
        self.assertEqual(ev["fechaISO"], "2026-07-09T18:30:00+00:00")
        self.assertEqual(ev["unidad"], {"vehicleId": "V-0042", "economico": "42", "placas": "ABC123D"})
        self.assertEqual(ev["responsable"]["accountId"], "juan@gpa.com.mx")
        self.assertEqual(ev["status"], "Pendiente")
        self.assertEqual(ev["answers"]["litros"], 48.3)
        self.assertEqual(ev["answers"]["km"], 123456)          # N entero → int
        self.assertEqual(ev["firma"], "SOL/" + "9e" * 16 + ".png")
        # la foto del odómetro aparece como evidencia con su campo
        self.assertIn({"campo": "photo", "key": "SOL/" + "3f" * 16 + ".jpg"}, ev["evidencias"])
        # las claves de Dynamo no viajan en answers
        for k in ("PK", "SK", "GSI1PK", "id", "accountId"):
            self.assertNotIn(k, ev["answers"])

    def test_evento_cl_semanal_con_evidencias_anidadas(self):
        item, _ = publisher.filtrar_record(_record("INSERT", _img_cl()))
        ev = publisher.construir_evento(item, "creacion")
        self.assertEqual(ev["tipo"], "CL")
        self.assertEqual(ev["subtipo"], "semanal")
        campos = {e["campo"] for e in ev["evidencias"]}
        self.assertIn("fotoKm", campos)
        self.assertIn("answers.fotoLlanta", campos)            # anidada, con ruta
        self.assertEqual(ev["answers"]["answers"]["carroceria"], "Con Raspaduras/Golpes")


class TestFirmaYEnvio(unittest.TestCase):
    def test_firma_hmac_reproducible(self):
        f = publisher.firmar("secreto", "1751900000", b'{"a":1}')
        import hashlib, hmac as h
        esperada = h.new(b"secreto", b'1751900000.{"a":1}', hashlib.sha256).hexdigest()
        self.assertEqual(f, esperada)

    def test_lote_reporta_fallidos_para_reintento(self):
        recs = {"Records": [_record("INSERT", _img_sol(), seq="s-1"),
                            _record("INSERT", _img_cl(), seq="s-2")]}
        with mock.patch.dict(os.environ, {"FLEET_BRIDGE_URL": "https://fc/bridge/ops",
                                          "FLEET_BRIDGE_SECRET": "x"}):
            with mock.patch.object(publisher, "enviar",
                                   side_effect=[RuntimeError("500"), None]):
                out = publisher.lambda_handler(recs, None)
        self.assertEqual(out["batchItemFailures"], [{"itemIdentifier": "s-1"}])

    def test_modo_espera_sin_url_confirma_todo(self):
        recs = {"Records": [_record("INSERT", _img_sol())]}
        with mock.patch.dict(os.environ, {"FLEET_BRIDGE_URL": ""}):
            with mock.patch.object(publisher, "enviar") as env_mock:
                out = publisher.lambda_handler(recs, None)
        env_mock.assert_not_called()
        self.assertEqual(out["batchItemFailures"], [])

    def test_headers_del_post(self):
        ev = {"x": 1}
        capturado = {}

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=0):
            capturado["req"] = req
            return _Resp()

        with mock.patch.object(publisher.urllib.request, "urlopen", fake_urlopen):
            publisher.enviar(ev, "https://fc/bridge/ops", "secreto")
        req = capturado["req"]
        self.assertEqual(req.get_header("X-gpa-contrato"), "gpa.ops.v1")
        ts = req.get_header("X-gpa-timestamp")
        self.assertEqual(req.get_header("X-gpa-firma"),
                         publisher.firmar("secreto", ts, req.data))


class TestGolden(unittest.TestCase):
    """Genera los payloads canónicos para las pruebas de contrato del receptor."""

    def test_generar_golden(self):
        GOLDEN_DIR.mkdir(exist_ok=True)
        casos = {
            "sol-creacion": (_record("INSERT", _img_sol()), None),
            "sol-cambio-estado": (_record("MODIFY", _img_sol("Aprobada"), _img_sol()), None),
            "cl-semanal-creacion": (_record("INSERT", _img_cl()), None),
        }
        for nombre, (rec, _) in casos.items():
            item, evento = publisher.filtrar_record(rec)
            ev = publisher.construir_evento(item, evento)
            ev["emitidoEn"] = "2026-07-09T00:00:00+00:00"      # determinista
            ev["bucketOrigen"] = "gpa-ops-evidencias-ENV-CUENTA"
            (GOLDEN_DIR / f"{nombre}.json").write_text(
                json.dumps(ev, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        self.assertEqual(len(list(GOLDEN_DIR.glob("*.json"))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
