# s3/extractor.py
# Extractor de documentos GPA desde S3
# ─────────────────────────────────────────────────────────────────
# Estructura de bucket gpa-documentos-{env}:
#
#   pendientes/
#     2026-04-22/
#       116873635.pdf     ← CP Tresguerras
#       FA10315862.pdf    ← FV relacionada
#       116873635.xml     ← XML CFDI complemento (opcional)
#
#   procesados/{anio}/{mes}/{sol_id}/
#       {folioCP}.pdf
#       {folioCP}_resultado.json
#
# El extractor detecta el tipo por prefijo del filename y
# agrupa CP+FV(s) para construir la SolicitudFlete.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import re
import json
import boto3
import logging
from urllib.parse import unquote_plus

logger = logging.getLogger(__name__)

S3_CLIENT   = boto3.client("s3")
S3_BUCKET   = os.environ.get("S3_BUCKET", "gpa-documentos-dev")
TABLE_NAME  = os.environ.get("DYNAMO_TABLE", "gpa_fletes_dev")

# Prefijos que identifican tipo de documento
RE_FV  = re.compile(r"^(FA|FC|FM|FLC|FMT|FL)\d", re.IGNORECASE)
RE_CP  = re.compile(r"^\d{9,}", re.IGNORECASE)
RE_PTX = re.compile(r"^(GCCR|GCR)", re.IGNORECASE)
RE_CFD = re.compile(r"^(FAC|GDL|ACRED)", re.IGNORECASE)


def clasificar_folio(filename: str) -> str:
    """Detecta el tipo de documento por nombre de archivo."""
    name = os.path.basename(filename).upper()
    base = re.sub(r"\.(PDF|XML)$", "", name)
    if RE_FV.match(base):  return "FV"
    if RE_PTX.match(base): return "PTX"
    if RE_CFD.match(base): return "CFDI4"
    if RE_CP.match(base):  return "CP"
    return "UNKNOWN"


def listar_pendientes(bucket: str, prefix: str = "pendientes/") -> list[dict]:
    """
    Lista todos los objetos en pendientes/ agrupados por carpeta-fecha.
    Retorna: [{"fecha": "2026-04-22", "archivos": [{"key", "tipo", "folio"}]}]
    """
    paginator = S3_CLIENT.get_paginator("list_objects_v2")
    carpetas: dict[str, list] = {}

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            partes = key.split("/")
            if len(partes) < 3:
                continue
            fecha = partes[1]          # pendientes/{fecha}/archivo.pdf
            fname = partes[-1]
            tipo  = clasificar_folio(fname)
            folio = re.sub(r"\.(pdf|xml)$", "", fname, flags=re.I)

            if fecha not in carpetas:
                carpetas[fecha] = []
            carpetas[fecha].append({
                "key":   key,
                "tipo":  tipo,
                "folio": folio,
                "ext":   fname.split(".")[-1].lower(),
            })

    return [
        {"fecha": fecha, "archivos": archivos}
        for fecha, archivos in sorted(carpetas.items())
    ]


def agrupar_por_cp(archivos: list[dict]) -> list[dict]:
    """
    Agrupa los archivos de una carpeta por CP.
    Cada CP es el ancla; las FVs se asocian por proximidad de fecha/hora.
    Para PTX: cada línea GCCR se empareja con su FV por folio de guía.

    Retorna lista de grupos: [{folioCP, foliosFV, tipoCP, archivos}]
    """
    cps   = [a for a in archivos if a["tipo"] in ("CP", "CFDI4")]
    fvs   = {a["folio"]: a for a in archivos if a["tipo"] == "FV"}
    ptxs  = [a for a in archivos if a["tipo"] == "PTX"]

    grupos = []

    for cp in cps:
        grupo = {
            "folioCP":   cp["folio"],
            "foliosFV":  list(fvs.keys()),  # asociar todas las FVs de la carpeta
            "tipoCP":    cp["tipo"],
            "archivos":  [cp] + list(fvs.values()),
        }
        grupos.append(grupo)

    # PTX: cada archivo GCCR agrupa sus propias FVs
    for ptx in ptxs:
        grupo = {
            "folioCP":   ptx["folio"],
            "foliosFV":  list(fvs.keys()),
            "tipoCP":    "PTX",
            "archivos":  [ptx] + list(fvs.values()),
        }
        grupos.append(grupo)

    return grupos


