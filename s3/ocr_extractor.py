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

from motor.catalogos import RFC_GPA

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
)
OCR_DPI = int(os.environ.get("OCR_DPI", "200"))

# Instrucción de extracción para Claude. Pide JSON estricto por página.
PROMPT_OCR = (
    "Eres un extractor de datos de comprobantes fiscales mexicanos (CFDI 4.0). "
    "La imagen es UNA página de un comprobante escaneado (carta porte o factura). "
    "Devuelve EXCLUSIVAMENTE un objeto JSON, sin texto adicional, con estas claves:\n"
    '  "rfcEmisor": string|null  (RFC de quien EMITE el comprobante)\n'
    '  "rfcReceptor": string|null  (RFC de quien RECIBE)\n'
    '  "tipoDocumento": "CARTA_PORTE"|"FACTURA"|"CFDI"|"OTRO"\n'
    '  "subtotal": number|null  (Sub-Total SIN IVA, solo el número)\n'
    '  "moneda": "MXN"|"USD"|null\n'
    '  "tipoCambio": number|null  (si aparece "Tipo de Cambio")\n'
    '  "folio": string|null  (folio o serie-folio del comprobante)\n'
    "Si la página no es un comprobante (anexo, acuse, etc.), usa tipoDocumento=OTRO "
    "y los demás en null."
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


# ── OCR de una página con Claude (Bedrock) ────────────────────────
def _bedrock_client():
    return boto3.client("bedrock-runtime")


def ocr_pagina(imagen_png: bytes, client=None, model_id: str = BEDROCK_MODEL_ID) -> dict:
    """Extrae los campos del comprobante de UNA página vía Bedrock/Claude."""
    client = client or _bedrock_client()
    resp = client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"text": PROMPT_OCR},
                {"image": {"format": "png", "source": {"bytes": imagen_png}}},
            ],
        }],
        inferenceConfig={"maxTokens": 1024, "temperature": 0},
    )
    texto = resp["output"]["message"]["content"][0]["text"]
    return _parse_json(texto)


def _parse_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta del modelo."""
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
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


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


# ── Orquestación end-to-end (S3 → OCR → caso) ─────────────────────
def procesar_pdf(pdf_bytes: bytes, folio_archivo: str = "", client=None) -> dict:
    """Renderiza el PDF, hace OCR de cada página y arma el caso."""
    paginas_img = render_paginas_pdf(pdf_bytes)
    paginas = []
    for i, img in enumerate(paginas_img):
        try:
            paginas.append(ocr_pagina(img, client=client))
        except Exception as exc:   # una página ilegible no tumba el caso
            logger.warning("OCR falló en página %d de %s: %s", i + 1, folio_archivo, exc)
            paginas.append({"tipoDocumento": "OTRO"})
    return armar_caso(paginas, folio_archivo)
