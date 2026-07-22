# Tests de ruteo de capas del motor según la clasificación OFICIAL
# ("CLASIFICACION GS.xlsx"): dispersión = GS0231/GS0232; TODO lo demás = VENTA.
# Las capas legacy (cargo envío por GS0248, back order por GS0229) quedan off
# por defecto y solo corren con su flag (CARGO_ENVIO_POR_SAP / BACKORDER_ENABLED).
import motor.evaluador as ev


# ── Happy path → R-000 (venta cliente, todo en orden) ─────────────
def test_happy_path_r000(run_eval):
    res = run_eval()
    assert res.codigo_motor == "R-000"
    assert res.estado == "AUTO_APROBADA"
    assert res.tipo_operacion == "VENTA_CLIENTE"


# ── Capa 1a — Dispersión interna (GS0231, solo GDL) ───────────────
def test_dispersion_ok_r800(run_eval, make_cp):
    # Tabla oficial 2026 (solo tórtón/cajas): ACT/TORTON/Jalisco = 17,207;
    # flete 18,000 ≤ 17,207*1.10 = 18,927.70 → R-800
    cp = make_cp(codigo_sap="GS0231", destino_estado="Jalisco",
                 tipo_vehiculo="TORTON", flete_mxn=18000.0)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-800"
    assert res.tipo_operacion == "DISPERSION_INTERNA"


def test_dispersion_excede_tarifa_r802(run_eval, make_cp):
    # 19,500 > tarifa+10% (18,927.70) aunque esté bajo el tope de $33,000.
    cp = make_cp(codigo_sap="GS0231", destino_estado="Jalisco",
                 tipo_vehiculo="TORTON", flete_mxn=19500.0)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-802"


def test_dispersion_sin_tarifa_dentro_del_tope_r800(run_eval, make_cp):
    # REGLA 2026-07-15 (120466326): sin tarifa de ruta pero DENTRO del tope
    # autorizado ($33,000 + IVA) → auto-aprobada (antes R-801 revisión).
    cp = make_cp(codigo_sap="GS0231", destino_estado="Yucatán",
                 tipo_vehiculo="PALLET", numero_pallets=1)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-800"


def test_dispersion_excede_tope_global_r802(run_eval, make_cp):
    # Por encima del tope de $33,000 MXN → revisión SIEMPRE (con o sin tarifa).
    cp = make_cp(codigo_sap="GS0231", destino_estado="Yucatán",
                 tipo_vehiculo="PALLET", numero_pallets=1, flete_mxn=34000.0)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-802"


