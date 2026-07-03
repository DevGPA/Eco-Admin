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
from collections import Counter
from typing import Optional

import boto3

from motor.catalogos import (RFC_GPA, sucursal_de_origen, FLETERAS_AUTORIZADAS,
                             fletera_por_nombre)

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
    """Tipo por palabras clave. CP se detecta ANTES que FV porque una carta porte
    también dice 'INGRESO' ('CARTA DE PORTE DE INGRESOS', 'TIPO COMPROBANTE: I')."""
    txt = " ".join(ln["text"] for ln in lineas).upper()
    if any(k in txt for k in ("CARTA PORTE", "CARTA DE PORTE", "CARTAPORTE",
                              "COMPLEMENTO CARTA", "PORTE DE INGRESO", "TRASLADO")):
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


_MESES_ES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
             "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}


def _fecha_iso(valor) -> Optional[str]:
    """Normaliza la fecha OCR a YYYY-MM-DD. Las fechas se guardan como RANGE
    key de los GSI y se filtran por rango lexicográfico: '12/05/2026' rompería
    todas las consultas por fecha. Devuelve None si no se reconoce."""
    if not valor:
        return None
    s = str(valor).strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)              # ya ISO
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)        # dd/mm/yyyy
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})", s.upper())
    if m:                                                          # 12 de mayo de 2026
        mes = _MESES_ES.get(m.group(2)[:3])
        if mes:
            return f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}"
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
                # Preferir un RFC AUTORIZADO; luego la razón social en el texto
                # (membrete-imagen); nunca un RFC arbitrario del documento.
                emisor = (next((r for r in otros if r in FLETERAS_AUTORIZADAS), None)
                          or fletera_por_nombre(" ".join(ln["text"] for ln in lineas))
                          or (otros[0] if otros else emisor))
        elif tipo_doc == "FV":
            emisor = g
            if not receptor or receptor == g:
                receptor = otros[0] if otros else receptor

    # Folio: descartar el UUID (folio fiscal); preferir serie-número cerca de "Folio".
    folio = campos.get("folio")
    if folio and _UUID_RE.search(str(folio)):
        folio = None
    folio = folio or _folio_no_fiscal(lineas)

    # Subtotal: por geometría (etiqueta → valor en la misma fila, aunque estén en
    # líneas separadas, que es lo común en la factura GPA), luego misma-línea, y
    # por último la Query (poco fiable). Sin esto el OCR de la factura tomaba un
    # monto suelto y daba R-101 falsos.
    subtotal = (_valor_etiqueta(["SUB-TOTAL", "SUBTOTAL", "SUB TOTAL", "SUMA"], lineas)
                or _monto_cerca_de(["SUB-TOTAL", "SUBTOTAL", "SUB TOTAL"], lineas)
                or _num(campos.get("subtotal")))

    return {
        "rfcEmisor":     emisor,
        "rfcReceptor":   receptor,
        "rfcsDetectados": rfcs_detectados,
        "tipoDoc":       tipo_doc,
        "subtotal":      subtotal,
        "moneda":        (campos.get("moneda") or "").upper() or None,
        "tipoCambio":    _num(campos.get("tipoCambio")) or None,
        "folio":         folio,
        # Fecha: la Query es poco fiable → reforzar con el texto crudo (primero
        # las líneas con la etiqueta FECHA, luego cualquier fecha del documento).
        "fecha":         (_fecha_iso(campos.get("fecha"))
                          or _fecha_iso(" ".join(ln["text"] for ln in lineas
                                                 if "FECHA" in ln["text"].upper()))
                          or _fecha_iso(" ".join(ln["text"] for ln in lineas))),
        "comentarios":   campos.get("comentarios"),
        "origenEstado":  campos.get("origenEstado"),
        "origenCiudad":  campos.get("origenCiudad"),
        "destinoEstado": campos.get("destinoEstado"),
        "destinoCiudad": campos.get("destinoCiudad"),
        "fletaRFC":      emisor,   # en un CP, la fletera es el emisor
        "fleteraTexto":  fletera_por_nombre(" ".join(ln["text"] for ln in lineas)),
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


def _fv_consolidada(pages: list[dict]) -> dict:
    """Funde las páginas OCR de UNA factura en una sola FV. Como cada página de la
    factura REPITE el Sub-Total (no es acumulable), el subtotal representativo es el
    valor que más se repite; si todas difieren, el mayor (suele ser el total)."""
    subs = [round(_num(p.get("subtotal")), 2) for p in pages if _num(p.get("subtotal")) > 0]
    if subs:
        conteo = Counter(subs).most_common(1)[0]
        subtotal = conteo[0] if conteo[1] > 1 else max(subs)
    else:
        subtotal = 0.0
    base = next((p for p in pages if p.get("tipoCambio")), pages[0])
    return {
        "subtotal":    subtotal,
        "moneda":      next((p.get("moneda") for p in pages if p.get("moneda")), base.get("moneda")),
        "tipoCambio":  next((p.get("tipoCambio") for p in pages if p.get("tipoCambio")), None),
        "folio":       next((p.get("folio") for p in pages if p.get("folio")), None),
        "comentarios": base.get("comentarios"),
        "fleteraTexto": next((p.get("fleteraTexto") for p in pages if p.get("fleteraTexto")), ""),
        "rfcEmisor":   base.get("rfcEmisor"),
        "partidas":    [pt for p in pages for pt in (p.get("partidas") or [])],
    }


def _consolidar_fvs(fv_pages: list[dict]) -> list[dict]:
    """Agrupa páginas FV en facturas (1 FV por factura) por orden de lectura:
    - un folio NUEVO inicia una factura distinta (se sumarán entre sí);
    - mismo folio, o página sin folio (continuación), pertenece a la factura en curso
      (su Sub-Total se repite, NO se suma).
    Así varias facturas de un CP siguen sumándose, pero una factura multipágina cuenta
    una sola vez."""
    grupos = []
    for p in fv_pages:
        d = _digitos(p.get("folio"))
        if grupos and (not d or d == _digitos(grupos[-1][0].get("folio"))):
            grupos[-1].append(p)        # continuación / misma factura
        else:
            grupos.append([p])          # folio nuevo → factura distinta
    return [_fv_consolidada(g) for g in grupos]


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
        # Fletera a nivel CASO: RFC del CP; si va en el logo, la razón social
        # detectada en el texto del CP o de la FV ("Embarcar por: TRES GUERRAS").
        "fletaRFC": (cp.get("fletaRFC") or cp.get("rfcEmisor")
                     or cp.get("fleteraTexto")
                     or next((fv.get("fleteraTexto") for fv in fvs if fv.get("fleteraTexto")), "")),
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

    # Una carta porte de COBRO trae su flete (Sub-Total). Las páginas del
    # complemento Carta Porte 3.1 (UBICACIONES, FIGURA TRANSPORTE…) también
    # clasifican como CP pero NO tienen importe: son continuación, no un 2º caso.
    # Anclar los casos solo en las CP con flete; si NINGUNA lo trae (no se pudo
    # leer), usar todas (mejor que perder el caso). Esto evita que un complemento
    # fantasma rompa el emparejado 1-CP→factura (daba SIN_FV_VINCULADA).
    cps_con_flete = [p for p in cps if _num(p.get("subtotal")) > 0]
    cps = cps_con_flete or cps

    # CP MULTIPÁGINA (lote real 29-06): una carta porte impresa en 2+ páginas
    # REPITE su Sub-Total en cada una (igual que las facturas). Dos páginas CP
    # consecutivas con el MISMO subtotal y folios no contradictorios son UNA
    # carta porte, no dos casos — contarlas doble rompía el emparejado
    # (SIN_FV_VINCULADA) o duplicaría el caso. Subtotales distintos = CPs
    # distintas (se respetan).
    consolidadas = []
    for p in cps:
        prev = consolidadas[-1] if consolidadas else None
        mismo_sub = prev is not None and round(_num(p.get("subtotal")), 2) == round(_num(prev.get("subtotal")), 2)
        dp, dq = _digitos(p.get("folio")), _digitos(prev.get("folio")) if prev else ""
        mismo_folio = (not dp) or (not dq) or dp == dq
        if prev is not None and mismo_sub and mismo_folio:
            # continuación: completar campos que la primera página no trajo
            for k, v in p.items():
                if prev.get(k) in (None, "", []) and v not in (None, "", []):
                    prev[k] = v
        else:
            consolidadas.append(dict(p))
    cps = consolidadas

    # Consolidar páginas FV en facturas (una factura multipágina = UNA FV, sin sumar
    # su Sub-Total repetido). Si hay una sola carta porte, todas las páginas FV del
    # PDF son su factura.
    facturas = _consolidar_fvs(fvs)

    casos, usadas = [], set()
    for cp in cps:
        refs = _folios_referenciados(cp.get("comentarios"))
        match = []
        for i, fv in enumerate(facturas):
            if _fv_coincide(fv.get("folio"), refs):
                match.append(fv)
                usadas.add(i)
        # Si los Comentarios del CP enlazan folios de FV → esas facturas (se suman).
        # Si NO hay enlace y el PDF trae un solo CP, TODAS las facturas del PDF son
        # suyas: 1 factura (multipágina, ya sin duplicar su Sub-Total) o N facturas
        # distintas, en cuyo caso se SUMAN sus subtotales (cada folio = una factura).
        # Con varios CP sin enlace no se puede desambiguar a ciegas → SIN_FV_VINCULADA.
        if not match and len(cps) == 1 and facturas:
            match = list(facturas)
            usadas.update(range(len(facturas)))
        casos.append(_construir_caso(cp, match, folio_archivo))

    fvs_sin_cp = [facturas[i].get("folio") for i in range(len(facturas)) if i not in usadas]
    # Observabilidad: un PDF que no arma casos antes desaparecía sin rastro.
    if not casos:
        logger.warning("%s: 0 casos (CP=%d FV_pag=%d facturas=%d ajenas=%d). RFCs: %s",
                       folio_archivo or "PDF", len(cps), len(fvs), len(facturas), len(ajenas),
                       sorted({r for p in paginas for r in (p.get("rfcsDetectados") or [])}))
    else:
        logger.info("%s: %d caso(s) (CP=%d FV_pag=%d facturas=%d ajenas=%d)",
                    folio_archivo or "PDF", len(casos), len(cps), len(fvs), len(facturas), len(ajenas))
    return {"casos": casos, "totalCP": len(cps), "totalFV": len(fvs),
            "totalFacturas": len(facturas), "fvsSinCP": fvs_sin_cp,
            "paginasAjenas": len(ajenas), "folioArchivo": folio_archivo}


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
        # Monto de la venta = Sub-Total de la(s) FV (regla de negocio). Es la
        # fuente del C1/C5; los renglones de tabla solo aportan las categorías.
        "montoVentaFV": _num(caso.get("montoVentaFV")),
        "monedaFV": moneda,
        "tipoCambioRef": tc,
        "campoEntregaFV": "ENTREGA_DOMICILIO",
        "fechaEmision": fecha_emision or caso.get("fechaEmision") or "",
    }


