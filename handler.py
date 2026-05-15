# handler.py  — v2.4.1
# Lambda GPA Motor de Fletes — API Gateway HTTP API v2
# ─────────────────────────────────────────────────────────────────
# Rutas:
#   POST  /evaluar              evaluar solicitud de flete
#   POST  /aprobar              aprobador 1 aprueba
#   POST  /rechazar             aprobador 1 rechaza
#   POST  /escalar              escalar a aprobador 2
#   GET   /monitor              kanban + filtro fecha
#   GET   /kpis                 KPIs del mes
#   GET   /solicitud/{id}       detalle + historial
#   GET   /solicitudes          listado paginado
#   GET   /auditor/fletera      por RFC de fletera
#   GET   /auditor/sucursal     por sucursal origen
#   GET   /auditor/destino      por estado destino
#   GET   /health               health check (sin auth)
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json, os, logging, traceback
from typing import Any
from motor.evaluador import SolicitudFlete, evaluar_solicitud
from motor.catalogos import R_CONCEPTOS
from db.validaciones import verificar_unicidad
from db.escritura    import guardar_solicitud, cambiar_estado
from db.queries      import (get_cola_revision, get_por_rango_fecha, get_kpis_mes,
                              get_solicitud_completa, get_por_fletera,
                              get_por_sucursal, get_por_destino)
from s3.extractor    import extraer_documentos_lote

logger = logging.getLogger()
logger.setLevel(logging.INFO)
VERSION = "2.4.1"

def _ok(b, s=200):
    return {"statusCode":s,"headers":{"Content-Type":"application/json",
            "Access-Control-Allow-Origin":os.environ.get("ALLOWED_ORIGIN","*"),
            "X-GPA-Motor-Version":VERSION},"body":json.dumps(b,ensure_ascii=False,default=str)}

def _err(msg, s=400, codigo=None):
    p={"error":msg,"status":s}
    if codigo: p["codigoMotor"]=codigo; p["concepto"]=R_CONCEPTOS.get(codigo,codigo)
    return {"statusCode":s,"headers":{"Content-Type":"application/json",
            "Access-Control-Allow-Origin":os.environ.get("ALLOWED_ORIGIN","*")},
            "body":json.dumps(p,ensure_ascii=False)}

def _body(ev):
    try: return json.loads(ev.get("body") or "{}")
    except: raise ValueError("Body debe ser JSON válido")

def _qs(ev): return ev.get("queryStringParameters") or {}

def _uid(ev):
    claims=ev.get("requestContext",{}).get("authorizer",{}).get("jwt",{}).get("claims",{})
    return claims.get("email") or claims.get("cognito:username") or ev.get("headers",{}).get("x-gpa-userid","desconocido")

# ── Router ────────────────────────────────────────────────────────
def lambda_handler(event, context):
    src=_detect_source(event)
    try:
        if src=="api_gateway": return _router(event)
        if src=="s3":          return _handle_s3(event)
        if src=="sqs":         return _handle_sqs(event)
        return _err("Trigger no reconocido",400)
    except ValueError as e: return _err(str(e),400)
    except Exception as exc:
        logger.error("Error:\n%s",traceback.format_exc())
        return _err(f"Error interno: {str(exc)}",500)

def _detect_source(ev):
    if "requestContext" in ev: return "api_gateway"
    if "Records" in ev:
        r=ev["Records"][0]
        if r.get("eventSource")=="aws:s3": return "s3"
        if r.get("eventSource")=="aws:sqs": return "sqs"
    return "unknown"

def _router(event):
    rc=event.get("requestContext",{})
    http=rc.get("http",{})
    method=http.get("method") or event.get("httpMethod","")
    path=http.get("path") or event.get("path","")
    for env in ("dev","staging","prod"):
        if path.startswith(f"/{env}/"): path=path[len(f"/{env}"):]; break
    if method=="GET" and path.startswith("/solicitud/"):
        return _route_solicitud(event, path.split("/")[-1])
    RUTAS={
        ("POST","/evaluar"):          _route_evaluar,
        ("POST","/aprobar"):          _route_aprobar,
        ("POST","/rechazar"):         _route_rechazar,
        ("POST","/escalar"):          _route_escalar,
        ("GET","/monitor"):           _route_monitor,
        ("GET","/kpis"):              _route_kpis,
        ("GET","/solicitudes"):       _route_solicitudes,
        ("GET","/auditor/fletera"):   _route_auditor_fletera,
        ("GET","/auditor/sucursal"):  _route_auditor_sucursal,
        ("GET","/auditor/destino"):   _route_auditor_destino,
        ("GET","/health"):            _route_health,
    }
    fn=RUTAS.get((method,path))
    if fn: return fn(event)
    return _err(f"Ruta no encontrada: {method} {path}",404)

