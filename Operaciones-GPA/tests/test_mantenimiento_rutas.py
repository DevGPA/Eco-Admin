# tests/test_mantenimiento_rutas.py
# Rutas /mantenimiento/* de punta a punta por lambda_handler, con una DynamoDB simulada
# (get/put/update/delete/query sobre PK y los 3 índices). Sin AWS.
#   python -m unittest tests.test_mantenimiento_rutas -v
# Fija «hoy» = 25-sep-2026 (semana 39) para que los casos sean reproducibles.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import copy
import json
import os
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m                          # noqa: E402
import handler                                  # noqa: E402
from mantenimiento import datos as D            # noqa: E402
from mantenimiento import logica as L           # noqa: E402
from mantenimiento import rutas as R            # noqa: E402

HOY = date(2026, 9, 25)          # viernes de la semana 39
JEFE = "mantenimiento@gpa.com.mx"
TEC1 = "tec1@gpa.com.mx"         # Cedis
TEC2 = "tec2@gpa.com.mx"         # Cedis, titular de AIR-GDL-02
ANA = "analista@gpa.com.mx"
ADMINAPP = "administracion@gpa.com.mx"

IDX_PK = {"tipo-fecha-idx": ("GSI1PK", "GSI1SK"), "sucursal-fecha-idx": ("GSI2PK", "GSI2SK"),
          "cuenta-fecha-idx": ("GSI3PK", "GSI3SK")}


def _eval(cond, item) -> bool:
    e = cond.get_expression()
    op, vals = e["operator"], e["values"]
    if op == "AND":
        return _eval(vals[0], item) and _eval(vals[1], item)
    v = item.get(vals[0].name)
    if v is None:
        return False
    if op == "=":
        return v == vals[1]
    if op == "BETWEEN":
        return vals[1] <= v <= vals[2]
    if op == ">=":
        return v >= vals[1]
    if op == "<":
        return v < vals[1]
    if op == "begins_with":
        return str(v).startswith(vals[1])
    raise AssertionError(op)


class Tabla:
    """DynamoDB de mentira, suficiente para el módulo: tabla + 3 índices."""

    def __init__(self):
        self.items = {}
        self.escrituras = 0

    def put_item(self, Item):
        self.escrituras += 1
        self.items[(Item["PK"], Item["SK"])] = copy.deepcopy(Item)

    def get_item(self, Key, **_):
        it = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": copy.deepcopy(it)} if it else {}

    def delete_item(self, Key):
        self.escrituras += 1
        self.items.pop((Key["PK"], Key["SK"]), None)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        self.escrituras += 1
        it = self.items.setdefault((Key["PK"], Key["SK"]), {"PK": Key["PK"], "SK": Key["SK"]})
        for par in UpdateExpression.replace("SET ", "", 1).split(", "):
            k, v = [x.strip() for x in par.split("=")]
            it[ExpressionAttributeNames[k]] = copy.deepcopy(ExpressionAttributeValues[v])

    def query(self, KeyConditionExpression, IndexName=None, ScanIndexForward=True, ExclusiveStartKey=None, **_):
        sel = [copy.deepcopy(i) for i in self.items.values() if _eval(KeyConditionExpression, i)]
        sk = IDX_PK[IndexName][1] if IndexName else "SK"
        sel.sort(key=lambda i: str(i.get(sk, "")), reverse=not ScanIndexForward)
        return {"Items": sel}


def ev(route, email, rol, sucursales=(), modulos=("mantenimiento",), body=None, rid=None, qs=None):
    return {"routeKey": route, "body": json.dumps(body or {}),
            "pathParameters": {"rid": rid} if rid else {},
            "queryStringParameters": qs or {},
            "requestContext": {"authorizer": {"jwt": {"claims": {
                "email": email, "custom:rol": rol, "custom:nombre": email.split("@")[0],
                "custom:sucursales": ",".join(sucursales), "custom:modulos": ",".join(modulos)}}}}}