# ══════════════════════════════════════════════════════════════════
# Extracción desde la CAPA DE TEXTO del PDF (CFDI digitales)
# ══════════════════════════════════════════════════════════════════
# Los CFDI de GPA y sus fleteras se generan electrónicamente: el PDF trae una
# capa de texto EXACTA. Rasterizar a imagen + OCR (Textract) sobre eso introduce
# errores (montos basura, RFC mal leídos). Cuando hay capa de texto se lee
# directo; el OCR queda solo como respaldo para escaneos reales (sin texto).
#
# Diseño independiente del proveedor donde se puede: la FACTURA siempre es de
# GPA (mismo formato), el FLETE se suma por claves SAT de transporte (estándar),
# TC/moneda por regex CFDI. Origen/destino y RFC de fletera dependen algo del
# layout del CP de cada fletera; si no se leen, el caso degrada a EN_REVISION
# (no a rechazo falso). Probado con CP de Tresguerras; afinar con más proveedores.

# Claves SAT de servicios de transporte (78101xxx flete/entrega/combustible/ferry,
# 78141xxx servicios de mensajería/entrega a domicilio). Estándar en todo CFDI.
_RE_CLAVE_FLETE = re.compile(r"\b78(10|14)\d{4}\b")

# Abreviaturas de estado → nombre del catálogo (origen/destino en cartas porte).
_EDO_ABBR = {
    "QR": "Quintana Roo", "QROO": "Quintana Roo", "YUC": "Yucatán",
    "JAL": "Jalisco", "NL": "Nuevo León", "BCS": "Baja California Sur",
    "BC": "Baja California", "BCN": "Baja California", "GTO": "Guanajuato",
    "QRO": "Querétaro", "SLP": "San Luis Potosí", "VER": "Veracruz",
    "TAMPS": "Tamaulipas", "TAB": "Tabasco", "CHIS": "Chiapas", "OAX": "Oaxaca",
    "SIN": "Sinaloa", "SON": "Sonora", "COAH": "Coahuila", "CHIH": "Chihuahua",
    "DGO": "Durango", "ZAC": "Zacatecas", "AGS": "Aguascalientes", "COL": "Colima",
    "MICH": "Michoacán", "MOR": "Morelos", "NAY": "Nayarit", "HGO": "Hidalgo",
    "PUE": "Puebla", "GRO": "Guerrero", "CAMP": "Campeche", "TLAX": "Tlaxcala",
}


