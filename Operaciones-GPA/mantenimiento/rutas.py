# mantenimiento/rutas.py
# Rutas /mantenimiento/* del Plan de Mantenimiento. handler.py las enruta con
# `manejar(route, event, cl, ctx)`; `ctx` trae los ayudantes del handler (resp,
# resp_gz, err, body, modulo_ok, resolver_urls) para no importar handler desde aquí.
#
# Nivel de acceso (se deriva en cada llamada, la pantalla solo lo pinta):
#   administra  correo en `administradores` del módulo, o rol admin de la app
#   consulta    rol analista → ve todo, no captura
#   ejecuta     operador/supervisor → ve su sucursal; ejecuta lo suyo y lo sin asignar
# Reprogramar (mover un plazo) es del administrador; el técnico lo PIDE con motivo.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

from db import modelos as m
from mantenimiento import logica as L
from mantenimiento import datos as D

_MX = timezone(timedelta(hours=-6))
CLAVE = D.CLAVE_MODULO

RUTAS = ("GET /mantenimiento", "GET /mantenimiento/activos", "GET /mantenimiento/asignables",
         "POST /mantenimiento/{rid}/estado", "POST /mantenimiento/{rid}/asignar",
         "POST /mantenimiento/correctivo", "POST /mantenimiento/admin/activo",
         "POST /mantenimiento/admin/tipo", "POST /mantenimiento/admin/titular",
         "POST /mantenimiento/admin/generar", "POST /mantenimiento/admin/publicar")


def hoy_mx():
    return datetime.now(_MX).date()


def _quien(cl) -> str:
    return cl.get("nombre") or cl.get("email") or "desconocido"


def _hist(cl, accion, motivo="") -> dict:
    return {"q": _quien(cl), "e": cl.get("email"), "c": D.ahora_iso(), "a": accion, "m": motivo or ""}


def _rid(event) -> str:
    return unquote(str((event.get("pathParameters") or {}).get("rid") or ""))


def _es_ruta(route) -> bool:
    return route in RUTAS


def manejar(route, event, cl, ctx):
    """Devuelve la respuesta, o None si la ruta no es de este módulo."""
    if not _es_ruta(route):
        return None
    if not ctx["modulo_ok"](cl, CLAVE):
        return ctx["err"]("Tu cuenta no tiene acceso a este módulo", 403)
    admins = D.administradores()
    niv = L.nivel(cl, admins)
    if route == "GET /mantenimiento":
        return _agenda(event, cl, niv, admins, ctx)
    if route == "GET /mantenimiento/activos":
        return ctx["resp_gz"]({"items": _activos_alcance(cl, niv), "tipos": D.tipos(),
                               "sucursales": D.sucursales_plan(), "nivel": niv}, event)
    if route == "GET /mantenimiento/asignables":
        return _asignables(cl, niv, ctx)
    if route == "POST /mantenimiento/{rid}/estado":
        return _estado(event, cl, niv, ctx)
    if route == "POST /mantenimiento/{rid}/asignar":
        return _asignar(event, cl, niv, ctx)
    if route == "POST /mantenimiento/correctivo":
        return _correctivo(event, cl, niv, ctx)
    if route.startswith("POST /mantenimiento/admin/"):
        if niv != "administra":
            return ctx["err"]("Solo el administrador del módulo de mantenimiento", 403)
        b = ctx["body"](event)
        if route.endswith("/activo"):
            return _admin_activo(b, cl, ctx)
        if route.endswith("/tipo"):
            return _admin_tipo(b, ctx)
        if route.endswith("/titular"):
            return _admin_titular(b, cl, ctx)
        if route.endswith("/generar"):
            return _admin_generar(b, cl, ctx)
        if route.endswith("/publicar"):
            return _admin_publicar(b, cl, ctx)
    return ctx["err"](f"Ruta no encontrada: {route}", 404)


# ── Lectura ──────────────────────────────────────────────────────
def _activos_alcance(cl, niv) -> list:
    alc = L.alcance_sucursales(cl, niv)
    return [a for a in D.activos() if L.en_alcance(a.get("sucursal"), alc)]


def _mps_alcance(cl, niv, anio) -> list:
    alc = L.alcance_sucursales(cl, niv)
    if alc is None:
        return D.mps_todos(anio)
    out = []
    for s in alc:
        out.extend(D.mps_sucursal(s, anio))
    return out


