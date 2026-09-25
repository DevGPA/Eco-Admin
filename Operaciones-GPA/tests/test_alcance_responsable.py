# tests/test_alcance_responsable.py
# Un OPERADOR marcado como «Responsable de alertas» lee el historial de su alcance
# (como supervisor) para que sus indicadores de pendientes digan la verdad.
# No gana autorización. Corre sin AWS.
#   python -m unittest tests.test_alcance_responsable -v
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


def cl(rol, email, sucs=None):
    return {"rol": rol, "email": email, "sucursales": sucs or [], "sucursal": "", "modulos": [], "nombre": email}


class Base(unittest.TestCase):
    responsables = [{"email": "gabriel@gpa.com.mx", "tipo": "sucursal"},
                    {"email": "corp@gpa.com.mx", "tipo": "corporativo"}]

    def setUp(self):
        self._o = (handler.responsables_alerta, handler.listar_registros, handler._resolver_urls)
        handler.responsables_alerta = lambda: list(self.responsables)
        self.llamadas = []
        def listar(tipo, rol, sucursales, account_id, desde=None, hasta_excl=None):
            self.llamadas.append({"tipo": tipo, "rol": rol, "sucursales": list(sucursales or []), "cuenta": account_id})
            return [{"id": "x", "sucursal": "Cancun", "_auditoria": {"geo": 1}}]
        handler.listar_registros = listar
        handler._resolver_urls = lambda o: o

    def tearDown(self):
        handler.responsables_alerta, handler.listar_registros, handler._resolver_urls = self._o

    def listar(self, quien):
        r = handler._listar(m.SOL, {"queryStringParameters": None, "headers": {}}, quien)
        self.assertEqual(r["statusCode"], 200)
        return json.loads(r["body"])["items"], self.llamadas[-1]


class TestAlcance(Base):
    def test_operador_sin_marca_solo_lo_suyo(self):
        _, l = self.listar(cl("operador", "otro@gpa.com.mx", ["Cancun"]))
        self.assertEqual(l["rol"], "operador")

    def test_operador_responsable_de_sucursal_lee_como_supervisor_de_sus_sucursales(self):
        _, l = self.listar(cl("operador", "gabriel@gpa.com.mx", ["Cancun"]))
        self.assertEqual(l["rol"], "supervisor")
        self.assertEqual(l["sucursales"], ["Cancun"])

    def test_operador_responsable_corporativo_lee_todo(self):
        _, l = self.listar(cl("operador", "corp@gpa.com.mx", ["Cancun"]))
        self.assertEqual(l["rol"], "supervisor")
        self.assertEqual(l["sucursales"], [], "vacío = todas las sucursales")

    def test_mayusculas_en_el_correo_no_importan(self):
        _, l = self.listar(cl("operador", "Gabriel@GPA.com.mx", ["Cancun"]))
        self.assertEqual(l["rol"], "supervisor")

    def test_supervisor_y_admin_no_cambian(self):
        for rol in ("supervisor", "admin", "analista"):
            _, l = self.listar(cl(rol, "gabriel@gpa.com.mx", ["Cancun"]))
            self.assertEqual(l["rol"], rol, rol)

    def test_operador_responsable_sigue_sin_ver_auditoria(self):
        items, _ = self.listar(cl("operador", "gabriel@gpa.com.mx", ["Cancun"]))
        self.assertTrue(all("_auditoria" not in i for i in items))

    def test_operador_responsable_no_gana_autorizacion(self):
        # La autorización sigue siendo por rol: un operador no cambia estados.
        ev = {"pathParameters": {"id": "x"}, "body": json.dumps({"status": "Aprobada"}), "headers": {}}
        r = handler._estado(m.SOL, ev, cl("operador", "gabriel@gpa.com.mx", ["Cancun"]))
        self.assertEqual(r["statusCode"], 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
