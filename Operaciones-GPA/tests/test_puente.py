# tests/test_puente.py
# Pruebas del publisher del puente (bridge/publisher.py) — sin AWS.
#   python -m unittest tests.test_puente -v
# Además genera los payloads golden en tests/golden/ para las pruebas
# de contrato del receptor en Fleet Command.
#
# Las imágenes de ejemplo son ESPEJOS de registros reales de
# gpa_operaciones_prod (mismos id/unidad/sucursal/km; el resto de campos
# replica la forma exacta que produce el frontend):
#   - SOL 34354ae5d278  solicitud  · eco 10 (JLL5377, Matiz), Guadalajara, km 77777
#   - SOL (reporte)     carga      · mismo vehículo, answers.formato="reporte"
#   - CL  88d8c62e3378  semanal    · eco 16 (PR3430A, F-350), Guadalajara
# Sucursales válidas en prod: Cabos, Cancun, Cedis, Ciudad de Mexico,
# Guadalajara, Monterrey, Vallarta.
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
    """Espejo de SOL 34354ae5d278 (solicitud de combustible, eco 10)."""
    return {
        "PK": {"S": "SOL#34354ae5d278"}, "SK": {"S": "META"},
        "GSI1PK": {"S": "SOL"}, "GSI1SK": {"S": "2026-07-08T15:42:11+00:00"},
        "GSI2PK": {"S": "SOL#Guadalajara"}, "GSI2SK": {"S": "2026-07-08T15:42:11+00:00"},
        "GSI3PK": {"S": "SOL#operador.gdl@gpa.com.mx"}, "GSI3SK": {"S": "2026-07-08T15:42:11+00:00"},
        "id": {"S": "34354ae5d278"}, "tipo_reg": {"S": "SOL"},
        "fecha": {"S": "2026-07-08T15:42:11+00:00"},
        "sucursal": {"S": "Guadalajara"}, "accountId": {"S": "operador.gdl@gpa.com.mx"},
        "vehicleId": {"S": "10"}, "economico": {"S": "10"},
        "placas": {"S": "JLL5377"}, "subMarca": {"S": "Matiz 5 Ptas"},
        "userId": {"S": "46"}, "responsable": {"S": "Operador Guadalajara"},
        "mail": {"S": "operador.gdl@gpa.com.mx"},
        "km": {"N": "77777"}, "tankBefore": {"N": "0.25"}, "tankAfter": {"N": "1"},
        "necesidad": {"S": "Ruta local"}, "litros": {"N": "26.25"},
        "monto": {"N": "699.04"}, "combustible": {"S": "Gasolina"},
        "producto": {"S": "TOKA COMBUSTIBLE MAGNA CHIP"},
        "precio": {"N": "26.63"}, "tanque": {"N": "35"},
        "obs": {"S": ""}, "status": {"S": status},
        "photo": {"S": "SOL/" + "3f" * 16 + ".jpg"},
        "firma": {"S": "SOL/" + "9e" * 16 + ".png"},
    }


def _img_sol_reporte():
    """Reporte de carga (mismo tipo_reg=SOL; se distingue por formato="reporte")."""
    return {
        "PK": {"S": "SOL#b2f4e6a8c0d2"}, "SK": {"S": "META"},
        "id": {"S": "b2f4e6a8c0d2"}, "tipo_reg": {"S": "SOL"},
        "formato": {"S": "reporte"},
        "fecha": {"S": "2026-07-08T19:05:47+00:00"},
        "sucursal": {"S": "Guadalajara"}, "accountId": {"S": "operador.gdl@gpa.com.mx"},
        "vehicleId": {"S": "10"}, "economico": {"S": "10"},
        "placas": {"S": "JLL5377"}, "subMarca": {"S": "Matiz 5 Ptas"},
        "areaResponsable": {"S": "MANTENIMIENTO"},
        "userId": {"S": "46"}, "responsable": {"S": "Operador Guadalajara"},
        "mail": {"S": "operador.gdl@gpa.com.mx"},
        "km": {"N": "77812"}, "lleno": {"BOOL": True},
        "litros": {"N": "25.5"}, "precioLitro": {"N": "26.63"},
        "monto": {"N": "679.07"}, "combustible": {"S": "Gasolina"},
        "producto": {"S": "TOKA COMBUSTIBLE MAGNA CHIP"},
        "precio": {"N": "26.63"}, "tanque": {"N": "35"},
        "ubicacion": {"M": {"lat": {"N": "20.6597"}, "lng": {"N": "-103.3496"}}},
        "fotoAntes":   {"S": "SOL/" + "a1" * 16 + ".jpg"},
        "fotoDespues": {"S": "SOL/" + "a2" * 16 + ".jpg"},
        "fotoBomba":   {"S": "SOL/" + "a3" * 16 + ".jpg"},
        "fotoTicket":  {"S": "SOL/" + "a4" * 16 + ".jpg"},
        "fotoPersona": {"S": "SOL/" + "a5" * 16 + ".jpg"},
        "obs": {"S": ""}, "status": {"S": "Pendiente"},
        "firma": {"S": "SOL/" + "a6" * 16 + ".png"},
    }


