# Tests de s3/ocr_extractor.py — clasificación por RFC y armado de caso.
# No requieren AWS/Bedrock ni PyMuPDF (se prueba la lógica pura con páginas mock).
import pytest

import json

import s3.ocr_extractor as ocr
from s3.ocr_extractor import (
    clasificar_por_rfc, clasificar_pagina, armar_caso, _parse_json,
    emparejar_casos, _folios_referenciados, _fv_coincide,
    caso_a_solicitud, _query_ascii, TEXTRACT_QUERIES,
    _parse_textract, _norm_rfc, _tipo_documento, _lineas_texto,
)
from motor.catalogos import RFC_GPA

CARRIER = "ACT680806665A"
CLIENTE = "PEA230227FL6"


def pag(emisor=None, receptor=None, subtotal=None, moneda=None, tc=None, folio=None):
    return {"rfcEmisor": emisor, "rfcReceptor": receptor, "subtotal": subtotal,
            "moneda": moneda, "tipoCambio": tc, "folio": folio}


def cp(subtotal, folio="116162584"):
    # Carta porte: la emite la fletera, GPA es receptor
    return pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=subtotal, moneda="MXN", folio=folio)


def fv(subtotal, folio="FA10314168", tc=17.77):
    # Factura de venta: la emite GPA
    return pag(emisor=RFC_GPA, receptor=CLIENTE, subtotal=subtotal, moneda="USD", tc=tc, folio=folio)


# ── Queries de Textract: deben ser ASCII ──────────────────────────
# Textract Queries rechaza acentos y '¿' con InvalidParameterException, lo que
# rompe el OCR de TODO documento. Este invariante evita la regresión.
def test_query_ascii_pliega_acentos_y_signos():
    assert _query_ascii("¿Cuál es la fecha de emisión?") == "Cual es la fecha de emision?"


def test_todas_las_queries_textract_son_ascii():
    for alias, texto in TEXTRACT_QUERIES:
        enviado = _query_ascii(texto)
        assert enviado.isascii() and enviado, f"Query '{alias}' no es ASCII válido: {enviado!r}"


# ── clasificar_por_rfc ────────────────────────────────────────────
def test_gpa_emisor_es_fv():
    assert clasificar_por_rfc(RFC_GPA, CLIENTE) == "FV"


def test_gpa_receptor_es_cp():
    assert clasificar_por_rfc(CARRIER, RFC_GPA) == "CP"


def test_gpa_en_ninguno_es_error():
    assert clasificar_por_rfc(CARRIER, CLIENTE) == "ERROR"


def test_clasificacion_ignora_mayusculas_y_espacios():
    assert clasificar_por_rfc("  gpa8402219y1  ", CLIENTE) == "FV"


def test_clasificacion_ambos_none_es_error():
    assert clasificar_por_rfc(None, None) == "ERROR"


# ── Parseo robusto desde texto crudo (refuerzo de las Queries) ────
import itertools
_idseq = itertools.count(1)


def _line(text, top=0.0, left=0.0):
    return {"Id": f"l-{next(_idseq)}", "BlockType": "LINE", "Text": text,
            "Geometry": {"BoundingBox": {"Top": top, "Left": left}}}


def _query(alias, answer):
    """Bloque QUERY + su ANSWER (lo que devuelven las Queries de Textract)."""
    qid, aid = f"q-{alias}", f"a-{alias}"
    blocks = [{"Id": qid, "BlockType": "QUERY", "Query": {"Alias": alias},
               "Relationships": [{"Type": "ANSWER", "Ids": [aid]}]}]
    blocks.append({"Id": aid, "BlockType": "QUERY_RESULT", "Text": answer})
    return blocks


def _resp(lines, queries=None):
    blocks = list(lines)
    for alias, ans in (queries or {}).items():
        blocks += _query(alias, ans)
    return {"Blocks": blocks}


def test_norm_rfc_valida_y_rechaza():
    assert _norm_rfc("gpa8402219y1") == "GPA8402219Y1"   # moral, 12
    assert _norm_rfc("XAXX010101000") == "XAXX010101000"  # física, 13
    assert _norm_rfc("TRES GUERRAS") is None              # nombre, no RFC
    assert _norm_rfc("Origen") is None
    assert _norm_rfc(None) is None


def test_rfc_con_separadores_se_normaliza():
    # Las facturas de GPA imprimen el RFC con guiones; debe reconocerse igual.
    assert _norm_rfc("GPA-840221-9Y1") == "GPA8402219Y1"
    assert _norm_rfc("R.F.C. GPA-840221-9Y1") is None  # con prefijo no es fullmatch
    # En el texto crudo (línea "R.F.C. GPA-840221-9Y1 ...") sí debe extraerlo:
    lineas = [{"text": "R.F.C. GPA-840221-9Y1 REG. EDO 62305", "top": 0.15, "left": 0.1}]
    rfcs = [r["rfc"] for r in ocr._rfcs_en_lineas(lineas)]
    assert "GPA8402219Y1" in rfcs


def test_tipo_documento_por_palabras_clave():
    assert _tipo_documento([{"text": "Complemento Carta Porte", "top": 0, "left": 0}]) == "CP"
    assert _tipo_documento([{"text": "CFDI de Ingreso", "top": 0, "left": 0}]) == "FV"
    assert _tipo_documento([{"text": "Documento cualquiera", "top": 0, "left": 0}]) is None


def test_parse_repara_rfc_basura_de_query_con_texto_crudo():
    # La Query devuelve basura (nombre/etiqueta), pero el RFC está en el texto.
    resp = _resp(
        lines=[
            _line("CARTA PORTE - Traslado", top=0.02),
            _line("Emisor", top=0.10), _line("RFC: TGU920101AB1", top=0.12),
            _line("Receptor", top=0.20), _line("RFC: GPA8402219Y1", top=0.22),
            _line("Folio Fiscal: EAB78FF3-1013-4CA2-BD30-95F44BCC0DDB", top=0.30),
            _line("Folio: 118295254", top=0.33),
            _line("Sub-Total: $5,000.00 MXN", top=0.40),
        ],
        queries={"rfcEmisor": "TRES GUERRAS", "rfcReceptor": "Origen",
                 "folio": "EAB78FF3-1013-4CA2-BD30-95F44BCC0DDB", "subtotal": "41.47"},
    )
    p = _parse_textract(resp)
    assert p["rfcEmisor"] == "TGU920101AB1"      # reparado desde el texto
    assert p["rfcReceptor"] == "GPA8402219Y1"    # GPA como receptor (CP)
    assert p["tipoDoc"] == "CP"
    assert p["folio"] == "118295254"             # NO el UUID
    assert p["subtotal"] == 5000.0               # etiqueta Sub-Total, no la línea suelta
    assert clasificar_pagina(p) == "CP"
    assert p["fletaRFC"] == "TGU920101AB1"       # la fletera (emisor del CP)


def test_parse_factura_gpa_emisor_es_fv():
    resp = _resp(
        lines=[
            _line("Factura - CFDI de Ingreso", top=0.02),
            _line("Emisor RFC GPA8402219Y1", top=0.10),
            _line("Receptor RFC TGU920101AB1", top=0.20),
            _line("Sub-Total 1,200.00 USD", top=0.40),
        ],
        queries={"rfcEmisor": "GPA", "rfcReceptor": "CLIENTE", "subtotal": "1200.00"},
    )
    p = _parse_textract(resp)
    assert p["rfcEmisor"] == "GPA8402219Y1"
    assert p["tipoDoc"] == "FV"
    assert clasificar_pagina(p) == "FV"


def test_clasificar_pagina_fallback_por_tipo_cuando_roles_ambiguos():
    # GPA aparece en el texto pero no se pudo fijar emisor/receptor.
    p = {"rfcEmisor": None, "rfcReceptor": None,
         "rfcsDetectados": ["GPA8402219Y1"], "tipoDoc": "CP"}
    assert clasificar_pagina(p) == "CP"
    # Sin GPA en el documento → ajena.
    p2 = {"rfcEmisor": None, "rfcReceptor": None,
          "rfcsDetectados": ["TGU920101AB1"], "tipoDoc": "CP"}
    assert clasificar_pagina(p2) == "ERROR"


# ── Consolidación de factura multipágina ──────────────────────────
def test_factura_multipagina_no_duplica_subtotal():
    # 1 carta porte + factura de 2 páginas que REPITEN el mismo subtotal.
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=1500, moneda="MXN", folio="CP1")
    fv_p1 = fv(subtotal=1200, folio="F-555", tc=17.5)
    fv_p2 = fv(subtotal=1200, folio="F-555", tc=17.5)   # misma factura, repite subtotal
    res = emparejar_casos([cp_pag, fv_p1, fv_p2], folio_archivo="ARCH")
    assert res["totalFV"] == 2 and res["totalFacturas"] == 1   # 2 páginas → 1 factura
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["montoVentaFV"] == 1200      # NO 2400 (no se duplica)


