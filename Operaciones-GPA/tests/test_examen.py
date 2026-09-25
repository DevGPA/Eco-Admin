# tests/test_examen.py
# Examen médico periódico: liga pública (token, consentimiento, validación, uno por
# campaña), conclusión del médico y acceso solo con marca «Expediente médico».
# Corre sin AWS.
#   python -m unittest tests.test_examen -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m        # noqa: E402
import handler                # noqa: E402

FIRMA = "data:image/png;base64," + "A" * 400
HOY = date(2026, 9, 25)


def parte_a(**extra):
    d = {"numEmpleado": "1042", "nombre": "Edgar Eduardo Grajales Gamboa", "sucursal": "Cancun",
         "fechaNacimiento": "1990-05-12", "puesto": "Almacenista", "sexo": "M",
         "heredo": {"abueloPaterno": "Negados", "madre": "DM2"},
         "noPatologicos": {"tabaquismo": {"si": False, "obs": ""}},
         "neurologico": {"q1": False, "q2": False},
         "consentimiento": True, "firma": FIRMA}
    d.update(extra)
    return d


class TestValidacionColaborador(unittest.TestCase):
    def test_completo_pasa(self):
        self.assertIsNone(m.validar_examen_colaborador(parte_a(), HOY))

    def test_identificacion_obligatoria(self):
        for k in ("numEmpleado", "nombre", "sucursal", "fechaNacimiento"):
            self.assertIsNotNone(m.validar_examen_colaborador(parte_a(**{k: ""}), HOY), k)

    def test_fecha_de_nacimiento_valida(self):
        self.assertIn("AAAA-MM-DD", m.validar_examen_colaborador(parte_a(fechaNacimiento="12/05/1990"), HOY))
        self.assertIn("no es válida", m.validar_examen_colaborador(parte_a(fechaNacimiento="2020-01-01"), HOY))
        self.assertIn("no es válida", m.validar_examen_colaborador(parte_a(fechaNacimiento="1900-01-01"), HOY))

    def test_sin_consentimiento_no_pasa(self):
        self.assertIn("aviso de privacidad", m.validar_examen_colaborador(parte_a(consentimiento=False), HOY))
        self.assertIn("aviso de privacidad", m.validar_examen_colaborador(parte_a(consentimiento="si"), HOY))

    def test_firma_obligatoria_y_acotada(self):
        self.assertIn("firma", m.validar_examen_colaborador(parte_a(firma=""), HOY))
        self.assertIn("grande", m.validar_examen_colaborador(parte_a(firma="data:image/png;base64," + "A" * 90_000), HOY))

    def test_textos_acotados(self):
        self.assertIn("demasiado largo", m.validar_examen_colaborador(
            parte_a(patologicos={"otras": "x" * 5000}), HOY))

    def test_edad(self):
        self.assertEqual(m.edad_de("1990-05-12", HOY), 36)
        self.assertEqual(m.edad_de("1990-09-26", HOY), 35)     # cumple mañana
        self.assertIsNone(m.edad_de("mala", HOY))


