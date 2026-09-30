# mantenimiento/logica.py
# Reglas PURAS del Plan de Mantenimiento (sin boto3, sin fechas «de hoy» escondidas).
# Todo recibe `hoy` o el año explícito para poderse probar con cualquier fecha.
#
# Fuente: docs/mantenimiento/ESPECIFICACION.md (§2 semanas, §5 asignación y
# niveles, §6 estatus, §8 correctivos, §9 año siguiente) y la agenda de referencia
# agenda-mantenimiento-GPA.html, cuyas funciones se portan aquí una a una.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import re
import unicodedata
from datetime import date, timedelta

# ── Estatus ───────────────────────────────────────────────────────
# Los que se GUARDAN. «vencida» nunca se guarda: se deriva (estatus_efectivo).
ESTATUS = ("programada", "proceso", "completada", "pendiente", "reprogramada", "norealizada")
CERRADOS = ("completada", "reprogramada", "norealizada")      # ya no se ejecutan
CON_MOTIVO = ("pendiente", "reprogramada", "norealizada")     # exigen motivo
ESTATUS_LBL = {"programada": "Programada", "proceso": "En proceso", "completada": "Completada",
               "pendiente": "Pendiente", "reprogramada": "Reprogramada",
               "norealizada": "No realizada", "vencida": "Vencida"}

# ── Nivel de acceso dentro del módulo (se deriva, no se captura) ──
NIVELES = ("administra", "ejecuta", "consulta")

# ── Periodicidad: texto del Excel → semanas. 0 = Variable (no se calcula) ──
PERIODICIDAD_BASE = (("POR MES", 4), ("2 MESES", 8), ("3 MESES", 13), ("4 MESES", 17),
                     ("6 MESES", 26), ("12 MESES", 52), ("ANUAL", 52), ("VARIABLE", 0))

# Sucursal del plan (código de 3 letras) → sucursal de la app. Es DATO: el
# importador lo escribe en el módulo (`sucursales`) y la app lo lee de ahí; esta
# tabla es solo el valor inicial. `Tisa` no existe hoy en CAT#SUCURSAL (acta).
SUCURSAL_APP = {"GDL": "Cedis", "CZD": "Guadalajara", "MEX": "Ciudad de Mexico",
                "MTY": "Monterrey", "CAN": "Cancun", "PVR": "Vallarta",
                "CBS": "Cabos", "TIS": "Tisa"}


def _sin_acento(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                   if unicodedata.category(c) != "Mn")


def norm_periodicidad(texto) -> str:
    """'2 meses' / '3MESES' / '12MESES' / 'VARIABLES' → '2 MESES' / '3 MESES' / '12 MESES' / 'VARIABLE'."""
    t = re.sub(r"\s+", " ", _sin_acento(texto).upper()).strip()
    t = re.sub(r"^(\d+)MESES$", r"\1 MESES", t)
    if t.startswith("VARIABLE"):
        t = "VARIABLE"
    return t


def semanas_periodo(texto, catalogo=None) -> int:
    """Semanas entre vencimientos. `catalogo` = {texto normalizado: semanas} editable;
    si no trae el texto, cae al valor base. Desconocido → 0 (no se calcula)."""
    t = norm_periodicidad(texto)
    if catalogo and t in catalogo:
        return int(catalogo[t] or 0)
    return dict(PERIODICIDAD_BASE).get(t, 0)


