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
                             fletera_por_nombre, TIPO_CAMBIO_DEFAULT,
                             normalizar_destino, DESTINOS_CATALOGO, SAPS_DISPERSION,
                             estado_por_cp, sucursal_por_cp)

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
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
    '  "comentarios": string|null (texto de Comentarios/Observaciones y CUALQUIER '
    'referencia a facturas: "F-40086093", "Facturas asociadas: 70088673")\n'
    '  "origenEstado": string|null, "origenCiudad": string|null\n'
    '  "destinoEstado": string|null, "destinoCiudad": string|null\n'
    '  "fletaRFC": string|null    (RFC de la fletera/transportista, = emisor del CP)\n'
    '  "partidas": [ {"descripcion": string, "cantidad": number, "importe": number, '
    '"pesoKg": number|null, "volumenL": number|null, "presentacion": string|null, '
    '"claveSat": string|null} ]  (renglones de productos; [] si no aplica)\n'
    "    pesoKg/volumenL/presentacion = tamaño/presentación de UNA unidad del producto "
    '(p.ej. "50 KGS", "20 L"); es el factor que define si el producto es excluido por '
    "tamaño. Extrae el número del peso/volumen de la descripción si viene ahí.\n"
    '  "fleteraNombre": string|null (razón social de la fletera/transportista, aunque '
    "su RFC solo esté en el logo del membrete)\n"
    '  "esNotaCredito": boolean     (true si es nota de crédito / CFDI tipo E-Egreso)\n'
    '  "esPreguia": boolean         (true si la página es un formato interno de '
    'GPA: "Pre Guía Almacén Origen" o "Solicitud de Traslado")\n'
    '  "destinatarioGPA": boolean   (true si el bloque DESTINATARIO del comprobante es '
    "General de Productos para el Agua — GPA se envía a sí misma)\n"
    "SELLO de Control Presupuestal: estampa rectangular de GPA (encabezado 'Formato de "
    "Control Presupuestal') con centro de costo, cuenta contable, código SAP y casillas "
    "de sucursal. Si aparece en la página:\n"
    '  "codigoSAP": string|null     (código GS0xxx del sello, p.ej. "GS0231")\n'
    '  "sucursalSello": string|null (casilla de sucursal MARCADA: Guadalajara, '
    "Monterrey, Pto. Vallarta, México, Cancún, Los Cabos o Corporativo)\n"
    '  "tipoFleteSello": string|null (texto del recuadro TIPO DE FLETE, p.ej. '
    '"DISP. SEMANAL", "GARANTIAS Y DEVOLUCIONES")\n'
    "Si la página no es un comprobante (anexo, acuse, etc.), usa tipoDocumento=OTRO "
    "y los demás en null/[]/false."
)