class BaseFalsa(unittest.TestCase):
    campanas = {"examen-2026": {"clave": "examen-2026", "nombre": "Examen 2026", "activa": True, "token": "tok123"},
                "vieja": {"clave": "vieja", "nombre": "2025", "activa": False, "token": "tokv"}}
    marcados = ["medico@gpa.com.mx", "rh@gpa.com.mx"]

    def setUp(self):
        self.examenes = {}
        self.creados = []
        self.parches = []
        self.s3 = []
        self._o = (handler.campana_examen, handler.campanas_examen, handler.expediente_medico,
                   handler.listar_examenes, handler.examen_de, handler.get_registro,
                   handler.merge_registro, handler.crear_registro, handler.guardar_dataurl,
                   handler._resolver_urls, handler.guardar_campana_examen)
        handler.campana_examen = lambda c: self.campanas.get(c)
        handler.campanas_examen = lambda: list(self.campanas.values())
        handler.expediente_medico = lambda: list(self.marcados)
        handler.listar_examenes = lambda: list(self.examenes.values())
        handler.examen_de = lambda camp, num: next((r for r in self.examenes.values()
                                                    if r.get("campana") == camp and r.get("numEmpleado") == num), None)
        handler.get_registro = lambda tipo, rid: self.examenes.get(rid)
        handler.merge_registro = lambda tipo, rid, parche: self.parches.append((rid, parche))
        def crear(tipo, datos, sucursal, cuenta):
            rid = f"x{len(self.creados)+1}"
            self.creados.append({"tipo": tipo, "datos": datos, "sucursal": sucursal, "cuenta": cuenta})
            self.examenes[rid] = {**datos, "id": rid}
            return {"id": rid, "fecha": "2026-09-25T10:00:00-06:00"}
        handler.crear_registro = crear
        handler.guardar_dataurl = lambda tipo, d: (self.s3.append((tipo, len(d))) or f"{tipo}/firma.png")
        handler._resolver_urls = lambda o: o
        handler.guardar_campana_examen = lambda clave, nombre, activa, token: {"clave": clave, "nombre": nombre, "activa": activa, "token": token}

    def tearDown(self):
        (handler.campana_examen, handler.campanas_examen, handler.expediente_medico,
         handler.listar_examenes, handler.examen_de, handler.get_registro,
         handler.merge_registro, handler.crear_registro, handler.guardar_dataurl,
         handler._resolver_urls, handler.guardar_campana_examen) = self._o

    def ev(self, body=None, qs=None, rid=None, ip="1.2.3.4"):
        return {"body": json.dumps(body or {}), "queryStringParameters": qs,
                "pathParameters": {"id": rid} if rid else {}, "headers": {},
                "requestContext": {"http": {"sourceIp": ip, "userAgent": "Mozilla"}}}

    @staticmethod
    def cl(rol, email):
        return {"rol": rol, "email": email, "sucursales": [], "sucursal": "", "modulos": [], "nombre": email}


class TestLigaPublica(BaseFalsa):
    def test_campana_activa_con_token_correcto(self):
        r = handler._examen_publico_campana(self.ev(qs={"c": "examen-2026", "t": "tok123"}))
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(json.loads(r["body"])["nombre"], "Examen 2026")

    def test_campana_inactiva_o_token_malo(self):
        self.assertEqual(handler._examen_publico_campana(self.ev(qs={"c": "vieja", "t": "tokv"}))["statusCode"], 404)
        self.assertEqual(handler._examen_publico_campana(self.ev(qs={"c": "examen-2026", "t": "otro"}))["statusCode"], 404)
        self.assertEqual(handler._examen_publico_campana(self.ev(qs={"c": "no-existe", "t": "x"}))["statusCode"], 404)

    def test_envio_correcto_crea_pendiente_medico(self):
        r = handler._examen_publico_enviar(self.ev({"campana": "examen-2026", "token": "tok123", "datos": parte_a()}))
        self.assertEqual(r["statusCode"], 200, r["body"])
        self.assertTrue(json.loads(r["body"])["folio"].startswith("EXM-"))
        c = self.creados[0]
        self.assertEqual(c["tipo"], m.EXM)
        self.assertEqual(c["cuenta"], "publico")
        self.assertEqual(c["sucursal"], "Cancun")
        d = c["datos"]
        self.assertEqual(d["status"], m.EXM_PENDIENTE)
        self.assertEqual(d["firma"], "EXM/firma.png", "la firma va a S3, no incrustada")
        self.assertEqual(self.s3, [("EXM", len(FIRMA))])
        self.assertTrue(d["consentimiento"]["aceptado"])
        self.assertEqual(d["consentimiento"]["version"], m.EXM_AVISO_VERSION)
        self.assertEqual(d["edad"], m.edad_de("1990-05-12", m.hoy_mx()))
        self.assertEqual(d["_auditoria"]["ip"], "1.2.3.4")
        self.assertEqual(d["campana"], "examen-2026")

    def test_token_incorrecto_no_guarda(self):
        r = handler._examen_publico_enviar(self.ev({"campana": "examen-2026", "token": "malo", "datos": parte_a()}))
        self.assertEqual(r["statusCode"], 403)
        self.assertEqual(self.creados, [])

    def test_campana_inactiva_no_guarda(self):
        r = handler._examen_publico_enviar(self.ev({"campana": "vieja", "token": "tokv", "datos": parte_a()}))
        self.assertEqual(r["statusCode"], 403)

    def test_sin_consentimiento_422(self):
        r = handler._examen_publico_enviar(self.ev({"campana": "examen-2026", "token": "tok123",
                                                    "datos": parte_a(consentimiento=False)}))
        self.assertEqual(r["statusCode"], 422)
        self.assertEqual(self.creados, [])

    def test_uno_por_empleado_y_campana(self):
        handler._examen_publico_enviar(self.ev({"campana": "examen-2026", "token": "tok123", "datos": parte_a()}))
        r = handler._examen_publico_enviar(self.ev({"campana": "examen-2026", "token": "tok123", "datos": parte_a()}))
        self.assertEqual(r["statusCode"], 409)
        self.assertEqual(len(self.creados), 1)
        # Otra campaña sí admite otro examen del mismo empleado
        self.campanas["examen-2027"] = {"clave": "examen-2027", "nombre": "2027", "activa": True, "token": "t27"}
        r2 = handler._examen_publico_enviar(self.ev({"campana": "examen-2027", "token": "t27", "datos": parte_a()}))
        self.assertEqual(r2["statusCode"], 200)


