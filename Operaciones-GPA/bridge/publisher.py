# bridge/publisher.py
# Publisher del puente Operaciones-GPA → Fleet Command (contrato gpa.ops.v1)
# ─────────────────────────────────────────────────────────────────
# Se dispara con DynamoDB Streams (NEW_AND_OLD_IMAGES) de la tabla
# gpa_operaciones_{env} y publica cada captura relevante al receptor
# de Fleet Command como POST JSON firmado con HMAC-SHA256.
#
# Reglas (ver bridge/CONTRATO-gpa.ops.v1.md):
#   - Solo registros SK=META de tipos en BRIDGE_TIPOS (default SOL,CL).
#   - INSERT              → evento "creacion"
#   - MODIFY con `status` distinto → evento "cambio_estado"
#     (parches internos como análisis de foto NO emiten)
#   - Sin FLEET_BRIDGE_URL configurada opera en modo espera: registra y
#     confirma el lote sin enviar (permite desplegar antes que el receptor).
#   - Fallas de envío se reportan como batchItemFailures → el stream
#     reintenta y, agotados los intentos, el registro cae a la DLQ.
#
# Sin dependencias: solo biblioteca estándar (probable en local sin boto3).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CONTRATO = "gpa.ops.v1"

# Clave de evidencia en el bucket de Operaciones-GPA: {SOL|CL|MC|FRM}/{uuid32}.{ext}
_KEY_EVIDENCIA = re.compile(r"^(SOL|CL|MC|FRM)/[0-9a-f]{32}\.(jpg|png|webp)$")

# Campos de infraestructura que no viajan en `answers`
_CAMPOS_INFRA = {
    "PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK",
    "id", "tipo_reg", "fecha", "sucursal", "accountId",
    "vehicleId", "placas", "economico", "userId", "responsable", "firma",
}


def _env(nombre: str, default: str = "") -> str:
    return os.environ.get(nombre, default).strip()


# ── Deserialización de imágenes del stream (DynamoDB JSON) ────────
def _des(av: dict):
    """AttributeValue de DynamoDB → valor Python (sin boto3)."""
    (t, v), = av.items()
    if t == "S":
        return v
    if t == "N":
        f = float(v)
        return int(f) if f == int(f) else f
    if t == "BOOL":
        return v
    if t == "NULL":
        return None
    if t == "M":
        return {k: _des(x) for k, x in v.items()}
    if t == "L":
        return [_des(x) for x in v]
    if t in ("SS", "NS"):
        return list(v)
    return v  # B/BS u otros: no se usan en esta tabla


def _imagen(record: dict, cual: str) -> dict | None:
    img = record.get("dynamodb", {}).get(cual)
    return {k: _des(v) for k, v in img.items()} if img else None


# ── Construcción del evento gpa.ops.v1 ───────────────────────────
def _evidencias(obj, ruta: str = "") -> list[dict]:
    """Recorre el registro y junta toda clave S3 de evidencia con su campo."""
    out = []
    if isinstance(obj, str) and _KEY_EVIDENCIA.match(obj):
        out.append({"campo": ruta or "?", "key": obj})
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_evidencias(v, f"{ruta}.{k}" if ruta else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_evidencias(v, f"{ruta}[{i}]"))
    return out


def construir_evento(item: dict, evento: str) -> dict:
    """Registro (imagen NEW deserializada) → evento del contrato gpa.ops.v1."""
    tipo = item.get("tipo_reg") or str(item.get("PK", "")).split("#", 1)[0]
    answers = {k: v for k, v in item.items() if k not in _CAMPOS_INFRA}
    subtipo = item.get("tipo") if tipo == "CL" else None
    firma = item.get("firma")
    if not (isinstance(firma, str) and _KEY_EVIDENCIA.match(firma)):
        firma = None
    return {
        "version": 1,
        "contrato": CONTRATO,
        "tipo": tipo,
        "subtipo": subtipo,
        "evento": evento,
        "registroId": item.get("id"),
        "folio": f"OPS-{item.get('id')}",
        "fechaISO": item.get("fecha"),
        "sucursal": item.get("sucursal"),
        "unidad": {
            "vehicleId": item.get("vehicleId"),
            "economico": item.get("economico"),
            "placas": item.get("placas"),
        },
        "responsable": {
            "nombre": item.get("responsable"),
            "userId": item.get("userId"),
            "accountId": item.get("accountId"),
        },
        "status": item.get("status"),
        "answers": answers,
        "evidencias": _evidencias(answers),
        "firma": firma,
        "bucketOrigen": _env("EVIDENCIAS_BUCKET"),
        "emitidoEn": datetime.now(timezone.utc).isoformat(),
    }


