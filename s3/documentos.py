# s3/documentos.py — subida y lectura de documentos del expediente.
# ─────────────────────────────────────────────────────────────────
# El archivo nunca pasa por la Lambda: el cliente lo sube directo a S3 con una
# URL prefirmada de corta vida. El bucket es privado y la Lambda es la única que
# puede firmar. Al leer se firma otra URL, también temporal.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import re
import secrets

import boto3
from botocore.config import Config

_S3 = None

# Solo estos tipos. Nada de ejecutables ni de HTML (que podría ejecutarse al abrirlo).
TIPOS_PERMITIDOS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}
TAM_MAXIMO = 15 * 1024 * 1024      # 15 MB por archivo
TTL_SUBIDA = 900                    # 15 min para subir
TTL_LECTURA = 300                   # 5 min para ver
_KEY_RE = re.compile(r"^GS-\d{4}-\d{3}/[a-z0-9_]{1,40}-[0-9a-f]{12}\.(pdf|jpg|png|webp|heic)$")


def cliente():
    global _S3
    if _S3 is None:
        _S3 = boto3.client("s3", config=Config(signature_version="s3v4"))
    return _S3


def bucket() -> str:
    return os.environ["DOCS_BUCKET"]


class DocumentoInvalido(Exception):
    """El archivo no cumple; el mensaje se le muestra a quien lo sube."""


def arma_key(folio: str, doc_id: str, content_type: str) -> str:
    ext = TIPOS_PERMITIDOS.get(content_type)
    if not ext:
        permitidos = ", ".join(sorted({v.upper() for v in TIPOS_PERMITIDOS.values()}))
        raise DocumentoInvalido(f"Ese tipo de archivo no se acepta. Suba {permitidos}.")
    return f"{folio}/{doc_id}-{secrets.token_hex(6)}.{ext}"


# Los anexos internos usan este identificador. Van al mismo bucket privado, pero
# NUNCA se listan en la vista del cliente: esa se arma por lista blanca.
ID_INTERNO = "interno"


def url_subida(folio: str, doc_id: str, content_type: str, tam: int) -> dict:
    """URL prefirmada para que el navegador haga PUT del archivo."""
    if tam and int(tam) > TAM_MAXIMO:
        mb = TAM_MAXIMO // (1024 * 1024)
        raise DocumentoInvalido(f"El archivo pesa más de {mb} MB. "
                                "Tome la foto con menos resolución o comprima el PDF.")
    key = arma_key(folio, doc_id, content_type)
    url = cliente().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type,
                "ServerSideEncryption": "AES256"},
        ExpiresIn=TTL_SUBIDA,
    )
    return {"url": url, "key": key, "contentType": content_type,
            "headers": {"Content-Type": content_type,
                        "x-amz-server-side-encryption": "AES256"}}


def url_lectura(key: str) -> str:
    """URL temporal para ver un documento ya guardado."""
    if not key or not _KEY_RE.match(key):
        return ""
    return cliente().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=TTL_LECTURA
    )


def resuelve_urls(caso: dict) -> dict:
    """Agrega a cada adjunto su URL temporal de lectura, sin tocar el guardado."""
    adjuntos = caso.get("adjuntos") or {}
    salida = {}
    for doc_id, info in adjuntos.items():
        if isinstance(info, dict):
            salida[doc_id] = {**info, "url": url_lectura(info.get("key", ""))}
        else:
            salida[doc_id] = info
    return {**caso, "adjuntos": salida}