def extraer_metadatos_s3(bucket: str, key: str) -> dict:
    """
    Lee los metadatos de un objeto S3.
    GPA puede poner metadatos custom en el upload:
        x-amz-meta-origen-sucursal: GDL
        x-amz-meta-fleta-rfc: ACT68080665A
        x-amz-meta-fecha-emision: 2026-04-22
    """
    resp = S3_CLIENT.head_object(Bucket=bucket, Key=key)
    meta = resp.get("Metadata", {})
    return {
        "origenSucursal":  meta.get("origen-sucursal", "GDL"),
        "codigoSAP":       meta.get("codigo-sap", ""),
        "fletaRFC":        meta.get("fleta-rfc", ""),
        "destinoEstado":   meta.get("destino-estado", ""),
        "destinoCiudad":   meta.get("destino-ciudad", ""),
        "tipoCambioRef":   float(meta.get("tipo-cambio", "17.35")),
        "fechaEmision":    meta.get("fecha-emision", key.split("/")[1]),
        "fleteBaseMXN":    float(meta.get("flete-mxn", "0")),
        "ferryMXN":        float(meta.get("ferry-mxn", "0")),
        "esCFDI4":         meta.get("es-cfdi4", "false").lower() == "true",
    }


def extraer_documentos_lote(bucket: str, key: str) -> list[dict]:
    """
    Punto de entrada del trigger S3.
    Dado el key del objeto recién subido, construye las
    solicitudes a evaluar.

    Retorna lista de dicts listos para POST /evaluar.
    """
    key = unquote_plus(key)
    logger.info("Extrayendo documentos desde s3://%s/%s", bucket, key)

    # Obtener metadatos del objeto disparador
    meta = extraer_metadatos_s3(bucket, key)

    # Determinar la carpeta-fecha del objeto
    partes = key.split("/")
    if len(partes) < 2:
        logger.warning("Key inesperado: %s", key)
        return []

    fecha_carpeta = partes[1] if partes[0] == "pendientes" else partes[0]

    # Listar todos los archivos de esa carpeta
    prefijo_carpeta = f"pendientes/{fecha_carpeta}/"
    resp = S3_CLIENT.list_objects_v2(Bucket=bucket, Prefix=prefijo_carpeta)
    archivos_raw = resp.get("Contents", [])

    archivos = []
    for obj in archivos_raw:
        k = obj["Key"]
        fname = k.split("/")[-1]
        tipo  = clasificar_folio(fname)
        folio = re.sub(r"\.(pdf|xml)$", "", fname, flags=re.I)
        archivos.append({"key": k, "tipo": tipo, "folio": folio})

    # Agrupar y construir solicitudes
    grupos  = agrupar_por_cp(archivos)
    solicitudes = []
    for grupo in grupos:
        sol = {
            "folioCP":       grupo["folioCP"],
            "foliosFV":      grupo["foliosFV"],
            "tipoCP":        grupo["tipoCP"],
            # Campos del metadata del objeto S3
            **meta,
            # Campos mínimos para el motor (partidas vacías → motor usará FV)
            "partidas":      [],
            "esCFDI4":       grupo["tipoCP"] == "CFDI4",
        }
        solicitudes.append(sol)
        logger.info(
            "Solicitud construida: CP=%s FVs=%s tipo=%s",
            sol["folioCP"], sol["foliosFV"], sol["tipoCP"]
        )

    return solicitudes


def mover_a_procesados(bucket: str, key: str, sol_id: str, resultado: dict):
    """
    Mueve el documento de pendientes/ a procesados/ después de evaluarlo.
    También escribe el JSON de resultado junto al documento.
    """
    fname = key.split("/")[-1]
    fecha = key.split("/")[1] if len(key.split("/")) > 1 else "unknown"
    anio, mes = fecha[:4], fecha[5:7]

    destino_key = f"procesados/{anio}/{mes}/{sol_id}/{fname}"

    # Copiar
    S3_CLIENT.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": key},
        Key=destino_key,
    )

    # Escribir resultado JSON
    resultado_key = f"procesados/{anio}/{mes}/{sol_id}/resultado_{fname.split('.')[0]}.json"
    S3_CLIENT.put_object(
        Bucket=bucket,
        Key=resultado_key,
        Body=json.dumps(resultado, ensure_ascii=False, default=str),
        ContentType="application/json",
    )

    # Eliminar de pendientes
    S3_CLIENT.delete_object(Bucket=bucket, Key=key)

    logger.info("Movido: %s → %s", key, destino_key)
    return destino_key