def test_facturas_sin_folio_subtotales_distintos_son_facturas_distintas():
    # REGLA CORREGIDA con el caso real M846228: una factura multipágina REPITE
    # su subtotal; páginas sin folio con subtotales DISTINTOS son facturas
    # DISTINTAS y se SUMAN (antes se tomaba solo el mayor → %flete inflado).
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=900, moneda="MXN", folio="CP2")
    fv_p1 = fv(subtotal=300, folio=None, tc=17.5)
    fv_p2 = fv(subtotal=950, folio=None, tc=17.5)
    res = emparejar_casos([cp_pag, fv_p1, fv_p2], folio_archivo="ARCH2")
    assert res["totalFacturas"] == 2
    assert res["casos"][0]["montoVentaFV"] == 1250   # 300 + 950


def test_un_cp_con_varias_facturas_distintas_suma_subtotales():
    # 1 carta porte + 2 facturas DISTINTAS (folios distintos) sin enlace en los
    # Comentarios → todas son del CP y se SUMAN sus subtotales (no el mayor).
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=900, moneda="MXN", folio="CP3")
    fv_a = fv(subtotal=1000, folio="F-100", tc=17.5)
    fv_b = fv(subtotal=500,  folio="F-200", tc=17.5)
    res = emparejar_casos([cp_pag, fv_a, fv_b], folio_archivo="ARCH3")
    assert res["totalFacturas"] == 2                 # 2 folios → 2 facturas
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["montoVentaFV"] == 1500              # 1000 + 500 (suma), no 1000
    assert set(caso["foliosFV"]) == {"F-100", "F-200"}


# ── armar_caso ────────────────────────────────────────────────────
def test_caso_cp_mas_fv_ok():
    res = armar_caso([cp(132.00), fv(4.41)], folio_archivo="116162584")
    assert res["status"] == "OK"
    assert res["fleteSinIvaMXN"] == pytest.approx(132.00)
    assert res["montoVentaFV"] == pytest.approx(4.41)
    assert res["monedaFV"] == "USD"
    assert res["tipoCambioRef"] == pytest.approx(17.77)
    assert res["foliosFV"] == ["FA10314168"]


def test_caso_suma_varias_fv():
    res = armar_caso([cp(200.0), fv(4.41, folio="FA1"), fv(5.59, folio="FA2")])
    assert res["status"] == "OK"
    assert res["montoVentaFV"] == pytest.approx(10.00)
    assert res["paginasFV"] == 2
    assert res["foliosFV"] == ["FA1", "FA2"]


def test_caso_suma_varios_cp_para_flete():
    res = armar_caso([cp(100.0), cp(32.0), fv(4.41)])
    assert res["fleteSinIvaMXN"] == pytest.approx(132.0)
    assert res["paginasCP"] == 2


def test_caso_sin_cp_es_error():
    res = armar_caso([fv(4.41)])
    assert res["status"] == "ERROR"
    assert res["error"] == "SIN_CARTA_PORTE"


def test_caso_sin_fv_es_error():
    res = armar_caso([cp(132.0)])
    assert res["status"] == "ERROR"
    assert res["error"] == "SIN_FACTURA_GPA"


def test_caso_cuenta_paginas_ajenas():
    ajena = pag(emisor=CARRIER, receptor=CLIENTE, subtotal=999)  # GPA no aparece
    res = armar_caso([cp(132.0), fv(4.41), ajena])
    assert res["status"] == "OK"
    assert res["paginasError"] == 1
    # la página ajena no contamina los montos
    assert res["fleteSinIvaMXN"] == pytest.approx(132.0)
    assert res["montoVentaFV"] == pytest.approx(4.41)


def test_caso_vacio_es_error():
    res = armar_caso([])
    assert res["status"] == "ERROR"


# ── _parse_json ───────────────────────────────────────────────────
def test_parse_json_extrae_objeto_con_prosa():
    txt = 'Claro, aquí está:\n{"rfcEmisor": "GPA8402219Y1", "subtotal": 4.41}\nEspero ayude.'
    d = _parse_json(txt)
    assert d["rfcEmisor"] == "GPA8402219Y1"
    assert d["subtotal"] == 4.41


def test_parse_json_sin_json_lanza():
    with pytest.raises(ValueError):
        _parse_json("no hay json aquí")


# ── Emparejamiento multi-caso (varios CP/FV en un PDF) ────────────
HORMIK = "TCH170824TH2"


def cp_doc(folio, subtotal, ref_fv, destino="Guerrero"):
    return {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": folio,
            "subtotal": subtotal, "moneda": "MXN", "fletaRFC": HORMIK,
            "comentarios": f"F-{ref_fv}/ COBRO AL REGRESO/ DOMICILIO",
            "destinoEstado": destino, "destinoCiudad": "Acapulco", "partidas": []}


def fv_doc(folio, subtotal, partidas=None):
    return {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": folio,
            "subtotal": subtotal, "moneda": "USD", "tipoCambio": 17.55,
            "partidas": partidas or [{"claveSat": "49241712", "descripcion": "TRICLORO",
                                      "cantidad": 1, "importe": subtotal}]}


def test_folios_referenciados():
    assert _folios_referenciados("F-40086093/ COBRO AL REGRESO") == ["40086093"]
    assert _folios_referenciados("F 40086102 y F-40086200") == ["40086102", "40086200"]
    assert _folios_referenciados(None) == []


def test_fv_coincide_por_digitos():
    assert _fv_coincide("FM40086093", ["40086093"]) is True
    assert _fv_coincide("FM40086093", ["99999999"]) is False
    assert _fv_coincide(None, ["40086093"]) is False


def test_emparejar_dos_casos_reales():
    # Bundle real FAC4927-FAC4935: 2 CP + 2 FV, cada CP referencia su FV.
    paginas = [
        cp_doc("FAC04927", 3330.00, "40086093"),
        fv_doc("FM40086093", 3852.25),
        cp_doc("FAC04935", 390.00, "40086102"),
        fv_doc("FM40086102", 15.55),
    ]
    res = emparejar_casos(paginas, folio_archivo="FAC4927-FAC4935")
    assert res["totalCP"] == 2 and res["totalFV"] == 2
    assert len(res["casos"]) == 2
    c1, c2 = res["casos"]
    assert c1["status"] == "OK" and c1["folioCP"] == "FAC04927"
    assert c1["foliosFV"] == ["FM40086093"]
    assert c1["fleteSinIvaMXN"] == pytest.approx(3330.00)
    assert c1["montoVentaFV"] == pytest.approx(3852.25)
    assert c2["foliosFV"] == ["FM40086102"]
    assert res["fvsSinCP"] == []


def test_emparejar_cp_sin_fv_es_error():
    # 2 CP (no aplica el fallback 1-1): el primero no enlaza con ninguna FV.
    paginas = [
        cp_doc("FAC04927", 3330.00, "99999999"),   # ref inexistente → sin FV
        cp_doc("FAC04935", 390.00, "40086093"),     # enlaza con la FV
        fv_doc("FM40086093", 100.0),
    ]
    res = emparejar_casos(paginas)
    assert res["casos"][0]["status"] == "ERROR"
    assert res["casos"][0]["error"] == "SIN_FV_VINCULADA"
    assert res["casos"][1]["status"] == "OK"


def test_emparejar_suma_varias_fv_a_un_cp():
    cp = cp_doc("FAC04927", 3330.00, "40086093")
    cp["comentarios"] = "F-40086093 y F-40086200"   # dos FV para un CP
    paginas = [cp, fv_doc("FM40086093", 3000.0), fv_doc("FM40086200", 852.25)]
    res = emparejar_casos(paginas)
    caso = res["casos"][0]
    assert caso["montoVentaFV"] == pytest.approx(3852.25)
    assert caso["foliosFV"] == ["FM40086093", "FM40086200"]


