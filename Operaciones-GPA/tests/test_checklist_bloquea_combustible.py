# tests/test_checklist_bloquea_combustible.py
# Candado: una unidad de reparto con el checklist VENCIDO no puede solicitar
# combustible. Corre sin AWS (se sustituye la lectura de checklists).
#   python -m unittest tests.test_checklist_bloquea_combustible -v
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "tabla-de-prueba")

import db.modelos as m                       # noqa: E402
import db.queries as q                       # noqa: E402

# Unidades de ejemplo (mismas formas que trae el catálogo real)
REPARTO = {"id": "16", "economico": "16", "responsable": "LOGISTICA",
           "combustible": "Gasolina", "sucursal": "Guadalajara", "activo": True}
ELECTRICA = {"id": "85", "economico": "85", "responsable": "LOGISTICA",
             "combustible": "Electrico", "sucursal": "Guadalajara", "activo": True}
MONTACARGAS = {"id": "42", "economico": "42", "responsable": "ALMACEN",
               "combustible": "Gas LP", "sucursal": "Guadalajara", "activo": True}
INACTIVA = {"id": "99", "economico": "99", "responsable": "LOGISTICA",
            "combustible": "Diesel", "sucursal": "Cancun", "activo": False}


def cl(vid, tipo, fecha, status="Aprobado"):
    return {"vehicleId": vid, "tipo": tipo, "fecha": fecha + "T10:00:00-06:00", "status": status}


class Base(unittest.TestCase):
    """Sustituye la lectura de DynamoDB por una lista en memoria."""

    registros: list = []

    def setUp(self):
        self._orig = q._checklists_cl_en_rango
        q._checklists_cl_en_rango = lambda desde, hasta_excl: [
            r for r in self.registros if desde <= str(r["fecha"])[:10] < hasta_excl]

    def tearDown(self):
        q._checklists_cl_en_rango = self._orig

    def estados(self, vehiculos, hoy, registros=None, config=None):
        self.registros = registros if registros is not None else []
        return q.estados_checklist_reparto(vehiculos, config or {}, date.fromisoformat(hoy))


class TestLimiteSemanalEsLunes(Base):
    """Semana lunes→domingo; el límite es el LUNES."""

    # 2026-09-21 es lunes; 22 martes; 27 domingo.
    def test_el_lunes_todavia_no_vence(self):
        e = self.estados([REPARTO], "2026-09-21")["16"]
        self.assertEqual(e["semanal"], "pendiente")
        self.assertEqual(e["limiteSemanal"], "2026-09-21")

    def test_el_martes_ya_esta_vencido(self):
        self.assertEqual(self.estados([REPARTO], "2026-09-22")["16"]["semanal"], "vencido")

    def test_el_domingo_sigue_vencido(self):
        self.assertEqual(self.estados([REPARTO], "2026-09-27")["16"]["semanal"], "vencido")

    def test_capturado_el_lunes_cumple_toda_la_semana(self):
        regs = [cl("16", "semanal", "2026-09-21")]
        for dia in ("2026-09-21", "2026-09-23", "2026-09-27"):
            self.assertEqual(self.estados([REPARTO], dia, regs)["16"]["semanal"], "cumplido", dia)

    def test_capturado_tarde_tambien_cumple(self):
        # Se hizo el miércoles: cuenta para la semana, deja de bloquear.
        regs = [cl("16", "semanal", "2026-09-23")]
        self.assertEqual(self.estados([REPARTO], "2026-09-23", regs)["16"]["semanal"], "cumplido")

    def test_el_de_la_semana_pasada_no_sirve(self):
        regs = [cl("16", "semanal", "2026-09-16")]      # semana anterior
        self.assertEqual(self.estados([REPARTO], "2026-09-22", regs)["16"]["semanal"], "vencido")

    def test_semana_que_cruza_de_mes(self):
        # Semana del lun 2026-08-31 al dom 2026-09-06: el registro es de agosto
        # y hoy es septiembre; debe encontrarlo igual.
        regs = [cl("16", "semanal", "2026-08-31")]
        self.assertEqual(self.estados([REPARTO], "2026-09-02", regs)["16"]["semanal"], "cumplido")


class TestLimiteMensualEsDia5(Base):
    def test_antes_del_dia_5_no_vence(self):
        # 2026-10-05 es lunes → el límite es ese mismo día.
        e = self.estados([REPARTO], "2026-10-04")["16"]
        self.assertEqual(e["mensual"], "pendiente")
        self.assertEqual(e["limiteMensual"], "2026-10-05")

    def test_el_dia_5_todavia_no_vence(self):
        self.assertEqual(self.estados([REPARTO], "2026-10-05")["16"]["mensual"], "pendiente")

    def test_el_dia_6_ya_esta_vencido(self):
        self.assertEqual(self.estados([REPARTO], "2026-10-06")["16"]["mensual"], "vencido")

    def test_si_el_5_cae_sabado_se_recorre_al_habil(self):
        # 2026-09-05 es sábado → el límite pasa al lunes 7.
        e = self.estados([REPARTO], "2026-09-06")["16"]
        self.assertEqual(e["limiteMensual"], "2026-09-07")
        self.assertEqual(e["mensual"], "pendiente")      # domingo 6: aún en plazo
        self.assertEqual(self.estados([REPARTO], "2026-09-08")["16"]["mensual"], "vencido")

    def test_capturado_en_el_mes_cumple(self):
        regs = [cl("16", "mensual", "2026-09-03")]
        self.assertEqual(self.estados([REPARTO], "2026-09-20", regs)["16"]["mensual"], "cumplido")

    def test_el_del_mes_pasado_no_sirve(self):
        regs = [cl("16", "mensual", "2026-08-03")]
        self.assertEqual(self.estados([REPARTO], "2026-09-20", regs)["16"]["mensual"], "vencido")