def _lineas_pdf_pagina(page) -> list[dict]:
    """Líneas de una página PDF con geometría normalizada 0-1: [{text,top,left}].
    Misma estructura que las líneas de Textract, para reusar los helpers de parseo."""
    r = page.rect
    W = float(r.width) or 1.0
    H = float(r.height) or 1.0
    out = []
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            txt = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if txt:
                x0, y0, _x1, _y1 = ln["bbox"]
                out.append({"text": txt, "top": y0 / H, "left": x0 / W})
    return out


def _montos_lineas(lineas):
    """[(top,left,valor)] de todos los montos con decimales del documento."""
    out = []
    for ln in lineas:
        for x in re.findall(r"[\d,]+\.\d{2}", ln["text"]):
            out.append((ln["top"], ln["left"], float(x.replace(",", ""))))
    return out


def _valor_etiqueta(labels, lineas, banda=0.012):
    """Monto asociado a una etiqueta por geometría: en su misma fila (top cercano)
    y a la derecha. Resuelve el layout en columnas (etiqueta y valor en líneas
    separadas, p.ej. 'Subtotal' … '811.66')."""
    labs = [l.upper() for l in labels]
    etis = [ln for ln in lineas if any(k in ln["text"].upper() for k in labs)]
    ms = _montos_lineas(lineas)
    for e in etis:
        aqui = re.findall(r"[\d,]+\.\d{2}", e["text"])
        if aqui:
            return float(aqui[-1].replace(",", ""))
        cand = sorted((abs(t - e["top"]), l, v) for (t, l, v) in ms
                      if abs(t - e["top"]) <= banda and l > e["left"])
        if cand:
            return cand[0][2]
    return None