# ── OCR backend: Amazon Textract (por defecto) ───────────────────
def _textract_resp(queries: dict, tabla=None) -> dict:
    """Construye una respuesta sintética de Textract (QUERIES + opcional TABLA)."""
    blocks, c = [], [0]
    def nid():
        c[0] += 1
        return f"b{c[0]}"
    for alias, answer in queries.items():
        qid, aid = nid(), nid()
        blocks.append({"BlockType": "QUERY", "Id": qid, "Query": {"Alias": alias, "Text": alias},
                       "Relationships": [{"Type": "ANSWER", "Ids": [aid]}]})
        blocks.append({"BlockType": "QUERY_RESULT", "Id": aid, "Text": answer})
    if tabla:
        cells, cell_ids = [], []
        for ri, row in enumerate(tabla, start=1):
            for ci, txt in enumerate(row, start=1):
                wid, cid = nid(), nid()
                blocks.append({"BlockType": "WORD", "Id": wid, "Text": txt})
                cells.append({"BlockType": "CELL", "Id": cid, "RowIndex": ri, "ColumnIndex": ci,
                              "Relationships": [{"Type": "CHILD", "Ids": [wid]}]})
                cell_ids.append(cid)
        tid = nid()
        blocks.append({"BlockType": "TABLE", "Id": tid,
                       "Relationships": [{"Type": "CHILD", "Ids": cell_ids}]})
        blocks.extend(cells)
    return {"Blocks": blocks}


class FakeTextract:
    def __init__(self, resp):
        self.resp, self.kw = resp, None
    def analyze_document(self, **kw):
        self.kw = kw
        return self.resp


def test_parse_textract_cp_con_tabla():
    resp = _textract_resp(
        {"rfcEmisor": "TCH170824TH2", "rfcReceptor": RFC_GPA, "subtotal": "$3,330.00",
         "moneda": "MXN", "folio": "FAC04927", "comentarios": "F-40086093",
         "origenCiudad": "Iztapalapa", "destinoEstado": "Guerrero"},
        tabla=[["Descripcion", "Cantidad", "Importe"],
               ["TRICLORO 50 KGS", "40", "3653.20"],
               ["CUERPO T", "2", "16.39"]],
    )
    p = ocr._parse_textract(resp)
    assert p["rfcEmisor"] == "TCH170824TH2"
    assert clasificar_por_rfc(p["rfcEmisor"], p["rfcReceptor"]) == "CP"
    assert p["subtotal"] == pytest.approx(3330.00)   # "$3,330.00" parseado
    assert p["folio"] == "FAC04927"
    assert p["fletaRFC"] == "TCH170824TH2"
    assert len(p["partidas"]) == 2
    assert p["partidas"][0]["descripcion"] == "TRICLORO 50 KGS"
    assert p["partidas"][0]["importe"] == pytest.approx(3653.20)


def test_ocr_textract_envia_queries_y_documento():
    fake = FakeTextract(_textract_resp({"rfcEmisor": RFC_GPA, "subtotal": "100"}))
    p = ocr._ocr_textract(b"png-bytes", client=fake)
    assert p["rfcEmisor"] == RFC_GPA
    assert fake.kw["FeatureTypes"] == ["QUERIES", "TABLES"]
    assert fake.kw["Document"] == {"Bytes": b"png-bytes"}


# ── OCR backend: Bedrock (Claude) ─────────────────────────────────
class FakeBedrock:
    def __init__(self, *respuestas):
        self._r, self._i = list(respuestas), 0
    def converse(self, **kwargs):
        out = self._r[self._i]; self._i += 1
        return {"output": {"message": {"content": [{"text": json.dumps(out)}]}}}


def test_ocr_bedrock_parsea_json():
    fake = FakeBedrock({"rfcEmisor": RFC_GPA, "subtotal": 4.41})
    d = ocr._ocr_bedrock(b"png", client=fake)
    assert d["rfcEmisor"] == RFC_GPA and d["subtotal"] == 4.41


def test_adaptar_bedrock_cumple_contrato_de_pagina():
    # El JSON crudo del modelo debe mapearse al MISMO contrato que _parse_textract:
    # tipoDoc CP/FV, RFCs normalizados, rfcsDetectados, señales y sello validado.
    raw = {
        "rfcEmisor": "UER-230428-II0", "rfcReceptor": "GPA-840221-9Y1",
        "tipoDocumento": "CARTA_PORTE", "subtotal": "1,462.96", "moneda": "mxn",
        "tipoCambio": None, "folio": "3fde084e-5e98-4c07-a8b1-5343fc0d5bdc",
        "fecha": "2026-06-08", "comentarios": None,
        "origenEstado": "Jalisco", "origenCiudad": "Guadalajara",
        "destinoEstado": "Nuevo León", "destinoCiudad": "Monterrey",
        "fletaRFC": "XXXX999999XX9", "fleteraNombre": "TRES GUERRAS",
        "esNotaCredito": False, "esPreguia": True, "destinatarioGPA": True,
        "codigoSAP": "codigo GS0231 ok", "sucursalSello": "Monterrey",
        "tipoFleteSello": "DISP. SEMANAL",
        "partidas": [{"descripcion": "Bomba", "cantidad": "2", "importe": "1,000.00"}],
    }
    p = ocr._adaptar_bedrock(raw)
    assert p["tipoDoc"] == "CP"
    assert p["rfcReceptor"] == "GPA8402219Y1"          # normalizado sin guiones
    assert "UER230428II0" in p["rfcsDetectados"]
    assert p["folio"] is None                          # UUID fiscal descartado
    assert p["subtotal"] == 1462.96 and p["moneda"] == "MXN"
    assert p["fletaRFC"] == ""                         # RFC inventado NO autorizado
    assert p["fleteraTexto"] != ""                     # razón social sí resolvió
    assert p["esPreguia"] is True and p["destinatarioGPA"] is True
    assert p["codigoSAP"] == "GS0231"                  # extraído y validado GS0xxx
    assert p["partidas"][0]["importe"] == 1000.0


def test_rfc_gpa_deformado_por_ocr_se_repara():
    # Caso real M845517 pág. 2 (log de prod): el modelo leyó "GPA940221471"
    # en vez de GPA8402219Y1 → la página caía a 'ajena' y el caso a R-093.
    # Un RFC con prefijo GPA en estos documentos ES GPA.
    p = ocr._adaptar_bedrock({
        "rfcEmisor": "GPA940221471", "rfcReceptor": None,
        "tipoDocumento": "FACTURA", "subtotal": 450.66, "moneda": "USD",
        "tipoCambio": 17.39, "folio": "FMTY 70088673",
    })
    assert p["rfcEmisor"] == RFC_GPA
    assert clasificar_pagina(p) == "FV"
    # E2E: la CP de Estrella (texto) + esta FV (OCR) arman el caso completo.
    cp_pag = pag(emisor="TEE070612ITA", receptor=RFC_GPA, subtotal=300.0,
                 moneda="MXN", folio="M845517")
    res = emparejar_casos([cp_pag, p], "M845517")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["foliosFV"] == ["FMTY 70088673"]
    assert caso["montoVentaFV"] == 450.66
    # Y un RFC ajeno NO se toca.
    assert ocr._rfc_gpa_tolerante("TEE070612ITA") == "TEE070612ITA"


def test_adaptar_bedrock_codigo_sap_invalido_se_descarta():
    p = ocr._adaptar_bedrock({"tipoDocumento": "FACTURA", "codigoSAP": "GSXX31"})
    assert p["codigoSAP"] == "" and p["tipoDoc"] == "FV"


def test_adaptar_bedrock_rol_rfc_manda_sobre_titulo():
    # Caso real M845517 (Estrella): el documento se TITULA "Factura" pero la
    # fletera emite y GPA es el receptor/pagador → es CARTA PORTE. El rol del
    # RFC manda sobre el tipoDocumento que reporte el modelo.
    p = ocr._adaptar_bedrock({
        "rfcEmisor": "TEE070612ITA", "rfcReceptor": RFC_GPA,
        "tipoDocumento": "FACTURA", "subtotal": 300.0,
    })
    assert p["tipoDoc"] == "CP"
    # Y una factura de GPA (GPA emite) es FV aunque el modelo diga otra cosa.
    p2 = ocr._adaptar_bedrock({
        "rfcEmisor": RFC_GPA, "rfcReceptor": "XAXX010101000",
        "tipoDocumento": "CARTA_PORTE", "subtotal": 338.0,
    })
    assert p2["tipoDoc"] == "FV"
    # Fletera autorizada emite y el receptor no se leyó → CP.
    p3 = ocr._adaptar_bedrock({"rfcEmisor": "TEE070612ITA", "tipoDocumento": "FACTURA"})
    assert p3["tipoDoc"] == "CP"