# Prompt corto para leer SOLO el sello presupuestal (páginas CP digitales cuya
# capa de texto es exacta pero el sello es una imagen estampada).
PROMPT_SELLO = (
    "La imagen es una carta porte con un SELLO rectangular de 'Formato de Control "
    "Presupuestal' de General de Productos para el Agua (GPA). Devuelve EXCLUSIVAMENTE "
    "un objeto JSON:\n"
    '  "codigoSAP": string|null     (código GS0xxx impreso en el sello, p.ej. "GS0231")\n'
    '  "sucursalSello": string|null (casilla de sucursal MARCADA: Guadalajara, '
    "Monterrey, Pto. Vallarta, México, Cancún, Los Cabos o Corporativo)\n"
    '  "tipoFleteSello": string|null (texto del recuadro TIPO DE FLETE)\n'
    "Si no hay sello visible, todo en null."
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
def _pagina_pobre(p: dict) -> bool:
    """Página OCR sin nada que emparejar: ni un RFC ni un monto."""
    return not p.get("rfcsDetectados") and not _num(p.get("subtotal"))


def ocr_pagina(imagen_png: bytes, client=None) -> dict:
    """Extrae los campos del comprobante de UNA página.
    Backends (env OCR_BACKEND): "textract" | "bedrock" | "hibrido".
    hibrido = Textract primero; si la página sale POBRE (sin RFC y sin monto),
    reintenta con Bedrock (Claude visión) y se queda con esa; si Bedrock falla,
    conserva lo de Textract (fail-open)."""
    if OCR_BACKEND == "bedrock":
        return _ocr_bedrock(imagen_png, client=client)
    pagina = _ocr_textract(imagen_png, client=client)
    if OCR_BACKEND == "hibrido" and _pagina_pobre(pagina):
        try:
            pagina = _ocr_bedrock(imagen_png)
        except Exception as exc:
            logger.warning("Híbrido: Bedrock falló, se conserva Textract: %s", exc)
    return pagina


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


def _folio_no_fiscal(lineas, serie_f: bool = False) -> Optional[str]:
    """Folio (serie-número) cerca de 'Folio', excluyendo 'Folio Fiscal'/UUID.

    serie_f: activa el respaldo serie-F ("Factura FMTY 70088749") — SOLO para
    páginas FV. En una carta porte ese patrón secuestra referencias ajenas
    (119524726: el CP menciona 'FD 408735' y el caso aterrizaba con ese folio
    en vez del suyo; la tarjeta quedaba imposible de encontrar en el tablero)."""
    for ln in lineas:
        u = ln["text"].upper()
        if "FOLIO" in u and "FISCAL" not in u and not _UUID_RE.search(ln["text"]):
            m = re.search(r"FOLIO\W*([A-Z]{0,3}[-\s]?\d{3,})", u)
            if m:
                return m.group(1).replace(" ", "")
    if not serie_f:
        return None
    # Serie-folio de las facturas GPA sin la palabra "Folio" en la línea:
    # el encabezado dice "Factura  FC 20109707" (o FA/FM/FLC/FMTY + dígitos —
    # la serie es F + sucursal, hasta 3 letras más). Sin esto el folio de la FV
    # quedaba vacío: rompía la unicidad (R-091) y fundía facturas DISTINTAS de
    # un mismo PDF como si fueran una multipágina (M846228 no sumaba sus FVs).
    for ln in lineas:
        # (?!AX\b): "FAX 8183722126" no es una serie de factura.
        m = re.search(r"\b(F(?!AX\b)[A-Z]{1,3})\s?-?(\d{6,})\b", ln["text"].upper())
        if m:
            return m.group(1) + m.group(2)
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
    senales = _senales_especiales(lineas)
    rfcs_pos = _rfcs_en_lineas(lineas)
    # Tolerancia al ruido del OCR sobre el RFC de GPA (ver _rfc_gpa_tolerante)
    rfcs_detectados = list(dict.fromkeys(
        _rfc_gpa_tolerante(r["rfc"]) for r in rfcs_pos))
    tipo_doc = _tipo_documento(lineas)
    emisor, receptor = _emisor_receptor(_norm_rfc(campos.get("rfcEmisor")),
                                        _norm_rfc(campos.get("rfcReceptor")),
                                        rfcs_pos, lineas)
    emisor, receptor = _rfc_gpa_tolerante(emisor), _rfc_gpa_tolerante(receptor)

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
    folio = folio or _folio_no_fiscal(lineas, serie_f=(tipo_doc == "FV"))

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
        "esMuestra":     tipo_doc == "FV" and bool(_RE_MUESTRA.search(
                             _sin_acentos(" ".join(ln["text"] for ln in lineas)))),
        **senales,       # esNotaCredito / esPreguia / destinatarioGPA
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
_BEDROCK_CLIENT = None


def _bedrock_runtime():
    """Cliente bedrock-runtime compartido (thread-safe) con reintentos
    ADAPTATIVOS: con el OCR de páginas en paralelo, un ThrottlingException
    puntual debe esperar-y-reintentar, no tirar la página a OTRO."""
    global _BEDROCK_CLIENT
    if _BEDROCK_CLIENT is None:
        from botocore.config import Config
        _BEDROCK_CLIENT = boto3.client("bedrock-runtime", config=Config(
            retries={"max_attempts": 6, "mode": "adaptive"},
            read_timeout=120))
    return _BEDROCK_CLIENT


_RE_SAP = re.compile(r"\bGS0\d{3}\b")

# Casilla del sello → sucursal del catálogo (para rellenar origen vacío).
_SUCURSAL_SELLO = {
    "GUADALAJARA": ("Guadalajara", "Jalisco"),
    "MONTERREY": ("Monterrey", "Nuevo León"),
    "PTO. VALLARTA": ("Puerto Vallarta", "Jalisco"),
    "PUERTO VALLARTA": ("Puerto Vallarta", "Jalisco"),
    "MEXICO": ("Iztapalapa", "CDMX"),
    "MÉXICO": ("Iztapalapa", "CDMX"),
    "CANCUN": ("Cancun", "Quintana Roo"),
    "CANCÚN": ("Cancun", "Quintana Roo"),
    "LOS CABOS": ("Cabo San Lucas", "Baja California Sur"),
}


def _codigo_sap_valido(v) -> str:
    m = _RE_SAP.search(str(v or "").upper())
    return m.group(0) if m else ""


def _rfc_gpa_tolerante(rfc: Optional[str]) -> Optional[str]:
    """El OCR de escaneos deforma dígitos del RFC de GPA (caso real M845517
    pág. 2: "GPA940221471" por GPA8402219Y1 → la página caía a 'ajena' y el
    caso quedaba sin FV). En los documentos de fletes de GPA, un RFC con el
    prefijo de GPA ES GPA: ningún cliente ni fletera lo lleva."""
    if rfc and rfc.upper().startswith(RFC_GPA[:3]):
        return RFC_GPA
    return rfc


def _adaptar_bedrock(raw: dict) -> dict:
    """Mapea el JSON del modelo (PROMPT_OCR) al MISMO contrato de dict de página
    que _parse_textract/_pagina_desde_texto. Sin esto, el pipeline (clasificar_
    pagina, emparejar_casos) no entiende la salida de Bedrock: 'tipoDocumento'
    usa otro vocabulario, faltan rfcsDetectados/señales y los RFC vienen crudos."""
    emisor = _rfc_gpa_tolerante(_norm_rfc(raw.get("rfcEmisor")))
    receptor = _rfc_gpa_tolerante(_norm_rfc(raw.get("rfcReceptor")))
    fleta = _norm_rfc(raw.get("fletaRFC"))
    # Clasificación: el ROL del RFC manda sobre el TÍTULO (regla del modelo de
    # documentos GPA). Las facturas de fletera se titulan "Factura" (Estrella:
    # "Factura M845517") pero la fletera EMITE y GPA paga → es CP; confiar en el
    # tipoDocumento del modelo las volvía FV y rompía el emparejado (lote 26-06).
    tipo_map = {"CARTA_PORTE": "CP", "FACTURA": "FV"}
    tipo_doc = clasificar_por_rfc(emisor, receptor)
    if tipo_doc == "ERROR":
        if (fleta and fleta in FLETERAS_AUTORIZADAS) \
                or (emisor and emisor in FLETERAS_AUTORIZADAS):
            tipo_doc = "CP"          # una fletera AUTORIZADA emite → carta porte
        else:
            tipo_doc = tipo_map.get(str(raw.get("tipoDocumento") or "").upper()) or "ERROR"
    folio = raw.get("folio")
    if folio and _UUID_RE.search(str(folio)):
        folio = None    # folio fiscal (UUID) no es el folio del comprobante
    partidas = [{
        "descripcion": str(p.get("descripcion") or ""),
        "cantidad": _num(p.get("cantidad")) or 1.0,
        "importe": _num(p.get("importe")),
        "pesoKg": _num(p.get("pesoKg")) or None,
        "volumenL": _num(p.get("volumenL")) or None,
        "presentacion": p.get("presentacion"),
        "claveSat": p.get("claveSat"),
    } for p in (raw.get("partidas") or []) if isinstance(p, dict)]
    return {
        "rfcEmisor":      emisor,
        "rfcReceptor":    receptor,
        "rfcsDetectados": list(dict.fromkeys(r for r in (emisor, receptor, fleta) if r)),
        "tipoDoc":        tipo_doc if tipo_doc in ("CP", "FV") else (raw.get("tipoDocumento") or "OTRO"),
        "subtotal":       _num(raw.get("subtotal")) or None,
        "moneda":         (str(raw.get("moneda") or "").upper() or None),
        "tipoCambio":     _num(raw.get("tipoCambio")) or None,
        "folio":          folio,
        "fecha":          _fecha_iso(str(raw.get("fecha") or "")),
        "comentarios":    raw.get("comentarios"),
        "origenEstado":   raw.get("origenEstado"),
        "origenCiudad":   raw.get("origenCiudad"),
        "destinoEstado":  raw.get("destinoEstado"),
        "destinoCiudad":  raw.get("destinoCiudad"),
        # Fletera: solo un RFC del catálogo autorizado (nunca uno inventado).
        "fletaRFC":       fleta if fleta in FLETERAS_AUTORIZADAS else
                          (emisor if emisor in FLETERAS_AUTORIZADAS else ""),
        "fleteraTexto":   fletera_por_nombre(str(raw.get("fleteraNombre") or "")),
        "partidas":       partidas,
        # Señales especiales (mismas que _senales_especiales en los otros caminos)
        "esNotaCredito":  bool(raw.get("esNotaCredito")),
        "esPreguia":      bool(raw.get("esPreguia")),
        "destinatarioGPA": bool(raw.get("destinatarioGPA")),
        "esMuestra":      any(_RE_MUESTRA.search(_sin_acentos(p["descripcion"]))
                              for p in partidas),
        # Sello de Control Presupuestal (validado; "" si no pasa el formato)
        "codigoSAP":      _codigo_sap_valido(raw.get("codigoSAP")),
        "sucursalSello":  str(raw.get("sucursalSello") or "").strip(),
        "tipoFleteSello": str(raw.get("tipoFleteSello") or "").strip(),
    }


def _ocr_bedrock(imagen_png: bytes, client=None, model_id: str = BEDROCK_MODEL_ID) -> dict:
    client = client or _bedrock_runtime()
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
    return _adaptar_bedrock(_parse_json(texto))


def leer_sello_cp(imagen_png: bytes, client=None, model_id: str = BEDROCK_MODEL_ID) -> dict:
    """Lee SOLO el sello de Control Presupuestal de una página CP (el sello es
    una imagen estampada incluso en CFDI digitales — la capa de texto nunca lo
    trae). Fail-open: cualquier error devuelve {} y el caso queda como estaba."""
    try:
        client = client or _bedrock_runtime()
        resp = client.converse(
            modelId=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"text": PROMPT_SELLO},
                    {"image": {"format": "png", "source": {"bytes": imagen_png}}},
                ],
            }],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
        raw = _parse_json(resp["output"]["message"]["content"][0]["text"])
        return {
            "codigoSAP": _codigo_sap_valido(raw.get("codigoSAP")),
            "sucursalSello": str(raw.get("sucursalSello") or "").strip(),
            "tipoFleteSello": str(raw.get("tipoFleteSello") or "").strip(),
        }
    except Exception as exc:
        logger.warning("leer_sello_cp falló (se ignora): %s", exc)
        return {}


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


