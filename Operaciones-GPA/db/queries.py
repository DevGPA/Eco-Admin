# db/queries.py
# Lecturas de DynamoDB — GPA Operaciones
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3
from datetime import date, timedelta
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


def _query_todo(t, **kwargs) -> list:
    """Query que recorre TODAS las páginas (LastEvaluatedKey).

    DynamoDB devuelve como mucho ~1 MB por llamada. Leer una sola página, como
    hacía el listado, truncaba EN SILENCIO cualquier consulta histórica larga
    («todo el historial», rangos de meses): el usuario veía una lista corta sin
    ningún aviso. Todos los listados pasan por aquí."""
    out = []
    while True:
        resp = t.query(**kwargs)
        out.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return out
        kwargs["ExclusiveStartKey"] = lek


# ── Registros, filtrados por rol ─────────────────────────────────
def listar_registros(tipo: str, rol: str, sucursales, account_id: str,
                     desde=None, hasta_excl=None) -> list:
    """
    Devuelve registros de un tipo según el alcance del usuario:
      admin / analista    → todos                          (GSI1)
      supervisor          → unión de sus sucursales        (GSI2 por cada una)
      operador            → solo lo que él capturó          (GSI3 por cuenta)
    `sucursales` es una lista; vacía para admin/analista = todas.
    Orden descendente por fecha.

    Ventana de fechas OPCIONAL (`desde`/`hasta_excl` en YYYY-MM-DD): filtra por la
    sort key del GSI (`fecha`), así que es KeyCondition (eficiente, no filtra en
    memoria). `hasta_excl` = día SIGUIENTE a "hasta"; como las fechas guardadas
    traen `T...`, el between/lt nunca incluye ese día. Sin rango = todo el historial.
    """
    t = _t()

    def _cf(cond, sk):        # combina la condición de partición con el rango de fecha
        if desde and hasta_excl:
            return cond & Key(sk).between(desde, hasta_excl)
        if desde:
            return cond & Key(sk).gte(desde)
        if hasta_excl:
            return cond & Key(sk).lt(hasta_excl)
        return cond

    # admin / analista, y supervisor SIN sucursal asignada (convención "vacío =
    # todas") → GSI1 (todos por tipo).
    if rol in ("admin", "analista") or (rol == "supervisor" and not sucursales):
        its = _query_todo(t, IndexName="tipo-fecha-idx",
                          KeyConditionExpression=_cf(Key("GSI1PK").eq(tipo), "GSI1SK"),
                          ScanIndexForward=False)
        return [_limpiar(m.from_dynamo(i)) for i in its]

    if rol == "operador":
        # El operador solo ve su propio historial de cargas
        its = _query_todo(t, IndexName="cuenta-fecha-idx",
                          KeyConditionExpression=_cf(Key("GSI3PK").eq(f"{tipo}#{account_id}"), "GSI3SK"),
                          ScanIndexForward=False)
        return [_limpiar(m.from_dynamo(i)) for i in its]

    # supervisor: registros de las sucursales asignadas
    out = []
    for suc in (sucursales or []):
        out.extend(_query_todo(t, IndexName="sucursal-fecha-idx",
                               KeyConditionExpression=_cf(Key("GSI2PK").eq(f"{tipo}#{suc}"), "GSI2SK"),
                               ScanIndexForward=False))
    out = [m.from_dynamo(i) for i in out]
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
                # Los registros RECHAZADOS, ANULADOS (reasignados) o devueltos POR
                # CORREGIR no cuentan para los controles de medidor (km/horas): no son
                # lecturas válidas. Ojo con «Por corregir»: si se devolvió justamente
                # porque el medidor estaba mal, ese valor no puede ser el «último».
                if str(d.get("status") or "") in ("Rechazada", "Rechazado", "Anulado", "Por corregir"):
                    continue
                # Lecturas en 0 tampoco: eran capturas SIN medidor (el campo era
                # opcional y se guardaba 0) y bloqueaban las lecturas reales
                # (p. ej. último 0 h vs 960.8 h reales del horómetro).
                try:
                    if float(d[campo]) <= 0:
                        continue
                except (TypeError, ValueError):
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
def articulos_epp() -> list:
    """Catálogo de artículos de EPP y uniforme (ordenado por grupo y nombre)."""
    items = [_limpiar(m.from_dynamo(x))
             for x in _items(_t().query(KeyConditionExpression=Key("PK").eq(m.PK_EPP_ART)))]
    return sorted(items, key=lambda a: (int(a.get("orden") or 100), str(a.get("nombre") or "")))