def test_folios_referenciados_facturas_asociadas():
    # Estrella enlaza la FV de GPA con "Facturas asociadas: 70088673".
    from s3.ocr_extractor import _folios_referenciados, _fv_coincide
    refs = _folios_referenciados("Facturas asociadas:  70088673")
    assert "70088673" in refs
    assert _fv_coincide("FMTY 70088673", refs)
    # Formato clásico sigue funcionando.
    assert "40086093" in _folios_referenciados("Comentarios: F-40086093")


def test_hibrido_pagina_pobre_reintenta_con_bedrock(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "hibrido")
    monkeypatch.setattr(ocr, "_ocr_textract",
                        lambda png, client=None: {"rfcsDetectados": [], "subtotal": None})
    llamadas = []
    def fake_bedrock(png, client=None):
        llamadas.append(1)
        return {"rfcsDetectados": [RFC_GPA], "subtotal": 811.66}
    monkeypatch.setattr(ocr, "_ocr_bedrock", fake_bedrock)
    p = ocr.ocr_pagina(b"png")
    assert llamadas and p["subtotal"] == 811.66


def test_hibrido_bedrock_falla_conserva_textract(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "hibrido")
    pagina_txt = {"rfcsDetectados": [], "subtotal": None, "tipoDoc": "OTRO"}
    monkeypatch.setattr(ocr, "_ocr_textract", lambda png, client=None: pagina_txt)
    def bedrock_roto(png, client=None):
        raise RuntimeError("AccessDenied")
    monkeypatch.setattr(ocr, "_ocr_bedrock", bedrock_roto)
    assert ocr.ocr_pagina(b"png") is pagina_txt        # fail-open


def test_hibrido_pagina_buena_no_llama_bedrock(monkeypatch):
    monkeypatch.setattr(ocr, "OCR_BACKEND", "hibrido")
    monkeypatch.setattr(ocr, "_ocr_textract",
                        lambda png, client=None: {"rfcsDetectados": [RFC_GPA], "subtotal": 100.0})
    def bedrock_prohibido(png, client=None):
        raise AssertionError("no debía llamarse")
    monkeypatch.setattr(ocr, "_ocr_bedrock", bedrock_prohibido)
    assert ocr.ocr_pagina(b"png")["subtotal"] == 100.0


def test_leer_sello_cp_valida_y_es_failopen():
    fake = FakeBedrock({"codigoSAP": "GS0231", "sucursalSello": "Monterrey",
                        "tipoFleteSello": "DISP. SEMANAL"})
    s = ocr.leer_sello_cp(b"png", client=fake)
    assert s == {"codigoSAP": "GS0231", "sucursalSello": "Monterrey",
                 "tipoFleteSello": "DISP. SEMANAL"}
    fake2 = FakeBedrock({"codigoSAP": "GSXX", "sucursalSello": None, "tipoFleteSello": None})
    assert ocr.leer_sello_cp(b"png", client=fake2)["codigoSAP"] == ""
    class Roto:
        def converse(self, **kw): raise RuntimeError("AccessDenied")
    assert ocr.leer_sello_cp(b"png", client=Roto()) == {}     # fail-open


def test_sello_gs0231_hace_el_caso_dispersion_sin_fv():
    # CP con sello GS0231 y sin factura anexa → dispersión interna, no R-093.
    cp_pag = dict(pag(receptor=RFC_GPA, subtotal=29739.88, moneda="MXN", folio="119338784"),
                  codigoSAP="GS0231", tipoFleteSello="DISP. SEMANAL")
    res = emparejar_casos([cp_pag], "119338784")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["destinatarioRFC"] == RFC_GPA
    assert caso["codigoSAP"] == "GS0231"
    sol = caso_a_solicitud(caso)
    assert sol["codigoSAP"] == "GS0231" and sol["tipoFleteSello"] == "DISP. SEMANAL"


def test_sucursal_sello_es_respaldo_de_origen_vacio():
    # Origen ilegible pero sello con casilla Monterrey → origenSucursal MTY.
    cp_pag = dict(pag(receptor=RFC_GPA, subtotal=500.0, moneda="MXN", folio="C9"),
                  sucursalSello="Monterrey")
    fv_pag = fv(subtotal=5000.0, folio="FA123456", tc=17.5)
    res = emparejar_casos([cp_pag, fv_pag], "X")
    caso = res["casos"][0]
    assert caso["origenSucursal"] == "MTY"
    # Y NUNCA pisa un origen legible.
    cp2 = dict(pag(receptor=RFC_GPA, subtotal=500.0, moneda="MXN", folio="C10"),
               origenCiudad="Guadalajara", origenEstado="Jalisco", sucursalSello="Monterrey")
    res2 = emparejar_casos([cp2, fv(subtotal=5000.0, folio="FA123457", tc=17.5)], "X")
    assert res2["casos"][0]["origenSucursal"] == "GDL"


def test_caso_a_solicitud_mapea_campos():
    caso = {
        "status": "OK", "folioCP": "FAC04927", "foliosFV": ["FM40086093"],
        "fletaRFC": HORMIK, "fleteSinIvaMXN": 3330.0, "tipoCambioRef": 17.55,
        "origenSucursal": "CDMX", "destinoEstado": "Guerrero", "destinoCiudad": "Acapulco",
        "fechaEmision": "2026-05-07",
        "partidas": [{"descripcion": "TRICLORO 50 KGS", "cantidad": 40,
                      "importe": 3653.20, "pesoKg": 50, "volumenL": 0}],
    }
    sol = caso_a_solicitud(caso)
    assert sol["folioCP"] == "FAC04927"
    assert sol["fleteBaseMXN"] == 3330.0
    assert sol["tipoCambioRef"] == 17.55
    assert sol["origenSucursal"] == "CDMX"
    assert sol["fechaEmision"] == "2026-05-07"
    assert sol["partidas"][0]["precioUnitarioUSD"] == pytest.approx(3653.20 / 40)
    assert sol["partidas"][0]["pesoKg"] == 50


def test_procesar_pdf_orquesta(monkeypatch):
    # PDF real de 4 páginas EN BLANCO (sin capa de texto) → fuerza la vía OCR;
    # ocr_pagina simulado devuelve 2 CP + 2 FV (independiente del backend real).
    import fitz
    _doc = fitz.open()
    for _ in range(4):
        _doc.new_page()
    pdf_bytes = _doc.tobytes()
    paginas = iter([
        {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "FAC04927",
         "subtotal": 3330.0, "comentarios": "F-40086093", "fletaRFC": HORMIK,
         "origenCiudad": "Iztapalapa", "destinoEstado": "Guerrero"},
        {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086093",
         "subtotal": 3852.25, "moneda": "USD", "tipoCambio": 17.55, "partidas": []},
        {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "FAC04935",
         "subtotal": 390.0, "comentarios": "F-40086102", "fletaRFC": HORMIK,
         "origenCiudad": "Iztapalapa", "destinoEstado": "Guerrero"},
        {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086102",
         "subtotal": 15.55, "moneda": "USD", "tipoCambio": 17.55, "partidas": []},
    ])
    monkeypatch.setattr(ocr, "ocr_pagina", lambda img, client=None: next(paginas))
    res = ocr.procesar_pdf(pdf_bytes, folio_archivo="FAC4927-FAC4935")
    assert len(res["casos"]) == 2
    assert res["casos"][0]["origenSucursal"] == "CDMX"   # Iztapalapa → CDMX
    assert res["casos"][0]["foliosFV"] == ["FM40086093"]


# ── Fixes MEDIO de la auditoría ───────────────────────────────────
def test_num_extrae_numero_con_unidad_y_miles():
    assert ocr._num("$3,330.00 MXN") == pytest.approx(3330.0)
    assert ocr._num("17.55") == pytest.approx(17.55)
    assert ocr._num("Total: 4.41 USD") == pytest.approx(4.41)
    assert ocr._num("sin numero") == 0.0
    assert ocr._num(None) == 0.0


def test_emparejar_unico_cp_fv_sin_comentario():
    # 1 CP + 1 FV sin comentario que los enlace → se emparejan igual
    cp = {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "116162584",
          "subtotal": 132.0, "moneda": "MXN", "fletaRFC": HORMIK}   # SIN comentarios
    fv = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40085931",
          "subtotal": 4.41, "moneda": "USD", "tipoCambio": 17.77, "partidas": []}
    res = emparejar_casos([cp, fv])
    assert len(res["casos"]) == 1
    assert res["casos"][0]["status"] == "OK"
    assert res["casos"][0]["foliosFV"] == ["FM40085931"]
    assert res["fvsSinCP"] == []