# ── POST /evaluar ─────────────────────────────────────────────────
def _route_evaluar(event):
    b=_body(event)
    req=["folioCP","foliosFV","origenSucursal","destinoEstado","fletaRFC","partidas","fleteBaseMXN","tipoCambioRef","fechaEmision"]
    miss=[r for r in req if r not in b]
    if miss: return _err(f"Campos requeridos: {miss}",400)
    if b.get("destinoEstado")=="Chiapas" and not b.get("destinoCiudad"):
        return _err("Chiapas requiere destinoCiudad. Autorizadas: Tapachula, Tuxtla Gutiérrez.",400)
    val=verificar_unicidad(b["folioCP"],b["foliosFV"])
    if not val["valido"]:
        _guardar_bloqueada(b,val)
        return _err(val["detalle"],409,val["codigo"])
    sol=SolicitudFlete(
        folio_cp=b["folioCP"],folios_fv=b["foliosFV"],
        origen_sucursal=b["origenSucursal"],codigo_sap=b.get("codigoSAP",""),
        destino_estado=b["destinoEstado"],destino_ciudad=b.get("destinoCiudad",""),
        fleta_rfc=b["fletaRFC"],campo_entrega_fv=b.get("campoEntregaFV",""),
        partidas=b["partidas"],flete_base_mxn=float(b["fleteBaseMXN"]),
        ferry_mxn=float(b.get("ferryMXN",0)),tipo_cambio_ref=float(b["tipoCambioRef"]),
        fecha_emision=b["fechaEmision"],folio_ptx_guia=b.get("folioPtxGuia"),
        costo_ptx_mxn=float(b.get("costoPtxMXN",0)),es_cfdi4=bool(b.get("esCFDI4",False)))
    resultado=evaluar_solicitud(sol)
    reg=guardar_solicitud(resultado)
    logger.info("EVALUAR %s → %s user=%s",b["folioCP"],resultado.codigo_motor,_uid(event))
    return _ok({"id":reg["id"],"folioCP":b["folioCP"],"codigoMotor":resultado.codigo_motor,
                "concepto":resultado.concepto,"estado":resultado.estado,
                "pctFlete":round(resultado.pct_flete*100,2),
                "montoBaseUSD":round(resultado.monto_base_usd,2),
                "fleteBaseUSD":round(resultado.flete_base_usd,2),
                "criterios":resultado.criterios_detalle,
                "fechaEvaluacion":reg["fechaEvaluacion"]},201)

# ── POST /aprobar /rechazar /escalar ──────────────────────────────
def _route_aprobar(event):
    b=_body(event)
    if "id" not in b: return _err("'id' requerido",400)
    uid=_uid(event); res=cambiar_estado(b["id"],"APROBADA_MANUAL",uid,b.get("comentario",""))
    logger.info("APROBAR %s por %s",b["id"],uid); return _ok(res)

def _route_rechazar(event):
    b=_body(event)
    if "id" not in b: return _err("'id' requerido",400)
    uid=_uid(event); res=cambiar_estado(b["id"],"RECHAZADA_MANUAL",uid,b.get("comentario",""))
    return _ok(res)

def _route_escalar(event):
    b=_body(event)
    if "id" not in b: return _err("'id' requerido",400)
    uid=_uid(event); res=cambiar_estado(b["id"],"ESCALADA",uid,b.get("comentario",""))
    return _ok(res)

# ── GET /monitor ──────────────────────────────────────────────────
def _route_monitor(event):
    qs=_qs(event); estado=qs.get("estado","EN_REVISION")
    desde=qs.get("desde"); hasta=qs.get("hasta")
    items=get_por_rango_fecha(estado,desde,hasta) if (desde and hasta) else get_cola_revision(desde)
    return _ok({"items":items,"estado":estado,"total":len(items)})

# ── GET /kpis ─────────────────────────────────────────────────────
def _route_kpis(event):
    from datetime import datetime; hoy=datetime.now(); qs=_qs(event)
    return _ok(get_kpis_mes(int(qs.get("anio",hoy.year)),int(qs.get("mes",hoy.month))))

# ── GET /solicitud/{id} ───────────────────────────────────────────
def _route_solicitud(event,sol_id):
    item=get_solicitud_completa(sol_id)
    if not item: return _err(f"Solicitud '{sol_id}' no encontrada",404)
    return _ok(item)

# ── GET /solicitudes ──────────────────────────────────────────────
def _route_solicitudes(event):
    qs=_qs(event); desde=qs.get("desde"); hasta=qs.get("hasta")
    if not desde or not hasta: return _err("'desde' y 'hasta' requeridos (YYYY-MM-DD)",400)
    estado=qs.get("estado","AUTO_APROBADA"); limit=min(int(qs.get("limit",50)),200)
    items=get_por_rango_fecha(estado,desde,hasta)[:limit]
    return _ok({"items":items,"total":len(items),"estado":estado,"desde":desde,"hasta":hasta})

