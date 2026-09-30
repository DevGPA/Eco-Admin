# tests/test_evidencias_tipos.py
# Las DOS puertas de las evidencias deben conocer TODOS los tipos que manda el
# cliente: la whitelist de `POST /evidencias/url-subida` (si rechaza el tipo, el
# módulo entero se queda sin fotos) y el patrón `_KEY_RE` que convierte la llave
# guardada en URL firmada al leer (si no la reconoce, la app pinta la llave cruda).
#
# El error real que motiva esta prueba: EPP y examen médico subían con tipo
# "EPP"/"EXM" y el servidor contestaba «tipo inválido»; el stub de S3 de las
# pruebas de pantalla (identidad) no podía verlo. Aquí se cruza la lista del
# servidor contra TIPO_EVID de frontend/gpa-api.js, leído del archivo real.
#   python -m unittest tests.test_evidencias_tipos -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import handler                        # noqa: E402
from s3 import evidencias as ev       # noqa: E402

HEX32 = "a" * 32


def tipos_del_cliente() -> dict:
    """TIPO_EVID tal como está escrito en frontend/gpa-api.js."""
    src = (RAIZ / "frontend" / "gpa-api.js").read_text(encoding="utf-8")
    mm = re.search(r"const TIPO_EVID\s*=\s*\{([^}]*)\}", src)
    assert mm, "No se encontró TIPO_EVID en gpa-api.js"
    pares = re.findall(r"(\w+)\s*:\s*\"([A-Z]+)\"", mm.group(1))
    return dict(pares)


def evento(tipo, content_type="image/jpeg"):
    return {"routeKey": "POST /evidencias/url-subida",
            "body": json.dumps({"tipo": tipo, "contentType": content_type}),
            "requestContext": {"authorizer": {"jwt": {"claims": {
                "email": "op@gpa.com.mx", "custom:rol": "operador"}}}}}


class TestPuertasDeEvidencias(unittest.TestCase):
    def setUp(self):
        # Sin S3 real: la firma se simula y se registra qué se pidió.
        self._subida, self._lectura = handler.url_subida, handler.url_lectura
        self.pedidas = []
        handler.url_subida = lambda tipo, ct: (self.pedidas.append((tipo, ct)) or
                                               {"key": f"{tipo}/{HEX32}.{ev._EXT.get(ct, 'jpg')}",
                                                "uploadUrl": "https://s3/put"})
        handler.url_lectura = lambda key: "https://s3/get/" + key

    def tearDown(self):
        handler.url_subida, handler.url_lectura = self._subida, self._lectura

    def test_el_cliente_no_manda_ningun_tipo_que_el_servidor_rechace(self):
        cliente = tipos_del_cliente()
        self.assertTrue(cliente, "TIPO_EVID vacío")
        for nombre, tipo in cliente.items():
            with self.subTest(modulo=nombre, tipo=tipo):
                r = handler.lambda_handler(evento(tipo), None)
                self.assertEqual(r["statusCode"], 200,
                                 f"url-subida rechaza el tipo {tipo!r} que manda el módulo {nombre}: {r['body']}")
                self.assertEqual(json.loads(r["body"])["key"], f"{tipo}/{HEX32}.jpg")

    def test_un_tipo_desconocido_sigue_rechazado(self):
        r = handler.lambda_handler(evento("OTRO"), None)
        self.assertEqual(r["statusCode"], 400)
        self.assertIn("tipo inválido", r["body"])

    def test_toda_llave_que_puede_generar_el_servidor_se_firma_al_leer(self):
        # Todo prefijo aceptado × toda extensión que sabe generar s3/evidencias.
        for tipo in handler._TIPOS_EVID:
            for ext in set(ev._EXT.values()):
                with self.subTest(tipo=tipo, ext=ext):
                    key = f"{tipo}/{HEX32}.{ext}"
                    self.assertEqual(handler._resolver_urls(key), "https://s3/get/" + key)

    def test_el_pdf_de_una_factura_de_epp_se_firma(self):
        key = f"EPP/{HEX32}.pdf"
        self.assertEqual(handler._resolver_urls({"fotoFactura": key})["fotoFactura"], "https://s3/get/" + key)

    def test_la_firma_del_examen_medico_se_firma(self):
        key = f"EXM/{HEX32}.png"
        self.assertEqual(handler._resolver_urls([key]), ["https://s3/get/" + key])

    def test_un_texto_que_no_es_llave_no_se_toca(self):
        for v in ("hola", "SOL/corta.jpg", "https://ya.firmada/x", "", None):
            with self.subTest(v=v):
                self.assertEqual(handler._resolver_urls(v), v)

    def test_la_whitelist_y_el_patron_son_la_misma_lista(self):
        for tipo in handler._TIPOS_EVID:
            self.assertTrue(handler._KEY_RE.match(f"{tipo}/{HEX32}.jpg"), tipo)
        self.assertFalse(handler._KEY_RE.match(f"OTRO/{HEX32}.jpg"))


if __name__ == "__main__":
    unittest.main()
