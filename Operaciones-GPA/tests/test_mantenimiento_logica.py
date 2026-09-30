# tests/test_mantenimiento_logica.py
# Reglas puras del Plan de Mantenimiento. Corre sin AWS.
#   python -m unittest tests.test_mantenimiento_logica -v
# Casos exigidos por docs/mantenimiento/INSTRUCCIONES.md §11 y por las decisiones
# del usuario (docs/mantenimiento/DECISIONES.md).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from mantenimiento import logica as L      # noqa: E402


def mp(codigo, anio, sem, **k):
    return {"codigo": codigo, "anio": anio, "semana": sem, "sucursal": k.pop("sucursal", "Cedis"), **k}


class TestSemanas(unittest.TestCase):
    def test_semana_1_de_2026_empieza_el_29_dic_2025(self):
        self.assertEqual(L.inicio_semana(2026, 1), date(2025, 12, 29))

    def test_la_semana_vence_el_sabado(self):
        self.assertEqual(L.fecha_limite(2026, 1), date(2026, 1, 3))
        self.assertEqual(L.fecha_limite(2026, 38), date(2026, 9, 19))

    def test_semana_de_hoy(self):
        self.assertEqual(L.semana_de(date(2026, 9, 29)), 40)
        self.assertEqual(L.semana_de(date(2025, 12, 29), 2026), 1)
        self.assertEqual(L.semana_de(date(2026, 1, 3), 2026), 1)
        self.assertEqual(L.semana_de(date(2026, 1, 4), 2026), 1)      # domingo cierra la semana
        self.assertEqual(L.semana_de(date(2026, 1, 5), 2026), 2)

    def test_se_acota_a_1_y_52(self):
        self.assertEqual(L.semana_de(date(2025, 12, 1), 2026), 1)
        self.assertEqual(L.semana_de(date(2026, 12, 31), 2026), 52)

    def test_wk12_como_excel(self):
        # 1-ene-2026 es jueves → WEEKDAY(…,12) = 3
        self.assertEqual(L.wk12(date(2026, 1, 1)), 3)
        self.assertEqual(L.wk12(date(2026, 1, 5)), 7)      # lunes
        self.assertEqual(L.wk12(date(2026, 1, 4)), 6)      # domingo


class TestPeriodicidad(unittest.TestCase):
    def test_normaliza_las_12_variantes_del_excel(self):
        for txt, esp in [("POR MES", 4), ("2 meses", 8), ("2 MESES", 8), ("3 MESES", 13), ("3MESES", 13),
                         ("4 MESES", 17), ("6 MESES", 26), ("12 MESES", 52), ("12MESES", 52), ("ANUAL", 52),
                         ("Variable", 0), ("VARIABLES", 0)]:
            with self.subTest(txt=txt):
                self.assertEqual(L.semanas_periodo(txt), esp)

    def test_catalogo_editable_manda(self):
        self.assertEqual(L.semanas_periodo("4 MESES", {"4 MESES": 16}), 16)

    def test_marcas_esperadas(self):
        self.assertEqual([L.marcas_esperadas(p) for p in (4, 8, 13, 17, 26, 52)], [13, 6, 4, 3, 2, 1])
        self.assertIsNone(L.marcas_esperadas(0))