def _decorar(mp: dict, act: dict | None, cl, niv, hoy) -> dict:
    """Campos DERIVADOS (no se persisten): estatus efectivo, lista, asignado, permisos."""
    a = L.asignado_efectivo(mp, act)
    yo = str(cl.get("email") or "").lower()
    d = {k: v for k, v in mp.items() if k not in ("textoExcel", "GSI3PK")}
    d.update({"estatusEfectivo": L.estatus_efectivo(mp, hoy), "lista": L.lista_de(mp, hoy),
              "asignado": a, "mia": bool(a and str(a).lower() == yo),
              "puedeEjecutar": L.puede_ejecutar(cl, niv, mp, act),
              "fechaLimite": L.fecha_limite(int(mp["anio"]), int(mp["semana"])).isoformat()})
    return d


def _agenda(event, cl, niv, admins, ctx):
    qs = event.get("queryStringParameters") or {}
    hoy = hoy_mx()
    anio_h, sem_h = L.semana_actual(hoy)
    try:
        anio = int(qs.get("anio") or anio_h)
    except ValueError:
        anio = anio_h
    acts = {a["codigo"]: a for a in _activos_alcance(cl, niv)}
    mps = _mps_alcance(cl, niv, anio)
    if niv != "administra":                      # la propuesta del año siguiente no se ve
        mps = [x for x in mps if x.get("publicado") is not False]
    items = [_decorar(x, acts.get(x.get("codigo")), cl, niv, hoy) for x in mps]
    alc = L.alcance_sucursales(cl, niv)
    if alc is None:
        cors = D.mpcs_todos()
    else:
        cors = []
        for s in alc:
            cors.extend(D.mpcs_sucursal(s))
    out = {"nivel": niv, "hoy": hoy.isoformat(), "anio": anio, "semanaActual": sem_h,
           "anioActual": anio_h, "rangoSemana": [d.isoformat() for d in L.rango_semana(anio_h, sem_h)],
           "items": ctx["resolver_urls"](items), "activos": list(acts.values()), "tipos": D.tipos(),
           "correctivos": ctx["resolver_urls"](cors), "sucursales": D.sucursales_plan(),
           "resumen": L.resumen(mps, hoy), "periodicidades": D.periodicidades()}
    if niv == "administra":
        out["administradores"] = admins
        out["actas"] = D.actas(3)
        out["hayPropuesta"] = any(x.get("publicado") is False for x in D.mps_todos(anio + 1))
    return ctx["resp_gz"](out, event)


def _asignables(cl, niv, ctx):
    """Cuentas que pueden ejecutar: con el módulo (o todos), activas y con rol que
    captura. Solo id (correo, que es la cuenta), nombre y sucursales."""
    if niv == "ejecuta" and cl.get("rol") != "supervisor":
        return ctx["err"]("Solo la jefatura consulta las cuentas asignables", 403)
    from auth_cognito import listar_cuentas
    out = []
    for c in listar_cuentas():
        if c.get("activo") is False or c.get("rol") not in ("operador", "supervisor"):
            continue
        mods = c.get("modulos") or []
        if mods and CLAVE not in mods:
            continue
        out.append({"id": c.get("email"), "nombre": c.get("nombre") or c.get("email"),
                    "sucursales": c.get("sucursales") or []})
    return ctx["resp"]({"items": sorted(out, key=lambda x: str(x["nombre"]).lower())})