def _sin_acentos(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


_RE_NOTA_CREDITO = re.compile(r"NOTA\s+(?:DE\s+)?CREDITO|\bE\s*-\s*EGRESO\b")
# Anexos que marcan DISPERSIÓN interna: "Pre Guía Almacén Origen" y
# "Solicitud de Traslado" (regla GPA 2026-07-14, caso 119748001 y los JC7xxxxx).
_RE_PREGUIA = re.compile(r"PRE\s*GUIA\s+ALMACEN\s+ORIGEN|SOLICITUD\s+DE\s+TRASLADO")
# Envío de MUESTRAS (partidas "MUESTRA Mosaico ..."): exento de mínimos y
# % de flete (regla GPA, caso 119518759). Solo se marca en páginas FV.
_RE_MUESTRA = re.compile(r"\bMUESTRAS?\b")


def _senales_especiales(lineas: list[dict]) -> dict:
    """Señales de página que cambian el armado del caso (capa texto Y Textract):
    - esNotaCredito: CFDI de Egreso / nota de crédito → es ANEXO, no CP ni FV
      (la NC de la fletera clasificaba como 2ª carta porte y creaba un caso
      fantasma — TPQ1A-955 pág. 2; la NC de GPA se confundiría con una FV).
    - esPreguia: "Pre Guía Almacén Origen" (formato interno GRL-AL-FO-17) →
      el PDF es una dispersión interna, que no lleva factura de venta.
    - destinatarioGPA: carta porte cuyo bloque DESTINATARIO es el propio GPA
      (GPA→GPA) → dispersión interna (caso real 119338784).
    """
    texto = _sin_acentos(" ".join(ln["text"] for ln in lineas))
    # (a) Nombre GPA justo bajo el rótulo DESTINATARIO (Textract lee el banner;
    # en la capa de texto del PDF el rótulo suele ser imagen y no aparece).
    destinatario_gpa = False
    for lbl in lineas:
        if "DESTINATARIO" not in _sin_acentos(lbl["text"]):
            continue
        for ln in lineas:
            if (lbl["top"] - 0.01 <= ln["top"] <= lbl["top"] + 0.10
                    and ln["left"] >= 0.45
                    and "GENERAL DE PRODUCTOS" in _sin_acentos(ln["text"])):
                destinatario_gpa = True
                break
        if destinatario_gpa:
            break
    # (b) Respaldo geométrico: la fila remitente/destinatario trae el nombre de
    # GPA en AMBOS lados (izq=remitente, der=destinatario) → GPA→GPA. En una
    # venta, el lado derecho es el cliente.
    if not destinatario_gpa:
        gpa_pos = [(ln["top"], ln["left"]) for ln in lineas
                   if ln["top"] < 0.35 and "GENERAL DE PRODUCTOS" in _sin_acentos(ln["text"])]
        destinatario_gpa = any(
            li < 0.45 <= ld and abs(ti - td) <= 0.03
            for ti, li in gpa_pos for td, ld in gpa_pos)
    return {
        "esNotaCredito": bool(_RE_NOTA_CREDITO.search(texto)),
        "esPreguia": bool(_RE_PREGUIA.search(texto)),
        "destinatarioGPA": destinatario_gpa,
    }


def clasificar_pagina(p: dict, rfc_gpa: str = RFC_GPA) -> str:
    """Clasifica una página combinando señales: rol del RFC (emisor/receptor) y,
    como respaldo, presencia del RFC de GPA en el texto + tipo de documento."""
    # Anexos que NO son comprobantes del caso: nota de crédito (CFDI Egreso) y
    # Pre Guía Almacén Origen. Clasificarlos como CP/FV rompía el emparejado.
    if p.get("esNotaCredito") or p.get("esPreguia"):
        return "ANEXO"
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
    """Folios de FV referenciados en el CP: 'F-40086093' en Comentarios, o
    'Facturas asociadas: 70088673' (facturas de fletera, p.ej. Estrella)."""
    if not comentarios:
        return []
    up = comentarios.upper()
    refs = re.findall(r"F[-\s]?0*(\d{4,})", up)
    m = re.search(r"FACTURAS?\s+ASOCIADAS?:?\s*([\d,\s/]+)", up)
    if m:
        refs += re.findall(r"0*(\d{4,})", m.group(1))
    return refs


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
        "esMuestra":   any(p.get("esMuestra") for p in pages),
    }


