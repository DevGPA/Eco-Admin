# tests/test_historico.py
# Consulta HISTÓRICA del servidor, con una DynamoDB simulada que se comporta como
# la real en lo que importa: evalúa las KeyCondition de boto3 sobre los índices,
# ordena por fecha y PAGINA (LastEvaluatedKey) como lo hace el servicio.
#   python -m unittest tests.test_historico -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import base64
import gzip
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m               # noqa: E402
import db.queries as q               # noqa: E402
import handler                       # noqa: E402

MX = timezone(timedelta(hours=-6))
HOY = datetime.now(MX).date()


# ── DynamoDB simulada ────────────────────────────────────────────
def _evaluar(cond, item) -> bool:
    """Evalúa una KeyConditionExpression de boto3 (eq / between / gte / lt / and)."""
    e = cond.get_expression()
    op, vals = e["operator"], e["values"]
    if op == "AND":
        return _evaluar(vals[0], item) and _evaluar(vals[1], item)
    attr = vals[0].name
    v = item.get(attr)
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
    raise AssertionError(f"operador no simulado: {op}")


SORT_KEY = {"tipo-fecha-idx": "GSI1SK", "sucursal-fecha-idx": "GSI2SK", "cuenta-fecha-idx": "GSI3SK"}


class TablaFalsa:
    """Query paginado: devuelve `pagina` items por llamada y LastEvaluatedKey."""

    def __init__(self, items, pagina=1000):
        self.items = items
        self.pagina = pagina
        self.llamadas = 0

    def query(self, IndexName, KeyConditionExpression, ScanIndexForward=True, ExclusiveStartKey=None, **_):
        self.llamadas += 1
        sk = SORT_KEY[IndexName]
        sel = [i for i in self.items if _evaluar(KeyConditionExpression, i)]
        sel.sort(key=lambda i: i[sk], reverse=not ScanIndexForward)
        ini = ExclusiveStartKey["pos"] if ExclusiveStartKey else 0
        pag = sel[ini:ini + self.pagina]
        resp = {"Items": pag}
        if ini + self.pagina < len(sel):
            resp["LastEvaluatedKey"] = {"pos": ini + self.pagina}
        return resp


def reg(tipo, rid, fecha, sucursal, cuenta, **extra):
    """Un registro tal como lo guarda crear_registro (llaves + GSI)."""
    f = fecha + "T10:00:00-06:00"
    d = {"id": rid, "tipo_reg": tipo, "fecha": f, "sucursal": sucursal, "accountId": cuenta,
         "status": "Aprobado", **extra}
    d.update(m.registro_keys(tipo, rid, sucursal, cuenta, f))
    return d


def datos_3_anios():
    """~3 años de registros: SOL, CL, MC, un formulario y EPP; 3 sucursales; 3 cuentas."""
    out = []
    sucs = ["Cedis", "Cancun", "Vallarta"]
    cuentas = ["op1@gpa.com.mx", "op2@gpa.com.mx", "op3@gpa.com.mx"]
    d = date(2024, 1, 3)
    n = 0
    while d <= HOY:
        for k, tipo in enumerate([m.SOL, m.CL, m.MC, "FRM#extintores", m.EPP]):
            n += 1
            # Tamaño realista: una solicitud real trae ~25 campos y 5-6 llaves de
            # S3 (≈1 KB). Sin esto el listado de 3 años no llega a los 50 KB que
            # disparan el gzip y la prueba de compresión no probaría nada.
            out.append(reg(tipo, f"{tipo[:3].lower()}{n:05d}", d.isoformat(),
                           sucs[n % 3], cuentas[n % 3],
                           km=1000 + n, _auditoria={"geo": "secreto"},
                           placas="ABC-12-34", economico=str(20 + n % 40), responsable="Operador Ejemplo",
                           fotos=[f"SOL/{n:05d}{k}.webp" for k in range(5)],
                           obs="Carga de ruta de reparto, sin novedades en la unidad. " * 6))
        d += timedelta(days=9)          # ~40 fechas al año × 5 tipos
    return out


class Base(unittest.TestCase):
    pagina = 1000

    def setUp(self):
        self.datos = datos_3_anios()
        self.tabla = TablaFalsa(self.datos, self.pagina)
        self._orig = q._t
        q._t = lambda: self.tabla
        # El servidor firma las llaves de S3; aquí pasan tal cual.
        self._orig_urls = handler._resolver_urls
        handler._resolver_urls = lambda o: o
        # _listar consulta la lista de responsables (para el alcance de un operador
        # marcado); aquí no hay ninguno, y no debe tocar la base real.
        self._orig_resp = handler.responsables_alerta
        handler.responsables_alerta = lambda: []

    def tearDown(self):
        q._t = self._orig
        handler._resolver_urls = self._orig_urls
        handler.responsables_alerta = self._orig_resp

    # Oráculo directo sobre los datos en memoria (sin índices ni paginación)
    def esperado(self, tipo, desde=None, hasta_excl=None, sucursales=None, cuenta=None):
        r = [x for x in self.datos if x["tipo_reg"] == tipo]
        if desde:
            r = [x for x in r if x["fecha"] >= desde]
        if hasta_excl:
            r = [x for x in r if x["fecha"] < hasta_excl]
        if sucursales:
            r = [x for x in r if x["sucursal"] in sucursales]
        if cuenta:
            r = [x for x in r if x["accountId"] == cuenta]
        return sorted((x["id"] for x in r), key=lambda i: i, reverse=True)

    def ids(self, regs):
        return [x["id"] for x in regs]


