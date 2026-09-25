# tests/test_epp_prerregistro.py
# Flujo en dos manos de EPP: alguien PRE-REGISTRA la entrega (todo menos firma y
# evidencias) y el RESPONSABLE DE ALERTAS de esa sucursal la concluye.
# Corre sin AWS: se sustituyen las lecturas/escrituras de la base.
#   python -m unittest tests.test_epp_prerregistro -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m        # noqa: E402
import handler                # noqa: E402

FOTO = "EPP/abc.jpg"
FIRMA = "EPP/firma.png"


def cl(rol, email, sucs=None):
    return {"rol": rol, "email": email, "sucursales": sucs or [], "sucursal": "", "modulos": [], "nombre": email}


def salida(status=None, **extra):
    d = {"movimiento": m.EPP_SALIDA, "sucursal": "Cancun", "numEmpleado": "1042",
         "empleado": "Edgar Grajales", "renglones": [{"articuloId": "casco", "cantidad": 1}], **extra}
    if status:
        d["status"] = status
    return d


class Base(unittest.TestCase):
    """Base falsa: responsables, registro y parches aplicados."""
    responsables = []
    registros = {}

    def setUp(self):
        self.parches = []
        self._o = (handler.responsables_alerta, handler.get_registro, handler.merge_registro,
                   handler.epp_prerregistros, handler._resolver_urls)
        handler.responsables_alerta = lambda: list(self.responsables)
        handler.get_registro = lambda tipo, rid: self.registros.get(rid)
        handler.merge_registro = lambda tipo, rid, parche: self.parches.append((rid, parche))
        handler.epp_prerregistros = lambda: [r for r in self.registros.values()
                                             if r.get("status") == m.EPP_PRERREGISTRO]
        handler._resolver_urls = lambda o: o

    def tearDown(self):
        (handler.responsables_alerta, handler.get_registro, handler.merge_registro,
         handler.epp_prerregistros, handler._resolver_urls) = self._o

    def evento(self, rid=None, body=None):
        return {"pathParameters": {"id": rid} if rid else {}, "body": json.dumps(body or {}),
                "headers": {}, "queryStringParameters": None}


class TestPreRegistro(Base):
    def test_salida_normal_sigue_exigiendo_firma(self):
        self.assertIn("firma", handler._validar_epp(m.EPP, salida(), cl("operador", "o@gpa.com.mx")))

    def test_prerregistro_no_exige_firma(self):
        self.assertIsNone(handler._validar_epp(m.EPP, salida(m.EPP_PRERREGISTRO), cl("operador", "o@gpa.com.mx")))

    def test_prerregistro_si_exige_empleado_y_articulos(self):
        d = salida(m.EPP_PRERREGISTRO); d["numEmpleado"] = ""
        self.assertIn("número de empleado", handler._validar_epp(m.EPP, d, cl("operador", "o")))
        d = salida(m.EPP_PRERREGISTRO); d["renglones"] = []
        self.assertIn("al menos un artículo", handler._validar_epp(m.EPP, d, cl("operador", "o")))

    def test_prerregistro_descarta_una_firma_colada(self):
        d = salida(m.EPP_PRERREGISTRO, firma=FIRMA)
        handler._validar_epp(m.EPP, d, cl("operador", "o"))
        self.assertNotIn("firma", d, "un pre-registro nace sin firma aunque el cliente la mande")

    def test_prerregistro_no_mueve_existencias(self):
        s = m.saldo_epp([{"movimiento": "entrada", "sucursal": "Cancun", "renglones": [{"articuloId": "casco", "cantidad": 5}]},
                         {**salida(m.EPP_PRERREGISTRO)},
                         {**salida(m.EPP_CONCLUIDA)}])
        self.assertEqual(s["Cancun"]["casco"], {"entradas": 5, "salidas": 1, "saldo": 4},
                         "solo la entrega concluida descuenta")


class TestQuienConcluye(Base):
    responsables = [{"email": "Suc@gpa.com.mx", "tipo": "sucursal"},
                    {"email": "corp@gpa.com.mx", "tipo": "corporativo"}]

    def test_responsable_de_sucursal_solo_las_suyas(self):
        self.assertTrue(handler._es_responsable_epp(cl("supervisor", "suc@gpa.com.mx", ["Cancun"]), "Cancun"))
        self.assertFalse(handler._es_responsable_epp(cl("supervisor", "suc@gpa.com.mx", ["Cancun"]), "Cedis"))

    def test_responsable_de_sucursal_sin_lista_ve_todas(self):
        self.assertTrue(handler._es_responsable_epp(cl("supervisor", "suc@gpa.com.mx", []), "Cedis"))

    def test_corporativo_todas(self):
        self.assertTrue(handler._es_responsable_epp(cl("supervisor", "corp@gpa.com.mx", ["Cancun"]), "Vallarta"))

    def test_el_correo_no_distingue_mayusculas(self):
        self.assertTrue(handler._es_responsable_epp(cl("supervisor", "SUC@GPA.COM.MX", ["Cancun"]), "Cancun"))

    def test_admin_sin_la_marca_no_concluye(self):
        # Decisión del área: «solo los marcados». Un admin se marca a sí mismo si lo necesita.
        self.assertFalse(handler._es_responsable_epp(cl("admin", "admin@gpa.com.mx"), "Cancun"))