def saldos_epp() -> dict:
    """Existencia de EPP por sucursal y artículo, sobre el historial COMPLETO.

    NO se ventana por fecha: un saldo es acumulado desde el primer movimiento;
    recortarlo a los últimos 45 días daría una existencia falsa.
    """
    t = _t()
    kwargs = dict(IndexName="tipo-fecha-idx",
                  KeyConditionExpression=Key("GSI1PK").eq(m.EPP))
    movs = []
    while True:
        resp = t.query(**kwargs)
        movs.extend(m.from_dynamo(x) for x in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return m.saldo_epp(movs)


def responsables_alerta() -> list:
    """Cuentas marcadas como responsables de alertas: [{email, tipo}] con tipo
    «sucursal» o «corporativo». Son quienes concluyen los pre-registros de EPP."""
    items = _items(_t().query(KeyConditionExpression=Key("PK").eq(m.PK_RESPONSABLE)))
    return [{"email": str(r.get("email") or ""), "tipo": str(r.get("tipo") or "")} for r in items if r.get("email")]


def epp_prerregistros() -> list:
    """Salidas de EPP en PRE-REGISTRO, sobre el historial completo (no se ventana:
    un pre-registro olvidado hace 2 meses sigue pendiente y debe verse)."""
    its = _query_todo(_t(), IndexName="tipo-fecha-idx",
                      KeyConditionExpression=Key("GSI1PK").eq(m.EPP), ScanIndexForward=False)
    out = []
    for it in its:
        d = m.from_dynamo(it)
        if str(d.get("movimiento") or "") == m.EPP_SALIDA and str(d.get("status") or "") == m.EPP_PRERREGISTRO:
            out.append(_limpiar(d))
    return out


def cargar_config() -> dict:
    """Solo el item de configuración (fechaInicio, correos, etc.). Existe para no
    tener que cargar TODOS los catálogos cuando únicamente hace falta esto."""
    cfg = _t().get_item(Key={"PK": m.PK_CONFIG, "SK": m.SK_CONFIG}).get("Item") or {}
    return _limpiar(m.from_dynamo(cfg))


def _checklists_cl_en_rango(desde: str, hasta_excl: str) -> list:
    """Checklists de reparto (CL) cuya fecha cae en [desde, hasta_excl).
    Va por KeyCondition sobre la sort key del GSI1 (fecha): trae solo las ~5
    semanas que hacen falta, no todo el historial."""
    t = _t()
    kwargs = dict(IndexName="tipo-fecha-idx",
                  KeyConditionExpression=Key("GSI1PK").eq(m.CL) & Key("GSI1SK").between(desde, hasta_excl))
    out = []
    while True:
        resp = t.query(**kwargs)
        out.extend(_items(resp))
        if "LastEvaluatedKey" not in resp:
            return out
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def estados_checklist_reparto(vehiculos: list, config: dict | None = None,
                              hoy=None) -> dict:
    """Cumplimiento del checklist de reparto POR UNIDAD, con la misma regla del
    Tablero de Seguimiento (semanal con límite lunes, mensual con límite día 5
    hábil). Devuelve, solo para las unidades de categoría «reparto» y activas:

        {vehicleId: {"semanal": estado, "mensual": estado,
                     "limiteSemanal": "YYYY-MM-DD", "limiteMensual": "YYYY-MM-DD"}}

    estado ∈ cumplido · pendiente · vencido · na
    Es la base del candado que impide solicitar combustible con el checklist
    vencido, y también lo que la app muestra antes de dejar capturar."""
    hoy = hoy or m.hoy_mx()
    hoy_str = hoy.isoformat()
    inicio = (config or {}).get("fechaInicio") or None

    ini_w, fin_w, lim_w = m.periodo_checklist("semanal", hoy)
    ini_m, fin_m, lim_m = m.periodo_checklist("mensual", hoy)
    # La semana en curso puede cruzar de mes: se consulta la unión de ambos rangos.
    desde = min(ini_w, ini_m)
    hasta = max(fin_w, fin_m)
    hasta_excl = (date.fromisoformat(hasta) + timedelta(days=1)).isoformat()

    hechos = {}          # {vid: {"semanal": True, "mensual": True}}
    for it in _checklists_cl_en_rango(desde, hasta_excl):
        d = m.from_dynamo(it)
        # Un checklist anulado o rechazado no cumple.
        if str(d.get("status") or "") in ("Anulado", "Rechazado", "Rechazada"):
            continue
        vid = str(d.get("vehicleId") or "")
        tipo = str(d.get("tipo") or "")
        fecha = str(d.get("fecha") or "")[:10]
        if not vid or tipo not in ("semanal", "mensual") or not fecha:
            continue
        ini, fin = (ini_w, fin_w) if tipo == "semanal" else (ini_m, fin_m)
        if ini <= fecha <= fin:
            hechos.setdefault(vid, {})[tipo] = True

    out = {}
    for v in vehiculos or []:
        if m.categoria_vehiculo(v) != "reparto":
            continue
        if str(v.get("activo", True)).lower() in ("false", "0", "no", "inactivo"):
            continue
        vid = str(v.get("id"))
        h = hechos.get(vid, {})
        out[vid] = {
            "semanal": m.estado_cumplimiento(bool(h.get("semanal")), lim_w, fin_w, hoy_str, inicio),
            "mensual": m.estado_cumplimiento(bool(h.get("mensual")), lim_m, fin_m, hoy_str, inicio),
            "limiteSemanal": lim_w,
            "limiteMensual": lim_m,
        }
    return out


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
    # Cumplimiento del checklist de reparto: la app lo necesita para avisar ANTES
    # de que el operador llene una solicitud de combustible que el servidor va a
    # rechazar. También es un derivado: no se persiste.
    try:
        chk = estados_checklist_reparto(veh, cfg)
    except Exception:          # nunca tumbar los catálogos por este extra
        chk = {}
    for v in veh:
        v["checklist"] = chk.get(str(v.get("id")))
    return {
        "vehicles":     sorted(veh, key=lambda v: str(v.get("economico", ""))),
        "users":        sorted(usr, key=lambda u: str(u.get("nombre", ""))),
        "sucursales":   sorted([s["nombre"] for s in suc]),
        "modulos":      sorted(mod, key=lambda x: (x.get("orden", 100), str(x.get("nombre", "")))),
        "plantillas":   sorted(plt, key=lambda x: str(x.get("nombre", ""))),
        "responsables": [{"email": r.get("email"), "tipo": r.get("tipo")} for r in rsp if r.get("email")],
        "eppArticulos": articulos_epp(),
        "config":       cfg,
    }


def get_plantilla(clave: str) -> dict | None:
    resp = _t().get_item(Key={"PK": m.PK_PLANTILLA, "SK": m.sk_plantilla(clave)})
    item = resp.get("Item")
    return _limpiar(m.from_dynamo(item)) if item else None