def _consolidar_fvs(fv_pages: list[dict]) -> list[dict]:
    """Agrupa páginas FV en facturas (1 FV por factura) por orden de lectura:
    - un folio NUEVO inicia una factura distinta (se sumarán entre sí);
    - mismo folio, o página sin folio (continuación), pertenece a la factura en curso
      (su Sub-Total se repite, NO se suma) — SALVO que traiga un Sub-Total
      DISTINTO no-cero: una factura multipágina REPITE su subtotal en cada
      página, así que un subtotal diferente es OTRA factura aunque el folio no
      se haya podido leer (M846228: 3 facturas sin folio legible se fundían en
      una y el %flete salía contra 1 sola en vez de la suma).
    Así varias facturas de un CP siguen sumándose, pero una factura multipágina cuenta
    una sola vez."""
    grupos = []
    for p in fv_pages:
        d = _digitos(p.get("folio"))
        misma = bool(grupos) and (not d or d == _digitos(grupos[-1][0].get("folio")))
        if misma and not d:
            sub_p = round(_num(p.get("subtotal")), 2)
            subs_grupo = {round(_num(q.get("subtotal")), 2)
                          for q in grupos[-1] if _num(q.get("subtotal")) > 0}
            if sub_p > 0 and subs_grupo and sub_p not in subs_grupo:
                misma = False           # sin folio pero con OTRO subtotal → otra factura
        if misma:
            grupos[-1].append(p)        # continuación / misma factura
        else:
            grupos.append([p])          # folio nuevo → factura distinta
    return [_fv_consolidada(g) for g in grupos]


