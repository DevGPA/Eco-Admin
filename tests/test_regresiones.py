# Regresiones — fija el comportamiento de los bugs corregidos en la auditoría.
import motor.evaluador as ev


# ── Bug: prefijo "GPA" secuestraba la operación hacia dispersión ──
def test_rfc_gpa_no_secuestra_a_dispersion(run_eval, make_cp):
    # Destinatario con RFC que empieza en GPA, operación normal desde CDMX.
    cp = make_cp(codigo_sap="GS0230", destinatario_rfc="GPA010101AAA",
                 origen_sucursal="CDMX", destino_estado="Jalisco")
    res = run_eval(cp=cp)
    assert res.tipo_operacion == "VENTA_CLIENTE"
    assert res.codigo_motor != "R-401-D"


def test_es_receptor_gpa_lista_vacia_por_defecto():
    # Sin RECEPTORES_INTERNOS_GPA configurados, ningún RFC dispara dispersión.
    assert ev._es_receptor_gpa("GPA999999999") is False


def test_receptor_interno_configurable_si_dispara(run_eval, make_cp, monkeypatch):
    # Si se configura el RFC como receptor interno, sí enruta a dispersión.
    monkeypatch.setattr(ev, "RECEPTORES_INTERNOS_GPA", {"GPA010101AAA"})
    assert ev._es_receptor_gpa("GPA010101AAA") is True
    cp = make_cp(codigo_sap="GS0230", destinatario_rfc="GPA010101AAA",
                 origen_sucursal="CDMX")   # dispersión fuera de GDL → R-401-D
    res = run_eval(cp=cp)
    assert res.codigo_motor == "R-401-D"
    assert res.tipo_operacion == "DISPERSION_INTERNA"


# ── Bug: división por cero cuando tipo de cambio = 0 ──────────────
def test_tipo_cambio_cero_no_crashea(run_eval, make_fv, make_cp):
    fv = make_fv(tc=0.0)
    cp = make_cp(tc=0.0)
    res = run_eval(fv=fv, cp=cp)            # no debe lanzar ZeroDivisionError
    assert res.codigo_motor.startswith("R-")


# ── Bug: criterio C3 duplicado en el caso borderline (R-302) ──────
def test_c3_no_duplicado_en_r302(run_eval, make_cp):
    cp = make_cp(destino_estado="Chiapas", destino_ciudad="San Cristóbal")
    res = run_eval(cp=cp)
    c3 = [c for c in res.criterios if c.criterio == "C3 Destino"]
    assert len(c3) == 1