def cuerpo(r):
    return json.loads(r["body"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tabla = Tabla()
        self._orig = (D._t, handler.url_lectura, handler.url_subida, R.hoy_mx)
        D._t = lambda: self.tabla
        handler.url_lectura = lambda k: "https://s3/" + k
        handler.url_subida = lambda t, c: {"key": f"{t}/{'a' * 32}.jpg", "uploadUrl": "https://s3/put"}
        R.hoy_mx = lambda: HOY
        import db.escritura as E
        self._orig_E = E._t
        E._t = lambda: self.tabla
        # cuentas «de Cognito» para /asignables
        import auth_cognito as A
        self._orig_A = A.listar_cuentas
        A.listar_cuentas = lambda: [
            {"email": TEC1, "nombre": "Técnico Uno", "rol": "operador", "sucursales": ["Cedis"], "modulos": ["mantenimiento"], "activo": True},
            {"email": TEC2, "nombre": "Técnico Dos", "rol": "operador", "sucursales": ["Cedis"], "modulos": [], "activo": True},
            {"email": "chofer@gpa.com.mx", "nombre": "Chofer", "rol": "operador", "sucursales": ["Cedis"], "modulos": ["combustible"], "activo": True},
            {"email": ANA, "nombre": "Analista", "rol": "analista", "sucursales": [], "modulos": [], "activo": True},
            {"email": "baja@gpa.com.mx", "nombre": "Baja", "rol": "operador", "sucursales": ["Cedis"], "modulos": [], "activo": False},
        ]
        self.sembrar()

    def tearDown(self):
        D._t, handler.url_lectura, handler.url_subida, R.hoy_mx = self._orig
        import db.escritura as E
        E._t = self._orig_E
        import auth_cognito as A
        A.listar_cuentas = self._orig_A

    def sembrar(self):
        self.tabla.put_item({"PK": m.PK_MODULO, "SK": m.sk_modulo("mantenimiento"), "clave": "mantenimiento",
                             "nombre": "Plan Mtto", "activo": True, "administradores": [JEFE],
                             "sucursales": L.SUCURSAL_APP})
        for s in ("Cedis", "Cancun", "Ciudad de Mexico"):
            self.tabla.put_item({"PK": m.PK_SUCURSAL, "SK": m.sk_sucursal(s), "nombre": s})
        for pref, nombre in (("AIR", "Mini split"), ("TRA", "Traspaletas"), ("MON", "Montacargas")):
            D.guardar_tipo({"pref": pref, "nombre": nombre, "procedimiento": "x", "puntos": ["a"],
                            "materiales": [], "herramienta": [], "esPropuesta": False})
        self.acts = {
            "AIR-GDL-01": {"codigo": "AIR-GDL-01", "tipo": "AIR", "descripcion": "GERENCIA VENTAS", "sucursal": "Cedis",
                           "sucCodigo": "GDL", "area": "Mini splits", "periodicidad": "6 MESES", "semPeriodo": 26,
                           "responsabilidad": "INTERNO", "titular": None, "activo": True, "origen": "excel"},
            "AIR-GDL-02": {"codigo": "AIR-GDL-02", "tipo": "AIR", "descripcion": "OFICINA", "sucursal": "Cedis",
                           "sucCodigo": "GDL", "area": "Mini splits", "periodicidad": "6 MESES", "semPeriodo": 26,
                           "responsabilidad": "INTERNO", "titular": TEC2, "activo": True, "origen": "excel"},
            "TRA-CAN-01": {"codigo": "TRA-CAN-01", "tipo": "TRA", "descripcion": "TRASPALETA", "sucursal": "Cancun",
                           "sucCodigo": "CAN", "area": "Equipo de carga ligero", "periodicidad": "4 MESES",
                           "semPeriodo": 17, "responsabilidad": "INTERNO", "titular": None, "activo": True, "origen": "excel"},
            "MON-MEX-01": {"codigo": "MON-MEX-01", "tipo": "MON", "descripcion": "HYSTER", "sucursal": "Ciudad de Mexico",
                           "sucCodigo": "MEX", "area": "Equipo de carga pesado", "periodicidad": "VARIABLE",
                           "semPeriodo": 0, "responsabilidad": "EXTERNO", "titular": None, "activo": True, "origen": "excel"},
        }
        for a in self.acts.values():
            D.guardar_activo(a)
        sem = {"AIR-GDL-01": [8, 46], "AIR-GDL-02": [8, 46], "TRA-CAN-01": [3, 20, 38], "MON-MEX-01": [12, 24, 38, 51]}
        for cod, ws in sem.items():
            a = self.acts[cod]
            for w in ws:
                D.poner_mp({"codigo": cod, "anio": 2026, "semana": w, "sucursal": a["sucursal"], "area": a["area"],
                            "origen": "importado"}, a)

    def llamar(self, *a, **k):
        return handler.lambda_handler(ev(*a, **k), None)

    def mp(self, cod, w, anio=2026):
        return D.get_mp(L.rid_mp(cod, anio, w))


class TestAgenda(Base):
    def test_el_tecnico_ve_su_sucursal_con_estatus_derivado(self):
        r = self.llamar("GET /mantenimiento", TEC1, "operador", ["Cedis"])
        self.assertEqual(r["statusCode"], 200)
        b = cuerpo(r)
        self.assertEqual(b["nivel"], "ejecuta")
        self.assertEqual(b["semanaActual"], 39)
        self.assertEqual({i["codigo"] for i in b["items"]}, {"AIR-GDL-01", "AIR-GDL-02"})
        por = {(i["codigo"], i["semana"]): i for i in b["items"]}
        self.assertEqual(por[("AIR-GDL-01", 8)]["estatusEfectivo"], "vencida")
        self.assertEqual(por[("AIR-GDL-01", 8)]["lista"], "atrasadas")
        self.assertEqual(por[("AIR-GDL-01", 46)]["estatusEfectivo"], "programada")
        self.assertEqual(por[("AIR-GDL-01", 46)]["lista"], "proximas")
        self.assertTrue(por[("AIR-GDL-01", 46)]["puedeEjecutar"], "sin asignar → cualquiera de la sucursal")
        self.assertFalse(por[("AIR-GDL-02", 46)]["puedeEjecutar"], "titular es tec2")
        self.assertEqual(por[("AIR-GDL-02", 46)]["asignado"], TEC2)
        self.assertNotIn("administradores", b)

    def test_el_administrador_ve_todo_y_el_analista_consulta(self):
        b = cuerpo(self.llamar("GET /mantenimiento", JEFE, "supervisor"))
        self.assertEqual(b["nivel"], "administra")
        self.assertEqual(len(b["items"]), 11)
        self.assertEqual(b["administradores"], [JEFE])
        self.assertEqual(b["resumen"]["total"], 11)
        b2 = cuerpo(self.llamar("GET /mantenimiento", ANA, "analista"))
        self.assertEqual(b2["nivel"], "consulta")
        self.assertEqual(len(b2["items"]), 11)
        self.assertFalse(any(i["puedeEjecutar"] for i in b2["items"]))

    def test_un_supervisor_de_sucursal_no_administra(self):
        b = cuerpo(self.llamar("GET /mantenimiento", "sup@gpa.com.mx", "supervisor", ["Cancun"]))
        self.assertEqual(b["nivel"], "ejecuta")
        self.assertEqual({i["codigo"] for i in b["items"]}, {"TRA-CAN-01"})

    def test_sin_el_modulo_403(self):
        r = self.llamar("GET /mantenimiento", TEC1, "operador", ["Cedis"], modulos=("combustible",))
        self.assertEqual(r["statusCode"], 403)

    def test_con_todos_los_modulos_entra(self):
        r = self.llamar("GET /mantenimiento", TEC1, "operador", ["Cedis"], modulos=())
        self.assertEqual(r["statusCode"], 200)

    def test_url_subida_acepta_MP(self):
        r = handler.lambda_handler({"routeKey": "POST /evidencias/url-subida",
                                    "body": json.dumps({"tipo": "MP", "contentType": "image/jpeg"}),
                                    "requestContext": ev("x", TEC1, "operador")["requestContext"]}, None)
        self.assertEqual(r["statusCode"], 200)
        self.assertTrue(handler._KEY_RE.match(cuerpo(r)["key"]))


class TestEstado(Base):
    def test_el_tecnico_completa_lo_sin_asignar_y_se_la_queda(self):
        rid = L.rid_mp("AIR-GDL-01", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "completada", "desc": "Filtros lavados", "checks": ["a"],
                              "fotos": ["MP/" + "b" * 32 + ".jpg"], "faltantes": ["Termómetro"]})
        self.assertEqual(r["statusCode"], 200, r["body"])
        mp = self.mp("AIR-GDL-01", 46)
        self.assertEqual(mp["estatus"], "completada")
        self.assertEqual(mp["asignadoA"], TEC1)
        self.assertEqual(mp["tecnicoEmail"], TEC1)
        self.assertTrue(mp["fin"])
        self.assertEqual([h["a"] for h in mp["hist"]], ["Tomó la actividad", "Completada"])
        # GSI3 reescrito: ahora aparece en «lo mío»
        crudo = self.tabla.items[(f"MP#{rid}", "META")]
        self.assertEqual(crudo["GSI3PK"], f"MP#{TEC1}")
        self.assertEqual([x["id"] for x in D.mps_cuenta(TEC1)], [rid])

    def test_no_toca_lo_asignado_a_otro(self):
        rid = L.rid_mp("AIR-GDL-02", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "completada", "desc": "x"})
        self.assertEqual(r["statusCode"], 403)
        self.assertEqual(self.mp("AIR-GDL-02", 46).get("estatus", "programada"), "programada")

    def test_ni_lo_de_otra_sucursal(self):
        rid = L.rid_mp("TRA-CAN-01", 2026, 38)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "completada", "desc": "x"})
        self.assertEqual(r["statusCode"], 403)

    def test_completar_exige_descripcion_y_pendiente_motivo(self):
        rid = L.rid_mp("AIR-GDL-01", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "completada"})
        self.assertEqual(r["statusCode"], 422)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "pendiente"})
        self.assertEqual(r["statusCode"], 422)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "pendiente", "motivo": "Falta refacción"})
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(self.mp("AIR-GDL-01", 46)["estatus"], "pendiente")

    def test_el_tecnico_pide_reprogramar_y_el_plazo_no_se_mueve(self):
        rid = L.rid_mp("AIR-GDL-01", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"estatus": "reprogramada", "reprogramadaA": 48, "motivo": "vacaciones"})
        self.assertEqual(r["statusCode"], 422, "reprogramar directo es del administrador")
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"], rid=rid,
                        body={"solicitar": "reprogramar", "motivo": "vacaciones", "semana": 48})
        self.assertEqual(r["statusCode"], 200, r["body"])
        mp = self.mp("AIR-GDL-01", 46)
        self.assertEqual(mp.get("estatus", "programada"), "programada")
        self.assertEqual(mp["solicitud"]["semana"], 48)
        self.assertIsNone(self.mp("AIR-GDL-01", 48))

    def test_el_administrador_reprograma_y_nace_el_vencimiento_nuevo(self):
        rid = L.rid_mp("AIR-GDL-01", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", JEFE, "supervisor", rid=rid,
                        body={"estatus": "reprogramada", "reprogramadaA": 48, "motivo": "carga de trabajo"})
        self.assertEqual(r["statusCode"], 200, r["body"])
        self.assertEqual(cuerpo(r)["nuevo"], L.rid_mp("AIR-GDL-01", 2026, 48))
        self.assertEqual(self.mp("AIR-GDL-01", 46)["estatus"], "reprogramada")
        nuevo = self.mp("AIR-GDL-01", 48)
        self.assertEqual(nuevo["origen"], "reprogramada")
        self.assertEqual(nuevo["reprogramadaDe"], 46)
        self.assertEqual(nuevo["fecha"], "2026-11-28")

    def test_el_analista_no_captura(self):
        rid = L.rid_mp("AIR-GDL-01", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/estado", ANA, "analista", rid=rid,
                        body={"estatus": "completada", "desc": "x"})
        self.assertEqual(r["statusCode"], 403)

    def test_rid_codificado_en_la_url(self):
        r = self.llamar("POST /mantenimiento/{rid}/estado", TEC1, "operador", ["Cedis"],
                        rid="AIR-GDL-01%232026%2346", body={"estatus": "proceso"})
        self.assertEqual(r["statusCode"], 200, r["body"])
        self.assertEqual(self.mp("AIR-GDL-01", 46)["estatus"], "proceso")
        self.assertTrue(self.mp("AIR-GDL-01", 46)["inicio"])