def _construir_caso(cp: dict, fvs: list[dict], folio_archivo: str,
                    es_dispersion: bool = False) -> dict:
    if not fvs and not es_dispersion:
        return {"status": "ERROR", "error": "SIN_FV_VINCULADA",
                "detalle": f"El CP {cp.get('folio')} no tiene FV de GPA emparejada.",
                "folioCP": cp.get("folio"), "folioArchivo": folio_archivo}
    partidas = [pt for fv in fvs for pt in (fv.get("partidas") or [])]
    if not fvs:
        # Dispersión interna (GPA→GPA / Pre Guía): no lleva factura de venta.
        # El motor la evalúa contra la tabla de tarifas, no contra la venta.
        tc, monto, moneda = TIPO_CAMBIO_DEFAULT, 0.0, "MXN"
    else:
        # Tipo de cambio: buscarlo en TODAS las facturas del caso (un caso puede
        # traer una FV en MXN sin TC y otra en USD con TC — el TC vale para ambas).
        tc = next((_num(fv.get("tipoCambio")) for fv in fvs
                   if _num(fv.get("tipoCambio")) > 0), None)
        monedas = {((fv.get("moneda") or "").upper() or "USD") for fv in fvs}

        if tc:
            # Monto del caso en USD: cada factura se convierte según SU moneda.
            total_usd = 0.0
            for fv in fvs:
                sub = _num(fv.get("subtotal"))
                total_usd += (sub / tc) if (fv.get("moneda") or "USD").upper() == "MXN" else sub
            monto, moneda = round(total_usd, 2), "USD"
        elif monedas <= {"MXN"}:
            # Regla de negocio: FV en MXN vs flete en MXN se evalúa DIRECTO (no
            # requiere TC del documento). El TC de respaldo se usa únicamente para
            # expresar los mínimos USD de C1; el % de flete (C5) no depende de él.
            tc = TIPO_CAMBIO_DEFAULT
            monto = round(sum(_num(fv.get("subtotal")) for fv in fvs), 2)
            moneda = "MXN"
        else:
            # Hay factura en USD y ningún TC en el caso → sí requiere revisión
            # (el flete está en MXN; convertirlo con un TC inventado altera el %).
            return {"status": "ERROR", "error": "SIN_TIPO_CAMBIO",
                    "detalle": "FV en USD sin tipo de cambio en ninguna factura del caso.",
                    "folioCP": cp.get("folio"), "folioArchivo": folio_archivo}
    # Origen: el real de la carta porte; si quedó ilegible, la casilla de
    # sucursal del SELLO presupuestal es un respaldo confiable (la marca GPA).
    ori_ciudad, ori_estado = cp.get("origenCiudad"), cp.get("origenEstado")
    if not ori_ciudad:
        sello_suc = str(cp.get("sucursalSello") or "").upper().strip()
        if sello_suc in _SUCURSAL_SELLO:
            ori_ciudad, ori_estado = _SUCURSAL_SELLO[sello_suc]
    return {
        # Destinatario GPA → el motor rutea a la Capa 1a (dispersión interna).
        "destinatarioRFC": RFC_GPA if es_dispersion else "",
        "status": "OK",
        "folioCP": str(cp.get("folio") or folio_archivo),
        "foliosFV": [str(fv.get("folio") or "") for fv in fvs],
        # Fletera a nivel CASO: RFC del CP; si va en el logo, la razón social
        # detectada en el texto del CP o de la FV ("Embarcar por: TRES GUERRAS").
        "fletaRFC": (cp.get("fletaRFC") or cp.get("rfcEmisor")
                     or cp.get("fleteraTexto")
                     or next((fv.get("fleteraTexto") for fv in fvs if fv.get("fleteraTexto")), "")),
        "fleteSinIvaMXN": _num(cp.get("subtotal")),
        # Monto del caso ya consolidado por moneda (mixto MXN+USD → USD con el
        # TC del caso; todo-MXN sin TC → directo en MXN con TC de respaldo).
        "montoVentaFV": monto,
        "monedaFV": moneda,
        "tipoCambioRef": tc,
        "origenEstado": ori_estado,
        "origenCiudad": ori_ciudad,
        # Sucursal derivada del ORIGEN real (no de la facturación); '' si no es plaza GPA
        "origenSucursal": sucursal_de_origen(ori_ciudad, ori_estado),
        "destinoEstado": cp.get("destinoEstado"),
        "destinoCiudad": cp.get("destinoCiudad"),
        "fechaEmision": cp.get("fecha") or next((fv.get("fecha") for fv in fvs if fv.get("fecha")), "") or "",
        "partidas": partidas,
        # Sello de Control Presupuestal (si se pudo leer): rutea GS0231/32 a
        # dispersión y GS0247 (com.ped) queda exento de mínimos/% en el motor.
        "codigoSAP": cp.get("codigoSAP") or "",
        "tipoFleteSello": cp.get("tipoFleteSello") or "",
        # Envío de MUESTRAS → exento de mínimos/% (regla GPA).
        "esMuestraFV": any(fv.get("esMuestra") for fv in fvs),
    }