class TestEstatusDerivado(unittest.TestCase):
    HOY = date(2026, 9, 29)           # semana 40

    def test_programada_con_semana_pasada_es_vencida(self):
        self.assertEqual(L.estatus_efectivo(mp("A", 2026, 39), self.HOY), "vencida")

    def test_programada_de_la_semana_en_curso_no_esta_vencida(self):
        self.assertEqual(L.estatus_efectivo(mp("A", 2026, 40), self.HOY), "programada")

    def test_lo_capturado_manda_sobre_la_fecha(self):
        for est in ("completada", "pendiente", "proceso", "norealizada", "reprogramada"):
            self.assertEqual(L.estatus_efectivo(mp("A", 2026, 10, estatus=est), self.HOY), est)

    def test_listas_del_tecnico(self):
        self.assertEqual(L.lista_de(mp("A", 2026, 40), self.HOY), "semana")
        self.assertEqual(L.lista_de(mp("A", 2026, 39), self.HOY), "atrasadas")
        self.assertEqual(L.lista_de(mp("A", 2026, 41), self.HOY), "proximas")
        self.assertEqual(L.lista_de(mp("A", 2027, 1), self.HOY), "proximas")
        self.assertEqual(L.lista_de(mp("A", 2026, 5, estatus="completada"), self.HOY), "cerradas")

    def test_rid(self):
        self.assertEqual(L.rid_mp("TRA-GDL-01", 2026, 38), "TRA-GDL-01#2026#38")
        self.assertEqual(L.partes_rid("TRA-GDL-01#2026#38"), ("TRA-GDL-01", 2026, 38))
        with self.assertRaises(ValueError):
            L.partes_rid("TRA-GDL-01#x")


class TestAsignacion(unittest.TestCase):
    def test_la_excepcion_manda_sobre_el_titular(self):
        act = {"codigo": "AIR-GDL-01", "titular": "marco@gpa.com.mx"}
        self.assertEqual(L.asignado_efectivo(mp("AIR-GDL-01", 2026, 8), act), "marco@gpa.com.mx")
        self.assertEqual(L.asignado_efectivo(mp("AIR-GDL-01", 2026, 8, asignadoA="luis@gpa.com.mx"), act),
                         "luis@gpa.com.mx")

    def test_sin_titular_ni_excepcion_queda_sin_asignar(self):
        self.assertIsNone(L.asignado_efectivo(mp("A", 2026, 1), {"codigo": "A"}))
        self.assertEqual(L.cuenta_gsi3(mp("A", 2026, 1, sucursal="Cancun"), None), "SIN_ASIGNAR#Cancun")

    def test_codigo_propuesto(self):
        self.assertEqual(L.codigo_propuesto("TRA", "GDL", ["TRA-GDL-01", "TRA-GDL-02"]), "TRA-GDL-03")
        self.assertEqual(L.codigo_propuesto("air", "czd", []), "AIR-CZD-01")