class TestParteMedica(BaseFalsa):
    def setUp(self):
        super().setUp()
        self.examenes["e1"] = {**parte_a(), "id": "e1", "status": m.EXM_PENDIENTE, "campana": "examen-2026"}
        self.examenes["e2"] = {**parte_a(), "id": "e2", "status": m.EXM_CONCLUIDO, "campana": "examen-2026"}

    def _concluir(self, quien, rid="e1", body=None):
        body = body if body is not None else {
            "medico": {"signos": {"peso": 80, "estatura": 1.75}, "diagnostico": "Sano", "clasificacion": "Apto"},
            "firmaMedico": "EXM/fm.png", "nombreMedico": "Dr. Abraham Alvarado Figueroa"}
        return handler._examen_concluir(self.ev(body, rid=rid), quien)

    def test_medico_concluye(self):
        r = self._concluir(self.cl("supervisor", "medico@gpa.com.mx"))
        self.assertEqual(r["statusCode"], 200)
        rid, p = self.parches[0]
        self.assertEqual(rid, "e1")
        self.assertEqual(p["status"], m.EXM_CONCLUIDO)
        self.assertEqual(p["nombreMedico"], "Dr. Abraham Alvarado Figueroa")
        self.assertEqual(p["concluidoEmail"], "medico@gpa.com.mx")

    def test_sin_diagnostico_o_clasificacion_o_firma(self):
        base = {"medico": {"diagnostico": "", "clasificacion": "Apto"}, "firmaMedico": "EXM/f.png"}
        self.assertEqual(self._concluir(self.cl("supervisor", "medico@gpa.com.mx"), body=base)["statusCode"], 422)
        base = {"medico": {"diagnostico": "Sano", "clasificacion": ""}, "firmaMedico": "EXM/f.png"}
        self.assertEqual(self._concluir(self.cl("supervisor", "medico@gpa.com.mx"), body=base)["statusCode"], 422)
        base = {"medico": {"diagnostico": "Sano", "clasificacion": "Apto"}, "firmaMedico": ""}
        self.assertEqual(self._concluir(self.cl("supervisor", "medico@gpa.com.mx"), body=base)["statusCode"], 422)
        self.assertEqual(self.parches, [])

    def test_sin_marca_no_concluye_ni_siendo_admin(self):
        self.assertEqual(self._concluir(self.cl("admin", "admin@gpa.com.mx"))["statusCode"], 403)
        self.assertEqual(self._concluir(self.cl("supervisor", "otro@gpa.com.mx"))["statusCode"], 403)

    def test_ya_concluido_409(self):
        self.assertEqual(self._concluir(self.cl("supervisor", "medico@gpa.com.mx"), rid="e2")["statusCode"], 409)

    def test_inexistente_404(self):
        self.assertEqual(self._concluir(self.cl("supervisor", "medico@gpa.com.mx"), rid="nada")["statusCode"], 404)