def _flete_sat(lineas):
    """Flete sin IVA del CP = suma de importes de las líneas con clave SAT de
    transporte (7810xxxx). Estándar en cualquier carta porte CFDI."""
    tops = [ln["top"] for ln in lineas if _RE_CLAVE_FLETE.match(ln["text"])]
    if not tops:
        return None
    ms = _montos_lineas(lineas)
    total = 0.0
    for tp in tops:
        fila = sorted((l, v) for (t, l, v) in ms if abs(t - tp) < 0.005)
        if fila:
            total += fila[-1][1]   # el importe (monto más a la derecha de la fila)
    return round(total, 2) if total > 0 else None


def _tc_moneda(lineas):
    full = " ".join(ln["text"] for ln in lineas).upper()
    tc = re.search(r"TIPO DE CAMBIO[:\s]*([\d.]+)", full)
    mon = re.search(r"MONEDA[:\s]*([A-Z]{3})", full)
    return (float(tc.group(1)) if tc else None,
            (mon.group(1) if mon else None))


def _ciudad_estado(txt):
    """'VALLADOLID, YUC.' → ('Valladolid','Yucatán'); tolera sufijo ', MEX' de las
    filas de domicilio ('GUADALAJARA, JAL., MEX'). None si no es ciudad,estado."""
    t = re.sub(r",?\s*(MEX|MEXICO|MÉXICO)\.?$", "", txt.strip(), flags=re.I).strip().rstrip(",")
    m = re.match(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]+?),\s*([A-ZÑ][A-ZÑ. ]{1,5}?)\.?$", t)
    if not m:
        return None
    ciudad = " ".join(m.group(1).split()).title()
    abbr = re.sub(r"[.\s]", "", m.group(2)).upper()
    estado = _EDO_ABBR.get(abbr)
    return (ciudad, estado) if estado else None