def filtrar_record(record: dict) -> tuple[dict, str] | None:
    """Decide si un record del stream emite evento. → (imagen_nueva, evento) o None."""
    nombre = record.get("eventName")
    if nombre not in ("INSERT", "MODIFY"):
        return None
    nueva = _imagen(record, "NewImage")
    if not nueva or nueva.get("SK") != "META":
        return None
    tipo = nueva.get("tipo_reg") or str(nueva.get("PK", "")).split("#", 1)[0]
    tipos = {t.strip() for t in _env("BRIDGE_TIPOS", "SOL,CL").split(",") if t.strip()}
    if tipo not in tipos:
        return None
    if nombre == "INSERT":
        return nueva, "creacion"
    vieja = _imagen(record, "OldImage") or {}
    if nueva.get("status") != vieja.get("status"):
        return nueva, "cambio_estado"
    return None  # MODIFY sin cambio de status (p. ej. merge de análisis de foto)


# ── Envío firmado ────────────────────────────────────────────────
def firmar(secreto: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + body
    return hmac.new(secreto.encode(), msg, hashlib.sha256).hexdigest()


def enviar(evento: dict, url: str, secreto: str, timeout: int = 20) -> None:
    """POST firmado al receptor. Lanza excepción si la respuesta no es 2xx."""
    body = json.dumps(evento, ensure_ascii=False, default=str).encode()
    ts = str(int(time.time()))
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GPA-Contrato": CONTRATO,
            "X-GPA-Timestamp": ts,
            "X-GPA-Firma": firmar(secreto, ts, body),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if not 200 <= resp.status < 300:
            raise RuntimeError(f"Receptor respondió {resp.status}")


def metrica_envio(ev: dict) -> None:
    """Métrica GPA/Bridge·EnviosExitosos en formato EMF (CloudWatch la extrae
    del log; sin dependencias). Alimenta la alarma de silencio del template."""
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace":  "GPA/Bridge",
                "Dimensions": [["Env"]],
                "Metrics":    [{"Name": "EnviosExitosos", "Unit": "Count"}],
            }],
        },
        "Env": _env("ENV", "dev"),
        "EnviosExitosos": 1,
        "tipo": ev.get("tipo"),
        "folio": ev.get("folio"),
        "evento": ev.get("evento"),
    }))


# ── Handler ──────────────────────────────────────────────────────
def lambda_handler(event, context):
    url = _env("FLEET_BRIDGE_URL")
    secreto = _env("FLEET_BRIDGE_SECRET")
    fallidos = []

    for record in event.get("Records", []):
        seq = record.get("dynamodb", {}).get("SequenceNumber", "")
        try:
            emision = filtrar_record(record)
            if not emision:
                continue
            item, nombre_evento = emision
            ev = construir_evento(item, nombre_evento)
            if not url:
                logger.info("[modo espera] FLEET_BRIDGE_URL vacía; no se envía %s %s (%s)",
                            ev["tipo"], ev["folio"], nombre_evento)
                continue
            enviar(ev, url, secreto)
            metrica_envio(ev)
            logger.info("Enviado %s %s (%s)", ev["tipo"], ev["folio"], nombre_evento)
        except Exception:
            logger.exception("Falló el envío del record seq=%s; se reintentará", seq)
            fallidos.append({"itemIdentifier": seq})

    return {"batchItemFailures": fallidos}
