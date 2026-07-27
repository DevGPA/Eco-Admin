# db/queries.py
# Lecturas de DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from boto3.dynamodb.conditions import Key

from db import modelos as m

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_operaciones_dev")
_table = None


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _items(resp) -> list:
    return [m.from_dynamo(i) for i in resp.get("Items", [])]


# ── Registros, filtrados por rol ─────────────────────────────────
def listar_registros(tipo: str, rol: str, sucursales, account_id: str) -> list:
    """
    Devuelve registros de un tipo según el alcance del usuario:
      admin / analista    → todos                          (GSI1)
      supervisor          → unión de sus sucursales        (GSI2 por cada una)
      operador            → solo lo que él capturó          (GSI3 por cuenta)
    `sucursales` es una lista; vacía para admin/analista = todas.
    Orden descendente por fecha.
    """
    t = _t()
    if rol in ("admin", "analista"):
        resp = t.query(IndexName="tipo-fecha-idx",
                       KeyConditionExpression=Key("GSI1PK").eq(tipo),
                       ScanIndexForward=False)
        return [_limpiar(i) for i in _items(resp)]

    if rol == "operador":
        # El operador solo ve su propio historial de cargas
        resp = t.query(IndexName="cuenta-fecha-idx",
                       KeyConditionExpression=Key("GSI3PK").eq(f"{tipo}#{account_id}"),
                       ScanIndexForward=False)
        return [_limpiar(i) for i in _items(resp)]

    # supervisor SIN sucursal asignada = ve todas (convención "vacío = todas",
    # igual que en la app). Así el supervisor siempre puede ver el historial.
    if rol == "supervisor" and not sucursales:
        resp = t.query(IndexName="tipo-fecha-idx",
                       KeyConditionExpression=Key("GSI1PK").eq(tipo),
                       ScanIndexForward=False)
        return [_limpiar(i) for i in _items(resp)]

    # supervisor: registros de las sucursales asignadas
    out = []
    for suc in (sucursales or []):
        resp = t.query(IndexName="sucursal-fecha-idx",
                       KeyConditionExpression=Key("GSI2PK").eq(f"{tipo}#{suc}"),
                       ScanIndexForward=False)
        out.extend(_items(resp))
    out.sort(key=lambda r: r.get("fecha", ""), reverse=True)
    return [_limpiar(i) for i in out]


def get_registro(tipo: str, rid: str) -> dict | None:
    resp = _t().get_item(Key={"PK": f"{tipo}#{rid}", "SK": "META"})
    item = resp.get("Item")
    return _limpiar(m.from_dynamo(item)) if item else None


def get_vehiculo(vid) -> dict | None:
    resp = _t().get_item(Key={"PK": m.PK_VEHICLE, "SK": m.sk_vehicle(vid)})
    it = resp.get("Item")
    return _limpiar(m.from_dynamo(it)) if it else None


def ultimo_medidor_por_vehiculo(tipos, campo: str = "km") -> dict:
    """Última lectura de `campo` por vehículo, tomando el registro MÁS RECIENTE
    (por fecha) entre los `tipos` dados (str o lista). Autoritativo: NO depende
    del rol ni de quién capturó (a diferencia de listar_registros, que filtra por
    cuenta para el operador). → {vehicleId(str): {"valor": float, "fecha": str}}.
    Uso: km sobre [SOL, CL] (odómetro compartido); horas sobre [MC]."""
    if isinstance(tipos, str):
        tipos = [tipos]
    t = _t()
    out: dict = {}
    for tipo in tipos:
        kwargs = dict(IndexName="tipo-fecha-idx",
                      KeyConditionExpression=Key("GSI1PK").eq(tipo),
                      ScanIndexForward=False,           # desc por fecha
                      ProjectionExpression="vehicleId, #c, fecha, #st",
                      ExpressionAttributeNames={"#c": campo, "#st": "status"})
        while True:
            resp = t.query(**kwargs)
            for it in resp.get("Items", []):
                vid = str(it.get("vehicleId") or "")
                if not vid or it.get(campo) is None:
                    continue
                d = m.from_dynamo(it)
                # Los registros RECHAZADOS o ANULADOS (reasignados) no cuentan para
                # los controles de medidor (km/horas): no son lecturas válidas.
                if str(d.get("status") or "") in ("Rechazada", "Rechazado", "Anulado"):
                    continue
                fecha = str(d.get("fecha") or "")
                prev = out.get(vid)
                if prev is None or fecha > str(prev["fecha"] or ""):
                    out[vid] = {"valor": float(d[campo]), "fecha": fecha}
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return out