def test_dispersion_fuera_de_gdl_r401d(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0231", origen_sucursal="CDMX")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-401-D"


# ── GS0232 — Dispersión EXPRESS también es dispersión ─────────────
def test_dispersion_express_gs0232(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0232", destino_estado="CDMX",
                 tipo_vehiculo="PALLET", numero_pallets=1, flete_mxn=1800.0)
    res = run_eval(cp=cp)
    assert res.tipo_operacion == "DISPERSION_INTERNA"
    assert res.codigo_motor == "R-800"


# ── Ruteo OFICIAL: GS0248 y GS0229 se evalúan como VENTA (C1–C5) ──
def test_gs0248_por_defecto_es_venta(run_eval, make_fv, make_cp):
    # Con la capa legacy apagada, GS0248 pasa por C1–C5 como cualquier venta.
    fv = make_fv(partidas=[], subtotal=10000.0, currency="MXN",
                 sku_id="00400000000000", descripcion="CARGO POR ENVIO")
    cp = make_cp(codigo_sap="GS0248", flete_mxn=10000.0)
    res = run_eval(fv=fv, cp=cp)
    assert res.tipo_operacion == "VENTA_CLIENTE"
    assert res.codigo_motor not in ("R-060", "R-061")


def test_gs0229_por_defecto_es_venta(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0229", destino_estado="Jalisco")
    res = run_eval(cp=cp)
    assert res.tipo_operacion == "VENTA_CLIENTE"
    assert res.codigo_motor != "R-050"


# ── Capas LEGACY conmutables (solo con su flag activo) ────────────
def test_cargo_envio_legacy_r060_con_flag(run_eval, make_fv, make_cp, monkeypatch):
    monkeypatch.setattr(ev, "CARGO_ENVIO_POR_SAP", True)
    fv = make_fv(partidas=[], subtotal=10000.0, currency="MXN",
                 sku_id="00400000000000", descripcion="CARGO POR ENVIO")
    cp = make_cp(codigo_sap="GS0248", flete_mxn=10000.0)
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-060"
    assert res.tipo_operacion == "CARGO_POR_ENVIO"


def test_cargo_envio_legacy_r061_con_flag(run_eval, make_fv, make_cp, monkeypatch):
    monkeypatch.setattr(ev, "CARGO_ENVIO_POR_SAP", True)
    fv = make_fv(partidas=[], subtotal=10000.0, currency="MXN",
                 sku_id="00400000000000", descripcion="CARGO POR ENVIO")
    cp = make_cp(codigo_sap="GS0248", flete_mxn=10500.0)  # delta 500 > 1% (100)
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-061"


def test_backorder_legacy_r050_con_flag(run_eval, make_cp, monkeypatch):
    monkeypatch.setattr(ev, "BACKORDER_ENABLED", True)
    cp = make_cp(codigo_sap="GS0229", destino_estado="Jalisco")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-050"
    assert res.tipo_operacion == "BACK_ORDER"


def test_backorder_legacy_r301_con_flag(run_eval, make_cp, monkeypatch):
    monkeypatch.setattr(ev, "BACKORDER_ENABLED", True)
    cp = make_cp(codigo_sap="GS0229", destino_estado="Oaxaca")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-301"


def test_backorder_legacy_r302_con_flag(run_eval, make_cp, monkeypatch):
    monkeypatch.setattr(ev, "BACKORDER_ENABLED", True)
    cp = make_cp(codigo_sap="GS0229", destino_estado="Chiapas",
                 destino_ciudad="San Cristóbal")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-302"


# ── Exenciones de monto (reglas GPA 2026-07-13) ───────────────────
def test_muestras_exentas_de_minimos_y_pct(run_eval, make_fv):
    # 119518759: FV de $0.07 USD, 7 renglones "MUESTRA ..." → ni R-101 ni
    # R-501/502; auto-aprobada si el resto de capas pasa.
    fv = make_fv(partidas=[], subtotal=0.07)
    fv.es_muestra = True
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-000"
    assert res.estado == "AUTO_APROBADA"
    assert any("MUESTRAS" in (c.valor or "") + (c.detalle or "") for c in res.criterios)


def test_gs0247_com_ped_validar_en_sistema(run_eval, make_fv, make_cp):
    # REGLA 2026-07-20 (refina la del 07-13): GS0247 sin mínimo de FV pero NO
    # auto-aprobada — código propio R-812 y a revisión para validar en sistema.
    fv = make_fv(partidas=[], subtotal=5.74)
    cp = make_cp(codigo_sap="GS0247", flete_mxn=143.0)
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-812"
    assert res.estado == "EN_REVISION"


def test_gs0245_requiere_autorizacion(run_eval, make_cp):
    # GS0245 nunca se auto-aprueba: revisión obligatoria (R-810).
    cp = make_cp(codigo_sap="GS0245")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-810"
    assert res.estado == "EN_REVISION"


def test_sin_exencion_r101_sigue_vivo(run_eval, make_fv):
    # La exención NO se cuela a casos normales: monto chico sin muestra → R-101.
    fv = make_fv(partidas=[], subtotal=100.0)
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-101"


def test_gs0242_dispersion_no_autorizada(run_eval, make_fv, make_cp):
    # GS0242 con monto chico daba R-101 "monto insuficiente" (confuso: no es
    # venta). Ahora concepto propio y revisión obligatoria (R-811).
    fv = make_fv(partidas=[], subtotal=50.0)
    cp = make_cp(codigo_sap="GS0242")
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-811"
    assert res.estado == "EN_REVISION"


# ── Reglas del reporte de comentarios (2026-07-14) ────────────────
def test_gs0248_exento_flete_lo_paga_cliente(run_eval, make_fv, make_cp):
    # 119696433: GS0248 = cargo por envío AL CLIENTE → sin mínimo de venta.
    fv = make_fv(partidas=[], subtotal=99.56)
    cp = make_cp(codigo_sap="GS0248")
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-000"


def test_sello_venta_manda_sobre_destinatario_gpa(run_eval, make_fv, make_cp):
    # 119687019: sello GS0230 (venta) pero destinatario GPA → caía a
    # R-401-D "dispersión desde no-GDL". El sello explícito manda: es VENTA.
    fv = make_fv(partidas=[], subtotal=552.24)
    cp = make_cp(codigo_sap="GS0230", destinatario_rfc="GPA8402219Y1",
                 origen_sucursal="CDMX", destino_estado="Tabasco")
    res = run_eval(fv=fv, cp=cp)
    assert res.tipo_operacion == "VENTA_CLIENTE"
    assert res.codigo_motor not in ("R-401-D", "R-800", "R-801", "R-802")


def test_sin_sello_destinatario_gpa_sigue_siendo_dispersion(run_eval, make_cp):
    # Sin sello legible, la heurística GPA→GPA sigue viva (119338784).
    cp = make_cp(codigo_sap="", destinatario_rfc="GPA8402219Y1",
                 destino_estado="CDMX", tipo_vehiculo="PALLET",
                 numero_pallets=1, flete_mxn=1800.0)
    res = run_eval(cp=cp)
    assert res.tipo_operacion == "DISPERSION_INTERNA"


def test_gs0229_validar_gs0244_exento(run_eval, make_fv, make_cp):
    # REGLA 2026-07-20: GS0229 (comp ped) → R-812 validar en sistema;
    # GS0244 (garantías) y GS0248 siguen exentos/automáticos.
    fv = make_fv(partidas=[], subtotal=10.67)
    res = run_eval(fv=fv, cp=make_cp(codigo_sap="GS0229"))
    assert res.codigo_motor == "R-812"
    fv2 = make_fv(partidas=[], subtotal=10.67)
    res2 = run_eval(fv=fv2, cp=make_cp(codigo_sap="GS0244"))
    assert res2.codigo_motor == "R-000"


def test_gs0246_sin_fv_no_es_r093_y_va_a_revision(run_eval, make_cp):
    # 120870151: "Garantías no es obligatorio la FV" — GS0246 sin factura no
    # es R-093; revisión con concepto propio (R-813).
    cp = make_cp(codigo_sap="GS0246")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-813"
    assert res.estado == "EN_REVISION"