# ── GET /auditor/fletera ──────────────────────────────────────────
def _route_auditor_fletera(event):
    qs=_qs(event); rfc=qs.get("rfc"); desde=qs.get("desde"); hasta=qs.get("hasta")
    if not rfc: return _err("'rfc' requerido",400)
    if not desde or not hasta: return _err("'desde' y 'hasta' requeridos",400)
    items=get_por_fletera(rfc,desde,hasta)
    return _ok({"items":items,"rfc":rfc,"total":len(items)})

# ── GET /auditor/sucursal ─────────────────────────────────────────
def _route_auditor_sucursal(event):
    qs=_qs(event); suc=qs.get("sucursal"); desde=qs.get("desde"); hasta=qs.get("hasta")
    if not suc: return _err("'sucursal' requerido",400)
    if not desde or not hasta: return _err("'desde' y 'hasta' requeridos",400)
    items=get_por_sucursal(suc,desde,hasta)
    return _ok({"items":items,"sucursal":suc,"total":len(items)})

# ── GET /auditor/destino ──────────────────────────────────────────
def _route_auditor_destino(event):
    qs=_qs(event); dest=qs.get("estado"); desde=qs.get("desde"); hasta=qs.get("hasta")
    if not dest: return _err("'estado' (destino) requerido",400)
    if not desde or not hasta: return _err("'desde' y 'hasta' requeridos",400)
    items=get_por_destino(dest,desde,hasta)
    return _ok({"items":items,"destinoEstado":dest,"total":len(items)})

# ── GET /health ───────────────────────────────────────────────────
def _route_health(event):
    import boto3; from datetime import datetime,timezone
    checks={"lambda":"ok","version":VERSION}
    try:
        boto3.client("dynamodb").describe_table(TableName=os.environ.get("DYNAMO_TABLE","gpa_fletes_dev"))
        checks["dynamodb"]="ok"
    except Exception as e: checks["dynamodb"]=f"error:{str(e)[:60]}"
    try:
        bucket=os.environ.get("S3_BUCKET","")
        if bucket: boto3.client("s3").head_bucket(Bucket=bucket); checks["s3"]="ok"
        else: checks["s3"]="not-configured"
    except Exception as e: checks["s3"]=f"error:{str(e)[:60]}"
    all_ok=all(v in("ok","not-configured") for v in checks.values())
    checks["timestamp"]=datetime.now(timezone.utc).isoformat()
    checks["status"]="healthy" if all_ok else "degraded"
    return _ok(checks, 200 if all_ok else 503)

# ── S3 / SQS triggers ────────────────────────────────────────────
def _handle_s3(event):
    resultados=[]
    for r in event["Records"]:
        bucket=r["s3"]["bucket"]["name"]; key=r["s3"]["object"]["key"]
        try:
            for sol in extraer_documentos_lote(bucket,key):
                resp=_route_evaluar({"requestContext":{},"path":"/evaluar","httpMethod":"POST","body":json.dumps(sol)})
                resultados.append({"key":key,"status":resp["statusCode"],"body":json.loads(resp["body"])})
        except Exception as exc:
            logger.error("S3 %s: %s",key,exc); resultados.append({"key":key,"error":str(exc)})
    return {"batchItemFailures":[],"resultados":resultados}

def _handle_sqs(event):
    failures=[]
    for r in event["Records"]:
        mid=r["messageId"]
        try:
            resp=_route_evaluar({"requestContext":{},"path":"/evaluar","httpMethod":"POST","body":r["body"]})
            if resp["statusCode"] not in(200,201,409): failures.append({"itemIdentifier":mid})
        except: failures.append({"itemIdentifier":mid})
    return {"batchItemFailures":failures}

def _guardar_bloqueada(body,val):
    try:
        import uuid; from datetime import datetime,timezone; from db.escritura import _dynamo_client
        ahora=datetime.now(timezone.utc).isoformat(); sid=str(uuid.uuid4())
        _dynamo_client().put_item(TableName=os.environ.get("DYNAMO_TABLE","gpa_fletes_dev"),
            Item={"PK":{"S":f"SOL#{sid}"},"SK":{"S":"#META"},"estado":{"S":"BLOQUEADA"},
                  "codigoMotor":{"S":val["codigo"]},"conceptoMotor":{"S":R_CONCEPTOS.get(val["codigo"],"")},
                  "folioCP":{"S":body.get("folioCP","")},"fechaEmision":{"S":body.get("fechaEmision",ahora[:10])},
                  "fechaEvaluacion":{"S":ahora},"detalle":{"S":val["detalle"]}})
    except Exception as e: logger.warning("No se pudo guardar bloqueada: %s",e)
