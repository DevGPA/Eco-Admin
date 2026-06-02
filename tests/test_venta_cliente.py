# Tests de la Capa 3 — venta cliente C1→C5 (motor/evaluador.py).
from conftest import SKU_EQUIPO, SKU_COSTAL


# ── C1 Monto ──────────────────────────────────────────────────────
def test_c1_monto_insuficiente_limpio_r101(run_eval, make_fv, make_partida):
    fv = make_fv(partidas=[make_partida(sku=SKU_EQUIPO, precio=300.0)])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-101"
    assert res.estado == "AUTO_RECHAZADA"


def test_c1_costal_sin_minimo_1000_r103(run_eval, make_fv, make_partida):
    fv = make_fv(partidas=[make_partida(sku=SKU_COSTAL, precio=500.0, peso=50.0)])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-103"


def test_c1_costal_equipo_insuficiente_r102(run_eval, make_fv, make_partida):
    # Costal por $1000 (pasa R-103) pero sin equipo elegible → R-102
    fv = make_fv(partidas=[make_partida(sku=SKU_COSTAL, precio=1000.0, peso=50.0)])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-102"


# Accesorio = producto restringido por tipo (<25 kg), p.ej. "PEGA VENECIANO".
def test_c1_accesorios_sin_minimo_r104(run_eval, make_fv, make_partida):
    fv = make_fv(partidas=[make_partida(descripcion="PEGA VENECIANO", precio=500.0, peso=2.0)])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-104"


def test_c1_accesorios_proporcion_baja_r105(run_eval, make_fv, make_partida):
    # monto 1000 (pasa R-104) pero elegible 40% < 50% → R-105
    fv = make_fv(partidas=[
        make_partida(descripcion="PEGA VENECIANO", precio=600.0, peso=2.0),  # restringido
        make_partida(descripcion="Reflector LED", precio=400.0, peso=2.0),    # elegible
    ])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-105"


# ── C2 Producto — documenta que C1 tiene precedencia ──────────────
def test_costal_sin_equipo_resuelve_en_c1_r102(run_eval, make_fv, make_partida):
    # Nota: R-201/R-202 (C2) son inalcanzables porque C1 atrapa antes el caso
    # "costal/accesorios sin elegible". Este test fija ese comportamiento real.
    fv = make_fv(partidas=[make_partida(sku=SKU_COSTAL, precio=2000.0, peso=50.0)])
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-102"   # equipo 0 < 500 (C1), no R-201


# ── C3 Destino ────────────────────────────────────────────────────
def test_c3_destino_no_cubierto_r301(run_eval, make_cp):
    res = run_eval(cp=make_cp(destino_estado="Oaxaca"))
    assert res.codigo_motor == "R-301"


# ── C4 Entrega / Sucursal / Fletera ──────────────────────────────
def test_c4a_no_domicilio_r401(run_eval, make_fv):
    fv = make_fv(campo_entrega="OCURRE")
    res = run_eval(fv=fv)
    assert res.codigo_motor == "R-401"


def test_c4b_sucursal_no_valida_r401s(run_eval, make_cp):
    res = run_eval(cp=make_cp(origen_sucursal="XYZ"))
    assert res.codigo_motor == "R-401-S"


def test_c4c_fletera_no_autorizada_r402(run_eval, make_cp):
    res = run_eval(cp=make_cp(transportista_rfc="NOAUTORIZADA999"))
    assert res.codigo_motor == "R-402"


# ── C5 Proporción de flete ────────────────────────────────────────
def test_c5_flete_alto_r501(run_eval, make_cp, flete_para_pct):
    cp = make_cp(flete_mxn=flete_para_pct(0.20))   # 20%
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-501"


def test_c5_flete_critico_r502(run_eval, make_cp, flete_para_pct):
    cp = make_cp(flete_mxn=flete_para_pct(0.40))   # 40%
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-502"


# ── C5 combinado con destino borderline (R-302) ──────────────────
def test_borderline_flete_bajo_r302(run_eval, make_cp, flete_para_pct):
    cp = make_cp(destino_estado="Chiapas", destino_ciudad="San Cristóbal",
                 flete_mxn=flete_para_pct(0.05))   # 5% ≤ 13%
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-302"


def test_borderline_flete_moderado_r602(run_eval, make_cp, flete_para_pct):
    cp = make_cp(destino_estado="Chiapas", destino_ciudad="San Cristóbal",
                 flete_mxn=flete_para_pct(0.14))   # 13% < 14% ≤ 15%
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-602"


def test_borderline_flete_alto_r601(run_eval, make_cp, flete_para_pct):
    cp = make_cp(destino_estado="Chiapas", destino_ciudad="San Cristóbal",
                 flete_mxn=flete_para_pct(0.20))   # > 15%
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-601"