class TestConcluir(Base):
    responsables = [{"email": "suc@gpa.com.mx", "tipo": "sucursal"}]

    def setUp(self):
        super().setUp()
        self.registros = {
            "p1": {**salida(m.EPP_PRERREGISTRO), "id": "p1", "accountId": "op@gpa.com.mx"},
            "ok1": {**salida(m.EPP_CONCLUIDA), "id": "ok1", "firma": FIRMA},
            "ent": {"id": "ent", "movimiento": "entrada", "sucursal": "Cancun", "status": m.EPP_PRERREGISTRO},
        }

    def _concluir(self, rid, quien, body=None):
        return handler._epp_concluir(self.evento(rid, body if body is not None else
                                                 {"firma": FIRMA, "evidencias": [FOTO]}), quien)

    def test_responsable_concluye_y_queda_aprobado(self):
        r = self._concluir("p1", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(len(self.parches), 1)
        rid, parche = self.parches[0]
        self.assertEqual(rid, "p1")
        self.assertEqual(parche["status"], m.EPP_CONCLUIDA)
        self.assertEqual(parche["firma"], FIRMA)
        self.assertEqual(parche["evidencias"], [FOTO])
        self.assertEqual(parche["concluidoEmail"], "suc@gpa.com.mx")
        self.assertIn("concluidoEn", parche)

    def test_sin_firma_no_concluye(self):
        r = self._concluir("p1", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]), {"evidencias": [FOTO]})
        self.assertEqual(r["statusCode"], 422)
        self.assertIn("firma", json.loads(r["body"])["error"] if "error" in json.loads(r["body"]) else r["body"])
        self.assertEqual(self.parches, [])

    def test_sin_evidencia_no_concluye(self):
        r = self._concluir("p1", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]), {"firma": FIRMA, "evidencias": []})
        self.assertEqual(r["statusCode"], 422)
        self.assertEqual(self.parches, [])

    def test_quien_no_es_responsable_no_puede(self):
        r = self._concluir("p1", cl("supervisor", "otro@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 403)
        r = self._concluir("p1", cl("admin", "admin@gpa.com.mx"))
        self.assertEqual(r["statusCode"], 403, "admin sin marca tampoco")
        self.assertEqual(self.parches, [])

    def test_responsable_de_otra_sucursal_no_puede(self):
        r = self._concluir("p1", cl("supervisor", "suc@gpa.com.mx", ["Cedis"]))
        self.assertEqual(r["statusCode"], 403)

    def test_una_entrega_ya_concluida_no_se_reconcluye(self):
        r = self._concluir("ok1", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 409)

    def test_una_entrada_no_se_concluye(self):
        r = self._concluir("ent", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 409)

    def test_registro_inexistente(self):
        r = self._concluir("nada", cl("supervisor", "suc@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 404)


class TestPendientes(Base):
    responsables = [{"email": "suc@gpa.com.mx", "tipo": "sucursal"},
                    {"email": "corp@gpa.com.mx", "tipo": "corporativo"}]

    def setUp(self):
        super().setUp()
        self.registros = {
            "a": {**salida(m.EPP_PRERREGISTRO), "id": "a", "sucursal": "Cancun"},
            "b": {**salida(m.EPP_PRERREGISTRO), "id": "b", "sucursal": "Cedis"},
            "c": {**salida(m.EPP_CONCLUIDA), "id": "c", "sucursal": "Cancun"},
        }

    def _items(self, quien):
        r = handler._epp_pendientes(self.evento(), quien)
        self.assertEqual(r["statusCode"], 200)
        return json.loads(r["body"])

    def test_responsable_de_sucursal_ve_solo_las_suyas(self):
        b = self._items(cl("supervisor", "suc@gpa.com.mx", ["Cancun"]))
        self.assertEqual([x["id"] for x in b["items"]], ["a"])
        self.assertTrue(b["responsable"])

    def test_corporativo_ve_todas(self):
        b = self._items(cl("supervisor", "corp@gpa.com.mx"))
        self.assertEqual(sorted(x["id"] for x in b["items"]), ["a", "b"])

    def test_quien_no_es_responsable_ve_lista_vacia_y_lo_sabe(self):
        b = self._items(cl("operador", "op@gpa.com.mx"))
        self.assertEqual(b["items"], [])
        self.assertFalse(b["responsable"])

    def test_solo_prerregistros_no_las_concluidas(self):
        b = self._items(cl("supervisor", "corp@gpa.com.mx"))
        self.assertNotIn("c", [x["id"] for x in b["items"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