def emparejar_casos(paginas: list[dict], folio_archivo: str = "") -> dict:
    """
    De las páginas OCR de UN PDF (que puede traer varios CP y varias FV) arma
    UN caso por cada CP, emparejando su(s) FV por el folio del campo Comentarios.
    """
    # Hojas de DESGLOSE de consolidados: se recolectan y anexan a los casos.
    desglose = [r for p in paginas for r in (p.get("desglose") or [])]
    paginas = [p for p in paginas if not p.get("desglose")]

    cps, fvs, ajenas = [], [], []
    for idx, p in enumerate(paginas):
        clase = clasificar_pagina(p)
        # Diagnóstico por página (visible en CloudWatch): sin esto, un lote de
        # páginas "ajenas" es una caja negra — no se sabe QUÉ leyó el OCR.
        logger.info("%s pag%d: clase=%s tipoDoc=%s rfcE=%s rfcR=%s sub=%s folio=%s nc=%s",
                    folio_archivo or "PDF", idx + 1, clase, p.get("tipoDoc"),
                    p.get("rfcEmisor"), p.get("rfcReceptor"), p.get("subtotal"),
                    p.get("folio"), p.get("esNotaCredito"))
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

    # Dispersión interna: si CUALQUIER página del PDF es la Pre Guía Almacén
    # Origen / Solicitud de Traslado, o el CP tiene a GPA como DESTINATARIO
    # (GPA→GPA), el caso no lleva factura de venta — no debe morir en
    # SIN_FV_VINCULADA (caso 119338784).
    hay_preguia = any(p.get("esPreguia") for p in paginas)
    preguia_pags = [p for p in paginas if p.get("esPreguia")]

    def _origen_desde_preguia(caso):
        # La Solicitud de Traslado / Pre Guía trae el origen real cuando el CP
        # no lo dice (JC757545/757471: el CP solo trae el domicilio de la
        # fletera en León; el origen GDL está en la hoja de traslado).
        if caso.get("status") != "OK" or caso.get("origenSucursal"):
            return
        for pgx in preguia_pags:
            oc, oe = pgx.get("origenCiudad"), pgx.get("origenEstado")
            suc = sucursal_de_origen(oc, oe)
            if not suc and pgx.get("sucursalSello"):
                s = str(pgx["sucursalSello"]).upper().strip()
                if s in _SUCURSAL_SELLO:
                    oc, oe = _SUCURSAL_SELLO[s]
                    suc = sucursal_de_origen(oc, oe)
            if suc:
                caso["origenCiudad"], caso["origenEstado"] = oc, oe
                caso["origenSucursal"] = suc
                return

    # PDFs "paquete": VARIOS CPs + facturas SIN referencias cruzadas (regla GPA
    # 2026-07-15, casos 119877129-119874733 y 119697309-119700106: "sumar todas
    # las CPs y sumar todas las FVs"). Sin refs no hay forma de repartir 1-a-1,
    # y partirlo daba SIN_FV_VINCULADA por CP: el paquete se evalúa como UN
    # caso agregado — flete TOTAL contra venta TOTAL (el %flete decide).
    if len(cps) > 1 and facturas:
        con_ref = any(_fv_coincide(fv.get("folio"), _folios_referenciados(cp.get("comentarios")))
                      for cp in cps for fv in facturas)
        if not con_ref:
            agregado = dict(cps[0])
            agregado["subtotal"] = sum(_num(c.get("subtotal")) for c in cps)
            agregado["folio"] = folio_archivo or agregado.get("folio")
            for c in cps[1:]:
                for k, v in c.items():
                    if agregado.get(k) in (None, "", []) and v not in (None, "", []):
                        agregado[k] = v
            caso = _construir_caso(
                agregado, list(facturas), folio_archivo,
                es_dispersion=(hay_preguia
                               or any(c.get("destinatarioGPA") for c in cps)
                               or any((c.get("codigoSAP") or "") in SAPS_DISPERSION for c in cps)))
            _origen_desde_preguia(caso)
            if desglose and caso.get("status") == "OK":
                caso["desglose"] = desglose
            logger.info("%s: paquete de %d CPs + %d facturas sin refs → 1 caso agregado",
                        folio_archivo or "PDF", len(cps), len(facturas))
            return {"casos": [caso], "totalCP": len(cps), "totalFV": len(fvs),
                    "totalFacturas": len(facturas), "fvsSinCP": [],
                    "paginasAjenas": len(ajenas), "folioArchivo": folio_archivo}

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
        caso = _construir_caso(cp, match, folio_archivo,
                               es_dispersion=(hay_preguia or bool(cp.get("destinatarioGPA"))
                                              or (cp.get("codigoSAP") or "") in SAPS_DISPERSION))
        _origen_desde_preguia(caso)
        # Consolidados: anexar la tabla de desglose (guía/ciudad/total) al caso
        # para que el revisor la vea en el detalle del monitor.
        if desglose and caso.get("status") == "OK":
            caso["desglose"] = desglose
        casos.append(caso)

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
        # Dispersión interna (GPA→GPA): rutea a la Capa 1a del motor.
        "destinatarioRFC": caso.get("destinatarioRFC") or "",
        # Sello presupuestal (GS0231/32 → dispersión; GS0247 exento de mínimos).
        "codigoSAP": caso.get("codigoSAP") or "",
        "tipoFleteSello": caso.get("tipoFleteSello") or "",
        # MUESTRAS → exento de mínimos/% de flete.
        "esMuestraFV": bool(caso.get("esMuestraFV")),
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
        # Consolidados: tabla de desglose (guía/ciudad/total) para el detalle.
        "desgloseConsolidado": caso.get("desglose", []),
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
    # "CIUDAD JUAREZ, CHI" (Tresguerras trunca CHIH; Chiapas siempre es CHIS)
    "CHI": "Chihuahua",
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


# Prefijos de CALLE: "AV. VERACRUZ" o "PROL. HIDALGO" son direcciones, no
# plazas — tomarlas como ciudad producía orígenes/destinos basura (120472995,
# 120493319: origen "Av."/"Prol.").
_ES_CALLE = re.compile(r"^(AV|AVE|AVENIDA|CALLE|CALZ|CALZADA|PROL|PROLONGACION|"
                       r"BLVD|BOULEVARD|CARR|CARRETERA|KM|PERIF|PERIFERICO)\b[. ]?", re.I)


def _ciudad_estado(txt):
    """'VALLADOLID, YUC.' → ('Valladolid','Yucatán'). Acepta abreviaturas
    ('JAL.', 'Q.R.') y nombres COMPLETOS tras la coma ('TOLUCA, EDO. DE
    MEXICO', 'MERIDA, YUCATAN'); tolera el sufijo-país ', MEX' de las filas
    de domicilio. None si no es ciudad,estado."""
    raw = txt.strip().rstrip(",")
    if _ES_CALLE.match(raw):
        return None
    t = re.sub(r",?\s*(MEX|MEXICO|MÉXICO)\.?$", "", raw, flags=re.I).strip().rstrip(",")
    # 1) Abreviatura corta tras la coma
    m = re.match(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]+?),\s*([A-ZÑ][A-ZÑ. ]{1,5}?)\.?$", t)
    if m:
        abbr = re.sub(r"[.\s]", "", m.group(2)).upper()
        estado = _EDO_ABBR.get(abbr)
        if estado:
            return (" ".join(m.group(1).split()).title(), estado)
    # 2) Nombre COMPLETO del estado tras la última coma. OJO: se intenta sobre
    # el texto ORIGINAL además del recortado — el recorte ", MEX" mutila
    # "EDO. DE MEXICO" → "EDO. DE" (bug real del folio 119581944, Toluca).
    for cand in (raw, t):
        if "," not in cand:
            continue
        ciudad_p, cola = cand.rsplit(",", 1)
        # Cola tal cual y sin puntos: "EDO. DE MEXICO" solo tiene alias
        # como "EDO DE MEXICO".
        for cola_v in (cola.strip().strip("."), re.sub(r"\.", "", cola).strip()):
            canon = normalizar_destino(cola_v)
            if (canon in DESTINOS_CATALOGO or canon.upper() in ("CHIAPAS", "OAXACA")) \
                    and re.match(r"^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]*$", ciudad_p.strip()):
                return (" ".join(ciudad_p.split()).title(), canon)
    # 3) "CIUDAD, MEX" sin OTRO estado: aquí MEX no es el sufijo-país sino el
    # ESTADO DE MÉXICO (120540032: "TEOTIHUACAN DE ARISTA, MEX" → destino
    # vacío → R-301 falso). Solo aplica si al recortar ", MEX" no quedó coma
    # (o sea, MEX era el único token de estado).
    m = re.match(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]+?),\s*MEX\.?$", raw)
    if m and "," not in t:
        return (" ".join(m.group(1).split()).title(), "Edo. México")
    return None


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