class TestAsignacion(Base):
    def test_excepcion_de_una_semana(self):
        rid = L.rid_mp("AIR-GDL-02", 2026, 46)
        r = self.llamar("POST /mantenimiento/{rid}/asignar", TEC1, "operador", ["Cedis"], rid=rid, body={"cuenta": TEC1})
        self.assertEqual(r["statusCode"], 403)
        r = self.llamar("POST /mantenimiento/{rid}/asignar", JEFE, "supervisor", rid=rid, body={"cuenta": TEC1})
        self.assertEqual(r["statusCode"], 200, r["body"])
        self.assertEqual(cuerpo(r)["asignado"], TEC1)
        self.assertEqual(self.tabla.items[(f"MP#{rid}", "META")]["GSI3PK"], f"MP#{TEC1}")
        # la otra semana del activo sigue siendo del titular
        self.assertEqual(self.tabla.items[(f"MP#{L.rid_mp('AIR-GDL-02', 2026, 8)}", "META")]["GSI3PK"], f"MP#{TEC2}")
        # quitar la excepción regresa al titular
        r = self.llamar("POST /mantenimiento/{rid}/asignar", JEFE, "supervisor", rid=rid, body={"cuenta": None})
        self.assertEqual(cuerpo(r)["asignado"], TEC2)
        self.assertEqual(self.tabla.items[(f"MP#{rid}", "META")]["GSI3PK"], f"MP#{TEC2}")

    def test_titular_por_area_reindexa_lo_mio(self):
        r = self.llamar("POST /mantenimiento/admin/titular", JEFE, "supervisor",
                        body={"area": "Mini splits", "sucursal": "Cedis", "titular": TEC1})
        self.assertEqual(r["statusCode"], 200, r["body"])
        b = cuerpo(r)
        self.assertEqual(sorted(b["activos"]), ["AIR-GDL-01", "AIR-GDL-02"])
        self.assertEqual(b["reindexados"], 4)
        self.assertEqual(D.activo("AIR-GDL-02")["titular"], TEC1)
        self.assertEqual(len(D.mps_cuenta(TEC1)), 4)
        self.assertEqual(len(D.mps_cuenta(TEC2)), 0)

    def test_asignables_solo_cuentas_con_el_modulo_y_sin_datos_de_mas(self):
        r = self.llamar("GET /mantenimiento/asignables", TEC1, "operador", ["Cedis"])
        self.assertEqual(r["statusCode"], 403)
        r = self.llamar("GET /mantenimiento/asignables", JEFE, "supervisor")
        self.assertEqual(r["statusCode"], 200)
        items = cuerpo(r)["items"]
        self.assertEqual([i["id"] for i in items], [TEC2, TEC1])     # orden por nombre
        self.assertEqual(set(items[0].keys()), {"id", "nombre", "sucursales"})


