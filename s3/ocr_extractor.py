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
import unicodedata
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
def _query_ascii(texto: str) -> str:
    """El feature Queries de Textract SOLO admite ASCII: acentos y signos como
    '¿' provocan InvalidParameterException ("Request has invalid parameters") y
    rompen el OCR de TODO documento. Plegamos a ASCII (quitando diacríticos y
    cualquier carácter no-ASCII) manteniendo el español legible en el código."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.encode("ascii", "ignore").decode("ascii").strip()


def _ocr_textract(imagen_png: bytes, client=None) -> dict:
    client = client or boto3.client("textract")
    resp = client.analyze_document(
        Document={"Bytes": imagen_png},
        FeatureTypes=["QUERIES", "TABLES"],
        QueriesConfig={"Queries": [{"Text": _query_ascii(t), "Alias": a} for a, t in TEXTRACT_QUERIES]},
    )
    return _parse_textract(resp)


# ── Parseo robusto desde el texto crudo ───────────────────────────
# Las *Queries* de Textract son poco fiables en estos escaneos (devuelven el
# nombre de la empresa en vez del RFC, una etiqueta en vez del receptor, el UUID
# en vez del folio…). Por eso reforzamos cada campo con el texto crudo (bloques
# LINE + geometría) y dejamos la Query solo como una señal más.

# RFC mexicano: 3-4 letras (incluye Ñ y &) + 6 dígitos de fecha + 3 de homoclave.
_RFC_RE  = re.compile(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}")
# Variante de BÚSQUEDA tolerante a separadores: algunas plantillas imprimen el RFC
# con guiones/puntos/espacios (p.ej. "GPA-840221-9Y1" en las facturas de GPA, vs
# "GPA8402219Y1" pegado en las cartas porte). Se normaliza quitando separadores.
_RFC_FIND_RE = re.compile(r"[A-ZÑ&]{3,4}[-.\s]?\d{6}[-.\s]?[A-Z0-9]{3}")
# Folio fiscal (UUID) del CFDI: NO es el folio serie-número que se necesita.
_UUID_RE = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", re.I)


def _norm_rfc(s) -> Optional[str]:
    """RFC normalizado (mayúsculas, sin separadores) si es válido; si no, None.
    Quita guiones/puntos/espacios: 'GPA-840221-9Y1' → 'GPA8402219Y1'."""
    if not s:
        return None
    t = re.sub(r"[-.\s]", "", str(s)).upper()
    return t if _RFC_RE.fullmatch(t) else None


def _lineas_texto(blocks) -> list[dict]:
    """Líneas OCR con su geometría: [{'text','top','left'}], en orden de lectura."""
    out = []
    for b in blocks:
        if b.get("BlockType") == "LINE":
            bb = (b.get("Geometry") or {}).get("BoundingBox") or {}
            out.append({"text": b.get("Text", ""),
                        "top": float(bb.get("Top", 0.0)),
                        "left": float(bb.get("Left", 0.0))})
    return out


def _rfcs_en_lineas(lineas) -> list[dict]:
    """Todos los RFC del texto crudo, con su posición [{'rfc','top','left'}].
    Tolera RFC con separadores (guiones/puntos) y los normaliza."""
    res = []
    for ln in lineas:
        for m in _RFC_FIND_RE.finditer(ln["text"].upper()):
            tok = re.sub(r"[-.\s]", "", m.group())
            if _RFC_RE.fullmatch(tok):
                res.append({"rfc": tok, "top": ln["top"], "left": ln["left"]})
    return res


def _rfc_cerca_de(labels, rfcs_pos, lineas) -> Optional[str]:
    """RFC más cercano (preferentemente por debajo) a la primera etiqueta dada."""
    tops = [ln["top"] for ln in lineas if any(k in ln["text"].upper() for k in labels)]
    if not tops or not rfcs_pos:
        return None
    lt = min(tops)
    cand = sorted(rfcs_pos, key=lambda r: (0 if r["top"] >= lt else 1, abs(r["top"] - lt)))
    return cand[0]["rfc"]


def _emisor_receptor(eq, rq, rfcs_pos, lineas):
    """(emisor, receptor) combinando las Queries (si son RFC válidos), las
    etiquetas Emisor/Receptor y, en último caso, el orden de lectura."""
    if eq and rq:
        return eq, rq
    uniq = list(dict.fromkeys(
        r["rfc"] for r in sorted(rfcs_pos, key=lambda x: (round(x["top"], 3), x["left"]))))
    emisor   = eq or _rfc_cerca_de(["EMISOR"],   rfcs_pos, lineas) or (uniq[0] if uniq else None)
    receptor = rq or _rfc_cerca_de(["RECEPTOR"], rfcs_pos, lineas) or (uniq[1] if len(uniq) > 1 else None)
    if emisor and receptor == emisor and len(uniq) > 1:
        receptor = next((u for u in uniq if u != emisor), receptor)
    return emisor, receptor


def _tipo_documento(lineas) -> Optional[str]:
    """Tipo por palabras clave: CP (carta porte/traslado) o FV (ingreso/factura)."""
    txt = " ".join(ln["text"] for ln in lineas).upper()
    if "CARTA PORTE" in txt or "CARTAPORTE" in txt or "TRASLADO" in txt:
        return "CP"
    if "INGRESO" in txt or "FACTURA" in txt:
        return "FV"
    return None


def _monto_cerca_de(labels, lineas) -> Optional[float]:
    """Mayor monto con decimales en la línea que contiene la etiqueta (p.ej. Sub-Total)."""
    for ln in lineas:
        u = ln["text"].upper()
        if any(k in u for k in labels):
            nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+\.\d{2}", ln["text"])]
            if nums:
                return max(nums)
    return None


def _folio_no_fiscal(lineas) -> Optional[str]:
    """Folio (serie-número) cerca de 'Folio', excluyendo 'Folio Fiscal'/UUID."""
    for ln in lineas:
        u = ln["text"].upper()
        if "FOLIO" in u and "FISCAL" not in u and not _UUID_RE.search(ln["text"]):
            m = re.search(r"FOLIO\W*([A-Z]{0,3}[-\s]?\d{3,})", u)
            if m:
                return m.group(1).replace(" ", "")
    return None


def _parse_textract(resp: dict) -> dict:
    """Convierte la respuesta de Textract (QUERIES + TABLES + LINES) al dict de página."""
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

    # Campos escalares desde las QUERIES (señal débil; se valida/repara abajo)
    campos = {}
    for b in blocks:
        if b.get("BlockType") == "QUERY":
            ans = None
            for rel in b.get("Relationships", []):
                if rel["Type"] == "ANSWER":
                    ans = by_id.get(rel["Ids"][0], {}).get("Text")
            campos[b.get("Query", {}).get("Alias")] = ans

    # --- Refuerzo con texto crudo ---
    lineas = _lineas_texto(blocks)
    rfcs_pos = _rfcs_en_lineas(lineas)
    rfcs_detectados = list(dict.fromkeys(r["rfc"] for r in rfcs_pos))
    tipo_doc = _tipo_documento(lineas)
    emisor, receptor = _emisor_receptor(_norm_rfc(campos.get("rfcEmisor")),
                                        _norm_rfc(campos.get("rfcReceptor")),
                                        rfcs_pos, lineas)

    # Alinear roles con GPA: en un CP, GPA es receptor; en una FV, GPA es emisor.
    # Así el RFC de la fletera (emisor del CP) queda correcto y la clasificación es directa.
    g = (RFC_GPA or "").strip().upper()
    if g and g in rfcs_detectados:
        otros = [r for r in rfcs_detectados if r != g]
        if tipo_doc == "CP":
            receptor = g
            if not emisor or emisor == g:
                emisor = otros[0] if otros else emisor
        elif tipo_doc == "FV":
            emisor = g
            if not receptor or receptor == g:
                receptor = otros[0] if otros else receptor

    # Folio: descartar el UUID (folio fiscal); preferir serie-número cerca de "Folio".
    folio = campos.get("folio")
    if folio and _UUID_RE.search(str(folio)):
        folio = None
    folio = folio or _folio_no_fiscal(lineas)

    # Subtotal: preferir el monto junto a la etiqueta Sub-Total (la Query suele tomar
    # una línea suelta); caer a la Query solo si no se halló la etiqueta.
    subtotal = _monto_cerca_de(["SUB-TOTAL", "SUBTOTAL", "SUB TOTAL"], lineas)
    if subtotal is None:
        subtotal = _num(campos.get("subtotal"))

    return {
        "rfcEmisor":     emisor,
        "rfcReceptor":   receptor,
        "rfcsDetectados": rfcs_detectados,
        "tipoDoc":       tipo_doc,
        "subtotal":      subtotal,
        "moneda":        (campos.get("moneda") or "").upper() or None,
        "tipoCambio":    _num(campos.get("tipoCambio")) or None,
        "folio":         folio,
        "fecha":         campos.get("fecha"),
        "comentarios":   campos.get("comentarios"),
        "origenEstado":  campos.get("origenEstado"),
        "origenCiudad":  campos.get("origenCiudad"),
        "destinoEstado": campos.get("destinoEstado"),
        "destinoCiudad": campos.get("destinoCiudad"),
        "fletaRFC":      emisor,   # en un CP, la fletera es el emisor
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


def clasificar_pagina(p: dict, rfc_gpa: str = RFC_GPA) -> str:
    """Clasifica una página combinando señales: rol del RFC (emisor/receptor) y,
    como respaldo, presencia del RFC de GPA en el texto + tipo de documento."""
    c = clasificar_por_rfc(p.get("rfcEmisor"), p.get("rfcReceptor"), rfc_gpa)
    if c in ("CP", "FV"):
        return c
    # Respaldo: GPA aparece en el documento pero los roles no quedaron claros.
    g = (rfc_gpa or "").strip().upper()
    if g and g in [str(r).upper() for r in (p.get("rfcsDetectados") or [])]:
        tipo = (p.get("tipoDoc") or "").upper()
        if tipo in ("CP", "FV"):
            return tipo
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
        clase = clasificar_pagina(p)
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
        clase = clasificar_pagina(p)
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
    # Observabilidad: un PDF que no arma casos antes desaparecía sin rastro.
    if not casos:
        logger.warning("%s: 0 casos (CP=%d FV=%d ajenas=%d). RFCs detectados: %s",
                       folio_archivo or "PDF", len(cps), len(fvs), len(ajenas),
                       sorted({r for p in paginas for r in (p.get("rfcsDetectados") or [])}))
    else:
        logger.info("%s: %d caso(s) (CP=%d FV=%d ajenas=%d)",
                    folio_archivo or "PDF", len(casos), len(cps), len(fvs), len(ajenas))
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