class TestVentanaYRangos(Base):
    def test_sin_fechas_aplica_la_ventana_por_defecto(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": None})
        self.assertIsNone(hasta)
        self.assertEqual(desde, (datetime.now(MX) - timedelta(days=handler.VENTANA_DIAS)).strftime("%Y-%m-%d"))
        regs = q.listar_registros(m.SOL, "admin", [], "a@gpa.com.mx", desde, hasta)
        self.assertEqual(self.ids(regs), self.esperado(m.SOL, desde=desde))
        self.assertTrue(all(r["fecha"] >= desde for r in regs))

    def test_todo_el_historial(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": {"todo": "1"}})
        self.assertIsNone(desde); self.assertIsNone(hasta)
        regs = q.listar_registros(m.SOL, "admin", [], "a", desde, hasta)
        self.assertEqual(self.ids(regs), self.esperado(m.SOL))
        self.assertGreater(len(regs), 100, "3 años deben ser más de 100 registros")

    def test_desde_viejo_trae_desde_ahi_hasta_hoy(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": {"desde": "2025-03-01"}})
        regs = q.listar_registros(m.CL, "admin", [], "a", desde, hasta)
        self.assertEqual(self.ids(regs), self.esperado(m.CL, desde="2025-03-01"))

    def test_solo_hasta_con_todo_trae_desde_el_principio(self):
        # Es lo que manda la app cuando solo se llena «Hasta»: todo=1 + hasta.
        desde, hasta = handler._rango_listado({"queryStringParameters": {"todo": "1", "hasta": "2024-06-30"}})
        self.assertIsNone(desde); self.assertEqual(hasta, "2024-07-01")
        regs = q.listar_registros(m.MC, "admin", [], "a", desde, hasta)
        self.assertEqual(self.ids(regs), self.esperado(m.MC, hasta_excl="2024-07-01"))
        self.assertTrue(all(r["fecha"][:10] <= "2024-06-30" for r in regs))

    def test_hasta_es_inclusivo_del_dia_completo(self):
        # Un registro del 2024-06-30 a las 10:00 debe entrar aunque «hasta» sea ese día.
        self.datos.append(reg(m.SOL, "solfin", "2024-06-30", "Cedis", "op1@gpa.com.mx"))
        desde, hasta = handler._rango_listado({"queryStringParameters": {"desde": "2024-06-01", "hasta": "2024-06-30"}})
        regs = q.listar_registros(m.SOL, "admin", [], "a", desde, hasta)
        self.assertIn("solfin", self.ids(regs))
        self.assertEqual(self.ids(regs), self.esperado(m.SOL, desde="2024-06-01", hasta_excl="2024-07-01"))

    def test_rango_cerrado(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": {"desde": "2025-01-01", "hasta": "2025-12-31"}})
        regs = q.listar_registros("FRM#extintores", "admin", [], "a", desde, hasta)
        self.assertEqual(self.ids(regs), self.esperado("FRM#extintores", desde="2025-01-01", hasta_excl="2026-01-01"))
        self.assertTrue(all(r["fecha"].startswith("2025") for r in regs))

    def test_fechas_mal_formadas_se_ignoran(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": {"desde": "01/03/2025", "hasta": "ayer"}})
        self.assertEqual(desde, (datetime.now(MX) - timedelta(days=handler.VENTANA_DIAS)).strftime("%Y-%m-%d"))
        self.assertIsNone(hasta)

    def test_rango_futuro_no_trae_nada(self):
        desde, hasta = handler._rango_listado({"queryStringParameters": {"desde": "2099-01-01"}})
        self.assertEqual(q.listar_registros(m.SOL, "admin", [], "a", desde, hasta), [])

    def test_orden_descendente_por_fecha(self):
        regs = q.listar_registros(m.EPP, "admin", [], "a", None, None)
        fechas = [r["fecha"] for r in regs]
        self.assertEqual(fechas, sorted(fechas, reverse=True))


class TestPaginacion(Base):
    """La real devuelve ~1 MB por llamada; aquí, 7 registros por página."""
    pagina = 7

    def test_todo_el_historial_no_se_trunca(self):
        regs = q.listar_registros(m.SOL, "admin", [], "a", None, None)
        esperados = self.esperado(m.SOL)
        self.assertEqual(len(regs), len(esperados), f"se perdieron {len(esperados) - len(regs)} registros")
        self.assertEqual(self.ids(regs), esperados)
        self.assertGreater(self.tabla.llamadas, 1, "debió recorrer varias páginas")

    def test_operador_tampoco_se_trunca(self):
        regs = q.listar_registros(m.CL, "operador", [], "op1@gpa.com.mx", None, None)
        self.assertEqual(self.ids(regs), self.esperado(m.CL, cuenta="op1@gpa.com.mx"))
        self.assertGreater(self.tabla.llamadas, 1)

    def test_supervisor_de_dos_sucursales_tampoco(self):
        regs = q.listar_registros(m.MC, "supervisor", ["Cedis", "Cancun"], "s", None, None)
        self.assertEqual(self.ids(regs), self.esperado(m.MC, sucursales=["Cedis", "Cancun"]))
        fechas = [r["fecha"] for r in regs]
        self.assertEqual(fechas, sorted(fechas, reverse=True), "la unión de sucursales debe quedar ordenada")

    def test_un_rango_de_meses_tampoco(self):
        regs = q.listar_registros(m.SOL, "admin", [], "a", "2024-01-01", "2025-01-01")
        self.assertEqual(self.ids(regs), self.esperado(m.SOL, desde="2024-01-01", hasta_excl="2025-01-01"))


class TestAlcancePorRol(Base):
    def test_admin_y_analista_ven_todo(self):
        for rol in ("admin", "analista"):
            regs = q.listar_registros(m.SOL, rol, [], "x", None, None)
            self.assertEqual(self.ids(regs), self.esperado(m.SOL), rol)

    def test_supervisor_sin_sucursal_ve_todo(self):
        regs = q.listar_registros(m.SOL, "supervisor", [], "s", None, None)
        self.assertEqual(self.ids(regs), self.esperado(m.SOL))

    def test_supervisor_solo_sus_sucursales(self):
        regs = q.listar_registros(m.SOL, "supervisor", ["Vallarta"], "s", None, None)
        self.assertEqual(self.ids(regs), self.esperado(m.SOL, sucursales=["Vallarta"]))
        self.assertTrue(all(r["sucursal"] == "Vallarta" for r in regs))

    def test_operador_solo_lo_suyo_tambien_en_el_archivo(self):
        regs = q.listar_registros(m.SOL, "operador", ["Cedis"], "op2@gpa.com.mx", "2024-01-01", None)
        self.assertEqual(self.ids(regs), self.esperado(m.SOL, desde="2024-01-01", cuenta="op2@gpa.com.mx"))
        self.assertTrue(all(r["accountId"] == "op2@gpa.com.mx" for r in regs))


class TestRespuestaDelServidor(Base):
    def _evento(self, qs=None, gzip_ok=True):
        return {"queryStringParameters": qs, "headers": {"accept-encoding": "gzip, deflate" if gzip_ok else "identity"}}

    def _cl(self, rol, cuenta="a@gpa.com.mx", sucs=None):
        return {"rol": rol, "email": cuenta, "sucursales": sucs or [], "sucursal": "", "modulos": []}

    def _items_de(self, resp):
        body = resp["body"]
        if resp.get("isBase64Encoded"):
            body = gzip.decompress(base64.b64decode(body)).decode()
        return json.loads(body)["items"]

    def test_listado_completo_viaja_comprimido_y_se_lee_entero(self):
        resp = handler._listar(m.SOL, self._evento({"todo": "1"}), self._cl("admin"))
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(resp.get("isBase64Encoded"), "un historial de 3 años supera los 50 KB: debe ir gzip")
        self.assertEqual(resp["headers"]["Content-Encoding"], "gzip")
        items = self._items_de(resp)
        self.assertEqual([i["id"] for i in items], self.esperado(m.SOL))

    def test_sin_gzip_en_el_cliente_va_plano(self):
        resp = handler._listar(m.SOL, self._evento({"todo": "1"}, gzip_ok=False), self._cl("admin"))
        self.assertFalse(resp.get("isBase64Encoded"))
        self.assertEqual([i["id"] for i in self._items_de(resp)], self.esperado(m.SOL))

    def test_operador_no_recibe_auditoria(self):
        resp = handler._listar(m.SOL, self._evento({"todo": "1"}), self._cl("operador", "op1@gpa.com.mx"))
        items = self._items_de(resp)
        self.assertTrue(items)
        self.assertTrue(all("_auditoria" not in i for i in items))

    def test_admin_si_recibe_auditoria(self):
        items = self._items_de(handler._listar(m.SOL, self._evento({"todo": "1"}), self._cl("admin")))
        self.assertTrue(all("_auditoria" in i for i in items))

    def test_sin_acceso_al_modulo_403(self):
        cl = {"rol": "operador", "email": "x", "sucursales": [], "sucursal": "", "modulos": ["mtto"]}
        resp = handler._listar(m.SOL, self._evento({"todo": "1"}), cl)
        self.assertEqual(resp["statusCode"], 403)

    def test_epp_tambien_lista_por_rango(self):
        resp = handler._listar(m.EPP, self._evento({"desde": "2024-01-01", "hasta": "2024-12-31"}), self._cl("admin"))
        items = self._items_de(resp)
        self.assertEqual([i["id"] for i in items], self.esperado(m.EPP, desde="2024-01-01", hasta_excl="2025-01-01"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
