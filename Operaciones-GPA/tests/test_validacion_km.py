# tests/test_validacion_km.py
# Regla de kilometraje (db.modelos.evaluar_km) — sin AWS.
#   python -m unittest tests.test_validacion_km -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.modelos import evaluar_km, evaluar_horas  # noqa: E402


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

    def test_tope_unico_1000_para_todos_los_combustibles(self):
        # Ya no hay topes especiales: Gas LP y Eléctrico se controlan igual que
        # gasolina y diésel. Antes eran 100 y 300 km y trababan capturas buenas.
        for c in (None, "", "Gasolina", "Diesel", "Gas LP", "GAS LP", "gas lp",
                  "Electrico", "Eléctrico", "ELECTRICO", "cualquier cosa"):
            self.assertIsNone(evaluar_km(50999, 50000, c), c)
            self.assertIsNone(evaluar_km(51000, 50000, c), c)   # exactamente el tope
            self.assertIsNotNone(evaluar_km(51001, 50000, c), c)

    def test_sin_combustible_se_comporta_igual(self):
        # El parámetro quedó por compatibilidad; omitirlo no cambia nada.
        self.assertEqual(evaluar_km(51001, 50000), evaluar_km(51001, 50000, "Gas LP"))

    def test_mensaje_del_tope_dice_la_cifra_correcta(self):
        self.assertIn("1,000", evaluar_km(52000, 50000, "Gasolina"))
        self.assertIn("1,000", evaluar_km(52000, 50000, "Electrico"))
        self.assertIn("1,000", evaluar_km(52000, 50000, "Gas LP"))

    def test_acepta_strings_del_front(self):
        self.assertIsNone(evaluar_km("50500", "50000"))
        self.assertEqual(evaluar_km("abc", "50000"), "Kilometraje inválido")

    def test_km_nuevo_none_no_bloquea(self):
        # Si no viene km, otros validadores lo exigen; aquí no inventamos error.
        self.assertIsNone(evaluar_km(None, 50000))


class TestEvaluarHoras(unittest.TestCase):
    def test_primera_lectura_permite(self):
        self.assertIsNone(evaluar_horas(1250, None))

    def test_dentro_de_rango_permite(self):
        self.assertIsNone(evaluar_horas(1250, 1250))
        self.assertIsNone(evaluar_horas(1300, 1250))
        self.assertIsNone(evaluar_horas(1350, 1250))      # exactamente +100

    def test_menor_bloquea(self):
        msg = evaluar_horas(1249, 1250)
        self.assertIsNotNone(msg)
        self.assertIn("menor", msg)

    def test_excede_100_bloquea(self):
        msg = evaluar_horas(1351, 1250)
        self.assertIsNotNone(msg)
        self.assertIn("exceden", msg)

    def test_acepta_strings_e_invalidos(self):
        self.assertIsNone(evaluar_horas("1300", "1250"))
        self.assertEqual(evaluar_horas("abc", "1250"), "Horas inválidas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
