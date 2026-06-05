# s3/ocr_extractor.py
# Extracción de datos de fletes desde PDFs ESCANEADOS (solo imagen) vía OCR.
# ─────────────────────────────────────────────────────────────────
# Realidad de los documentos GPA (verificada con archivos reales):
#   - Los PDF NO tienen capa de texto: son escaneos → se requiere OCR real.
#   - 1 PDF = 1 caso = Carta Porte (CP) + Factura(s) de Venta (FV) en sus páginas.
#   - El flete SIN IVA sale del Sub-Total del CP (MXN).
#   - El monto de venta sale del Subtotal de la(s) FV(s) de GPA (se suman).
#   - CP vs FV se determina por el ROL del RFC de GPA en el CFDI:
#       GPA emisor   → FV
#       GPA receptor → CP
#       GPA en ninguno → documento ajeno → ERROR
#
# OCR: Claude (visión) vía Amazon Bedrock. Modelo configurable con
# BEDROCK_MODEL_ID (debe ser un modelo/inference-profile habilitado en la cuenta).
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations
import os
import re
import json
import logging
from typing import Optional

import boto3

from motor.catalogos import RFC_GPA, sucursal_de_origen

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
)
OCR_DPI = int(os.environ.get("OCR_DPI", "200"))

# Motor de OCR: "textract" (nativo AWS, recomendado) o "bedrock" (Claude visión).
OCR_BACKEND = os.environ.get("OCR_BACKEND", "textract").lower()

# Preguntas Textract (alias → pregunta) para los campos escalares del comprobante.
# (máx. 15 por análisis; los renglones de productos salen de las TABLAS.)
TEXTRACT_QUERIES = [
    ("rfcEmisor",    "¿Cuál es el RFC del emisor?"),
    ("rfcReceptor",  "¿Cuál es el RFC del receptor?"),
    ("subtotal",     "¿Cuál es el subtotal sin IVA?"),
    ("moneda",       "¿Cuál es la moneda?"),
    ("tipoCambio",   "¿Cuál es el tipo de cambio?"),
    ("folio",        "¿Cuál es el folio?"),
    ("fecha",        "¿Cuál es la fecha de emisión?"),
    ("comentarios",  "¿Cuáles son los comentarios?"),
    ("origenEstado", "¿Cuál es el estado de origen?"),
    ("origenCiudad", "¿Cuál es la ciudad o municipio de origen?"),
    ("destinoEstado", "¿Cuál es el estado de destino?"),
    ("destinoCiudad", "¿Cuál es la ciudad o municipio de destino?"),
]

# Instrucción de extracción para Claude. Pide JSON estricto por página.
PROMPT_OCR = (
    "Eres un extractor de datos de comprobantes fiscales mexicanos (CFDI 4.0). "
    "La imagen es UNA página de un comprobante escaneado (carta porte o factura). "
    "Devuelve EXCLUSIVAMENTE un objeto JSON, sin texto adicional, con estas claves:\n"
    '  "rfcEmisor": string|null   (RFC de quien EMITE el comprobante)\n'
    '  "rfcReceptor": string|null (RFC de quien RECIBE)\n'
    '  "tipoDocumento": "CARTA_PORTE"|"FACTURA"|"CFDI"|"OTRO"\n'
    '  "subtotal": number|null    (Sub-Total SIN IVA, solo el número)\n'
    '  "moneda": "MXN"|"USD"|null\n'
    '  "tipoCambio": number|null  (si aparece "Tipo de Cambio")\n'
    '  "folio": string|null       (folio o serie-folio del comprobante)\n'
    '  "fecha": string|null        (fecha de emisión en formato YYYY-MM-DD)\n'
    '  "comentarios": string|null (texto del campo Comentarios; suele enlazar la FV: "F-40086093")\n'
    '  "origenEstado": string|null, "origenCiudad": string|null\n'
    '  "destinoEstado": string|null, "destinoCiudad": string|null\n'
    '  "fletaRFC": string|null    (RFC de la fletera/transportista, = emisor del CP)\n'
    '  "partidas": [ {"descripcion": string, "cantidad": number, "importe": number, '
    '"pesoKg": number|null, "volumenL": number|null, "presentacion": string|null, '
    '"claveSat": string|null} ]  (renglones de productos; [] si no aplica)\n'
    "    pesoKg/volumenL/presentacion = tamaño/presentación de UNA unidad del producto "
    '(p.ej. "50 KGS", "20 L"); es el factor que define si el producto es excluido por '
    "tamaño. Extrae el número del peso/volumen de la descripción si viene ahí.\n"
    "Si la página no es un comprobante (anexo, acuse, etc.), usa tipoDocumento=OTRO "
    "y los demás en null/[]."
)


