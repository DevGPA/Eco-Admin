# Tests de ruteo de capas del motor: dispersión (1a), cargo envío (1b),
# back order (2) y detección de tipo de operación.


# ── Happy path → R-000 (venta cliente, todo en orden) ─────────────
def test_happy_path_r000(run_eval):
    res = run_eval()
    assert res.codigo_motor == "R-000"
    assert res.estado == "AUTO_APROBADA"
    assert res.tipo_operacion == "VENTA_CLIENTE"


# ── Capa 1a — Dispersión interna (GS0231, solo GDL) ───────────────
def test_dispersion_ok_r800(run_eval, make_cp):
    # ACT/PALLET/CDMX = tarifa 1901; flete 1800 ≤ 1901*1.10 → R-800
    cp = make_cp(codigo_sap="GS0231", destino_estado="CDMX",
                 tipo_vehiculo="PALLET", numero_pallets=1, flete_mxn=1800.0)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-800"
    assert res.tipo_operacion == "DISPERSION_INTERNA"


def test_dispersion_excede_tarifa_r802(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0231", destino_estado="CDMX",
                 tipo_vehiculo="PALLET", numero_pallets=1, flete_mxn=2500.0)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-802"


def test_dispersion_sin_tarifa_r801(run_eval, make_cp):
    # ACT no tiene tarifa PALLET para "Yucatán" → R-801
    cp = make_cp(codigo_sap="GS0231", destino_estado="Yucatán",
                 tipo_vehiculo="PALLET", numero_pallets=1)
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-801"


def test_dispersion_fuera_de_gdl_r401d(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0231", origen_sucursal="CDMX")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-401-D"


# ── Capa 1b — Cargo por envío (GS0248) ────────────────────────────
def test_cargo_envio_dentro_tolerancia_r060(run_eval, make_fv, make_cp):
    fv = make_fv(partidas=[], subtotal=10000.0, currency="MXN",
                 sku_id="00400000000000", descripcion="CARGO POR ENVIO")
    cp = make_cp(codigo_sap="GS0248", flete_mxn=10000.0)
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-060"
    assert res.tipo_operacion == "CARGO_POR_ENVIO"


def test_cargo_envio_fuera_tolerancia_r061(run_eval, make_fv, make_cp):
    fv = make_fv(partidas=[], subtotal=10000.0, currency="MXN",
                 sku_id="00400000000000", descripcion="CARGO POR ENVIO")
    cp = make_cp(codigo_sap="GS0248", flete_mxn=10500.0)  # delta 500 > 1% (100)
    res = run_eval(fv=fv, cp=cp)
    assert res.codigo_motor == "R-061"


# ── Capa 2 — Back order (GS0229) ──────────────────────────────────
def test_backorder_destino_ok_r050(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0229", destino_estado="Jalisco")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-050"
    assert res.tipo_operacion == "BACK_ORDER"


def test_backorder_destino_no_cubierto_r301(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0229", destino_estado="Oaxaca")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-301"


def test_backorder_destino_borderline_r302(run_eval, make_cp):
    cp = make_cp(codigo_sap="GS0229", destino_estado="Chiapas",
                 destino_ciudad="San Cristóbal")
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-302"
