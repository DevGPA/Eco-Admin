# s3/evidencias.py
# URLs prefirmadas para subir/leer CFDIs, comprobantes y firmas — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import uuid
import boto3

BUCKET = os.environ.get("EVIDENCIAS_BUCKET", "")
TTL    = int(os.environ.get("URL_FIRMADA_TTL", "900"))
_client = None

# Comprobantes pueden ser imágenes (foto del ticket/firma) o PDF (CFDI).
_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "application/pdf": "pdf", "application/xml": "xml", "text/xml": "xml",
}


def _c():
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def url_subida(carpeta: str, content_type: str) -> dict:
    """
    Genera una URL PUT prefirmada para subir una evidencia.
    `carpeta` agrupa por tipo (FIRMA, CFDI, TICKET). Devuelve {key, uploadUrl}.
    El cliente sube el archivo con PUT a uploadUrl y guarda `key` en el registro.
    """
    ext = _EXT.get(content_type, "bin")
    carpeta = carpeta if carpeta in ("FIRMA", "CFDI", "TICKET", "VIA") else "VIA"
    key = f"{carpeta}/{uuid.uuid4().hex}.{ext}"
    upload_url = _c().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=TTL,
    )
    return {"key": key, "uploadUrl": upload_url}


def url_lectura(key: str) -> str | None:
    """URL GET prefirmada para mostrar una evidencia. None si key vacío."""
    if not key:
        return None
    return _c().generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=TTL,
    )
