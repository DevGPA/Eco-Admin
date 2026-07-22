# handler.py  — v2.4.1
# Lambda GPA Motor de Fletes — API Gateway HTTP API v2
# ─────────────────────────────────────────────────────────────────
# Rutas:
#   POST  /evaluar              evaluar solicitud de flete
#   POST  /aprobar              aprobador 1 aprueba
#   POST  /rechazar             aprobador 1 rechaza
#   POST  /escalar              escalar a aprobador 2
#   POST  /confirmar-rechazo    aceptar el rechazo del motor (sale del Kanban)
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
from dataclasses import asdict
from typing import Any
from motor.evaluador import (SolicitudInput, evaluar, CriterioDetalle,
                              CartaPorte, FacturaVenta, Partida, LineaCargo)
from motor.catalogos import R_CONCEPTOS, normalizar_destino
from db.validaciones import verificar_unicidad
from db.escritura    import guardar_solicitud, cambiar_estado
from db.queries      import (get_cola_revision, get_por_rango_fecha, get_kpis_mes,
                              get_solicitud_completa, get_por_fletera,
                              get_por_sucursal, get_por_destino)
from s3.ocr_extractor import procesar_objeto_s3, caso_a_solicitud

logger = logging.getLogger()
logger.setLevel(logging.INFO)
VERSION = "2.6.9"   # Tarifas oficiales 2026 de dispersión (solo tórtón y cajas 25/50kg)

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
        ("POST","/confirmar-rechazo"): _route_confirmar_rechazo,
        ("GET","/monitor"):           _route_monitor,
        ("GET","/kpis"):              _route_kpis,
        ("GET","/solicitudes"):       _route_solicitudes,
        ("GET","/auditor/fletera"):   _route_auditor_fletera,
        ("GET","/auditor/sucursal"):  _route_auditor_sucursal,
        ("GET","/auditor/destino"):   _route_auditor_destino,
        ("POST","/upload-url"):       _route_upload_url,
        ("GET","/documento"):         _route_documento,
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
    try:
        tc=float(b["tipoCambioRef"])
    except (TypeError,ValueError):
        return _err("tipoCambioRef debe ser numérico",400)
    if tc<=0:
        return _err("tipoCambioRef debe ser mayor a 0",400)
    if normalizar_destino(str(b.get("destinoEstado") or "")).upper()=="CHIAPAS" and not b.get("destinoCiudad"):
        return _err("Chiapas requiere destinoCiudad. Autorizadas: Tapachula, Tuxtla Gutiérrez.",400)
    val=verificar_unicidad(b["folioCP"],b["foliosFV"])
    if not val["valido"]:
        _guardar_bloqueada(b,val)
        return _err(val["detalle"],409,val["codigo"])
    sol=_build_solicitud_input(b)
    resultado=evaluar(sol)
    # Consolidados: anexar el desglose (guía/ciudad/total) al detalle del caso —
    # es la tabla contra la que el revisor valida (antes lo hacía en Excel).
    des=b.get("desgloseConsolidado") or []
    if des:
        try:
            suma=sum(float(d.get("total",0) or 0) for d in des)
            detalle="; ".join(f"{d.get('guia','?')} → {d.get('ciudad','?')} ({d.get('compania','')}) "
                              f"${float(d.get('total',0) or 0):,.2f}" for d in des)[:900]
            resultado.criterios.append(CriterioDetalle(
                "Desglose consolidado","INFO",
                f"{len(des)} guías · ${suma:,.2f} MXN",detalle))
        except Exception as e:
            logger.warning("Desglose consolidado no anexado: %s",e)
    # Sello de Control Presupuestal leído del documento (visión): visible en el
    # detalle para el revisor (código de gasto GS0xxx + tipo de flete).
    if b.get("codigoSAP") or b.get("tipoFleteSello"):
        resultado.criterios.append(CriterioDetalle(
            "Sello presupuestal","INFO",
            str(b.get("codigoSAP") or "sin código"),
            str(b.get("tipoFleteSello") or "")))
    resultado.archivo_s3=str(b.get("archivoS3") or "")   # PDF de referencia (S3)
    reg=guardar_solicitud(resultado)
    # Re-procesamiento: los AUTO_RECHAZADA previos del mismo folio quedan
    # REEMPLAZADA (fuera del Kanban; el historial se conserva para auditoría).
    for prev in val.get("reemplaza",[]):
        try:
            cambiar_estado(prev,"REEMPLAZADA","MOTOR_V24",
                           f"Reevaluación del folio {b['folioCP']} → {reg['id']}")
        except Exception as e:
            logger.warning("No se pudo marcar REEMPLAZADA %s: %s",prev,e)
    logger.info("EVALUAR %s → %s user=%s",b["folioCP"],resultado.codigo_motor,_uid(event))
    return _ok({"id":reg["id"],"folioCP":b["folioCP"],"codigoMotor":resultado.codigo_motor,
                "concepto":resultado.concepto_motor,"estado":resultado.estado,
                "pctFlete":round(resultado.pct_flete*100,2),
                "montoBaseUSD":round(resultado.monto_base_usd,2),
                "fleteBaseUSD":round(resultado.flete_base_usd,2),
                "criterios":[asdict(c) for c in resultado.criterios],
                "fechaEvaluacion":reg["fechaEvaluacion"]},201)