class TestQueUnidadesAplica(Base):
    def test_montacargas_nunca_entra(self):
        est = self.estados([REPARTO, MONTACARGAS], "2026-09-22")
        self.assertIn("16", est)
        self.assertNotIn("42", est, "un montacargas no lleva checklist de reparto")

    def test_electrica_de_reparto_si_entra(self):
        self.assertIn("85", self.estados([ELECTRICA], "2026-09-22"))

    def test_unidad_inactiva_no_entra(self):
        self.assertNotIn("99", self.estados([INACTIVA], "2026-09-22"))

    def test_categoria_explicita_manda(self):
        v = dict(MONTACARGAS, categoria="reparto")
        self.assertIn("42", self.estados([v], "2026-09-22"))


class TestRegistrosQueNoCuentan(Base):
    def test_anulado_no_cumple(self):
        regs = [cl("16", "semanal", "2026-09-21", status="Anulado")]
        self.assertEqual(self.estados([REPARTO], "2026-09-22", regs)["16"]["semanal"], "vencido")

    def test_rechazado_no_cumple(self):
        regs = [cl("16", "semanal", "2026-09-21", status="Rechazado")]
        self.assertEqual(self.estados([REPARTO], "2026-09-22", regs)["16"]["semanal"], "vencido")

    def test_de_otra_unidad_no_cumple(self):
        regs = [cl("77", "semanal", "2026-09-21")]
        self.assertEqual(self.estados([REPARTO], "2026-09-22", regs)["16"]["semanal"], "vencido")

    def test_el_mensual_no_tapa_al_semanal(self):
        regs = [cl("16", "mensual", "2026-09-21")]
        e = self.estados([REPARTO], "2026-09-22", regs)["16"]
        self.assertEqual(e["mensual"], "cumplido")
        self.assertEqual(e["semanal"], "vencido")


class TestArranqueGoLive(Base):
    def test_no_se_reclama_lo_anterior_al_arranque(self):
        cfg = {"fechaInicio": "2026-09-23"}
        # El límite de la semana (lun 21) es anterior al arranque → no se exige.
        e = self.estados([REPARTO], "2026-09-24", [], cfg)["16"]
        self.assertNotEqual(e["semanal"], "vencido")

    def test_despues_del_arranque_si_se_reclama(self):
        cfg = {"fechaInicio": "2026-09-01"}
        self.assertEqual(self.estados([REPARTO], "2026-09-22", [], cfg)["16"]["semanal"], "vencido")


class TestMensajeDelCandado(Base):
    """El texto que ve el operador debe decirle QUÉ falta y DÓNDE hacerlo."""

    def _msg(self, hoy, registros=(), veh=REPARTO):
        import handler
        self.registros = list(registros)
        orig_veh, orig_cfg = handler.get_vehiculo, handler.cargar_config
        handler.get_vehiculo = lambda vid: veh if str(vid) == str(veh["id"]) else None
        handler.cargar_config = lambda: {}
        orig_hoy = m.hoy_mx
        m.hoy_mx = lambda: date.fromisoformat(hoy)
        try:
            return handler._validar_checklist_al_dia(
                m.SOL, {"vehicleId": veh["id"], "km": 1000})
        finally:
            handler.get_vehiculo, handler.cargar_config = orig_veh, orig_cfg
            m.hoy_mx = orig_hoy

    def test_bloquea_y_explica(self):
        msg = self._msg("2026-09-22")
        self.assertIsNotNone(msg)
        self.assertIn("#16", msg)
        self.assertIn("SEMANAL", msg)
        self.assertIn("Mtto", msg)

    def test_no_bloquea_si_esta_al_dia(self):
        self.assertIsNone(self._msg("2026-09-22", [cl("16", "semanal", "2026-09-21"),
                                                   cl("16", "mensual", "2026-09-02")]))

    def test_no_bloquea_al_montacargas(self):
        self.assertIsNone(self._msg("2026-09-22", [], veh=MONTACARGAS))

    def test_el_reporte_de_carga_no_se_bloquea(self):
        import handler
        self.assertIsNone(handler._validar_checklist_al_dia(
            m.SOL, {"vehicleId": "16", "formato": "reporte"}))

    def test_checklist_y_montacargas_no_se_bloquean(self):
        import handler
        for tipo in (m.CL, m.MC):
            self.assertIsNone(handler._validar_checklist_al_dia(tipo, {"vehicleId": "16"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