class TestNivel(unittest.TestCase):
    ADMINS = ["mantenimiento@gpa.com.mx"]

    def test_los_cuatro_casos(self):
        self.assertEqual(L.nivel({"email": "tec@gpa.com.mx", "rol": "operador"}, self.ADMINS), "ejecuta")
        self.assertEqual(L.nivel({"email": "sup@gpa.com.mx", "rol": "supervisor"}, self.ADMINS), "ejecuta")
        self.assertEqual(L.nivel({"email": "ana@gpa.com.mx", "rol": "analista"}, self.ADMINS), "consulta")
        self.assertEqual(L.nivel({"email": "Mantenimiento@GPA.com.mx", "rol": "supervisor"}, self.ADMINS),
                         "administra")

    def test_un_supervisor_NO_obtiene_administra(self):
        self.assertNotEqual(L.nivel({"email": "sup@gpa.com.mx", "rol": "supervisor"}, self.ADMINS), "administra")

    def test_el_admin_de_la_app_administra(self):
        self.assertEqual(L.nivel({"email": "administracion@gpa.com.mx", "rol": "admin"}, []), "administra")

    def test_alcance(self):
        cl = {"email": "t@gpa.com.mx", "rol": "operador", "sucursales": ["Cedis"]}
        self.assertEqual(L.alcance_sucursales(cl, "ejecuta"), ["Cedis"])
        self.assertIsNone(L.alcance_sucursales({**cl, "sucursales": []}, "ejecuta"))
        self.assertIsNone(L.alcance_sucursales(cl, "administra"))

    def test_ejecutar_exige_estar_asignado_o_que_este_sin_asignar(self):
        tec = {"email": "tec@gpa.com.mx", "rol": "operador", "sucursales": ["Cedis"]}
        act = {"codigo": "A", "titular": "otro@gpa.com.mx"}
        self.assertFalse(L.puede_ejecutar(tec, "ejecuta", mp("A", 2026, 40), act), "asignada a otro")
        self.assertTrue(L.puede_ejecutar(tec, "ejecuta", mp("A", 2026, 40), {"codigo": "A"}), "sin asignar")
        self.assertTrue(L.puede_ejecutar(tec, "ejecuta", mp("A", 2026, 40, asignadoA="tec@gpa.com.mx"), act))
        self.assertFalse(L.puede_ejecutar(tec, "ejecuta", mp("A", 2026, 40, sucursal="Cancun"), None),
                         "otra sucursal")
        self.assertTrue(L.puede_ejecutar({"email": "j@gpa.com.mx", "rol": "supervisor"}, "administra",
                                         mp("A", 2026, 40, sucursal="Cancun"), act))
        self.assertFalse(L.puede_ejecutar({"email": "a@gpa.com.mx", "rol": "analista"}, "consulta",
                                          mp("A", 2026, 40), None))

    def test_reprogramar_es_del_administrador(self):
        self.assertTrue(L.puede_reprogramar("administra"))
        self.assertFalse(L.puede_reprogramar("ejecuta"))
        err = L.validar_cambio({"estatus": "reprogramada", "reprogramadaA": 45, "motivo": "x"}, "ejecuta")
        self.assertIn("administrador", err)
        self.assertIsNone(L.validar_cambio({"estatus": "reprogramada", "reprogramadaA": 45, "motivo": "x"},
                                           "administra"))
        self.assertIsNone(L.validar_cambio({"solicitar": "reprogramar", "motivo": "vacaciones"}, "ejecuta"))
        self.assertIn("motivo", L.validar_cambio({"solicitar": "reprogramar"}, "ejecuta"))

    def test_motivos_y_descripcion_obligatorios(self):
        self.assertIn("motivo", L.validar_cambio({"estatus": "pendiente"}, "ejecuta"))
        self.assertIn("motivo", L.validar_cambio({"estatus": "norealizada"}, "ejecuta"))
        self.assertIn("Describe", L.validar_cambio({"estatus": "completada"}, "ejecuta"))
        self.assertIsNone(L.validar_cambio({"estatus": "completada", "desc": "Lavado de filtros"}, "ejecuta"))
        self.assertIn("inválido", L.validar_cambio({"estatus": "vencida"}, "administra"))


class TestReinicioReloj(unittest.TestCase):
    def test_6_meses_en_la_39_retira_la_46_y_conserva_la_8(self):
        r = L.reinicio_reloj([8, 46], 26, 39)
        self.assertEqual(r, {"quitar": [46], "nuevas": [], "conservar": [8]})

    def test_2_meses_en_la_20_retira_33_y_46_y_agrega_28_36_44_52(self):
        r = L.reinicio_reloj([7, 19, 33, 46], 8, 20)
        self.assertEqual(r["quitar"], [33, 46])
        self.assertEqual(r["nuevas"], [28, 36, 44, 52])
        self.assertEqual(r["conservar"], [7, 19])

    def test_variable_no_recalcula(self):
        r = L.reinicio_reloj([12, 24, 38, 51], 0, 20)
        self.assertEqual(r, {"quitar": [], "nuevas": [], "conservar": [12, 24, 38, 51]})

    def test_la_semana_del_correctivo_se_retira_y_las_coincidentes_no_se_duplican(self):
        # Como en la agenda de referencia: el preventivo hecho en la semana 10 cubre el
        # vencimiento de esa misma semana (se retira); 20 y 30 ya coinciden con el nuevo
        # calendario y se conservan sin duplicarse; se agregan 40 y 50.
        r = L.reinicio_reloj([10, 20, 30], 10, 10)
        self.assertEqual(r["quitar"], [10])
        self.assertEqual(r["nuevas"], [40, 50])
        self.assertEqual(r["conservar"], [])