# ── POST /upload-url ──────────────────────────────────────────────
def _route_upload_url(event):
    """URL prefirmada de S3 para subir un PDF a pendientes/{fecha}/.
    El objeto subido dispara el Lambda (OCR → evaluar) de forma asíncrona."""
    import boto3, re as _re
    from botocore.config import Config
    from datetime import datetime, timezone
    b=_body(event)
    nombre=str(b.get("filename","")).strip()
    # Solo PDF: es lo único que el pipeline OCR procesa (los fletes son
    # documentos escaneados). Aceptar otros formatos sería una falla silenciosa.
    if not nombre.lower().endswith(".pdf"):
        return _err("Solo se aceptan documentos PDF",400)
    bucket=os.environ.get("S3_BUCKET","")
    if not bucket: return _err("S3_BUCKET no configurado",500)
    fecha=str(b.get("fecha") or "")
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$",fecha):
        fecha=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base=_re.split(r"[\\/]",nombre)[-1]          # descartar componentes de ruta
    seguro=_re.sub(r"[^A-Za-z0-9._-]","_",base)
    seguro=_re.sub(r"\.{2,}",".",seguro).lstrip(".") or "archivo.pdf"  # sin '..' ni punto inicial
    # Extensión en minúsculas: el filtro de sufijo de S3 (.pdf) es sensible a
    # mayúsculas; sin esto un "FACTURA.PDF" se sube pero no dispara el OCR.
    seguro=_re.sub(r"\.([A-Za-z0-9]+)$", lambda m: "."+m.group(1).lower(), seguro)
    key=f"pendientes/{fecha}/{seguro}"
    # Firma SigV4 + endpoint regional + virtual-hosted: evita el 403
    # SignatureDoesNotMatch que produce el cliente S3 por defecto cuando la
    # URL se consume desde el navegador (host/firma inconsistentes).
    region=os.environ.get("AWS_REGION") or "us-east-1"
    s3=boto3.client("s3", region_name=region,
                    endpoint_url=f"https://s3.{region}.amazonaws.com",
                    config=Config(signature_version="s3v4",
                                  s3={"addressing_style":"virtual"}))
    url=s3.generate_presigned_url(
        "put_object", Params={"Bucket":bucket,"Key":key}, ExpiresIn=900)
    logger.info("UPLOAD-URL %s user=%s",key,_uid(event))
    return _ok({"url":url,"key":key,"bucket":bucket,"fecha":fecha})


def _route_documento(event):
    """URL prefirmada de LECTURA para abrir el PDF de un caso desde el monitor.
    El bucket es privado; la URL dura 5 minutos y solo firma objetos del bucket."""
    import boto3
    from botocore.config import Config
    key=str(_qs(event).get("key") or "").strip()
    if not key or ".." in key:
        return _err("'key' requerida",400)
    bucket=os.environ.get("S3_BUCKET","")
    if not bucket: return _err("S3_BUCKET no configurado",500)
    region=os.environ.get("AWS_REGION") or "us-east-1"
    s3=boto3.client("s3", region_name=region,
                    endpoint_url=f"https://s3.{region}.amazonaws.com",
                    config=Config(signature_version="s3v4",
                                  s3={"addressing_style":"virtual"}))
    url=s3.generate_presigned_url("get_object",
        Params={"Bucket":bucket,"Key":key,
                "ResponseContentDisposition":"inline",
                "ResponseContentType":"application/pdf"},
        ExpiresIn=300)
    return _ok({"url":url})