def test_emparejar_varios_cp_sin_refs_agrega_en_un_caso():
    # REGLA GPA 2026-07-15 (119877129-119874733, 119697309-119700106): un PDF
    # "paquete" con VARIOS CPs + facturas SIN referencias cruzadas se evalúa
    # como UN caso agregado: flete TOTAL contra venta TOTAL (antes cada CP
    # moría en SIN_FV_VINCULADA → R-093 falso).
    cp1 = {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "A", "subtotal": 100, "moneda": "MXN"}
    cp2 = {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "B", "subtotal": 200, "moneda": "MXN"}
    fv1 = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "F1", "subtotal": 10, "moneda": "MXN"}
    fv2 = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "F2", "subtotal": 20, "moneda": "MXN"}
    res = emparejar_casos([cp1, fv1, cp2, fv2], "PAQUETE-X")
    assert len(res["casos"]) == 1
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["fleteSinIvaMXN"] == 300          # suma de las CPs
    assert caso["montoVentaFV"] == 30             # suma de las FVs
    assert caso["folioCP"] == "PAQUETE-X"


def test_caso_usd_sin_tipo_cambio_es_error():
    cp = cp_doc("FAC04927", 3330.0, "40086093")
    fv = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086093",
          "subtotal": 3852.25, "moneda": "USD", "partidas": []}   # USD SIN tipoCambio
    res = emparejar_casos([cp, fv])
    assert res["casos"][0]["status"] == "ERROR"
    assert res["casos"][0]["error"] == "SIN_TIPO_CAMBIO"


def test_caso_mxn_sin_tc_ya_no_es_error():
    # Regla 2026-07-04 (usuario): FV en MXN vs flete en MXN se evalúa DIRECTO;
    # el TC solo se necesita cuando hay factura en USD (ver
    # test_usd_sin_tc_sigue_siendo_error).
    cp = cp_doc("FAC04927", 3330.0, "40086093")
    fv = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086093",
          "subtotal": 3852.25, "moneda": "MXN", "partidas": []}   # MXN sin TC
    res = emparejar_casos([cp, fv])
    assert res["casos"][0]["status"] == "OK"
    assert res["casos"][0]["monedaFV"] == "MXN"


def test_caso_a_solicitud_convierte_partidas_mxn_a_usd():
    # FV en MXN: los precios de partidas se convierten a USD con el TC.
    caso = {"status": "OK", "folioCP": "X", "foliosFV": ["F1"], "fletaRFC": HORMIK,
            "fleteSinIvaMXN": 1000.0, "tipoCambioRef": 20.0, "monedaFV": "MXN",
            "origenSucursal": "GDL",
            "partidas": [{"descripcion": "Bomba", "cantidad": 2, "importe": 4000.0}]}
    sol = caso_a_solicitud(caso)
    # 4000 MXN / 2 u = 2000 MXN/u → /20 = 100 USD/u
    assert sol["partidas"][0]["precioUnitarioUSD"] == pytest.approx(100.0)
    assert sol["fleteBaseMXN"] == 1000.0       # el flete se queda en MXN
    assert sol["tipoCambioRef"] == 20.0


def test_caso_a_solicitud_usd_no_convierte():
    caso = {"status": "OK", "folioCP": "X", "foliosFV": ["F1"], "fletaRFC": HORMIK,
            "fleteSinIvaMXN": 1000.0, "tipoCambioRef": 17.5, "monedaFV": "USD",
            "partidas": [{"descripcion": "Bomba", "cantidad": 2, "importe": 200.0}]}
    sol = caso_a_solicitud(caso)
    assert sol["partidas"][0]["precioUnitarioUSD"] == pytest.approx(100.0)  # 200/2, sin factor


def test_caso_a_solicitud_incluye_monto_venta_fv():
    # El Sub-Total de la FV (montoVentaFV) debe viajar al /evaluar: es la
    # fuente del monto del pedido (C1/C5), no la suma de renglones de tabla.
    caso = {"status": "OK", "folioCP": "X", "foliosFV": ["F1"], "fletaRFC": HORMIK,
            "fleteSinIvaMXN": 1000.0, "tipoCambioRef": 17.5, "monedaFV": "USD",
            "montoVentaFV": 845.50, "origenSucursal": "GDL", "partidas": []}
    sol = caso_a_solicitud(caso)
    assert sol["montoVentaFV"] == pytest.approx(845.50)
    assert sol["monedaFV"] == "USD"


# ── _fecha_iso ────────────────────────────────────────────────────
@pytest.mark.parametrize("crudo,esperado", [
    ("2026-05-07", "2026-05-07"),
    ("2026-05-07T10:33:00", "2026-05-07"),
    ("07/05/2026", "2026-05-07"),          # dd/mm/yyyy del OCR
    ("7-5-2026", "2026-05-07"),
    ("12 de mayo de 2026", "2026-05-12"),
    ("FECHA: 07/05/2026 10:33", "2026-05-07"),
    ("sin fecha", None),
    (None, None),
])
def test_fecha_iso(crudo, esperado):
    assert ocr._fecha_iso(crudo) == esperado


# ── Extracción desde la CAPA DE TEXTO del PDF (CFDI digitales) ─────
from s3.ocr_extractor import (
    _pagina_desde_texto, _flete_sat, _valor_etiqueta, _ciudad_estado,
    _origen_destino, _tc_moneda,
)


def test_ciudad_estado_abreviaturas():
    assert _ciudad_estado("VALLADOLID, YUC.") == ("Valladolid", "Yucatán")
    assert _ciudad_estado("CANCUN, Q.R.") == ("Cancun", "Quintana Roo")
    assert _ciudad_estado("MONTERREY, N.L.") == ("Monterrey", "Nuevo León")
    assert _ciudad_estado("texto cualquiera") is None


def test_flete_sat_suma_claves_transporte():
    lineas = [
        {"text": "78101802 - Flete", "top": 0.46, "left": 0.36},
        {"text": "1,427.96", "top": 0.46, "left": 0.87},
        {"text": "78101801 - Entrega", "top": 0.47, "left": 0.36},
        {"text": "438.00", "top": 0.47, "left": 0.88},
        {"text": "78101802 - Combustible", "top": 0.48, "left": 0.36},
        {"text": "35.00", "top": 0.48, "left": 0.89},
    ]
    assert _flete_sat(lineas) == 1900.96


def test_valor_etiqueta_geometria():
    lineas = [
        {"text": "Subtotal", "top": 0.74, "left": 0.81},
        {"text": "811.66", "top": 0.74, "left": 0.90},
        {"text": "Total", "top": 0.76, "left": 0.81},
        {"text": "941.53", "top": 0.76, "left": 0.90},
    ]
    assert _valor_etiqueta(["SUBTOTAL", "SUB-TOTAL"], lineas) == 811.66


def test_tc_moneda_regex():
    assert _tc_moneda([{"text": "Moneda: USD Tipo de Cambio: 17.45", "top": 0, "left": 0}]) == (17.45, "USD")


def _cp_lineas():
    return [
        {"text": "CARTA DE PORTE DE INGRESOS", "top": 0.05, "left": 0.4},
        {"text": "CANCUN, Q.R.", "top": 0.11, "left": 0.07},
        {"text": "VALLADOLID, YUC.", "top": 0.11, "left": 0.35},
        {"text": "(GPA8402219Y1)GENERAL DE PRODUCTOS", "top": 0.20, "left": 0.05},
        {"text": "(AUPM980703941)MAURICIO AGUILAR PEREZ", "top": 0.20, "left": 0.35},
        {"text": "78101802 - Flete", "top": 0.46, "left": 0.36}, {"text": "1,427.96", "top": 0.46, "left": 0.87},
        {"text": "78101801 - Entrega", "top": 0.47, "left": 0.36}, {"text": "438.00", "top": 0.47, "left": 0.88},
        {"text": "Moneda: MXN", "top": 0.03, "left": 0.5},
    ]


def test_pagina_texto_cp():
    p = _pagina_desde_texto(_cp_lineas())
    assert p["tipoDoc"] == "CP"
    assert p["rfcReceptor"] == "GPA8402219Y1"
    assert clasificar_pagina(p) == "CP"
    assert p["subtotal"] == 1865.96            # 1427.96 + 438.00
    assert p["origenCiudad"] == "Cancun" and p["origenEstado"] == "Quintana Roo"
    assert p["destinoEstado"] == "Yucatán"
    # Fletera en la imagen del membrete → no se asigna el RFC del cliente.
    assert p["fletaRFC"] == "" and p["fletaRFC"] != "AUPM980703941"