def ultima_solicitud_vehiculo(vid) -> dict | None:
    """Última SOLICITUD de combustible (no reporte) de una unidad, sobre el
    historial completo (GSI1 por fecha desc). Autoritativa: no depende del rol.
    Se usa para exigir asignación (solicitud Aprobada) antes del reporte de carga."""
    if vid in (None, ""):
        return None
    t = _t()
    vid = str(vid)
    kwargs = dict(IndexName="tipo-fecha-idx",
                  KeyConditionExpression=Key("GSI1PK").eq(m.SOL),
                  ScanIndexForward=False)
    while True:
        resp = t.query(**kwargs)
        for it in resp.get("Items", []):
            if str(it.get("vehicleId") or "") == vid and it.get("formato") != "reporte":
                d = m.from_dynamo(it)
                # Una solicitud ANULADA (por reasignación) ya no es vigente: se salta.
                if str(d.get("status") or "") == "Anulado":
                    continue
                return _limpiar(d)
        if "LastEvaluatedKey" not in resp:
            return None
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def solicitud_asignable_vehiculo(vid) -> dict | None:
    """Solicitud de combustible ASIGNABLE a un reporte de carga: la más reciente
    de la unidad que esté APROBADA, no sea reporte ni esté Anulada, y que TODAVÍA
    no tenga un reporte que la referencie (`solicitudId`). Fuerza la relación
    1 a 1 solicitud↔reporte. Autoritativa (no depende del rol). Recorre el
    historial completo de SOL para saber qué solicitudes ya fueron reportadas."""
    if vid in (None, ""):
        return None
    t = _t()
    vid = str(vid)
    reportadas: set = set()   # ids de solicitudes ya vinculadas por un reporte
    candidatas: list = []     # solicitudes aprobadas asignables, desc por fecha
    kwargs = dict(IndexName="tipo-fecha-idx",
                  KeyConditionExpression=Key("GSI1PK").eq(m.SOL),
                  ScanIndexForward=False)
    while True:
        resp = t.query(**kwargs)
        for it in resp.get("Items", []):
            if str(it.get("vehicleId") or "") != vid:
                continue
            d = m.from_dynamo(it)
            if d.get("formato") == "reporte":
                sid = d.get("solicitudId")
                if sid:
                    reportadas.add(str(sid))
                continue
            estado = str(d.get("status") or "")
            if estado == "Anulado":
                continue
            if estado == "Aprobada":
                candidatas.append(d)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    # candidatas viene desc por fecha (más reciente primero)
    for d in candidatas:
        if str(d.get("id")) not in reportadas:
            return _limpiar(d)
    return None


def _limpiar(item: dict) -> dict:
    """Quita las claves internas de Dynamo antes de mandar al cliente."""
    for k in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"):
        item.pop(k, None)
    return item


# ── Catálogos ────────────────────────────────────────────────────
def cargar_catalogos() -> dict:
    t = _t()
    veh = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_VEHICLE)))
    usr = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_USER)))
    suc = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_SUCURSAL)))
    mod = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_MODULO)))
    plt = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_PLANTILLA)))
    rsp = _items(t.query(KeyConditionExpression=Key("PK").eq(m.PK_RESPONSABLE)))
    cfg = t.get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG}).get("Item") or {}
    for lst in (veh, usr, suc, mod, plt, rsp):
        for it in lst:
            _limpiar(it)
    cfg = _limpiar(m.from_dynamo(cfg))
    # Último km REAL por unidad (combustible) para que la validación del
    # formulario compare contra el historial completo, no contra lo que ve el
    # operador (que solo tiene sus propias cargas). Ver evaluar_km / _validar_km.
    ult_km = ultimo_medidor_por_vehiculo([m.SOL, m.CL], "km")   # odómetro compartido
    ult_hr = ultimo_medidor_por_vehiculo([m.MC], "horas")       # horómetro montacargas
    for v in veh:
        k = ult_km.get(str(v.get("id")))
        h = ult_hr.get(str(v.get("id")))
        # Campos DERIVADOS (no se persisten): siempre reflejan el cálculo actual.
        v["ultimoKm"] = k["valor"] if k else None
        v["ultimoKmFecha"] = k["fecha"] if k else None
        v["ultimasHoras"] = h["valor"] if h else None
        v["ultimasHorasFecha"] = h["fecha"] if h else None
    return {
        "vehicles":     sorted(veh, key=lambda v: str(v.get("economico", ""))),
        "users":        sorted(usr, key=lambda u: str(u.get("nombre", ""))),
        "sucursales":   sorted([s["nombre"] for s in suc]),
        "modulos":      sorted(mod, key=lambda x: (x.get("orden", 100), str(x.get("nombre", "")))),
        "plantillas":   sorted(plt, key=lambda x: str(x.get("nombre", ""))),
        "responsables": [{"email": r.get("email"), "tipo": r.get("tipo")} for r in rsp if r.get("email")],
        "config":       cfg,
    }


def get_plantilla(clave: str) -> dict | None:
    resp = _t().get_item(Key={"PK": m.PK_PLANTILLA, "SK": m.sk_plantilla(clave)})
    item = resp.get("Item")
    return _limpiar(m.from_dynamo(item)) if item else None