def _build_solicitud_input(b: dict) -> SolicitudInput:
    """Mapea el JSON plano del request al modelo estructurado del motor v2.4."""
    tc_ref = float(b["tipoCambioRef"])
    partidas = [
        Partida(
            sku=str(p.get("sku","")),
            descripcion=str(p.get("descripcion","")),
            cantidad=float(p.get("cantidad",0)),
            precio_unitario_usd=float(p.get("precioUnitarioUSD",0)),
            peso_unitario_kg=float(p.get("pesoKg",0)),
            volumen_unitario_l=float(p.get("volumenL",0)),
        )
        for p in b.get("partidas",[])
    ]
    # Monto de la venta: el Sub-Total declarado de la FV manda (regla GPA: "el
    # monto de la venta sale de la FV"). La suma de partidas es solo el respaldo
    # cuando no viene declarado (p. ej. requests manuales del API).
    monto_decl = 0.0
    try: monto_decl = float(b.get("montoVentaFV") or 0)
    except (TypeError, ValueError): monto_decl = 0.0
    moneda_fv = str(b.get("monedaFV") or "USD").upper()
    if monto_decl > 0:
        subtotal_usd = monto_decl / tc_ref if moneda_fv == "MXN" else monto_decl
    else:
        subtotal_usd = sum(p.importe_usd for p in partidas)
    folios_fv = b.get("foliosFV") or []
    campo_entrega = b.get("campoEntregaFV","ENTREGA_DOMICILIO")
    # Una FV principal con todas las partidas; los folios adicionales se registran vacíos
    facturas = []
    for i, folio in enumerate(folios_fv):
        facturas.append(FacturaVenta(
            folio=str(folio),
            subtotal_sin_iva=subtotal_usd if i==0 else 0.0,
            currency="USD",
            tipo_cambio_doc=tc_ref,
            campo_entrega=campo_entrega,
            partidas=partidas if i==0 else [],
            es_muestra=bool(b.get("esMuestraFV")),
        ))
    # Líneas de cargo de la carta porte: flete base + ferry opcional
    lineas = [LineaCargo(codigo="78101802", descripcion="FLETE",
                          importe=float(b["fleteBaseMXN"]), currency="MXN")]
    ferry = float(b.get("ferryMXN",0))
    if ferry > 0:
        lineas.append(LineaCargo(codigo="78101700", descripcion="FERRY",
                                  importe=ferry, currency="MXN"))
    cp = CartaPorte(
        folio=str(b["folioCP"]),
        transportista_rfc=str(b["fletaRFC"]),
        destinatario_rfc=str(b.get("destinatarioRFC","")),
        codigo_sap=str(b.get("codigoSAP","")),
        tipo_servicio_cp="ENTREGA_DOMICILIO" if campo_entrega=="ENTREGA_DOMICILIO" else "OCURRE",
        destino_ciudad=str(b.get("destinoCiudad","")),
        # Canónico del catálogo ("JALISCO"→"Jalisco", "Estado de México"→"Edo. México")
        # para que DynamoDB/monitor/auditor guarden un solo nombre por estado.
        destino_estado=normalizar_destino(str(b["destinoEstado"])),
        origen_sucursal=str(b["origenSucursal"]),
        tipo_vehiculo=str(b.get("tipoVehiculo","PALLET")),
        numero_pallets=int(b.get("numeroPallets",0)),
        lineas_cargo=lineas,
        currency="MXN",
        tipo_cambio_doc=tc_ref,
        codigo_rastreo=b.get("folioPtxGuia"),
        es_cfdi40=bool(b.get("esCFDI4",False)),
    )
    return SolicitudInput(facturas_venta=facturas, carta_porte=cp,
                           fecha_emision=str(b["fechaEmision"]))

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

def _route_confirmar_rechazo(event):
    # El aprobador ACEPTA el rechazo del motor: la tarjeta pasa a un estado
    # terminal (RECHAZO_ACEPTADO) que el tablero ya no muestra, para que las
    # rechazadas revisadas no se acumulen en el Kanban. Sigue siendo
    # reemplazable: re-subir el PDF corregido la reevalúa (no queda sellada).
    b=_body(event)
    if "id" not in b: return _err("'id' requerido",400)
    uid=_uid(event)
    res=cambiar_estado(b["id"],"RECHAZO_ACEPTADO",uid,
                       b.get("comentario","") or "Rechazo del motor aceptado")
    logger.info("CONFIRMAR-RECHAZO %s por %s",b["id"],uid); return _ok(res)

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
    checks={"lambda":"ok","version":VERSION,
            "ocr":os.environ.get("OCR_BACKEND","textract").lower()}
    try:
        boto3.client("dynamodb").describe_table(TableName=os.environ.get("DYNAMO_TABLE","gpa_fletes_dev"))
        checks["dynamodb"]="ok"
    except Exception as e: checks["dynamodb"]=f"error:{str(e)[:60]}"
    try:
        bucket=os.environ.get("S3_BUCKET","")
        if bucket: boto3.client("s3").head_bucket(Bucket=bucket); checks["s3"]="ok"
        else: checks["s3"]="not-configured"
    except Exception as e: checks["s3"]=f"error:{str(e)[:60]}"
    # "version"/"ocr" son informativos, no checks — excluirlos del veredicto
    all_ok=all(v in("ok","not-configured") for k,v in checks.items() if k not in("version","ocr"))
    checks["timestamp"]=datetime.now(timezone.utc).isoformat()
    checks["status"]="healthy" if all_ok else "degraded"
    return _ok(checks, 200 if all_ok else 503)