# ── Render PDF → imágenes PNG por página ──────────────────────────
def render_paginas_pdf(pdf_bytes: bytes, dpi: int = OCR_DPI) -> list[bytes]:
    """Convierte cada página del PDF a PNG. Requiere PyMuPDF (pymupdf)."""
    import fitz  # PyMuPDF
    paginas: list[bytes] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            paginas.append(pix.tobytes("png"))
    finally:
        doc.close()
    return paginas


# ── OCR de una página — backend conmutable (OCR_BACKEND) ──────────
def ocr_pagina(imagen_png: bytes, client=None) -> dict:
    """Extrae los campos del comprobante de UNA página (Textract o Bedrock)."""
    if OCR_BACKEND == "bedrock":
        return _ocr_bedrock(imagen_png, client=client)
    return _ocr_textract(imagen_png, client=client)


# --- Backend 1: Amazon Textract (nativo AWS, recomendado) ---------
def _ocr_textract(imagen_png: bytes, client=None) -> dict:
    client = client or boto3.client("textract")
    resp = client.analyze_document(
        Document={"Bytes": imagen_png},
        FeatureTypes=["QUERIES", "TABLES"],
        QueriesConfig={"Queries": [{"Text": t, "Alias": a} for a, t in TEXTRACT_QUERIES]},
    )
    return _parse_textract(resp)


def _parse_textract(resp: dict) -> dict:
    """Convierte la respuesta de Textract (QUERIES + TABLES) al dict de página."""
    blocks = resp.get("Blocks", [])
    by_id = {b["Id"]: b for b in blocks}

    def _texto(block):
        out = []
        for rel in block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for cid in rel["Ids"]:
                    w = by_id.get(cid, {})
                    if w.get("BlockType") in ("WORD", "SELECTION_ELEMENT"):
                        out.append(w.get("Text", ""))
        return " ".join(out).strip()

    # Campos escalares desde las QUERIES
    campos = {}
    for b in blocks:
        if b.get("BlockType") == "QUERY":
            ans = None
            for rel in b.get("Relationships", []):
                if rel["Type"] == "ANSWER":
                    ans = by_id.get(rel["Ids"][0], {}).get("Text")
            campos[b.get("Query", {}).get("Alias")] = ans

    return {
        "rfcEmisor":     campos.get("rfcEmisor"),
        "rfcReceptor":   campos.get("rfcReceptor"),
        "subtotal":      _num(campos.get("subtotal")),
        "moneda":        (campos.get("moneda") or "").upper() or None,
        "tipoCambio":    _num(campos.get("tipoCambio")) or None,
        "folio":         campos.get("folio"),
        "fecha":         campos.get("fecha"),
        "comentarios":   campos.get("comentarios"),
        "origenEstado":  campos.get("origenEstado"),
        "origenCiudad":  campos.get("origenCiudad"),
        "destinoEstado": campos.get("destinoEstado"),
        "destinoCiudad": campos.get("destinoCiudad"),
        "fletaRFC":      campos.get("rfcEmisor"),   # en un CP, la fletera es el emisor
        "partidas":      _partidas_de_tablas(blocks, by_id, _texto),
    }