# ── Cambio de estatus ────────────────────────────────────────────
def _estado(event, cl, niv, ctx):
    if niv == "consulta":
        return ctx["err"]("Esta cuenta puede ver pero no capturar", 403)
    rid = _rid(event)
    try:
        codigo, anio, sem = L.partes_rid(rid)
    except ValueError as e:
        return ctx["err"](str(e))
    mp = D.get_mp(rid)
    if not mp:
        return ctx["err"]("Vencimiento no encontrado", 404)
    act = D.activo(codigo)
    if not L.puede_ejecutar(cl, niv, mp, act):
        return ctx["err"]("Esta actividad está asignada a otra persona o es de otra sucursal", 403)
    b = ctx["body"](event)
    err = L.validar_cambio(b, niv)
    if err:
        return ctx["err"](err, 422)
    hist = list(mp.get("hist") or [])
    parche = {}
    # El técnico PIDE reprogramar: se anota la solicitud, el plazo no se mueve.
    if b.get("solicitar") == "reprogramar":
        parche["solicitud"] = {"tipo": "reprogramar", "motivo": str(b.get("motivo"))[:500],
                               "semana": b.get("semana"), "por": cl.get("email"), "en": D.ahora_iso()}
        hist.append(_hist(cl, "Solicitó reprogramar", str(b.get("motivo"))))
        parche["hist"] = hist
        D.parchar_mp(rid, parche)
        return ctx["resp"]({"ok": True, "id": rid, "solicitud": parche["solicitud"]})
    est = b["estatus"]
    for k in ("desc", "checks", "incidencias", "faltantes", "fotos", "motivo", "piezas"):
        if k in b:
            parche[k] = b[k]
    if "fotos" in parche:
        parche["fotos"] = [f for f in (parche["fotos"] or []) if isinstance(f, str) and f][:6]
    parche["estatus"] = est
    parche["tecnico"] = _quien(cl)
    parche["tecnicoEmail"] = cl.get("email")
    if est == "proceso" and not mp.get("inicio"):
        parche["inicio"] = D.ahora_iso()
    if est in L.CERRADOS or est == "pendiente":
        parche["fin"] = D.ahora_iso()
    if est == "programada":                       # el administrador reabre
        parche["fin"] = None
    # Quien toma una actividad sin asignar se la queda esa semana (aparece en «mías»).
    if niv == "ejecuta" and not L.asignado_efectivo(mp, act) and est in ("proceso", "completada"):
        parche["asignadoA"] = cl.get("email")
        hist.append(_hist(cl, "Tomó la actividad"))
        parche["GSI3PK"] = f"{m.MP}#{cl.get('email')}"
    hist.append(_hist(cl, L.ESTATUS_LBL.get(est, est), str(b.get("motivo") or "")))
    parche["hist"] = hist
    if est == "reprogramada":
        nueva = int(b["reprogramadaA"])
        parche["reprogramadaA"] = nueva
        parche["solicitud"] = None
        nuevo_rid = L.rid_mp(codigo, anio, nueva)
        creado = False
        if nueva != sem and not D.existe_mp(nuevo_rid):
            D.poner_mp({"codigo": codigo, "anio": anio, "semana": nueva, "sucursal": mp.get("sucursal"),
                        "area": mp.get("area"), "origen": "reprogramada", "reprogramadaDe": sem,
                        "asignadoA": mp.get("asignadoA"), "publicado": mp.get("publicado", True),
                        "hist": [_hist(cl, f"Reprogramada desde la semana {sem}", str(b.get("motivo") or ""))]},
                       act)
            creado = True
        D.parchar_mp(rid, parche)
        return ctx["resp"]({"ok": True, "id": rid, "estatus": est, "nuevo": nuevo_rid if creado else None})
    D.parchar_mp(rid, parche)
    return ctx["resp"]({"ok": True, "id": rid, "estatus": est})


# ── Asignación ───────────────────────────────────────────────────
def _asignar(event, cl, niv, ctx):
    if niv != "administra":
        return ctx["err"]("Solo el administrador del módulo asigna", 403)
    rid = _rid(event)
    try:
        codigo, _, _ = L.partes_rid(rid)
    except ValueError as e:
        return ctx["err"](str(e))
    mp = D.get_mp(rid)
    if not mp:
        return ctx["err"]("Vencimiento no encontrado", 404)
    b = ctx["body"](event)
    cuenta = (str(b.get("cuenta") or "").strip().lower() or None)
    act = D.activo(codigo)
    hist = list(mp.get("hist") or [])
    hist.append(_hist(cl, f"Asignada a {cuenta}" if cuenta else "Se quitó la excepción de asignación"))
    mp["asignadoA"] = cuenta
    D.parchar_mp(rid, {"asignadoA": cuenta, "hist": hist,
                       "GSI3PK": f"{m.MP}#{L.cuenta_gsi3(mp, act)}"})
    return ctx["resp"]({"ok": True, "id": rid, "asignado": L.asignado_efectivo(mp, act)})