class TestAnioSiguiente(unittest.TestCase):
    def test_desde_la_ultima_completada(self):
        # 6 meses, última completada en la 46 → 46+26 = 72 → semana 20 del año nuevo, luego 46
        self.assertEqual(L.semanas_siguiente_anio([8, 46], 46, 26), [20, 46])
        # 2 meses, última completada en la 44 → 52 sigue en el año actual; 60 → 8, 16, …
        self.assertEqual(L.semanas_siguiente_anio([], 44, 8), [8, 16, 24, 32, 40, 48])

    def test_sin_ejecucion_conserva_las_del_anio(self):
        self.assertEqual(L.semanas_siguiente_anio([3, 20, 38], None, 17), [3, 20, 38])

    def test_sin_nada_queda_sin_programar_y_variable_aparte(self):
        self.assertEqual(L.semanas_siguiente_anio([], None, 17), [])
        self.assertIsNone(L.semanas_siguiente_anio([12, 24], 12, 0))

    def test_generar_anio_clasifica_y_mide_la_carga(self):
        activos = [{"codigo": "AIR-GDL-01", "semPeriodo": 26, "activo": True},
                   {"codigo": "AIR-GDL-02", "semPeriodo": 26, "activo": True},
                   {"codigo": "MON-MEX-01", "semPeriodo": 0, "activo": True},
                   {"codigo": "EXT-MTY-01", "semPeriodo": 26, "activo": True},
                   {"codigo": "BAJA-01", "semPeriodo": 4, "activo": False}]
        mps = [mp("AIR-GDL-01", 2026, 8, estatus="completada"), mp("AIR-GDL-01", 2026, 46),
               mp("AIR-GDL-02", 2026, 8), mp("AIR-GDL-02", 2026, 46),
               mp("MON-MEX-01", 2026, 12)]
        g = L.generar_anio(activos, mps, 2027)
        self.assertEqual(g["anio"], 2027)
        self.assertIn(("AIR-GDL-01", 8), g["propuestas"])       # 8 completada → 34 → 60 → 8, 34
        self.assertIn(("AIR-GDL-01", 34), g["propuestas"])
        self.assertIn(("AIR-GDL-02", 8), g["propuestas"])       # sin ejecución: conserva 8 y 46
        self.assertIn(("AIR-GDL-02", 46), g["propuestas"])
        self.assertEqual(g["variables"], ["MON-MEX-01"])
        self.assertEqual(g["sinProgramar"], ["EXT-MTY-01"])
        self.assertEqual(g["total"], 4)
        self.assertEqual(g["carga"][8], 2)

    def test_picos(self):
        carga = {w: 5 for w in range(1, 53)}
        carga[8] = 44
        carga[46] = 34
        p = L.semanas_pico(carga)
        self.assertEqual([x["semana"] for x in p], [8, 46])
        self.assertEqual(len(p[0]["alternativas"]), 2)


class TestResumen(unittest.TestCase):
    def test_cumplimiento_sobre_lo_exigible(self):
        hoy = date(2026, 9, 29)      # semana 40
        mps = [mp("A", 2026, 10, estatus="completada"), mp("B", 2026, 20), mp("C", 2026, 40),
               mp("D", 2026, 50), mp("E", 2026, 30, estatus="pendiente")]
        r = L.resumen(mps, hoy)
        self.assertEqual(r["total"], 5)
        self.assertEqual(r["exigibles"], 4)          # A, B, C, E (D es futura)
        self.assertEqual(r["hechas"], 1)
        self.assertEqual(r["cumplimiento"], 25)
        self.assertEqual(r["vencida"], 1)            # B
        self.assertEqual(r["programada"], 2)         # C (esta semana) y D (futura)


if __name__ == "__main__":
    unittest.main()