def _origen_destino_tabla_ccp(lineas):
    """Tabla "ORÍGENES, DESTINOS Y PUNTOS INTERMEDIOS" del complemento Carta
    Porte (HORMIK y otros): fila Origen con IdUbicacion OR#####, fila Destino
    con DE#####; la plaza va al final de la dirección: "... CP: 39893,
    Acapulco de Juárez, Guerrero, MEX". (Caso real FAC6637 → R-301 falso.)
    Devuelve parciales (None en lo que no encuentre)."""
    full_nl = "\n".join(ln["text"] for ln in lineas)

    def _plaza(id_pat):
        m = re.search(id_pat + r"\b.{0,400}?CP:?\s*\d{4,5}\s*,\s*([^,\n]+?)\s*,\s*([^,\n]+?)\s*,\s*MEX",
                      full_nl, re.S | re.I)
        if not m:
            return (None, None)
        ciudad = " ".join(m.group(1).split()).title()
        canon = normalizar_destino(re.sub(r"\.", "", m.group(2)).strip())
        return (ciudad, canon) if canon in DESTINOS_CATALOGO else (None, None)

    o_c, o_e = _plaza(r"\bOR\d{4,7}")
    d_c, d_e = _plaza(r"\bDE\d{4,7}")
    return (o_c, o_e, d_c, d_e)


_PLAZA_DE_SUCURSAL = {
    "GDL": ("Guadalajara", "Jalisco"), "CDMX": ("Iztapalapa", "CDMX"),
    "MTY": ("Monterrey", "Nuevo León"), "CUN": ("Cancun", "Quintana Roo"),
    "PVR": ("Puerto Vallarta", "Jalisco"), "SJD": ("Cabo San Lucas", "Baja California Sur"),
}


def _origen_destino_por_cp(lineas):
    """RESPALDO por CÓDIGO POSTAL (regla GPA 2026-07-16): el CP del bloque
    DESTINATARIO (columna derecha) determina el ESTADO destino sin ambigüedad,
    y el del REMITENTE (columna izquierda) la sucursal de origen. Es numérico:
    sobrevive al OCR mejor que los nombres de plaza. Se excluyen el 'Lugar de
    Expedición' (caja superior de la fletera) y la fila del RECEPTOR ('REG:')."""
    izq, der = [], []
    for ln in lineas:
        if not (0.10 < ln["top"] < 0.35):
            continue
        u = ln["text"].upper()
        if "REG" in u or "EXPEDICI" in u:
            continue
        m = re.search(r"\bC\.?P\.?[:.\s]\s*(\d{5})\b", u)
        if not m:
            continue
        (izq if ln["left"] < 0.45 else der).append(m.group(1))
    oc = oe = de = None
    if izq:
        suc = sucursal_por_cp(izq[0])
        if suc:
            oc, oe = _PLAZA_DE_SUCURSAL[suc]
        else:
            # No es plaza GPA: aún así el ESTADO de origen es dato útil (la
            # tarjeta sale con "León/Guanajuato" en vez de vacío y el revisor
            # ve de dónde salió realmente).
            oe = estado_por_cp(izq[0])
    if der:
        est = estado_por_cp(der[0])
        # Chiapas exige ciudad autorizada: sin ciudad legible mejor dejarlo
        # vacío (revisión) que disparar el rechazo/errores de validación.
        if est and est != "Chiapas":
            de = est
    return (oc, oe, None, de)


def _origen_destino(lineas):
    """Origen y destino del CP. La tabla del complemento Carta Porte (si
    existe) es el dato estructurado más confiable, pero COMPLEMENTA a las
    demás estrategias: lo que la tabla no traiga se sigue buscando con ellas,
    campo por campo, y el CÓDIGO POSTAL entra como último respaldo (nunca se
    sustituye un dato ya encontrado por un None)."""
    t = _origen_destino_tabla_ccp(lineas)
    if t[1] and t[3]:                         # tabla completa → listo
        return t
    r = _origen_destino_estrategias(lineas)
    res = (t[0] or r[0], t[1] or r[1], t[2] or r[2], t[3] or r[3])
    if res[1] and res[3]:
        return res
    c = _origen_destino_por_cp(lineas)
    return (res[0] or c[0], res[1] or c[1], res[2] or c[2], res[3] or c[3])


def _origen_destino_estrategias(lineas):
    """Estrategias por layout de fletera; si ninguna funciona, el caso degrada
    a EN_REVISION (no a rechazo). Devuelve (ciudadO, estadoO, ciudadD, estadoD)."""
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
            # "AV. VERACRUZ" / "PROL. HIDALGO" son CALLES, no plazas (120472995,
            # 120493319: producían origen/destino "Av."/"Prol.").
            if m and not _ES_CALLE.match(m.group(1)):
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
        # Ambos en el mismo lado pero en la MISMA fila y con plazas DISTINTAS
        # → extremos: izquierdo=origen, derecho=destino.
        fila0 = cands[0][0]
        fila = sorted((c for c in cands if abs(c[0] - fila0) < 0.02), key=lambda c: c[1])
        if len(fila) >= 2 and fila[0][2] != fila[-1][2]:
            return (fila[0][2][0], fila[0][2][1], fila[-1][2][0], fila[-1][2][1])
        # Solo un candidato legible → devolver ese lado y dejar el otro vacío
        # (revisión). NUNCA duplicarlo como origen Y destino (folio 119581944:
        # destino quedaba "Jalisco" siendo Toluca/Edo. México).
        if ori:
            return (ori[2][0], ori[2][1], None, None)
        if dst:
            return (None, None, dst[2][0], dst[2][1])

    return (None, None, None, None)


