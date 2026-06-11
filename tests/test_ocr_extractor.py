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
    # render simulado: 4 "páginas"; OCR simulado (independiente del backend): 2 CP + 2 FV
    monkeypatch.setattr(ocr, "render_paginas_pdf", lambda b, dpi=None: [b"", b"", b"", b""])
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
    res = ocr.procesar_pdf(b"pdf", folio_archivo="FAC4927-FAC4935")
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


def test_emparejar_varios_cp_sin_comentario_no_hace_fallback():
    # Con 2 CP + 2 FV sin comentario NO se adivina el emparejamiento (evita errores)
    cp1 = {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "A", "subtotal": 100, "moneda": "MXN"}
    cp2 = {"rfcEmisor": HORMIK, "rfcReceptor": RFC_GPA, "folio": "B", "subtotal": 200, "moneda": "MXN"}
    fv1 = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "F1", "subtotal": 10, "moneda": "MXN"}
    fv2 = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "F2", "subtotal": 20, "moneda": "MXN"}
    res = emparejar_casos([cp1, fv1, cp2, fv2])
    assert all(c["status"] == "ERROR" for c in res["casos"])
    assert res["casos"][0]["error"] == "SIN_FV_VINCULADA"


def test_caso_usd_sin_tipo_cambio_es_error():
    cp = cp_doc("FAC04927", 3330.0, "40086093")
    fv = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086093",
          "subtotal": 3852.25, "moneda": "USD", "partidas": []}   # USD SIN tipoCambio
    res = emparejar_casos([cp, fv])
    assert res["casos"][0]["status"] == "ERROR"
    assert res["casos"][0]["error"] == "SIN_TIPO_CAMBIO"


def test_caso_sin_tipo_cambio_siempre_es_error():
    # Sin TC no se puede evaluar (el flete es MXN y los mínimos USD), sea USD o MXN.
    cp = cp_doc("FAC04927", 3330.0, "40086093")
    fv = {"rfcEmisor": RFC_GPA, "rfcReceptor": CLIENTE, "folio": "FM40086093",
          "subtotal": 3852.25, "moneda": "MXN", "partidas": []}   # MXN sin TC
    res = emparejar_casos([cp, fv])
    assert res["casos"][0]["status"] == "ERROR"
    assert res["casos"][0]["error"] == "SIN_TIPO_CAMBIO"


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
