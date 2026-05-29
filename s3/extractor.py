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
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

S3_CLIENT   = boto3.client("s3")
S3_BUCKET   = os.environ.get("S3_BUCKET", "gpa-documentos-dev")

# Tipo de cambio de respaldo cuando el upload no trae el metadato (configurable).
TIPO_CAMBIO_DEFAULT = float(os.environ.get("TIPO_CAMBIO_DEFAULT", "17.35"))

# Prefijos que identifican tipo de documento
RE_FV    = re.compile(r"^(FA|FC|FM|FLC|FMT|FL)\d", re.IGNORECASE)
RE_CP    = re.compile(r"^\d{9,}", re.IGNORECASE)
RE_PTX   = re.compile(r"^(GCCR|GCR)", re.IGNORECASE)
RE_CFD   = re.compile(r"^(FAC|GDL|ACRED)", re.IGNORECASE)
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _to_float(valor, default: float = 0.0) -> float:
    """Convierte un metadato S3 (texto arbitrario) a float sin lanzar excepción.

    Tolera símbolo de moneda, espacios y valores vacíos; ante texto no numérico
    registra una advertencia y devuelve el default en vez de propagar ValueError.
    """
    if valor is None:
        return default
    s = str(valor).strip().replace("$", "").replace(" ", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        logger.warning("Metadato numérico inválido %r → usando %s", valor, default)
        return default


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
                "ext":   os.path.splitext(fname)[1].lstrip(".").lower(),
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

    # La asociación FV→CP por folio de guía aún no está implementada: se asignan
    # todas las FVs de la carpeta a cada ancla. Eso es correcto solo si hay un
    # único CP/PTX por carpeta. Avisar cuando hay ambigüedad para no inflar montos
    # ni bloquear FVs de otros CP por R-091.
    anclas = len(cps) + len(ptxs)
    if anclas > 1 and fvs:
        logger.warning(
            "Carpeta con %d CP/PTX comparten %d FV(s): asociación FV→CP ambigua. "
            "Revisar emparejamiento por folio de guía antes de evaluar.",
            anclas, len(fvs),
        )

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
    try:
        resp = S3_CLIENT.head_object(Bucket=bucket, Key=key)
        meta = resp.get("Metadata", {})
    except ClientError as e:
        logger.warning("No se pudieron leer metadatos de s3://%s/%s: %s", bucket, key, e)
        meta = {}

    # Fecha de respaldo desde el path (pendientes/{fecha}/archivo) si es válida.
    partes = key.split("/")
    fecha_fallback = partes[1] if len(partes) > 1 and RE_FECHA.match(partes[1]) else ""

    return {
        # Vacío en vez de "GDL": no inventar una sucursal real; el motor lo tratará
        # como sucursal no válida (R-401-S) y forzará revisión, en lugar de asumir GDL.
        "origenSucursal":  meta.get("origen-sucursal", ""),
        "codigoSAP":       meta.get("codigo-sap", ""),
        "fletaRFC":        meta.get("fleta-rfc", ""),
        "destinoEstado":   meta.get("destino-estado", ""),
        "destinoCiudad":   meta.get("destino-ciudad", ""),
        "tipoCambioRef":   _to_float(meta.get("tipo-cambio"), TIPO_CAMBIO_DEFAULT),
        "fechaEmision":    meta.get("fecha-emision", fecha_fallback),
        "fleteBaseMXN":    _to_float(meta.get("flete-mxn"), 0.0),
        "ferryMXN":        _to_float(meta.get("ferry-mxn"), 0.0),
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

    # Determinar la carpeta-fecha del objeto. Solo procesamos el layout
    # canónico pendientes/{fecha}/archivo; cualquier otro key se ignora
    # (evita construir prefijos sin sentido y listar carpetas inexistentes).
    partes = key.split("/")
    if partes[0] != "pendientes" or len(partes) < 3:
        logger.warning("Key fuera del layout esperado pendientes/{fecha}/archivo: %s", key)
        return []

    fecha_carpeta = partes[1]

    # Listar TODOS los archivos de esa carpeta (paginado, sin truncar a 1000)
    prefijo_carpeta = f"pendientes/{fecha_carpeta}/"
    paginator = S3_CLIENT.get_paginator("list_objects_v2")
    archivos_raw = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefijo_carpeta):
        archivos_raw.extend(page.get("Contents", []))

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
            # Una sola fuente de verdad: metadato es-cfdi4 OR clasificación por archivo
            "esCFDI4":       bool(meta.get("esCFDI4")) or grupo["tipoCP"] == "CFDI4",
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
    partes = key.split("/")
    fname = partes[-1]
    # Validar que el segmento sea una fecha real; si no, cuarentena en sin-fecha/
    fecha = partes[1] if len(partes) > 1 and RE_FECHA.match(partes[1]) else ""
    anio, mes = (fecha[:4], fecha[5:7]) if fecha else ("sin-fecha", "00")

    destino_key = f"procesados/{anio}/{mes}/{sol_id}/{fname}"
    resultado_key = f"procesados/{anio}/{mes}/{sol_id}/resultado_{os.path.splitext(fname)[0]}.json"

    # Copiar + escribir resultado, y solo borrar el original si la copia se confirma.
    # Si algo falla, se conserva el documento en pendientes/ (no se pierde).
    try:
        S3_CLIENT.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=destino_key,
        )
        S3_CLIENT.put_object(
            Bucket=bucket,
            Key=resultado_key,
            Body=json.dumps(resultado, ensure_ascii=False, default=str),
            ContentType="application/json",
        )
        # Verificar que la copia exista antes del borrado irreversible
        S3_CLIENT.head_object(Bucket=bucket, Key=destino_key)
    except ClientError as e:
        logger.error("No se movió %s (se conserva el original): %s", key, e)
        raise

    S3_CLIENT.delete_object(Bucket=bucket, Key=key)
    logger.info("Movido: %s → %s", key, destino_key)
    return destino_key