class TestCorrectivo(Base):
    def test_con_preventivo_reinicia_el_reloj_sin_tocar_la_historia(self):
        # AIR-GDL-01: 6 meses, semanas 8 y 46; correctivo en la 39 → se retira la 46, la 8 se conserva
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"],
                        body={"codigo": "AIR-GDL-01", "falla": "No enfría", "desc": "Cambio de capacitor y servicio",
                              "refacciones": "Capacitor", "resp": "INTERNO", "conPreventivo": True,
                              "fotos": ["MP/" + "c" * 32 + ".jpg"]})
        self.assertEqual(r["statusCode"], 200, r["body"])
        b = cuerpo(r)
        self.assertEqual(b["semanasRetiradas"], [46])
        self.assertEqual(b["semanasNuevas"], [])
        self.assertIsNone(self.mp("AIR-GDL-01", 46))
        self.assertIsNotNone(self.mp("AIR-GDL-01", 8), "la vencida es historia")
        act = D.activo("AIR-GDL-01")
        self.assertEqual(act["reprog"]["base"], 39)
        cors = D.mpcs_sucursal("Cedis")
        self.assertEqual(len(cors), 1)
        self.assertEqual(cors[0]["codigo"], "AIR-GDL-01")
        self.assertTrue(cors[0]["conPreventivo"])
        self.assertEqual(cors[0]["semana"], 39)

    def test_sin_preventivo_no_toca_el_calendario(self):
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"],
                        body={"codigo": "AIR-GDL-01", "falla": "Gotea", "desc": "Se destapó el drenaje", "conPreventivo": False})
        self.assertEqual(r["statusCode"], 200)
        self.assertIsNotNone(self.mp("AIR-GDL-01", 46))
        self.assertNotIn("reprog", D.activo("AIR-GDL-01"))

    def test_variable_no_recalcula(self):
        r = self.llamar("POST /mantenimiento/correctivo", JEFE, "supervisor",
                        body={"codigo": "MON-MEX-01", "falla": "x", "desc": "y", "conPreventivo": True})
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(cuerpo(r)["semanasRetiradas"], [])
        self.assertIsNotNone(self.mp("MON-MEX-01", 51))

    def test_2_meses_en_la_20_agrega_28_36_44_52(self):
        a = {"codigo": "MON-GDL-01", "tipo": "MON", "descripcion": "DOOSAN", "sucursal": "Cedis", "sucCodigo": "GDL",
             "area": "Equipo de carga pesado", "periodicidad": "2 MESES", "semPeriodo": 8, "responsabilidad": "EXTERNO",
             "titular": None, "activo": True, "origen": "excel"}
        D.guardar_activo(a)
        for w in (7, 19, 33, 46):
            D.poner_mp({"codigo": "MON-GDL-01", "anio": 2026, "semana": w, "sucursal": "Cedis", "area": a["area"]}, a)
        R.hoy_mx = lambda: date(2026, 5, 15)          # semana 20
        r = self.llamar("POST /mantenimiento/correctivo", JEFE, "supervisor",
                        body={"codigo": "MON-GDL-01", "falla": "x", "desc": "y", "conPreventivo": True})
        b = cuerpo(r)
        self.assertEqual(b["semanasRetiradas"], [33, 46])
        self.assertEqual(b["semanasNuevas"], [28, 36, 44, 52])
        self.assertEqual(sorted(x["semana"] for x in D.mps_activo("MON-GDL-01")), [7, 19, 28, 36, 44, 52])
        self.assertEqual(self.mp("MON-GDL-01", 28)["origen"], "correctivo")

    def test_una_semana_con_captura_no_se_retira(self):
        D.parchar_mp(L.rid_mp("AIR-GDL-01", 2026, 46), {"estatus": "pendiente", "motivo": "x"})
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"],
                        body={"codigo": "AIR-GDL-01", "falla": "x", "desc": "y", "conPreventivo": True})
        self.assertEqual(cuerpo(r)["semanasRetiradas"], [])
        self.assertIsNotNone(self.mp("AIR-GDL-01", 46))

    def test_exige_equipo_falla_y_descripcion_y_alcance(self):
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"], body={"codigo": "TRA-CAN-01", "falla": "x", "desc": "y"})
        self.assertEqual(r["statusCode"], 403)
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"], body={"codigo": "AIR-GDL-01", "desc": "y"})
        self.assertEqual(r["statusCode"], 422)
        r = self.llamar("POST /mantenimiento/correctivo", TEC1, "operador", ["Cedis"], body={"codigo": "NADA-01", "falla": "x", "desc": "y"})
        self.assertEqual(r["statusCode"], 422)


