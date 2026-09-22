# tests/test_foto_km.py
# Candado de la foto del kilometraje en Combustible (handler._validar_foto_km).
# Corre sin AWS: solo evalúa la regla.
#   python -m unittest tests.test_foto_km -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m                                   # noqa: E402
from handler import _validar_foto_km, _foto_ok           # noqa: E402

LLAVE = "evidencias/2026/09/abc123.jpg"     # lo que manda el cliente tras subirla


class TestReporteDeCarga(unittest.TestCase):
    """El reporte de carga exige la foto de km y medidor ANTES de cargar."""

    def _rep(self, **extra):
        return {"formato": "reporte", "vehicleId": "16", "km": 97710, **extra}

    def test_sin_foto_antes_se_rechaza(self):
        msg = _validar_foto_km(m.SOL, self._rep())
        self.assertIsNotNone(msg)
        self.assertIn("foto del kilometraje", msg)

    def test_foto_antes_vacia_se_rechaza(self):
        for v in ("", "   ", None, 0, [], {}):
            self.assertIsNotNone(_validar_foto_km(m.SOL, self._rep(fotoAntes=v)), repr(v))

    def test_con_foto_antes_pasa(self):
        self.assertIsNone(_validar_foto_km(m.SOL, self._rep(fotoAntes=LLAVE)))

    def test_no_basta_con_las_otras_fotos(self):
        # Ticket, bomba y persona no sustituyen la del odómetro.
        d = self._rep(fotoTicket=LLAVE, fotoBomba=LLAVE, fotoPersona=LLAVE, fotoDespues=LLAVE)
        self.assertIsNotNone(_validar_foto_km(m.SOL, d))


class TestSolicitud(unittest.TestCase):
    """La solicitud exige la foto principal, que es la del odómetro."""

    def test_sin_fotos_se_rechaza(self):
        msg = _validar_foto_km(m.SOL, {"vehicleId": "16", "km": 91127})
        self.assertIsNotNone(msg)
        self.assertIn("foto del kilometraje", msg)

    def test_lista_de_fotos_vacia_se_rechaza(self):
        self.assertIsNotNone(_validar_foto_km(m.SOL, {"fotos": [], "photo": None}))

    def test_con_foto_principal_pasa(self):
        self.assertIsNone(_validar_foto_km(m.SOL, {"photo": LLAVE, "fotos": [LLAVE]}))

    def test_cliente_viejo_que_solo_manda_fotos_pasa(self):
        # Compatibilidad: una app en caché manda 'fotos' sin 'photo'.
        self.assertIsNone(_validar_foto_km(m.SOL, {"fotos": [LLAVE, LLAVE]}))

    def test_photo_vacio_pero_fotos_con_una_pasa(self):
        self.assertIsNone(_validar_foto_km(m.SOL, {"photo": "", "fotos": [LLAVE]}))


class TestNoAfectaOtrosModulos(unittest.TestCase):
    """El candado es solo de Combustible: no debe tocar checklist ni montacargas."""

    def test_checklist_no_se_valida_aqui(self):
        self.assertIsNone(_validar_foto_km(m.CL, {"km": 1000}))

    def test_montacargas_no_se_valida_aqui(self):
        self.assertIsNone(_validar_foto_km(m.MC, {"horas": 1250}))


class TestFotoOk(unittest.TestCase):
    def test_solo_cadenas_con_contenido(self):
        self.assertTrue(_foto_ok(LLAVE))
        self.assertTrue(_foto_ok("data:image/jpeg;base64,AAAA"))
        for v in ("", "  ", None, 0, False, [], {}, 123):
            self.assertFalse(_foto_ok(v), repr(v))


if __name__ == "__main__":
    unittest.main(verbosity=2)