def test_pagina_texto_fv():
    fv = [
        {"text": "Factura  FC 20109707", "top": 0.02, "left": 0.6},
        {"text": "R.F.C. GPA-840221-9Y1", "top": 0.10, "left": 0.05},
        {"text": "AUPM980703941", "top": 0.12, "left": 0.05},
        {"text": "Subtotal", "top": 0.74, "left": 0.81}, {"text": "811.66", "top": 0.74, "left": 0.90},
        {"text": "Moneda: USD Tipo de Cambio: 17.45", "top": 0.745, "left": 0.05},
    ]
    p = _pagina_desde_texto(fv)
    assert p["tipoDoc"] == "FV" and p["rfcEmisor"] == "GPA8402219Y1"
    assert clasificar_pagina(p) == "FV"
    assert p["subtotal"] == 811.66 and p["moneda"] == "USD" and p["tipoCambio"] == 17.45


# ── Cross-proveedor: clasificación robusta y layouts variados ─────
from s3.ocr_extractor import _origen_destino, _texto_util

OSORIO = "TOS0407087T2"   # fletera autorizada


def test_clasifica_cp_por_receptor_gpa():
    # GPA en el bloque RECEPTOR → carta porte (aunque GPA aparezca antes como
    # remitente de la mercancía y el comprobante diga "Ingreso").
    lineas = [
        {"text": "TRANSPORTADORA OSORIO", "top": 0.02, "left": 0.1},
        {"text": "R.F.C. " + OSORIO, "top": 0.04, "left": 0.1},
        {"text": "Tipo de Comprobante: Ingreso", "top": 0.06, "left": 0.6},
        {"text": "RECEPTOR", "top": 0.20, "left": 0.05},
        {"text": "R.F.C.: GPA8402219Y1", "top": 0.22, "left": 0.05},
        {"text": "SUBTOTAL", "top": 0.50, "left": 0.80}, {"text": "1,100.00", "top": 0.50, "left": 0.90},
    ]
    p = _pagina_desde_texto(lineas)
    assert clasificar_pagina(p) == "CP"
    assert p["fletaRFC"] == OSORIO
    assert p["subtotal"] == 1100.0     # prefiere la etiqueta SUBTOTAL


def test_clasifica_fv_por_receptor_cliente():
    # Receptor = cliente (no GPA) → factura de venta de GPA.
    lineas = [
        {"text": "General de Productos para el Agua", "top": 0.02, "left": 0.1},
        {"text": "Factura - Ingreso", "top": 0.04, "left": 0.6},
        {"text": "Emisor R.F.C. GPA8402219Y1", "top": 0.06, "left": 0.05},
        {"text": "RECEPTOR", "top": 0.20, "left": 0.05},
        {"text": "R.F.C. PEA230227FL6", "top": 0.22, "left": 0.05},
        {"text": "Subtotal", "top": 0.70, "left": 0.80}, {"text": "609.36", "top": 0.70, "left": 0.90},
    ]
    p = _pagina_desde_texto(lineas)
    assert clasificar_pagina(p) == "FV"
    assert p["rfcEmisor"] == "GPA8402219Y1"
    assert p["subtotal"] == 609.36


def test_origen_destino_inline():
    lineas = [{"text": "ORIGEN: CANCUN QROO - DESTINO: MERIDA YUCATAN", "top": 0.4, "left": 0.05},
              {"text": "ROLANDO CERVERA MALDONADO", "top": 0.42, "left": 0.05}]
    oc, oe, dc, de = _origen_destino(lineas)
    assert oe == "Quintana Roo" and de == "Yucatan"
    assert "Maldonado" not in (de or "")     # no arrastra el nombre de la línea siguiente


def test_complemento_sin_flete_no_crea_caso_fantasma():
    # CP con flete + página de complemento (CP sin importe) + FV → UN caso, no
    # SIN_FV_VINCULADA por contar el complemento como 2ª carta porte.
    cp_cobro = pag(emisor=OSORIO, receptor=RFC_GPA, subtotal=1100.0, moneda="MXN", folio="A-68947")
    complemento = pag(emisor=OSORIO, receptor=RFC_GPA, subtotal=None, folio=None)  # UBICACIONES, sin importe
    factura = fv(subtotal=725.45, folio="FC20109420", tc=17.39)
    res = emparejar_casos([cp_cobro, complemento, factura], folio_archivo="A68947")
    assert len(res["casos"]) == 1
    assert res["casos"][0]["status"] == "OK"
    assert res["casos"][0]["montoVentaFV"] == 725.45


def test_texto_util_detecta_revuelto():
    legible = ("CARTA PORTE  RECEPTOR R.F.C. GPA8402219Y1  General de Productos "
               "para el Agua  Subtotal 811.66  IVA 129.87  Total 941.53  "
               "Moneda USD  Origen Cancun  Destino Merida")
    assert _texto_util(legible) is True              # tiene RFC y montos
    assert _texto_util("!#$%&/()=?¡" * 40) is False  # factura con fuente rara (sin RFC ni montos)
    assert _texto_util("corto") is False             # casi vacío


def test_parse_textract_fecha_desde_texto_crudo():
    # La Query de fecha falla → se recupera del texto ("FECHA DE EMISION dd/mm/yyyy").
    resp = _resp(lines=[
        _line("CARTA PORTE DE INGRESOS", top=0.02),
        _line("FECHA DE EMISION 03/06/2026", top=0.08),
        _line("RFC: GPA8402219Y1", top=0.20),
    ])
    assert _parse_textract(resp)["fecha"] == "2026-06-03"


def test_ciudad_estado_tolera_sufijo_mex():
    from s3.ocr_extractor import _ciudad_estado
    assert _ciudad_estado("GUADALAJARA, JAL., MEX") == ("Guadalajara", "Jalisco")
    assert _ciudad_estado("ACAPULCO, GRO., MEX") == ("Acapulco", "Guerrero")