# ── Correctivo ───────────────────────────────────────────────────
def _correctivo(event, cl, niv, ctx):
    if niv == "consulta":
        return ctx["err"]("Esta cuenta puede ver pero no capturar", 403)
    b = ctx["body"](event)
    codigo = str(b.get("codigo") or "").strip().upper()
    act = D.activo(codigo) if codigo else None
    if not act:
        return ctx["err"]("Indica el equipo (activo) que falló", 422)
    if not L.en_alcance(act.get("sucursal"), L.alcance_sucursales(cl, niv)):
        return ctx["err"]("Ese equipo es de otra sucursal", 403)
    if not str(b.get("falla") or "").strip():
        return ctx["err"]("Describe qué falló", 422)
    if not str(b.get("desc") or "").strip():
        return ctx["err"]("Describe qué se hizo", 422)
    hoy = hoy_mx()
    anio_h, sem_h = L.semana_actual(hoy)
    try:
        sem = int(b.get("semana") or sem_h)
    except (TypeError, ValueError):
        sem = sem_h
    sem = max(1, min(sem, sem_h))          # nunca en el futuro
    con_prev = bool(b.get("conPreventivo"))
    datos = {"codigo": codigo, "descripcionActivo": act.get("descripcion"), "area": act.get("area"),
             "anio": anio_h, "semana": sem, "falla": str(b.get("falla"))[:1000],
             "desc": str(b.get("desc"))[:2000], "refacciones": str(b.get("refacciones") or "")[:500],
             "resp": "EXTERNO" if str(b.get("resp") or "").upper() == "EXTERNO" else "INTERNO",
             "conPreventivo": con_prev,
             "fotos": [f for f in (b.get("fotos") or []) if isinstance(f, str) and f][:6],
             "tecnico": _quien(cl), "fin": D.ahora_iso(), "semanasRetiradas": [], "semanasNuevas": []}
    # Reinicio del reloj: solo si incluyó el preventivo y el activo tiene periodicidad fija.
    p = int(act.get("semPeriodo") or 0)
    if con_prev and p:
        mps = D.mps_activo(codigo, anio_h)
        r = L.reinicio_reloj([x["semana"] for x in mps], p, sem)
        for x in mps:
            w = int(x["semana"])
            # Solo se retiran las que no tienen captura y cuya fecha no pasó (lo vencido es historia).
            if w in r["quitar"] and (x.get("estatus") or "programada") == "programada" \
                    and L.fecha_limite(anio_h, w) >= hoy:
                D.borrar_mp(x["id"])
                datos["semanasRetiradas"].append(w)
        for w in r["nuevas"]:
            rid = L.rid_mp(codigo, anio_h, w)
            if not D.existe_mp(rid):
                D.poner_mp({"codigo": codigo, "anio": anio_h, "semana": w, "sucursal": act.get("sucursal"),
                            "area": act.get("area"), "origen": "correctivo",
                            "hist": [_hist(cl, f"Creada por reinicio de calendario en la semana {sem}")]}, act)
                datos["semanasNuevas"].append(w)
    mpc = D.crear_mpc(datos, act.get("sucursal"), cl.get("email"))
    if con_prev and p:
        D.guardar_activo({**act, "reprog": {"base": sem, "anio": anio_h, "por": mpc["id"]}})
    return ctx["resp"]({"ok": True, "id": mpc["id"], "semanasRetiradas": datos["semanasRetiradas"],
                        "semanasNuevas": datos["semanasNuevas"]})


# ── Administración del módulo ────────────────────────────────────
def _admin_activo(b, cl, ctx):
    if b.get("eliminar"):                         # baja lógica
        a = D.activo(str(b.get("codigo") or ""))
        if not a:
            return ctx["err"]("Activo no encontrado", 404)
        D.guardar_activo({**a, "activo": False, "bajaPor": cl.get("email"), "bajaEn": D.ahora_iso()})
        return ctx["resp"]({"ok": True, "codigo": a["codigo"], "activo": False})
    tipos = {t["pref"]: t for t in D.tipos()}
    pref = str(b.get("tipo") or L.tipo_de(b.get("codigo") or "")).upper()
    if pref not in tipos:
        return ctx["err"]("Tipo de activo desconocido (créalo primero en Tipos)", 422)
    sucs = D.sucursales_plan()
    suc_cod = str(b.get("sucCodigo") or "").upper()
    sucursal = b.get("sucursal") or sucs.get(suc_cod)
    if not sucursal:
        return ctx["err"]("Indica la sucursal", 422)
    if not suc_cod:
        suc_cod = next((k for k, v in sucs.items() if v == sucursal), "")
    codigo = str(b.get("codigo") or "").strip().upper()
    existente = D.activo(codigo) if codigo else None
    if not codigo:
        codigo = L.codigo_propuesto(pref, suc_cod or "XXX", [a["codigo"] for a in D.activos()])
    per = L.norm_periodicidad(b.get("periodicidad") or (existente or {}).get("periodicidad") or "")
    item = {**(existente or {}), "codigo": codigo, "tipo": pref, "sucursal": sucursal, "sucCodigo": suc_cod,
            "descripcion": str(b.get("descripcion") or (existente or {}).get("descripcion") or tipos[pref].get("nombre"))[:120],
            "modelo": str(b.get("modelo") or (existente or {}).get("modelo") or "")[:80],
            "serie": str(b.get("serie") or (existente or {}).get("serie") or "")[:80],
            "area": str(b.get("area") or (existente or {}).get("area") or "")[:80],
            "periodicidad": per, "semPeriodo": L.semanas_periodo(per, D.periodicidades()),
            "responsabilidad": "EXTERNO" if str(b.get("responsabilidad") or (existente or {}).get("responsabilidad") or "").upper() == "EXTERNO" else "INTERNO",
            "activo": True if b.get("activo") is None else bool(b.get("activo")),
            "origen": (existente or {}).get("origen") or "modulo"}
    if "titular" in b:
        item["titular"] = (str(b.get("titular") or "").lower() or None)
    if item.get("area"):
        D.guardar_area(item["area"])
    D.guardar_activo(item)
    return ctx["resp"]({"ok": True, "activo": item})


