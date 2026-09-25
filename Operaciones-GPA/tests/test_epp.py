# tests/test_epp.py
# Saldo de EPP y candados del movimiento. Corre sin AWS.
#   python -m unittest tests.test_epp -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m                       # noqa: E402
from handler import _validar_epp             # noqa: E402

FOTO = "evidencias/2026/09/factura.jpg"


def ent(suc, renglones, **extra):
    return {"movimiento": m.EPP_ENTRADA, "sucursal": suc, "renglones": renglones, **extra}


def sal(suc, renglones, **extra):
    return {"movimiento": m.EPP_SALIDA, "sucursal": suc, "renglones": renglones, **extra}


def r(aid, cant, talla=None):
    d = {"articuloId": aid, "cantidad": cant}
    if talla:
        d["talla"] = talla
    return d


class TestSaldo(unittest.TestCase):
    def test_sin_movimientos(self):
        self.assertEqual(m.saldo_epp([]), {})
        self.assertEqual(m.saldo_epp(None), {})

    def test_entrada_menos_salida(self):
        s = m.saldo_epp([ent("Cedis", [r("casco", 10)]), sal("Cedis", [r("casco", 3)])])
        self.assertEqual(s["Cedis"]["casco"], {"entradas": 10, "salidas": 3, "saldo": 7})

    def test_cada_sucursal_lleva_su_existencia(self):
        s = m.saldo_epp([ent("Cedis", [r("casco", 10)]), ent("Cancun", [r("casco", 4)]),
                         sal("Cedis", [r("casco", 2)])])
        self.assertEqual(s["Cedis"]["casco"]["saldo"], 8)
        self.assertEqual(s["Cancun"]["casco"]["saldo"], 4)

    def test_la_talla_no_parte_el_saldo(self):
        # Decisión del área: el inventario es por artículo. La talla queda en el
        # vale, pero 29 y 26 suman al mismo saldo.
        s = m.saldo_epp([ent("Cedis", [r("calzado_casquillo", 5)]),
                         sal("Cedis", [r("calzado_casquillo", 1, "29")]),
                         sal("Cedis", [r("calzado_casquillo", 1, "26")])])
        self.assertEqual(s["Cedis"]["calzado_casquillo"]["saldo"], 3)

    def test_salida_sin_existencia_deja_saldo_negativo(self):
        # No se bloquea la entrega; el negativo señala la factura que falta.
        s = m.saldo_epp([sal("Cedis", [r("faja", 2)])])
        self.assertEqual(s["Cedis"]["faja"]["saldo"], -2)

    def test_varios_renglones_en_un_movimiento(self):
        s = m.saldo_epp([ent("Cedis", [r("casco", 5), r("lentes", 20), r("guantes", 12)])])
        self.assertEqual(s["Cedis"]["lentes"]["saldo"], 20)
        self.assertEqual(len(s["Cedis"]), 3)

    def test_anulado_o_rechazado_no_cuenta(self):
        s = m.saldo_epp([ent("Cedis", [r("casco", 10)]),
                         ent("Cedis", [r("casco", 99)], status="Anulado"),
                         sal("Cedis", [r("casco", 5)], status="Rechazado")])
        self.assertEqual(s["Cedis"]["casco"], {"entradas": 10, "salidas": 0, "saldo": 10})

    def test_basura_no_tumba_el_calculo(self):
        s = m.saldo_epp([
            {"movimiento": "otra_cosa", "sucursal": "Cedis", "renglones": [r("casco", 5)]},
            ent("Cedis", [{"articuloId": "", "cantidad": 3}]),      # sin artículo
            ent("Cedis", [{"articuloId": "casco", "cantidad": "x"}]),  # cantidad inválida
            ent("Cedis", [r("casco", 0)]),                           # cantidad 0
            ent("Cedis", [r("casco", 4)]),
        ])
        self.assertEqual(s["Cedis"]["casco"]["saldo"], 4)

    def test_enteros_sin_decimal(self):
        s = m.saldo_epp([ent("Cedis", [r("casco", 3.0)])])
        self.assertIsInstance(s["Cedis"]["casco"]["saldo"], int)