class TestAdministracion(Base):
    def test_solo_el_administrador(self):
        for ruta in ("POST /mantenimiento/admin/activo", "POST /mantenimiento/admin/tipo", "POST /mantenimiento/admin/titular",
                     "POST /mantenimiento/admin/generar", "POST /mantenimiento/admin/publicar"):
            self.assertEqual(self.llamar(ruta, TEC1, "operador", ["Cedis"], body={})["statusCode"], 403, ruta)
            self.assertEqual(self.llamar(ruta, "sup@gpa.com.mx", "supervisor", ["Cedis"], body={})["statusCode"], 403, ruta)

    def test_alta_de_activo_propone_codigo(self):
        r = self.llamar("POST /mantenimiento/admin/activo", JEFE, "supervisor",
                        body={"tipo": "AIR", "sucCodigo": "GDL", "descripcion": "COMEDOR", "periodicidad": "6 meses",
                              "area": "Mini splits", "responsabilidad": "INTERNO"})
        self.assertEqual(r["statusCode"], 200, r["body"])
        a = cuerpo(r)["activo"]
        self.assertEqual(a["codigo"], "AIR-GDL-03")
        self.assertEqual(a["sucursal"], "Cedis")
        self.assertEqual(a["semPeriodo"], 26)
        self.assertEqual(a["periodicidad"], "6 MESES")
        self.assertEqual(a["origen"], "modulo")
        # el admin de la app también administra
        r = self.llamar("POST /mantenimiento/admin/activo", ADMINAPP, "admin", body={"codigo": "AIR-GDL-03", "eliminar": True})
        self.assertEqual(r["statusCode"], 200)
        self.assertFalse(D.activo("AIR-GDL-03")["activo"])

    def test_tipo_desconocido_se_rechaza(self):
        r = self.llamar("POST /mantenimiento/admin/activo", JEFE, "supervisor", body={"tipo": "ZZZ", "sucCodigo": "GDL"})
        self.assertEqual(r["statusCode"], 422)

    def test_editar_tipo(self):
        r = self.llamar("POST /mantenimiento/admin/tipo", JEFE, "supervisor",
                        body={"pref": "MON", "nombre": "Montacargas", "procedimiento": "Servicio por horas…",
                              "puntos": ["Horómetro", "Frenos"], "materiales": [], "herramienta": ["Horómetro"], "esPropuesta": False})
        self.assertEqual(r["statusCode"], 200)
        t = {x["pref"]: x for x in D.tipos()}["MON"]
        self.assertEqual(t["puntos"], ["Horómetro", "Frenos"])
        self.assertFalse(t["esPropuesta"])

    def test_generar_simula_y_luego_aplica_como_propuesta_invisible_hasta_publicar(self):
        D.parchar_mp(L.rid_mp("AIR-GDL-01", 2026, 8), {"estatus": "completada"})
        antes = self.tabla.escrituras
        r = self.llamar("POST /mantenimiento/admin/generar", JEFE, "supervisor", body={"anio": 2027})
        b = cuerpo(r)
        self.assertTrue(b["simulacion"])
        self.assertEqual(self.tabla.escrituras, antes, "la simulación no escribe")
        self.assertIn(["AIR-GDL-01", 34], b["propuestas"])     # 8 completada → 34, 60→8
        self.assertIn(["AIR-GDL-01", 8], b["propuestas"])
        self.assertIn(["AIR-GDL-02", 46], b["propuestas"])     # sin ejecución: conserva
        self.assertEqual(b["variables"], ["MON-MEX-01"])
        r = self.llamar("POST /mantenimiento/admin/generar", JEFE, "supervisor", body={"anio": 2027, "aplicar": True})
        b = cuerpo(r)
        self.assertFalse(b["simulacion"])
        self.assertEqual(b["creados"], b["total"])
        # el técnico NO ve la propuesta; el administrador sí
        tec = cuerpo(self.llamar("GET /mantenimiento", TEC1, "operador", ["Cedis"], qs={"anio": "2027"}))
        self.assertEqual(tec["items"], [])
        jefe = cuerpo(self.llamar("GET /mantenimiento", JEFE, "supervisor", qs={"anio": "2027"}))
        self.assertEqual(len(jefe["items"]), 7)
        self.assertTrue(cuerpo(self.llamar("GET /mantenimiento", JEFE, "supervisor"))["hayPropuesta"])
        r = self.llamar("POST /mantenimiento/admin/publicar", JEFE, "supervisor", body={"anio": 2027})
        self.assertEqual(cuerpo(r)["publicados"], 7)
        tec = cuerpo(self.llamar("GET /mantenimiento", TEC1, "operador", ["Cedis"], qs={"anio": "2027"}))
        self.assertEqual(len(tec["items"]), 4)

    def test_generar_un_anio_pasado_se_rechaza(self):
        r = self.llamar("POST /mantenimiento/admin/generar", JEFE, "supervisor", body={"anio": 2026})
        self.assertEqual(r["statusCode"], 422)

    def test_guardar_modulo_conserva_administradores(self):
        # El panel activa/desactiva mandando el módulo sin `administradores`: no se pierden.
        from db.escritura import guardar_modulo
        guardar_modulo({"clave": "mantenimiento", "nombre": "Plan Mtto", "activo": False})
        self.assertEqual(D.administradores(), [JEFE])
        guardar_modulo({"clave": "mantenimiento", "nombre": "Plan Mtto", "administradores": [" Nuevo@GPA.com.mx ", JEFE]})
        self.assertEqual(D.administradores(), [JEFE, "nuevo@gpa.com.mx"])


if __name__ == "__main__":
    unittest.main()