def test_origen_prefiere_ciudad_que_mapea_a_sucursal():
    # Fila superior = TERMINAL de la fletera ("GONZALEZ GALLO, JAL."), no la
    # ciudad; el domicilio del remitente trae la real (GUADALAJARA → GDL).
    lineas = [
        {"text": "GONZALEZ GALLO, JAL.", "top": 0.14, "left": 0.12},
        {"text": "ACAPULCO, GRO.", "top": 0.14, "left": 0.58},
        {"text": "GUADALAJARA, JAL., MEX", "top": 0.22, "left": 0.06},
        {"text": "ACAPULCO, GRO., MEX", "top": 0.22, "left": 0.51},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert oc == "Guadalajara" and oe == "Jalisco"     # no "Gonzalez Gallo"
    assert de == "Guerrero"


def test_ciudad_estado_nombre_completo():
    # Estados con NOMBRE COMPLETO tras la coma (folio real 119581944: Toluca).
    from s3.ocr_extractor import _ciudad_estado
    assert _ciudad_estado("TOLUCA, EDO. DE MEXICO") == ("Toluca", "Edo. México")
    assert _ciudad_estado("MERIDA, YUCATAN") == ("Merida", "Yucatán")
    # "CIUDAD JUAREZ, CHI" (Tresguerras trunca CHIH; Chiapas siempre es CHIS)
    assert _ciudad_estado("CIUDAD JUAREZ, CHI") == ("Ciudad Juarez", "Chihuahua")
    assert _ciudad_estado("TUXTLA GUTIERREZ, CHIS.") == ("Tuxtla Gutierrez", "Chiapas")


def test_origen_destino_no_duplica_con_un_solo_candidato():
    # Folio real 119581944: la fila superior trae la terminal + un destino que
    # antes no parseaba → el fallback duplicaba la terminal como origen Y
    # destino ("Jalisco" siendo Toluca). Con un solo lado legible, el otro debe
    # quedar vacío (revisión), nunca duplicado.
    lineas = [
        {"text": "GONZALEZ GALLO, JAL.", "top": 0.14, "left": 0.12},
        {"text": "DESTINO ILEGIBLE SIN COMA", "top": 0.14, "left": 0.58},
        {"text": "GUADALAJARA, JAL., MEX", "top": 0.22, "left": 0.06},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert (oc, oe) == ("Guadalajara", "Jalisco")
    assert dc is None and de is None               # jamás "Gonzalez Gallo"


def test_origen_destino_tabla_carta_porte_hormik():
    # HORMIK (FAC6637): tabla "ORÍGENES, DESTINOS Y PUNTOS INTERMEDIOS" con
    # filas OR#####/DE##### y la plaza al final de la dirección. Antes caía a
    # R-301 "destino no cubierto" con destino vacío.
    lineas = [
        {"text": "ORIGENES, DESTINOS Y PUNTOS INTERMEDIOS", "top": 0.10, "left": 0.2},
        {"text": "Origen OR00256", "top": 0.14, "left": 0.05},
        {"text": "AV EJE 5 SUR #36,Central de Abasto CP: 09040,Iztapalapa,Ciudad de México,MEX",
         "top": 0.14, "left": 0.15},
        {"text": "TCH170824TH2", "top": 0.14, "left": 0.55},
        {"text": "Destino DE02469", "top": 0.19, "left": 0.05},
        {"text": "CARRETERA BARRA VIEJA #LOTE 4 MANZANA 1/ GPA/ A&B WATERS int CONDOMINIO",
         "top": 0.19, "left": 0.15},
        {"text": "BAYAM RESIDENSES,Plan de los Amates CP: 39893,Acapulco de Juárez,Guerrero,MEX",
         "top": 0.20, "left": 0.15},
        {"text": "GPA8402219Y1", "top": 0.19, "left": 0.55},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert oe == "CDMX" and oc == "Iztapalapa"
    assert de == "Guerrero" and dc == "Acapulco De Juárez"


def test_tabla_ccp_complementa_no_sustituye():
    # La tabla solo trae el DESTINO legible → el ORIGEN se sigue buscando con
    # las demás estrategias (fila remitente Tresguerras). Nunca degrada.
    lineas = [
        {"text": "Destino DE02469", "top": 0.19, "left": 0.05},
        {"text": "X CP: 39893,Acapulco de Juárez,Guerrero,MEX", "top": 0.20, "left": 0.15},
        # origen por estrategia clásica (domicilio del remitente):
        {"text": "GUADALAJARA, JAL., MEX", "top": 0.22, "left": 0.06},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert (dc, de) == ("Acapulco De Juárez", "Guerrero")   # de la tabla
    assert (oc, oe) == ("Guadalajara", "Jalisco")           # de la estrategia clásica


def test_origen_destino_toluca_estado_completo():
    # Caso 119581944 completo: destino con nombre de estado completo a la derecha.
    lineas = [
        {"text": "GONZALEZ GALLO, JAL.", "top": 0.14, "left": 0.12},
        {"text": "TOLUCA, EDO. DE MEXICO", "top": 0.14, "left": 0.58},
        {"text": "GUADALAJARA, JAL., MEX", "top": 0.22, "left": 0.06},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert (oc, oe) == ("Guadalajara", "Jalisco")
    assert (dc, de) == ("Toluca", "Edo. México")


def test_nota_de_credito_es_anexo_no_cp():
    # TPQ1A-955 pág. 2: la NC de la fletera (E-Egreso, receptor GPA) clasificaba
    # como 2ª carta porte y creaba un caso fantasma.
    from s3.ocr_extractor import _senales_especiales, clasificar_pagina
    lineas = [
        {"text": "URUZ ENVIA Y RECIBE", "top": 0.05, "left": 0.2},
        {"text": "TIPO COMPROBANTE E Egreso", "top": 0.15, "left": 0.5},
        {"text": "Nota de crédito", "top": 0.20, "left": 0.06},
        {"text": "(GPA8402219Y1)GENERAL DE PRODUCTOS", "top": 0.30, "left": 0.1},
    ]
    s = _senales_especiales(lineas)
    assert s["esNotaCredito"] is True
    assert clasificar_pagina({"esNotaCredito": True, "rfcReceptor": RFC_GPA}) == "ANEXO"


def test_preguia_dispersion_sin_fv_no_es_r093():
    # 119338784: CP GPA→GPA + Pre Guía Almacén Origen → dispersión interna,
    # no lleva factura de venta (antes moría en SIN_FV_VINCULADA/R-093).
    cp_pag = dict(pag(receptor=RFC_GPA, subtotal=29739.88, moneda="MXN", folio="119338784"),
                  fletaRFC=OSORIO)
    preguia = {"tipoDoc": "OTRO", "esPreguia": True, "rfcEmisor": None, "rfcReceptor": None,
               "rfcsDetectados": [], "subtotal": None, "moneda": None, "tipoCambio": None,
               "folio": None, "fecha": None, "comentarios": None, "partidas": []}
    res = emparejar_casos([cp_pag, preguia], "119338784")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["destinatarioRFC"] == RFC_GPA
    assert caso["foliosFV"] == []


def test_destinatario_gpa_pareado_misma_fila():
    from s3.ocr_extractor import _senales_especiales
    # Dispersión: GPA como remitente Y destinatario en la misma fila.
    disp = [
        {"text": "(XAXX010101000)GENERAL DE PRODUCTOS PARA", "top": 0.167, "left": 0.229},
        {"text": "(XAXX010101000)GENERAL DE PRODUCTOS PARA", "top": 0.167, "left": 0.683},
    ]
    assert _senales_especiales(disp)["destinatarioGPA"] is True
    # Venta: el lado derecho es el CLIENTE → no es dispersión.
    venta = [
        {"text": "(XAXX010101000)GENERAL DE PRODUCTOS PARA", "top": 0.167, "left": 0.229},
        {"text": "(XAXX010101000)RAUL ROJAS MEDINA", "top": 0.167, "left": 0.683},
    ]
    assert _senales_especiales(venta)["destinatarioGPA"] is False


def test_folio_fv_serie_sucursal():
    # M846228: la serie de la factura es F + sucursal ("FMTY 70088749");
    # el regex solo cubría FA/FC/FM/FV/FLC → folio vacío → las 3 facturas del
    # PDF se fundían como una multipágina y el %flete salía contra 1 sola.
    from s3.ocr_extractor import _folio_no_fiscal
    assert _folio_no_fiscal([{"text": "FMTY 70088749", "top": 0.05, "left": 0.76}], serie_f=True) == "FMTY70088749"
    assert _folio_no_fiscal([{"text": "Factura FGDL 20109707", "top": 0.02, "left": 0.6}], serie_f=True) == "FGDL20109707"
    # "FAX + número" no es una serie de factura.
    assert _folio_no_fiscal([{"text": "FAX 8183722126", "top": 0.05, "left": 0.1}], serie_f=True) is None
    # El respaldo serie-F es SOLO para FV: en una carta porte secuestraba
    # referencias ajenas ("FD 408735" en el CP 119524726 → folio equivocado).
    assert _folio_no_fiscal([{"text": "REMISION FD 408735", "top": 0.4, "left": 0.2}]) is None


def test_consolidar_fvs_sin_folio_con_subtotales_distintos():
    # Páginas FV sin folio legible pero con subtotales DISTINTOS son facturas
    # DISTINTAS (una multipágina repite su subtotal). M846228: 1562.04 MXN +
    # 1815.44 USD + 6248.17 MXN deben sumar, no quedarse con una.
    from s3.ocr_extractor import _consolidar_fvs
    pags = [
        {"folio": None, "subtotal": 1562.04, "moneda": "MXN", "tipoCambio": None, "partidas": []},
        {"folio": None, "subtotal": 1815.44, "moneda": "USD", "tipoCambio": 17.21, "partidas": []},
        {"folio": None, "subtotal": 6248.17, "moneda": "MXN", "tipoCambio": None, "partidas": []},
    ]
    fvs = _consolidar_fvs(pags)
    assert len(fvs) == 3
    assert sorted(round(f["subtotal"], 2) for f in fvs) == [1562.04, 1815.44, 6248.17]
    # Y una factura multipágina (mismo subtotal repetido, sin folio) sigue siendo UNA.
    pags2 = [
        {"folio": "FA123456", "subtotal": 811.66, "moneda": "USD", "tipoCambio": 17.45, "partidas": []},
        {"folio": None, "subtotal": 811.66, "moneda": "USD", "tipoCambio": None, "partidas": []},
        {"folio": None, "subtotal": None, "moneda": None, "tipoCambio": None, "partidas": []},
    ]
    assert len(_consolidar_fvs(pags2)) == 1


def test_fletera_por_nombre_en_texto_de_la_factura():
    # El CP trae el RFC de la fletera en el LOGO (no en texto), pero la factura
    # de GPA dice "Embarcar por TRES GUERRAS" → la fletera se resuelve a nivel caso.
    cp_pag = dict(pag(receptor=RFC_GPA, subtotal=1000, moneda="MXN", folio="C1"),
                  fletaRFC="", fleteraTexto="")
    fv_pag = dict(fv(subtotal=500, folio="F-9999"), fleteraTexto="ACT68080665A")
    res = emparejar_casos([cp_pag, fv_pag], "X")
    assert res["casos"][0]["fletaRFC"] == "ACT68080665A"


def test_cp_multipagina_mismo_subtotal_es_una_sola():
    # CP impresa en 2 páginas que repiten el mismo Sub-Total → UN caso (lote 29-06).
    p1 = dict(pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=3946.89, moneda="MXN"))
    p2 = dict(pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=3946.89, moneda="MXN"))
    f1 = fv(subtotal=24648.83, folio="F-5551")
    f2 = fv(subtotal=509.46, folio="F-5552")
    res = emparejar_casos([p1, p2, f1, f2], "RANGO")
    assert len(res["casos"]) == 1
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["fleteSinIvaMXN"] == 3946.89          # no duplicada
    assert caso["montoVentaFV"] == 24648.83 + 509.46  # facturas sumadas


def test_fletera_nombre_ambiguo_no_asigna():
    from motor.catalogos import fletera_por_nombre
    assert fletera_por_nombre("factura de TRES GUERRAS con TINY PACK") == ""
    assert fletera_por_nombre("embarcar por TRES GUERRAS") == "ACT68080665A"
    assert fletera_por_nombre("calle alvaro obregon 123") == ""   # calle ≠ fletera


def test_origen_destino_formato_estrella_sin_coma():
    # Estrella: "MONTERREY NUEVO LEON" (sin coma, estado completo), repetida →
    # plaza única inequívoca (entrega local) → origen=destino=Monterrey/NL.
    lineas = [
        {"text": "MONTERREY NUEVO LEON", "top": 0.10, "left": 0.34},
        {"text": "MONTERREY NUEVO LEON", "top": 0.13, "left": 0.35},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert (oc, oe) == ("Monterrey", "Nuevo Leon")
    assert (dc, de) == ("Monterrey", "Nuevo Leon")


def test_origen_destino_estrella_ambiguo_no_adivina():
    # Dos plazas DISTINTAS sin etiquetas → no se adivina cuál es cuál.
    lineas = [
        {"text": "MONTERREY NUEVO LEON", "top": 0.10, "left": 0.34},
        {"text": "GUADALAJARA JALISCO", "top": 0.13, "left": 0.35},
    ]
    oc, oe, dc, de = _origen_destino(lineas)
    assert oe is None and de is None


# ── Reglas de negocio 2026-07-04 (retro del usuario con casos reales) ──
def test_mxn_vs_mxn_sin_tc_evalua_directo():
    # 119483518: FV en MXN sin tipo de cambio → NO es error; MXN vs MXN directo.
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=1000, moneda="MXN", folio="C1")
    fv_mxn = pag(emisor=RFC_GPA, receptor=CLIENTE, subtotal=17350.0, moneda="MXN", folio="F-9111")
    res = emparejar_casos([cp_pag, fv_mxn], "X")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["monedaFV"] == "MXN" and caso["montoVentaFV"] == 17350.0
    assert caso["tipoCambioRef"] > 0          # respaldo solo para los mínimos USD


def test_tc_se_busca_en_todas_las_facturas():
    # 119581188: FV en MXN sin TC + FV en USD CON TC → el TC del caso es el de
    # la factura USD y cada moneda se convierte por separado.
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=3946.89, moneda="MXN", folio="C1")
    fv_mxn = pag(emisor=RFC_GPA, receptor=CLIENTE, subtotal=1735.0, moneda="MXN", folio="F-9222")
    fv_usd = fv(subtotal=800.0, folio="F-9333", tc=17.35)
    res = emparejar_casos([cp_pag, fv_mxn, fv_usd], "X")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["tipoCambioRef"] == 17.35
    assert caso["monedaFV"] == "USD"
    assert caso["montoVentaFV"] == pytest.approx(1735.0 / 17.35 + 800.0)   # 900.0


def test_usd_sin_tc_sigue_siendo_error():
    cp_pag = pag(emisor=CARRIER, receptor=RFC_GPA, subtotal=100, moneda="MXN", folio="C1")
    fv_usd = pag(emisor=RFC_GPA, receptor=CLIENTE, subtotal=500, moneda="USD", folio="F-9444")
    res = emparejar_casos([cp_pag, fv_usd], "X")
    assert res["casos"][0].get("error") == "SIN_TIPO_CAMBIO"


# ── Desglose de consolidados (hoja-Excel dentro del PDF, caso ACRED3129) ──
def test_parse_desglose_consolidado():
    from s3.ocr_extractor import _parse_desglose
    texto = ("No. GUÍA\nFECHA\nCIUDAD\nCOMPAÑÍA\nMÉTODO D# DE PAQU TOTAL\n"
             "48980JRZE38QLZEJ\n22/05/2026 SAN PATRICIO\nTHE POOLCITY\nConvenio\n1\n500.00\n$     \n"
             "47910OK6SAUJZLBB\n22/05/2026 La Barca\nRIVAS DURAN\nConvenio\n2\n240.00\n$     \n")
    rows = _parse_desglose(texto)
    assert len(rows) == 2
    assert rows[0] == {"guia": "48980JRZE38QLZEJ", "fecha": "22/05/2026",
                       "ciudad": "SAN PATRICIO", "compania": "THE POOLCITY",
                       "paquetes": 1, "total": 500.0}
    assert rows[1]["total"] == 240.0
    assert _parse_desglose("página normal sin tabla") == []


def test_desglose_viaja_al_caso_y_solicitud():
    from s3.ocr_extractor import _pagina_desde_texto
    hoja = _pagina_desde_texto([
        {"text": "No. GUÍA", "top": 0.05, "left": 0.1}, {"text": "FECHA", "top": 0.05, "left": 0.3},
        {"text": "CIUDAD", "top": 0.05, "left": 0.4}, {"text": "COMPAÑÍA", "top": 0.05, "left": 0.5},
        {"text": "MÉTODO D# DE PAQU TOTAL", "top": 0.05, "left": 0.7},
        {"text": "48980JRZE38QLZEJ", "top": 0.08, "left": 0.1},
        {"text": "22/05/2026 SAN PATRICIO", "top": 0.10, "left": 0.1},
        {"text": "THE POOLCITY", "top": 0.12, "left": 0.1},
        {"text": "Convenio", "top": 0.14, "left": 0.1},
        {"text": "1", "top": 0.16, "left": 0.1},
        {"text": "500.00", "top": 0.18, "left": 0.1},
    ])
    assert hoja["tipoDoc"] == "DESGLOSE" and len(hoja["desglose"]) == 1
    res = emparejar_casos([hoja, cp(1000.0, "ACRED1"), fv(900.0, "F-7777")], "ACRED1")
    caso = res["casos"][0]
    assert caso["status"] == "OK"
    assert caso["desglose"][0]["guia"] == "48980JRZE38QLZEJ"
    sol = caso_a_solicitud(caso)
    assert sol["desgloseConsolidado"][0]["total"] == 500.0


def test_origen_destino_por_codigo_postal():
    # RESPALDO por CP (regla GPA 2026-07-16): el CP del destinatario (columna
    # derecha) da el estado; el del remitente, la sucursal de origen. Se
    # ignoran el Lugar de Expedición y la fila del receptor (REG:).
    from s3.ocr_extractor import _origen_destino_por_cp
    lineas = [
        {"text": "LUGAR DE EXPEDICION 44890", "top": 0.04, "left": 0.80},
        {"text": "CP: 44190,   TEL: 3310573231", "top": 0.24, "left": 0.06},
        {"text": "CP: 55800,   TEL: 5949562931", "top": 0.24, "left": 0.51},
        {"text": "GPA8402219Y1, GENERAL DE PRODUCTOS (REG: 601, CP: 44930)", "top": 0.29, "left": 0.10},
    ]
    oc, oe, dc, de = _origen_destino_por_cp(lineas)
    assert (oc, oe) == ("Guadalajara", "Jalisco")      # 44190 → GDL
    assert de == "Edo. México"                          # 55800 (Teotihuacán)
    # Chiapas sin ciudad NO se rellena (exige ciudad autorizada).
    _, _, _, de2 = _origen_destino_por_cp([
        {"text": "CP: 29000, TEL: 1", "top": 0.24, "left": 0.51}])
    assert de2 is None


def test_estado_por_cp_rangos():
    from motor.catalogos import estado_por_cp, sucursal_por_cp
    assert estado_por_cp("77500") == "Quintana Roo"
    assert estado_por_cp("63000") == "Nayarit"
    assert estado_por_cp("09040") == "CDMX"
    assert estado_por_cp("48300") == "Jalisco"
    assert estado_por_cp("1234") is None
    assert sucursal_por_cp("48300") == "PVR"            # Puerto Vallarta ≠ GDL
    assert sucursal_por_cp("44190") == "GDL"
    assert sucursal_por_cp("67130") == "MTY"