# ── Desglose de consolidados (hoja-Excel dentro del PDF) ──────────
# Los consolidados (ACRED/GDL…) incluyen una página con la tabla de revisión:
# No. GUÍA | FECHA | CIUDAD | COMPAÑÍA | MÉTODO | # PAQUETES | TOTAL.
# Se extrae y se anexa al detalle del caso para que el revisor la vea en el
# monitor (es la misma tabla contra la que hoy revisan en Excel).
_RE_DESGLOSE_ROW = re.compile(
    r"(?m)^([A-Z0-9]{10,})\s*\n(\d{2}/\d{2}/\d{4})\s+(.+)\n(.+)\n(.+)\n(\d+)\n([\d,]+\.\d{2})")


def _parse_desglose(texto: str) -> list[dict]:
    up = (texto or "").upper()
    if "GU" not in up or "TOTAL" not in up or "CIUDAD" not in up:
        return []
    rows = []
    for m in _RE_DESGLOSE_ROW.finditer(texto):
        rows.append({"guia": m.group(1), "fecha": m.group(2),
                     "ciudad": " ".join(m.group(3).split()),
                     "compania": " ".join(m.group(4).split()),
                     "paquetes": int(m.group(6)),
                     "total": float(m.group(7).replace(",", ""))})
    return rows


def _pagina_desde_texto(lineas: list[dict]) -> dict:
    """Construye el dict de página (mismos campos que _parse_textract) desde la
    capa de texto del PDF. Reusa los helpers de RFC/emisor-receptor/tipo/folio."""
    # ¿Es la hoja de DESGLOSE de un consolidado? (tabla guía/ciudad/total, sin
    # RFCs). Se marca como tal para anexarla a los casos del PDF, no se clasifica.
    _texto_pagina = "\n".join(ln["text"] for ln in lineas)
    _rows_desglose = _parse_desglose(_texto_pagina)
    if _rows_desglose:
        return {"tipoDoc": "DESGLOSE", "desglose": _rows_desglose,
                "rfcEmisor": None, "rfcReceptor": None, "rfcsDetectados": [],
                "subtotal": None, "moneda": None, "tipoCambio": None, "folio": None,
                "fecha": None, "comentarios": None, "origenEstado": None,
                "origenCiudad": None, "destinoEstado": None, "destinoCiudad": None,
                "fletaRFC": None, "fleteraTexto": "", "partidas": []}

    senales = _senales_especiales(lineas)
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
    mcom = re.search(r"(?:OBSERVACIONES|COMENTARIOS|REF|FACTURAS?\s+ASOCIADAS?)[:\s].{0,120}",
                     full, re.I)
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
        "folio":          _folio_no_fiscal(lineas, serie_f=(clase == "FV")),
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
        "esMuestra":      clase == "FV" and bool(_RE_MUESTRA.search(_sin_acentos(full))),
        **senales,              # esNotaCredito / esPreguia / destinatarioGPA
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
                    p = _pagina_desde_texto(_lineas_pdf_pagina(page))
                    # El SELLO presupuestal es una IMAGEN estampada incluso en
                    # CFDI digitales: la capa de texto nunca lo trae. Con Bedrock
                    # disponible, leerlo de la página CP (1 llamada; fail-open).
                    if (OCR_BACKEND in ("bedrock", "hibrido")
                            and clasificar_pagina(p) == "CP" and not p.get("codigoSAP")):
                        png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
                        paginas.append((i, "sello", p, png))
                    else:
                        paginas.append((i, "lista", p, None))
                else:                            # revuelto/escaneo → rasterizar + OCR
                    png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
                    paginas.append((i, "ocr", None, png))
            except Exception as exc:   # una página ilegible no tumba el lote
                logger.warning("Página %d de %s ilegible: %s", i + 1, folio_archivo, exc)
                paginas.append((i, "lista", {"tipoDoc": "OTRO"}, None))
    finally:
        doc.close()

    # Fase 2 — OCR/sello en PARALELO. En serie, un escaneo de 25 páginas
    # (~30 s de visión por página) excedía incluso los 900 s de la Lambda
    # (GDL1A-21701, lote 26-06). Son llamadas de red (I/O): con 4 hilos el
    # mismo documento baja a ~3 min. La rasterización (pymupdf) queda arriba,
    # en un solo hilo, porque fitz no es thread-safe.
    def _resolver(t):
        i, tipo, p, png = t
        try:
            if tipo == "ocr":
                return ocr_pagina(png, client=client)
            if tipo == "sello":
                p.update({k: v for k, v in leer_sello_cp(png).items() if v})
            return p
        except Exception as exc:
            logger.warning("Página %d de %s ilegible: %s", i + 1, folio_archivo, exc)
            return {"tipoDoc": "OTRO"}

    if any(t[1] != "lista" for t in paginas):
        from concurrent.futures import ThreadPoolExecutor
        hilos = max(1, int(os.environ.get("OCR_CONCURRENCIA", "4")))
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            resueltas = list(ex.map(_resolver, paginas))
    else:
        resueltas = [t[2] for t in paginas]
    return emparejar_casos(resueltas, folio_archivo)


def procesar_objeto_s3(bucket: str, key: str, s3_client=None, bedrock_client=None) -> dict:
    """Descarga el PDF de S3 y devuelve los casos (emparejar_casos)."""
    s3 = s3_client or boto3.client("s3")
    pdf_bytes = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    folio = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return procesar_pdf(pdf_bytes, folio_archivo=folio, client=bedrock_client)