def _admin_tipo(b, ctx):
    pref = str(b.get("pref") or "").strip().upper()
    if not (2 <= len(pref) <= 4) or not pref.isalpha():
        return ctx["err"]("El prefijo son 3 letras (p. ej. AIR)", 422)
    lista = lambda k: [str(x)[:120] for x in (b.get(k) or []) if str(x).strip()]
    item = {"pref": pref, "nombre": str(b.get("nombre") or pref)[:80],
            "procedimiento": str(b.get("procedimiento") or "")[:4000],
            "puntos": lista("puntos"), "materiales": lista("materiales"), "herramienta": lista("herramienta"),
            "supervision": str(b.get("supervision") or "")[:2000],
            "esPropuesta": bool(b.get("esPropuesta"))}
    D.guardar_tipo(item)
    return ctx["resp"]({"ok": True, "tipo": item})


def _admin_titular(b, cl, ctx):
    """Titular de un activo o de un área completa de una sucursal. Reindexa los MP del año
    en curso y siguientes que no tengan excepción, para que «lo mío» siga sirviendo."""
    titular = (str(b.get("titular") or "").strip().lower() or None)
    if b.get("codigo"):
        acts = [a for a in [D.activo(str(b["codigo"]).upper())] if a]
    elif b.get("area") and b.get("sucursal"):
        acts = [a for a in D.activos(True) if a.get("area") == b["area"] and a.get("sucursal") == b["sucursal"]]
    else:
        return ctx["err"]("Indica un activo (codigo) o un área con su sucursal", 422)
    if not acts:
        return ctx["err"]("Activo no encontrado", 404)
    anio_h = hoy_mx().year
    n = 0
    for a in acts:
        a["titular"] = titular
        D.guardar_activo(a)
        for x in D.mps_activo(a["codigo"]):
            if int(x.get("anio") or 0) >= anio_h and not x.get("asignadoA"):
                D.reindexar_cuenta(x, a)
                n += 1
    return ctx["resp"]({"ok": True, "activos": [a["codigo"] for a in acts], "titular": titular, "reindexados": n})


def _admin_generar(b, cl, ctx):
    """Arma el año siguiente como PROPUESTA (publicado=False). Sin `aplicar` solo simula."""
    hoy = hoy_mx()
    try:
        anio = int(b.get("anio") or hoy.year + 1)
    except (TypeError, ValueError):
        return ctx["err"]("Año inválido", 422)
    if anio <= hoy.year:
        return ctx["err"]("Solo se genera un año posterior al actual", 422)
    acts = D.activos(True)
    g = L.generar_anio(acts, D.mps_todos(anio - 1), anio, D.periodicidades())
    g["yaExisten"] = len(D.mps_todos(anio))
    if not b.get("aplicar"):
        return ctx["resp"]({"ok": True, "simulacion": True, **g})
    por_cod = {a["codigo"]: a for a in acts}
    creados = 0
    for codigo, w in g["propuestas"]:
        rid = L.rid_mp(codigo, anio, w)
        if D.existe_mp(rid):
            continue
        a = por_cod[codigo]
        D.poner_mp({"codigo": codigo, "anio": anio, "semana": w, "sucursal": a.get("sucursal"),
                    "area": a.get("area"), "origen": "generado", "publicado": False,
                    "hist": [_hist(cl, "Generada como propuesta")]}, a)
        creados += 1
    return ctx["resp"]({"ok": True, "simulacion": False, "creados": creados, **g})


def _admin_publicar(b, cl, ctx):
    try:
        anio = int(b.get("anio") or 0)
    except (TypeError, ValueError):
        anio = 0
    if not anio:
        return ctx["err"]("Indica el año a publicar", 422)
    n = 0
    for x in D.mps_todos(anio):
        if x.get("publicado") is False:
            D.parchar_mp(x["id"], {"publicado": True, "publicadoPor": cl.get("email"), "publicadoEn": D.ahora_iso()})
            n += 1
    return ctx["resp"]({"ok": True, "anio": anio, "publicados": n})