# ── S3 / SQS triggers ────────────────────────────────────────────
def _handle_s3(event):
    # OCR del PDF (escaneo) → casos (1 por CP) → evaluar cada uno.
    resultados=[]
    for r in event["Records"]:
        bucket=r["s3"]["bucket"]["name"]; key=r["s3"]["object"]["key"]
        try:
            res=procesar_objeto_s3(bucket,key)
            for caso in res.get("casos",[]):
                if caso.get("status")!="OK":
                    logger.warning("S3 %s caso %s: %s",key,caso.get("folioCP"),caso.get("error"))
                    # Visible en el monitor (EN_REVISION): un documento que el OCR
                    # no pudo armar debe revisarlo un humano, no perderse en logs.
                    _guardar_caso_error(caso,key)
                    resultados.append({"key":key,"folioCP":caso.get("folioCP"),"error":caso.get("error")})
                    continue
                sol=caso_a_solicitud(caso)
                sol["archivoS3"]=key   # referencia al PDF para abrirlo desde el monitor
                resp=_route_evaluar({"requestContext":{},"path":"/evaluar","httpMethod":"POST","body":json.dumps(sol)})
                resultados.append({"key":key,"folioCP":caso["folioCP"],"status":resp["statusCode"],"body":json.loads(resp["body"])})
        except Exception as exc:
            logger.error("S3 %s: %s",key,exc)
            _guardar_caso_error({"error":"OCR_FALLIDO","detalle":str(exc)},key)
            resultados.append({"key":key,"error":str(exc)})
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

def _guardar_caso_error(caso,key):
    """Persiste un caso que el OCR no pudo armar (SIN_TIPO_CAMBIO, SIN_FV_VINCULADA,
    SIN_CARTA_PORTE…) como EN_REVISION para que aparezca en el monitor."""
    try:
        import uuid; from datetime import datetime,timezone,timedelta; from db.escritura import _dynamo_client
        ahora=datetime.now(timezone.utc).isoformat(); sid=str(uuid.uuid4())
        folio=str(caso.get("folioCP") or caso.get("folioArchivo") or key.rsplit("/",1)[-1])
        err=str(caso.get("error","OCR_ERROR"))
        # CP sin factura anexa = motivo de RECHAZO del negocio (R-093). Los demás
        # errores de extracción sí van a revisión humana.
        if err in ("SIN_FV_VINCULADA","SIN_FACTURA_GPA"):
            codigo,estado_reg,concepto="R-093","AUTO_RECHAZADA",R_CONCEPTOS.get("R-093","Sin factura anexa")
        else:
            codigo,estado_reg,concepto=err,"EN_REVISION","Documento requiere revisión (OCR)"
        # DEDUPE: S3/Lambda reintentan el mismo objeto (entrega at-least-once y
        # reintentos en escaneos grandes) → sin este guard, cada reintento creaba
        # otra tarjeta idéntica (visto en prod: TPQ1A-955 ×8 EN_REVISION).
        try:
            desde=(datetime.now(timezone.utc)-timedelta(days=3)).strftime("%Y-%m-%d")
            hasta=datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for it in get_por_rango_fecha(estado_reg,desde,hasta):
                if str(it.get("folioCP"))==folio and str(it.get("codigoMotor"))==codigo:
                    logger.info("Error OCR duplicado %s (%s): ya hay tarjeta activa",folio,codigo)
                    return
        except Exception as e:
            logger.warning("Dedupe de error OCR no disponible: %s",e)
        _dynamo_client().put_item(TableName=os.environ.get("DYNAMO_TABLE","gpa_fletes_dev"),
            Item={"PK":{"S":f"SOL#{sid}"},"SK":{"S":"#META"},"estado":{"S":estado_reg},
                  "codigoMotor":{"S":codigo},
                  "conceptoMotor":{"S":concepto},
                  "tipoOperacion":{"S":"VENTA_CLIENTE"},
                  "folioCP":{"S":folio},"fechaEmision":{"S":ahora[:10]},
                  "fechaEvaluacion":{"S":ahora},
                  "detalle":{"S":str(caso.get("detalle",""))},
                  "archivoS3":{"S":key}})
        # El R-093 lleva item CP# para que al re-subir el PDF YA con su factura,
        # la unicidad lo detecte como rechazo de máquina y lo REEMPLACE sola.
        if codigo=="R-093" and folio:
            _dynamo_client().put_item(TableName=os.environ.get("DYNAMO_TABLE","gpa_fletes_dev"),
                Item={"PK":{"S":f"CP#{folio}"},"SK":{"S":f"SOL#{sid}"},
                      "estado":{"S":estado_reg},"fechaEmision":{"S":ahora[:10]}})
    except Exception as e: logger.warning("No se pudo guardar caso de error OCR: %s",e)

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