class TestAcceso(BaseFalsa):
    def setUp(self):
        super().setUp()
        self.examenes["e1"] = {**parte_a(), "id": "e1", "status": m.EXM_PENDIENTE, "campana": "examen-2026"}
        self.examenes["e2"] = {**parte_a(numEmpleado="7"), "id": "e2", "status": m.EXM_CONCLUIDO, "campana": "vieja"}

    def test_listar_solo_con_marca(self):
        self.assertEqual(handler._examen_listar(self.ev(), self.cl("admin", "admin@gpa.com.mx"))["statusCode"], 403)
        r = handler._examen_listar(self.ev(), self.cl("operador", "RH@gpa.com.mx"))
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(len(json.loads(r["body"])["items"]), 2)

    def test_listar_por_campana(self):
        r = handler._examen_listar(self.ev(qs={"campana": "examen-2026"}), self.cl("operador", "rh@gpa.com.mx"))
        self.assertEqual([x["id"] for x in json.loads(r["body"])["items"]], ["e1"])

    def test_campanas_las_ve_marca_o_admin(self):
        self.assertEqual(handler._examen_campanas(self.ev(), self.cl("admin", "admin@gpa.com.mx"))["statusCode"], 200)
        self.assertEqual(handler._examen_campanas(self.ev(), self.cl("operador", "rh@gpa.com.mx"))["statusCode"], 200)
        self.assertEqual(handler._examen_campanas(self.ev(), self.cl("supervisor", "x@gpa.com.mx"))["statusCode"], 403)

    def test_crear_campana_genera_token_y_lo_conserva(self):
        r = handler._admin_examen_campana(self.ev({"clave": "Examen 2027!", "nombre": "Examen 2027"}), self.cl("admin", "a@gpa.com.mx"))
        self.assertEqual(r["statusCode"], 200)
        c = json.loads(r["body"])["campana"]
        self.assertEqual(c["clave"], "examen-2027")
        self.assertTrue(len(c["token"]) >= 16)
        # Al desactivar una existente NO se cambia su token (la liga sigue siendo la misma)
        r2 = handler._admin_examen_campana(self.ev({"clave": "examen-2026", "nombre": "Examen 2026", "activa": False}), self.cl("admin", "a@gpa.com.mx"))
        self.assertEqual(json.loads(r2["body"])["campana"]["token"], "tok123")
        self.assertFalse(json.loads(r2["body"])["campana"]["activa"])

    def test_marca_expediente_solo_admin(self):
        llamadas = []
        orig = handler.guardar_expediente_medico
        handler.guardar_expediente_medico = lambda e, a: llamadas.append((e, a))
        try:
            self.assertEqual(handler._admin_expediente_medico(self.ev({"email": "rh@gpa.com.mx", "activo": True}),
                                                              self.cl("supervisor", "s@gpa.com.mx"))["statusCode"], 403)
            self.assertEqual(handler._admin_expediente_medico(self.ev({"email": "rh@gpa.com.mx", "activo": True}),
                                                              self.cl("admin", "a@gpa.com.mx"))["statusCode"], 200)
            self.assertEqual(llamadas, [("rh@gpa.com.mx", True)])
        finally:
            handler.guardar_expediente_medico = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