def marcas_esperadas(sem_periodo: int) -> int | None:
    """Cuántos vencimientos al año pide una periodicidad (4→13, 8→6, 13→4, 17→3, 26→2, 52→1)."""
    return (52 // sem_periodo) if sem_periodo else None


# ── Semanas del plan (fórmula del Excel) ─────────────────────────
def wk12(d: date) -> int:
    """WEEKDAY(d, 12) de Excel: martes=1 … domingo=6, lunes=7."""
    wd = d.weekday()            # lunes=0 … domingo=6
    return 7 if wd == 0 else wd


def inicio_semana(anio: int, sem: int) -> date:
    """Lunes con que empieza la semana `sem`. La semana 1 arranca en
    1-ene − WEEKDAY(1-ene, 12): para 2026 es el 29-dic-2025."""
    e1 = date(anio, 1, 1)
    return e1 - timedelta(days=wk12(e1)) + timedelta(weeks=sem - 1)


def fecha_limite(anio: int, sem: int) -> date:
    """La semana es un PLAZO: vence el sábado (inicio + 5)."""
    return inicio_semana(anio, sem) + timedelta(days=5)


def semana_de(fecha: date, anio: int | None = None) -> int:
    """Número de semana (1..52) de una fecha dentro del año `anio` (por omisión, el de
    la fecha). Se acota igual que la agenda: antes del plan → 1, después → 52."""
    anio = anio or fecha.year
    n = (fecha - inicio_semana(anio, 1)).days // 7 + 1
    return max(1, min(52, n))


def semana_actual(hoy: date) -> tuple[int, int]:
    """(anio, semana) del plan al día `hoy`."""
    return hoy.year, semana_de(hoy, hoy.year)


def rango_semana(anio: int, sem: int) -> tuple[date, date]:
    ini = inicio_semana(anio, sem)
    return ini, ini + timedelta(days=5)


# ── Identificadores ──────────────────────────────────────────────
def rid_mp(codigo: str, anio: int, sem: int) -> str:
    return f"{codigo}#{int(anio)}#{int(sem)}"


def partes_rid(rid: str) -> tuple[str, int, int]:
    """'TRA-GDL-01#2026#38' → ('TRA-GDL-01', 2026, 38). Lanza ValueError si no cuadra."""
    p = str(rid or "").split("#")
    if len(p) != 3 or not p[1].isdigit() or not p[2].isdigit():
        raise ValueError(f"Identificador de vencimiento inválido: {rid!r}")
    return p[0], int(p[1]), int(p[2])


def tipo_de(codigo: str) -> str:
    return str(codigo or "").split("-")[0]


def codigo_propuesto(pref: str, suc: str, existentes) -> str:
    """Siguiente consecutivo TIPO-SUC-## que no choque con `existentes`."""
    usados = {str(c).upper() for c in (existentes or [])}
    n = 1
    while True:
        c = f"{pref.upper()}-{suc.upper()}-{n:02d}"
        if c not in usados:
            return c
        n += 1


# ── Estatus derivado y listas ────────────────────────────────────
def estatus_efectivo(mp: dict, hoy: date) -> str:
    """Lo guardado manda. Si sigue `programada` y su semana ya venció → `vencida`."""
    est = str(mp.get("estatus") or "programada")
    if est == "programada" and fecha_limite(int(mp["anio"]), int(mp["semana"])) < hoy:
        return "vencida"
    return est


def lista_de(mp: dict, hoy: date) -> str:
    """En qué lista lo ve el técnico: semana · atrasadas · proximas · cerradas."""
    if str(mp.get("estatus") or "") in CERRADOS:
        return "cerradas"
    anio_h, sem_h = semana_actual(hoy)
    a, s = int(mp["anio"]), int(mp["semana"])
    if (a, s) == (anio_h, sem_h):
        return "semana"
    return "atrasadas" if (a, s) < (anio_h, sem_h) else "proximas"


# ── Asignación ───────────────────────────────────────────────────
def asignado_efectivo(mp: dict, activo: dict | None) -> str | None:
    """Manda la excepción de la semana; si no hay, el titular del activo; si no, nadie."""
    return (mp or {}).get("asignadoA") or (activo or {}).get("titular") or None


def cuenta_gsi3(mp: dict, activo: dict | None) -> str:
    """Valor con que se indexa «lo mío» (GSI3PK = MP#{cuenta}). Sin asignar → SIN_ASIGNAR#{sucursal}."""
    a = asignado_efectivo(mp, activo)
    return a if a else f"SIN_ASIGNAR#{mp.get('sucursal') or ''}"


# ── Nivel y alcance ──────────────────────────────────────────────
def nivel(cl: dict, administradores) -> str:
    """administra ← correo en `administradores` del módulo, o rol admin de la app
    consulta    ← rol analista
    ejecuta     ← operador / supervisor (el supervisor NO se vuelve administrador)."""
    email = str(cl.get("email") or "").lower()
    admins = {str(a or "").lower() for a in (administradores or [])}
    if email and email in admins:
        return "administra"
    if cl.get("rol") == "admin":
        return "administra"
    if cl.get("rol") == "analista":
        return "consulta"
    return "ejecuta"


def alcance_sucursales(cl: dict, niv: str) -> list | None:
    """None = todas. El administrador y quien consulta ven todo; quien ejecuta, sus sucursales
    (lista vacía en la cuenta = todas, como en el resto de la app)."""
    if niv in ("administra", "consulta"):
        return None
    sucs = cl.get("sucursales") or []
    return list(sucs) if sucs else None


def en_alcance(sucursal, alcance) -> bool:
    return alcance is None or str(sucursal) in alcance


def puede_ejecutar(cl: dict, niv: str, mp: dict, activo: dict | None) -> bool:
    """Decisión del usuario (#2): el técnico ejecuta lo asignado a él y lo que está
    SIN asignar de su sucursal. El administrador, todo. Quien consulta, nada."""
    if niv == "administra":
        return True
    if niv != "ejecuta":
        return False
    if not en_alcance(mp.get("sucursal"), alcance_sucursales(cl, niv)):
        return False
    a = asignado_efectivo(mp, activo)
    return a is None or str(a).lower() == str(cl.get("email") or "").lower()


def puede_reprogramar(niv: str) -> bool:
    """Reprogramar mueve un plazo: solo el administrador. El técnico lo PIDE."""
    return niv == "administra"


def validar_cambio(body: dict, niv: str) -> str | None:
    """Reglas del POST /{rid}/estado. Devuelve el mensaje de error o None."""
    est = str(body.get("estatus") or "")
    if body.get("solicitar"):
        if body.get("solicitar") != "reprogramar":
            return "Solo se puede solicitar «reprogramar»."
        if not str(body.get("motivo") or "").strip():
            return "Escribe el motivo de la reprogramación."
        return None
    if est not in ESTATUS:
        return "Estatus inválido."
    if est == "reprogramada":
        if not puede_reprogramar(niv):
            return "Reprogramar es del administrador del módulo: pídelo con motivo."
        sem = body.get("reprogramadaA")
        if not isinstance(sem, int) or not (1 <= sem <= 52):
            return "Indica la semana a la que se reprograma (1 a 52)."
    if est == "programada" and niv != "administra":
        return "Solo el administrador reabre una actividad."
    if est in CON_MOTIVO and not str(body.get("motivo") or "").strip():
        return "Escribe el motivo."
    if est == "completada" and not str(body.get("desc") or "").strip():
        return "Describe lo realizado para poder completar."
    return None


# ── Correctivo: reinicio del reloj ───────────────────────────────
def reinicio_reloj(semanas, sem_periodo: int, base: int) -> dict:
    """Un correctivo que INCLUYÓ el preventivo reinicia el calendario del activo
    desde `base` (la semana del correctivo) más su periodicidad.
      quitar    = semanas ≥ base que no coinciden con el calendario nuevo
      nuevas    = base+p, base+2p, … ≤ 52 (lo que se pasa de 52 cae al año siguiente)
      conservar = semanas < base: son historia, no se «des-incumplen»
    Variable (p = 0) no recalcula nada."""
    semanas = sorted({int(w) for w in (semanas or [])})
    if not sem_periodo:
        return {"quitar": [], "nuevas": [], "conservar": semanas}
    nuevas = list(range(int(base) + int(sem_periodo), 53, int(sem_periodo)))
    quitar = [w for w in semanas if w >= base and w not in nuevas]
    conservar = [w for w in semanas if w < base]
    return {"quitar": quitar, "nuevas": [w for w in nuevas if w not in semanas],
            "conservar": conservar}


# ── Año siguiente (motor §9) ─────────────────────────────────────
def semanas_siguiente_anio(semanas_actual, ultima_completada, sem_periodo: int) -> list | None:
    """Semanas del año entrante para UN activo.
      · Variable (p=0) → None (se lista aparte, la jefatura la pone a mano).
      · Con última semana Completada `u`: se avanza u+p, u+2p… hasta pasar la 52; el
        sobrante es la primera del año nuevo y de ahí cada p semanas.
      · Sin ejecución: se conservan las del año en curso. Si tampoco hay → [] (sin programar)."""
    if not sem_periodo:
        return None
    p = int(sem_periodo)
    if ultima_completada:
        w = int(ultima_completada)
        while w <= 52:
            w += p
        primera = w - 52
        return list(range(primera, 53, p))
    return sorted({int(w) for w in (semanas_actual or [])})


def carga_por_semana(pares) -> dict:
    """{semana: cuántos vencimientos} a partir de [(codigo, semana), …]."""
    out = {}
    for _, w in pares:
        out[int(w)] = out.get(int(w), 0) + 1
    return out


def semanas_pico(carga: dict, factor: float = 2.0, minimo: int = 8) -> list:
    """Semanas con carga muy por encima del promedio, con las alternativas ±1/±2
    menos cargadas. No mueve nada: la jefatura decide."""
    if not carga:
        return []
    prom = sum(carga.values()) / 52.0
    out = []
    for w, n in sorted(carga.items()):
        if n >= minimo and n > prom * factor:
            alts = sorted((carga.get(v, 0), v) for v in (w - 2, w - 1, w + 1, w + 2) if 1 <= v <= 52)
            out.append({"semana": w, "carga": n, "promedio": round(prom, 1),
                        "alternativas": [v for _, v in alts[:2]]})
    return out


def generar_anio(activos, mps_actual, anio_nuevo: int, catalogo_periodicidad=None) -> dict:
    """Arma la PROPUESTA del año `anio_nuevo` (§9). No escribe: devuelve qué crearía.
    `activos`: lista de activos (activo=True). `mps_actual`: los MP del año en curso."""
    por_codigo = {}
    for mp in mps_actual or []:
        por_codigo.setdefault(mp["codigo"], []).append(mp)
    propuestas, variables, sin_programar = [], [], []
    for a in activos or []:
        if a.get("activo") is False:
            continue
        p = int(a.get("semPeriodo") or 0)
        mps = por_codigo.get(a["codigo"], [])
        completadas = [int(x["semana"]) for x in mps if x.get("estatus") == "completada"]
        sems = semanas_siguiente_anio([int(x["semana"]) for x in mps],
                                      max(completadas) if completadas else None, p)
        if sems is None:
            variables.append(a["codigo"])
        elif not sems:
            sin_programar.append(a["codigo"])
        else:
            propuestas.extend((a["codigo"], w) for w in sems)
    carga = carga_por_semana(propuestas)
    return {"anio": int(anio_nuevo), "propuestas": propuestas, "variables": variables,
            "sinProgramar": sin_programar, "carga": carga, "picos": semanas_pico(carga),
            "total": len(propuestas)}


# ── Cumplimiento (tablero) ───────────────────────────────────────
def resumen(mps, hoy: date) -> dict:
    """Conteos del tablero: exigibles = vencimientos cuya semana ya llegó."""
    anio_h, sem_h = semana_actual(hoy)
    cnt = {k: 0 for k in list(ESTATUS) + ["vencida"]}
    exig = hechas = 0
    for mp in mps or []:
        e = estatus_efectivo(mp, hoy)
        cnt[e] = cnt.get(e, 0) + 1
        if (int(mp["anio"]), int(mp["semana"])) <= (anio_h, sem_h):
            exig += 1
            if e == "completada":
                hechas += 1
    pct = round(hechas * 100.0 / exig) if exig else 0
    return {"total": len(mps or []), "exigibles": exig, "hechas": hechas, "cumplimiento": pct,
            **cnt}