def _partidas_de_tablas(blocks, by_id, texto_celda) -> list[dict]:
    """Extrae renglones de productos de las TABLAS de conceptos de Textract."""
    partidas = []
    for tbl in blocks:
        if tbl.get("BlockType") != "TABLE":
            continue
        filas = {}
        for rel in tbl.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue
            for cid in rel["Ids"]:
                c = by_id.get(cid, {})
                if c.get("BlockType") == "CELL":
                    filas.setdefault(c["RowIndex"], {})[c["ColumnIndex"]] = texto_celda(c)
        # Mapear columnas por la cabecera (fila 1)
        col = {}
        for idx, txt in filas.get(1, {}).items():
            t = txt.upper()
            if "DESCRIP" in t or "CONCEPTO" in t:   col["descripcion"] = idx
            elif "CANT" in t:                       col["cantidad"] = idx
            elif "IMPORTE" in t or "TOTAL" in t:    col["importe"] = idx
        if "descripcion" not in col or "importe" not in col:
            continue   # no parece una tabla de conceptos
        for r in sorted(filas):
            if r == 1:
                continue
            row = filas[r]
            desc = (row.get(col["descripcion"]) or "").strip()
            if not desc:
                continue
            partidas.append({
                "descripcion": desc,
                "cantidad": _num(row.get(col.get("cantidad"))) or 1,
                "importe": _num(row.get(col.get("importe"))),
            })
    return partidas


# --- Backend 2: Amazon Bedrock (Claude visión) --------------------
def _ocr_bedrock(imagen_png: bytes, client=None, model_id: str = BEDROCK_MODEL_ID) -> dict:
    client = client or boto3.client("bedrock-runtime")
    resp = client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"text": PROMPT_OCR},
                {"image": {"format": "png", "source": {"bytes": imagen_png}}},
            ],
        }],
        inferenceConfig={"maxTokens": 4096, "temperature": 0},
    )
    texto = resp["output"]["message"]["content"][0]["text"]
    return _parse_json(texto)