def _estado_de_token(tok: Optional[str]) -> Optional[str]:
    """Abreviatura ('YUC','Q.R.','ROO') o nombre ('JALISCO','Quintana Roo') → nombre
    de estado; el motor (normalizar_destino) lo canoniza al catálogo. None si no aplica."""
    if not tok:
        return None
    t = re.sub(r"[.\s]", "", tok).upper()
    if t in _EDO_ABBR:
        return _EDO_ABBR[t]
    limpio = " ".join(tok.split()).strip(" .-,")
    return limpio.title() if len(t) >= 4 else None


def _part_ciudad_estado(s: str):
    """'CANCUN QROO' / 'GUADALAJARA, Jalisco' → (ciudad, estado_token)."""
    s = re.sub(r"^\s*\d+\s+", "", s.strip()).strip(" -,")   # quita prefijos tipo '03 '
    if "," in s:
        ciudad, est = s.rsplit(",", 1)
        return ciudad.strip(), est.strip()
    parts = s.split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return s, ""


def _origen_destino(lineas):
    """Origen y destino del CP. El layout varía mucho por fletera, así que se
    intentan varias estrategias; si ninguna funciona, el caso degrada a
    EN_REVISION (no a rechazo). Devuelve (ciudadO, estadoO, ciudadD, estadoD)."""
    full = " ".join(ln["text"] for ln in lineas)

    # A) una LÍNEA con "ORIGEN: <ciudad> <ESTADO> ... DESTINO: <ciudad> <ESTADO>"
    # (se parsea por línea para no arrastrar el nombre del destinatario de la
    # línea siguiente). Ej. Osorio: "ORIGEN: CANCUN QROO - DESTINO: MERIDA YUCATAN".
    for ln in lineas:
        u = ln["text"]
        if re.search(r"ORIGEN", u, re.I) and re.search(r"DESTINO", u, re.I):
            m = re.search(r"ORIGEN[:\s]+(.+?)\s*-?\s*DESTINO[:\s]+(.+)", u, re.I)
            if m:
                oc, ot = _part_ciudad_estado(m.group(1))
                dc, dt = _part_ciudad_estado(m.group(2))
                eo, ed = _estado_de_token(ot), _estado_de_token(dt)
                if eo and ed:
                    return (oc.title() or None, eo, dc.title() or None, ed)

    # B) complemento SAT CCP 3.1: "Entidad: XX - Nombre" (1º origen, 2º destino)
    ents = re.findall(r"Entidad:\s*([A-ZÑ]{2,4})\b", full)
    if len(ents) >= 2:
        eo, ed = _estado_de_token(ents[0]), _estado_de_token(ents[1])
        if eo and ed:
            return (None, eo, None, ed)

    # B2) formato Estrella: "CIUDAD ESTADO_COMPLETO" sin coma ("MONTERREY NUEVO
    # LEON"). Solo se usa si es INEQUÍVOCO (todas las coincidencias son la misma
    # plaza — típico de entrega local); con plazas distintas no se adivina cuál
    # es origen y cuál destino → queda para revisión humana.
    plazas = set()
    for ln in lineas:
        if ln["top"] < 0.35:
            m = re.match(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]{2,25}?)\s+"
                         r"(NUEVO LEON|NUEVO LEÓN|QUINTANA ROO|BAJA CALIFORNIA SUR|"
                         r"BAJA CALIFORNIA|SAN LUIS POTOSI|SAN LUIS POTOSÍ|JALISCO|"
                         r"YUCATAN|YUCATÁN|GUERRERO|VERACRUZ|PUEBLA|GUANAJUATO|"
                         r"QUERETARO|QUERÉTARO|MICHOACAN|MICHOACÁN|NAYARIT|SINALOA|"
                         r"SONORA|MORELOS|AGUASCALIENTES|CHIHUAHUA|DURANGO|ZACATECAS|"
                         r"HIDALGO|CAMPECHE|TABASCO|COLIMA|COAHUILA|TAMAULIPAS|"
                         r"CHIAPAS|OAXACA)\s*$", ln["text"].strip().upper())
            if m:
                plazas.add((m.group(1).title().strip(), m.group(2).title()))
    if len(plazas) == 1:
        (ciu, edo), = plazas
        return (ciu, edo, ciu, edo)

    # C) geométrico: líneas "Ciudad, ESTADO" en el tercio superior. Origen a la
    # IZQUIERDA, destino a la DERECHA. La fila superior puede traer la TERMINAL
    # de la fletera ("GONZALEZ GALLO, JAL."), no la ciudad; por eso, para el
    # origen se prefiere el candidato izquierdo cuya ciudad mapea a una plaza
    # GPA (sucursal_de_origen), p. ej. la fila del domicilio del remitente
    # ("GUADALAJARA, JAL., MEX").
    cands = []
    for ln in lineas:
        if ln["top"] < 0.30:
            ce = _ciudad_estado(ln["text"])
            if ce:
                cands.append((ln["top"], ln["left"], ce))
    if cands:
        cands.sort()
        izq = [c for c in cands if c[1] < 0.45]
        der = [c for c in cands if c[1] >= 0.45]
        ori = next((c for c in izq if sucursal_de_origen(c[2][0], c[2][1])), None) \
              or (izq[0] if izq else None)
        dst = der[0] if der else None
        if ori and dst:
            return (ori[2][0], ori[2][1], dst[2][0], dst[2][1])
        fila0 = cands[0][0]
        fila = sorted((c for c in cands if abs(c[0] - fila0) < 0.02), key=lambda c: c[1])
        return (fila[0][2][0], fila[0][2][1], fila[-1][2][0], fila[-1][2][1])

    return (None, None, None, None)


