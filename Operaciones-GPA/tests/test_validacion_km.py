# tests/test_validacion_km.py
# Regla de kilometraje (db.modelos.evaluar_km) — sin AWS.
#   python -m unittest tests.test_validacion_km -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.modelos import evaluar_km  # noqa: E402


class TestEvaluarKm(unittest.TestCase):
    def test_primer_registro_sin_historial_permite(self):
        self.assertIsNone(evaluar_km(50000, None))

    def test_igual_o_dentro_de_rango_permite(self):
        self.assertIsNone(evaluar_km(50000, 50000))
        self.assertIsNone(evaluar_km(50999, 50000))
        self.assertIsNone(evaluar_km(51000, 50000))      # exactamente el tope

    def test_menor_al_ultimo_bloquea(self):
        msg = evaluar_km(49999, 50000)
        self.assertIsNotNone(msg)
        self.assertIn("menor", msg)

    def test_excede_tope_normal_1000_bloquea(self):
        msg = evaluar_km(51001, 50000)
        self.assertIsNotNone(msg)
        self.assertIn("excede", msg)

    def test_tope_especial_100_gas_lp_y_electrico(self):
        self.assertIsNone(evaluar_km(50100, 50000, "Gas LP"))
        self.assertIsNotNone(evaluar_km(50101, 50000, "Gas LP"))
        self.assertIsNone(evaluar_km(50100, 50000, "Electrico"))
        self.assertIsNotNone(evaluar_km(50101, 50000, "Electrico"))

    def test_acepta_strings_del_front(self):
        self.assertIsNone(evaluar_km("50500", "50000"))
        self.assertEqual(evaluar_km("abc", "50000"), "Kilometraje inválido")

    def test_km_nuevo_none_no_bloquea(self):
        # Si no viene km, otros validadores lo exigen; aquí no inventamos error.
        self.assertIsNone(evaluar_km(None, 50000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