def _img_cl():
    """Espejo de CL 88d8c62e3378 (checklist semanal, eco 16)."""
    return {
        "PK": {"S": "CL#88d8c62e3378"}, "SK": {"S": "META"},
        "id": {"S": "88d8c62e3378"}, "tipo_reg": {"S": "CL"},
        "tipo": {"S": "semanal"},
        "fecha": {"S": "2026-07-06T13:20:38+00:00"},
        "sucursal": {"S": "Guadalajara"}, "accountId": {"S": "chofer.gdl@gpa.com.mx"},
        "vehicleId": {"S": "16"}, "economico": {"S": "16"}, "placas": {"S": "PR3430A"},
        "subMarca": {"S": "F-350 Chas Cabina Xl"},
        "userId": {"S": "16"}, "responsable": {"S": "Chofer Guadalajara"},
        "km": {"N": "154302"},
        "fotoKm": {"S": "CL/" + "77" * 16 + ".jpg"},
        "answers": {"M": {
            "llantas": {"S": "Bien"},
            "carroceria": {"S": "Con Raspaduras/Golpes"},
            "nivelAceite": {"S": "OK"},
            "fotoLlanta": {"S": "CL/" + "ab" * 16 + ".webp"},
        }},
        "obs": {"S": "sin novedades"},
        "firma": {"S": "CL/" + "cd" * 16 + ".png"},
        "status": {"S": "Aprobado"},
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
        self.assertEqual(item["id"], "34354ae5d278")

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

    def test_frm_no_cruza_el_puente(self):
        img = _img_sol()
        img["PK"] = {"S": "FRM#seguridad-extintores#000000000001"}
        img["tipo_reg"] = {"S": "FRM#seguridad-extintores"}
        self.assertIsNone(publisher.filtrar_record(_record("INSERT", img)))

    def test_catalogos_no_cruzan(self):
        img = {"PK": {"S": "CAT#VEHICLE"}, "SK": {"S": "VEH#10"}}
        self.assertIsNone(publisher.filtrar_record(_record("INSERT", img)))

    def test_remove_no_emite(self):
        self.assertIsNone(publisher.filtrar_record(_record("REMOVE", _img_sol())))


class TestEvento(unittest.TestCase):
    def test_evento_sol_solicitud(self):
        item, _ = publisher.filtrar_record(_record("INSERT", _img_sol()))
        ev = publisher.construir_evento(item, "creacion")
        self.assertEqual(ev["contrato"], "gpa.ops.v1")
        self.assertEqual(ev["version"], 1)
        self.assertEqual(ev["tipo"], "SOL")
        self.assertIsNone(ev["subtipo"])
        self.assertEqual(ev["folio"], "OPS-34354ae5d278")
        self.assertEqual(ev["fechaISO"], "2026-07-08T15:42:11+00:00")
        self.assertEqual(ev["sucursal"], "Guadalajara")
        self.assertEqual(ev["unidad"], {"vehicleId": "10", "economico": "10", "placas": "JLL5377"})
        self.assertEqual(ev["responsable"]["accountId"], "operador.gdl@gpa.com.mx")
        self.assertEqual(ev["status"], "Pendiente")
        self.assertEqual(ev["answers"]["km"], 77777)           # N entero → int
        self.assertEqual(ev["answers"]["litros"], 26.25)
        # discriminador: la solicitud NO lleva formato
        self.assertNotIn("formato", ev["answers"])
        self.assertEqual(ev["firma"], "SOL/" + "9e" * 16 + ".png")
        self.assertIn({"campo": "photo", "key": "SOL/" + "3f" * 16 + ".jpg"}, ev["evidencias"])
        # las claves de Dynamo no viajan en answers
        for k in ("PK", "SK", "GSI1PK", "id", "accountId"):
            self.assertNotIn(k, ev["answers"])

    def test_evento_sol_reporte_de_carga(self):
        item, _ = publisher.filtrar_record(_record("INSERT", _img_sol_reporte()))
        ev = publisher.construir_evento(item, "creacion")
        self.assertEqual(ev["tipo"], "SOL")
        # discriminador del reporte de carga (mismo tipo SOL)
        self.assertEqual(ev["answers"]["formato"], "reporte")
        self.assertEqual(ev["answers"]["litros"], 25.5)
        self.assertEqual(ev["answers"]["precioLitro"], 26.63)
        self.assertEqual(ev["answers"]["monto"], 679.07)
        self.assertIs(ev["answers"]["lleno"], True)
        # evidencias de 5 puntos, cada una con su campo
        campos = {e["campo"] for e in ev["evidencias"]}
        for c in ("fotoAntes", "fotoDespues", "fotoBomba", "fotoTicket", "fotoPersona"):
            self.assertIn(c, campos)

    def test_evento_cl_semanal_con_evidencias_anidadas(self):
        item, _ = publisher.filtrar_record(_record("INSERT", _img_cl()))
        ev = publisher.construir_evento(item, "creacion")
        self.assertEqual(ev["tipo"], "CL")
        self.assertEqual(ev["subtipo"], "semanal")
        self.assertEqual(ev["folio"], "OPS-88d8c62e3378")
        self.assertEqual(ev["unidad"], {"vehicleId": "16", "economico": "16", "placas": "PR3430A"})
        self.assertEqual(ev["status"], "Aprobado")             # CL nace aprobado
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

    def test_metrica_emf_tras_envio_exitoso(self):
        recs = {"Records": [_record("INSERT", _img_sol())]}
        emitidas = []
        with mock.patch.dict(os.environ, {"FLEET_BRIDGE_URL": "https://fc/bridge/ops",
                                          "FLEET_BRIDGE_SECRET": "x", "ENV": "prod"}):
            with mock.patch.object(publisher, "enviar"):
                with mock.patch("builtins.print", lambda s: emitidas.append(s)):
                    publisher.lambda_handler(recs, None)
        self.assertEqual(len(emitidas), 1)
        emf = json.loads(emitidas[0])
        self.assertEqual(emf["EnviosExitosos"], 1)
        self.assertEqual(emf["Env"], "prod")
        cw = emf["_aws"]["CloudWatchMetrics"][0]
        self.assertEqual(cw["Namespace"], "GPA/Bridge")
        self.assertEqual(cw["Metrics"], [{"Name": "EnviosExitosos", "Unit": "Count"}])

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
            "sol-creacion": _record("INSERT", _img_sol()),
            "sol-reporte-creacion": _record("INSERT", _img_sol_reporte()),
            "sol-cambio-estado": _record("MODIFY", _img_sol("Aprobada"), _img_sol()),
            "cl-semanal-creacion": _record("INSERT", _img_cl()),
        }
        for nombre, rec in casos.items():
            item, evento = publisher.filtrar_record(rec)
            ev = publisher.construir_evento(item, evento)
            ev["emitidoEn"] = "2026-07-09T00:00:00+00:00"      # determinista
            ev["bucketOrigen"] = "gpa-ops-evidencias-ENV-CUENTA"
            (GOLDEN_DIR / f"{nombre}.json").write_text(
                json.dumps(ev, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        self.assertEqual(len(list(GOLDEN_DIR.glob("*.json"))), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