def _pagina_desde_texto(lineas: list[dict]) -> dict:
    """Construye el dict de página (mismos campos que _parse_textract) desde la
    capa de texto del PDF. Reusa los helpers de RFC/emisor-receptor/tipo/folio."""
    rfcs_pos = _rfcs_en_lineas(lineas)
    rfcs_detectados = list(dict.fromkeys(r["rfc"] for r in rfcs_pos))
    tipo_doc = _tipo_documento(lineas)
    g = (RFC_GPA or "").strip().upper()
    gpa_en = bool(g and g in rfcs_detectados)
    fletera = next((r for r in rfcs_detectados if r in FLETERAS_AUTORIZADAS), None)
    rec_lbl = _rfc_cerca_de(["RECEPTOR"], rfcs_pos, lineas)

    # Clasificación CP vs FV, en orden de fiabilidad. El señal robusto es QUIÉN
    # está en el bloque RECEPTOR del CFDI: en una carta porte GPA es el receptor
    # (la fletera le cobra); en una factura GPA, el receptor es el cliente. NO usar
    # el orden de aparición (en una CP, GPA sale primero como remitente de la
    # mercancía → se confundía con emisor), ni solo el tipo (un CFDI de fletera
    # también es "Ingreso").
    if rec_lbl and g and rec_lbl == g:
        clase = "CP"                       # GPA es el RECEPTOR → carta porte
    elif rec_lbl and rec_lbl != g:
        clase = "FV"                       # receptor = cliente → factura de GPA
    elif fletera:
        clase = "CP"                       # una fletera AUTORIZADA emite → CP
    elif gpa_en and tipo_doc in ("CP", "FV"):
        clase = tipo_doc                   # señal textual (CARTA PORTE / Factura)
    else:
        e0, r0 = _emisor_receptor(None, None, rfcs_pos, lineas)
        clase = clasificar_por_rfc(e0, r0)

    if clase == "CP":
        receptor = g or rec_lbl
        # Fletera: RFC autorizado presente en el texto; si su RFC va en la imagen
        # del membrete, intentar por RAZÓN SOCIAL en el texto (p. ej. "TRES
        # GUERRAS" sí aparece aunque el RFC esté en el logo). Si tampoco, vacío →
        # C4c revisión. NUNCA el RFC del cliente/destinatario (daba R-402 falso).
        emisor = fletera or fletera_por_nombre(" ".join(ln["text"] for ln in lineas)) or ""
    elif clase == "FV":
        emisor = g or None
        receptor = rec_lbl or next((r for r in rfcs_detectados if r != g), None)
    else:
        emisor, receptor = _emisor_receptor(None, None, rfcs_pos, lineas)

    tc, moneda = _tc_moneda(lineas)
    full = " ".join(ln["text"] for ln in lineas)
    coment = None
    mcom = re.search(r"(?:OBSERVACIONES|COMENTARIOS|REF)[:\s].{0,120}", full, re.I)
    if mcom:
        coment = mcom.group(0)

    # Subtotal del documento:
    #  - CP → flete sin IVA: el "Sub-Total" del CP cuando aparece (confiable), o
    #    la suma de importes por clave SAT de transporte (Tresguerras lo trae en
    #    la imagen, sin etiqueta de texto).
    #  - FV → "Sub-Total"/"Suma" de la factura GPA.
    if clase == "CP":
        subtotal = (_valor_etiqueta(["SUB-TOTAL", "SUBTOTAL", "SUB TOTAL"], lineas)
                    or _flete_sat(lineas))
        oC, oE, dC, dE = _origen_destino(lineas)
    else:
        subtotal = _valor_etiqueta(["SUB-TOTAL", "SUBTOTAL", "SUB TOTAL", "SUMA"], lineas)
        oC = oE = dC = dE = None

    return {
        "rfcEmisor":      emisor,
        "rfcReceptor":    receptor,
        "rfcsDetectados": rfcs_detectados,
        "tipoDoc":        tipo_doc,
        "subtotal":       subtotal,
        "moneda":         (moneda or "").upper() or None,
        "tipoCambio":     tc,
        "folio":          _folio_no_fiscal(lineas),
        "fecha":          _fecha_iso(full),
        "comentarios":    coment,
        "origenEstado":   oE,
        "origenCiudad":   oC,
        "destinoEstado":  dE,
        "destinoCiudad":  dC,
        "fletaRFC":       emisor,
        # Razón social de fletera detectada en el texto de ESTA página (la FV de
        # GPA trae "Embarcar por: TRES GUERRAS" aunque el CP tenga el RFC en el
        # logo) — se usa a nivel caso si el CP no trajo RFC.
        "fleteraTexto":   fletera_por_nombre(full),
        "partidas":       [],   # del texto aún no se extraen renglones (ver follow-up)
    }