def _parse_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta del modelo (Bedrock)."""
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini == -1 or fin == -1 or fin < ini:
        raise ValueError(f"OCR no devolvió JSON: {texto[:200]!r}")
    return json.loads(texto[ini:fin + 1])


# ── Clasificación por rol del RFC de GPA ──────────────────────────
def clasificar_por_rfc(rfc_emisor: Optional[str], rfc_receptor: Optional[str],
                       rfc_gpa: str = RFC_GPA) -> str:
    """'FV' si GPA emite, 'CP' si GPA recibe, 'ERROR' si GPA no aparece."""
    g = (rfc_gpa or "").strip().upper()
    e = (rfc_emisor or "").strip().upper()
    r = (rfc_receptor or "").strip().upper()
    if e == g:
        return "FV"
    if r == g:
        return "CP"
    return "ERROR"


def _num(valor) -> float:
    """Extrae el primer número de un texto, tolerando $, comas (miles) y unidades.

    Ej: "$3,330.00 MXN" → 3330.0, "17.55" → 17.55, "Total: 4.41 USD" → 4.41.
    Devuelve 0.0 si no hay número (en vez de fallar silenciosamente).
    """
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).replace(",", "")          # quitar separador de miles
    m = re.search(r"-?\d+(?:\.\d+)?", s)      # primer número
    return float(m.group()) if m else 0.0


# ── Armado del caso (1 PDF) → datos para evaluar ──────────────────
def armar_caso(paginas: list[dict], folio_archivo: str = "") -> dict:
    """
    A partir de las páginas OCR de UN PDF, arma el caso de flete.

    Devuelve dict con:
      status: "OK" | "ERROR"
      Si OK: folioCP, foliosFV, fleteSinIvaMXN, montoVentaFV, monedaFV,
             tipoCambioRef, paginasCP/FV/Error.
      Si ERROR: error (código), detalle.
    """
    cps, fvs, ajenas = [], [], []
    for p in paginas:
        clase = clasificar_por_rfc(p.get("rfcEmisor"), p.get("rfcReceptor"))
        (cps if clase == "CP" else fvs if clase == "FV" else ajenas).append(p)

    if not cps:
        return {"status": "ERROR", "error": "SIN_CARTA_PORTE",
                "detalle": "Ninguna página tiene a GPA como RECEPTOR (no hay CP).",
                "folioArchivo": folio_archivo, "paginasError": len(ajenas)}
    if not fvs:
        return {"status": "ERROR", "error": "SIN_FACTURA_GPA",
                "detalle": "Ninguna página tiene a GPA como EMISOR (no hay FV).",
                "folioArchivo": folio_archivo, "paginasError": len(ajenas)}

    flete_sin_iva = sum(_num(cp.get("subtotal")) for cp in cps)   # MXN (suma de CP)
    monto_venta   = sum(_num(fv.get("subtotal")) for fv in fvs)   # moneda de la FV
    fv0 = fvs[0]
    moneda = (fv0.get("moneda") or "USD").upper()
    tc = _num(fv0.get("tipoCambio")) or None

    if ajenas:
        logger.warning("Caso %s: %d página(s) con RFC ajeno a GPA (ignoradas).",
                       folio_archivo, len(ajenas))

    return {
        "status": "OK",
        "folioCP": str(cps[0].get("folio") or folio_archivo),
        "foliosFV": [str(fv.get("folio") or "") for fv in fvs],
        "fleteSinIvaMXN": flete_sin_iva,
        "montoVentaFV": monto_venta,
        "monedaFV": moneda,
        "tipoCambioRef": tc,
        "paginasCP": len(cps),
        "paginasFV": len(fvs),
        "paginasError": len(ajenas),
    }


# ── Varios CP/FV en un PDF → varios casos (1 caso por CP) ─────────
def _folios_referenciados(comentarios: Optional[str]) -> list[str]:
    """Folios de FV referenciados en Comentarios del CP (p.ej. 'F-40086093')."""
    if not comentarios:
        return []
    return re.findall(r"F[-\s]?0*(\d{4,})", comentarios.upper())


def _digitos(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


def _fv_coincide(fv_folio: Optional[str], refs: list[str]) -> bool:
    d = _digitos(fv_folio)
    if not d or not refs:
        return False
    return any(d == r or d.endswith(r) or r.endswith(d) for r in refs)


def _construir_caso(cp: dict, fvs: list[dict], folio_archivo: str) -> dict:
    if not fvs:
        return {"status": "ERROR", "error": "SIN_FV_VINCULADA",
                "detalle": f"El CP {cp.get('folio')} no tiene FV de GPA emparejada.",
                "folioCP": cp.get("folio"), "folioArchivo": folio_archivo}
    partidas = [pt for fv in fvs for pt in (fv.get("partidas") or [])]
    fv0 = fvs[0]
    moneda = (fv0.get("moneda") or "USD").upper()
    tc = _num(fv0.get("tipoCambio")) or None
    # El flete (CP) SIEMPRE viene en MXN y los mínimos de C1 son en USD, así que el
    # tipo de cambio se necesita siempre (convertir flete y, si la FV es MXN, el monto).
    # Sin TC válido, mejor marcar para revisión que evaluar con un valor inventado.
    if not tc:
        return {"status": "ERROR", "error": "SIN_TIPO_CAMBIO",
                "detalle": f"FV {fv0.get('folio')} sin tipo de cambio; requiere revisión "
                           "(el flete está en MXN y los mínimos en USD).",
                "folioCP": cp.get("folio"), "folioArchivo": folio_archivo}
    return {
        "status": "OK",
        "folioCP": str(cp.get("folio") or folio_archivo),
        "foliosFV": [str(fv.get("folio") or "") for fv in fvs],
        "fletaRFC": cp.get("fletaRFC") or cp.get("rfcEmisor"),
        "fleteSinIvaMXN": _num(cp.get("subtotal")),
        "montoVentaFV": sum(_num(fv.get("subtotal")) for fv in fvs),
        "monedaFV": moneda,
        "tipoCambioRef": tc,
        "origenEstado": cp.get("origenEstado"),
        "origenCiudad": cp.get("origenCiudad"),
        # Sucursal derivada del ORIGEN real (no de la facturación); '' si no es plaza GPA
        "origenSucursal": sucursal_de_origen(cp.get("origenCiudad"), cp.get("origenEstado")),
        "destinoEstado": cp.get("destinoEstado"),
        "destinoCiudad": cp.get("destinoCiudad"),
        "fechaEmision": cp.get("fecha") or fv0.get("fecha") or "",
        "partidas": partidas,
    }


def emparejar_casos(paginas: list[dict], folio_archivo: str = "") -> dict:
    """
    De las páginas OCR de UN PDF (que puede traer varios CP y varias FV) arma
    UN caso por cada CP, emparejando su(s) FV por el folio del campo Comentarios.
    """
    cps, fvs, ajenas = [], [], []
    for p in paginas:
        clase = clasificar_por_rfc(p.get("rfcEmisor"), p.get("rfcReceptor"))
        (cps if clase == "CP" else fvs if clase == "FV" else ajenas).append(p)

    casos, usadas = [], set()
    unico = (len(cps) == 1 and len(fvs) == 1)   # un solo CP + una sola FV
    for cp in cps:
        refs = _folios_referenciados(cp.get("comentarios"))
        match = []
        for i, fv in enumerate(fvs):
            if _fv_coincide(fv.get("folio"), refs):
                match.append(fv)
                usadas.add(i)
        # Fallback: si hay exactamente 1 CP y 1 FV y el comentario no los enlazó
        # (o el OCR no lo captó), emparejarlos de todos modos.
        if not match and unico:
            match = [fvs[0]]
            usadas.add(0)
        casos.append(_construir_caso(cp, match, folio_archivo))

    fvs_sin_cp = [fvs[i].get("folio") for i in range(len(fvs)) if i not in usadas]
    return {"casos": casos, "totalCP": len(cps), "totalFV": len(fvs),
            "fvsSinCP": fvs_sin_cp, "paginasAjenas": len(ajenas),
            "folioArchivo": folio_archivo}


# ── Caso → entrada del endpoint /evaluar ──────────────────────────
def caso_a_solicitud(caso: dict, fecha_emision: str = "") -> dict:
    """Convierte un caso OK (de emparejar_casos) al dict plano para POST /evaluar.

    El monto del motor (y los mínimos de C1) son en USD. Si la FV viene en MXN,
    los precios de las partidas se convierten a USD con el tipo de cambio. El flete
    se deja en MXN (el motor lo convierte con tipoCambioRef).
    """
    tc = caso.get("tipoCambioRef") or 1.0
    moneda = (caso.get("monedaFV") or "USD").upper()
    factor_usd = (1.0 / tc) if moneda == "MXN" else 1.0   # partidas MXN → USD
    partidas = []
    for p in caso.get("partidas", []):
        cant = _num(p.get("cantidad")) or 1.0
        partidas.append({
            "descripcion": p.get("descripcion", ""),
            "cantidad": cant,
            "precioUnitarioUSD": (_num(p.get("importe")) / cant) * factor_usd,
            "pesoKg": _num(p.get("pesoKg")),
            "volumenL": _num(p.get("volumenL")),
        })
    return {
        "folioCP": caso["folioCP"],
        "foliosFV": caso["foliosFV"],
        "origenSucursal": caso.get("origenSucursal", ""),
        "destinoEstado": caso.get("destinoEstado") or "",
        "destinoCiudad": caso.get("destinoCiudad") or "",
        "fletaRFC": caso.get("fletaRFC") or "",
        "partidas": partidas,
        "fleteBaseMXN": caso.get("fleteSinIvaMXN", 0.0),
        "tipoCambioRef": tc,
        "campoEntregaFV": "ENTREGA_DOMICILIO",
        "fechaEmision": fecha_emision or caso.get("fechaEmision") or "",
    }


# ── Orquestación end-to-end (S3 → OCR → casos) ────────────────────
def procesar_pdf(pdf_bytes: bytes, folio_archivo: str = "", client=None) -> dict:
    """Renderiza el PDF, hace OCR de cada página y arma los casos (1 por CP)."""
    paginas_img = render_paginas_pdf(pdf_bytes)
    paginas = []
    for i, img in enumerate(paginas_img):
        try:
            paginas.append(ocr_pagina(img, client=client))
        except Exception as exc:   # una página ilegible no tumba el lote
            logger.warning("OCR falló en página %d de %s: %s", i + 1, folio_archivo, exc)
            paginas.append({"tipoDocumento": "OTRO"})
    return emparejar_casos(paginas, folio_archivo)


def procesar_objeto_s3(bucket: str, key: str, s3_client=None, bedrock_client=None) -> dict:
    """Descarga el PDF de S3 y devuelve los casos (emparejar_casos)."""
    s3 = s3_client or boto3.client("s3")
    pdf_bytes = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    folio = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return procesar_pdf(pdf_bytes, folio_archivo=folio, client=bedrock_client)