class TestCandadosEntrada(unittest.TestCase):
    ADMIN = {"rol": "admin", "email": "a@gpa.com.mx"}
    OPER = {"rol": "operador", "email": "o@gpa.com.mx"}

    def test_pide_factura_y_su_foto(self):
        base = ent("Cedis", [r("casco", 5)])
        self.assertIn("factura", _validar_epp(m.EPP, base, self.ADMIN))
        self.assertIn("foto de la factura",
                      _validar_epp(m.EPP, {**base, "factura": "A-123"}, self.ADMIN))
        self.assertIsNone(_validar_epp(
            m.EPP, {**base, "factura": "A-123", "fotoFactura": FOTO}, self.ADMIN))

    def test_solo_responsable_registra_entradas(self):
        d = ent("Cedis", [r("casco", 5)], factura="A-1", fotoFactura=FOTO)
        self.assertIn("supervisor", _validar_epp(m.EPP, d, self.OPER))
        self.assertIsNone(_validar_epp(m.EPP, d, {"rol": "supervisor"}))


class TestCandadosSalida(unittest.TestCase):
    OPER = {"rol": "operador", "email": "o@gpa.com.mx"}

    def _sal(self, **extra):
        return sal("Cedis", [r("casco", 1)], **extra)

    def test_pide_numero_nombre_y_firma(self):
        self.assertIn("número de empleado", _validar_epp(m.EPP, self._sal(), self.OPER))
        self.assertIn("nombre del empleado",
                      _validar_epp(m.EPP, self._sal(numEmpleado="1042"), self.OPER))
        self.assertIn("firma", _validar_epp(
            m.EPP, self._sal(numEmpleado="1042", empleado="Edgar Grajales"), self.OPER))
        self.assertIsNone(_validar_epp(m.EPP, self._sal(
            numEmpleado="1042", empleado="Edgar Grajales", firma=FOTO), self.OPER))

    def test_no_pide_existencia(self):
        # Se entrega aunque no haya saldo: el candado no la bloquea.
        self.assertIsNone(_validar_epp(m.EPP, self._sal(
            numEmpleado="1", empleado="X", firma=FOTO), self.OPER))

    def test_cualquiera_con_acceso_puede_entregar(self):
        d = self._sal(numEmpleado="1", empleado="X", firma=FOTO)
        for rol in ("operador", "supervisor", "admin"):
            self.assertIsNone(_validar_epp(m.EPP, d, {"rol": rol}), rol)


class TestCandadosComunes(unittest.TestCase):
    ADMIN = {"rol": "admin"}

    def test_movimiento_valido(self):
        self.assertIn("entrada o salida", _validar_epp(
            m.EPP, {"sucursal": "Cedis", "renglones": [r("casco", 1)]}, self.ADMIN))

    def test_pide_sucursal(self):
        self.assertIn("sucursal", _validar_epp(
            m.EPP, {"movimiento": m.EPP_SALIDA, "renglones": [r("casco", 1)]}, self.ADMIN))

    def test_pide_al_menos_un_articulo(self):
        self.assertIn("al menos un artículo", _validar_epp(m.EPP, sal("Cedis", []), self.ADMIN))

    def test_renglon_sin_articulo_o_con_cantidad_mala(self):
        self.assertIn("no tiene artículo", _validar_epp(
            m.EPP, sal("Cedis", [{"cantidad": 1}]), self.ADMIN))
        self.assertIn("mayor a 0", _validar_epp(
            m.EPP, sal("Cedis", [r("casco", 0)]), self.ADMIN))
        self.assertIn("no es un número", _validar_epp(
            m.EPP, sal("Cedis", [{"articuloId": "casco", "cantidad": "dos"}]), self.ADMIN))

    def test_no_toca_otros_modulos(self):
        for tipo in (m.SOL, m.CL, m.MC):
            self.assertIsNone(_validar_epp(tipo, {"km": 1}, self.ADMIN))


if __name__ == "__main__":
    unittest.main(verbosity=2)