def _texto_util(texto: str) -> bool:
    """¿La capa de texto de la página es LEGIBLE? Algunas facturas de GPA traen
    el texto 'revuelto' (fuente con codificación propia → 0 RFCs, 0 montos, miles
    de glifos basura) aunque la imagen se vea bien. En ese caso conviene OCR, no
    leer el texto. Heurística: hay ≥1 RFC o ≥2 montos con decimales reconocibles."""
    if not texto or len(texto.strip()) < 80:
        return False
    t = re.sub(r"[-.\s]", "", texto.upper())
    tiene_rfc = bool(_RFC_RE.search(t))
    montos = len(re.findall(r"\d+\.\d{2}", texto))
    return tiene_rfc or montos >= 2


# ── Orquestación end-to-end (S3 → texto/OCR → casos) ──────────────
def procesar_pdf(pdf_bytes: bytes, folio_archivo: str = "", client=None) -> dict:
    """Por cada página, lo mejor de ambos mundos:
      - capa de texto LEGIBLE (CFDI digital) → leer directo (exacto);
      - texto revuelto o ausente (escaneo, o factura con fuente rara) → OCR.
    Luego arma los casos (1 por CP). Un PDF puede mezclar ambos (CP en texto +
    factura GPA que necesita OCR)."""
    import fitz
    paginas = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            try:
                texto = page.get_text() or ""
                if _texto_util(texto):           # capa de texto legible → directo
                    paginas.append(_pagina_desde_texto(_lineas_pdf_pagina(page)))
                else:                            # revuelto/escaneo → rasterizar + OCR
                    png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
                    paginas.append(ocr_pagina(png, client=client))
            except Exception as exc:   # una página ilegible no tumba el lote
                logger.warning("Página %d de %s ilegible: %s", i + 1, folio_archivo, exc)
                paginas.append({"tipoDoc": "OTRO"})
    finally:
        doc.close()
    return emparejar_casos(paginas, folio_archivo)


def procesar_objeto_s3(bucket: str, key: str, s3_client=None, bedrock_client=None) -> dict:
    """Descarga el PDF de S3 y devuelve los casos (emparejar_casos)."""
    s3 = s3_client or boto3.client("s3")
    pdf_bytes = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    folio = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return procesar_pdf(pdf_bytes, folio_archivo=folio, client=bedrock_client)
