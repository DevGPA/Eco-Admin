#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# seed/importar_plan_mtto.py — Importa el plan anual de mantenimiento (Excel) al módulo
# «Plan Mtto» de GPA Operaciones. SEGURO POR DEFECTO: sin --aplicar solo simula.
#
# Lee UNA COPIA del archivo «CALENDARIO MANTENIMIENTO 2025 SCS.xlsx» (hoja CALENDARIO 2026)
# celda por celda —incluidos los COLORES, que es donde vive la programación— y produce:
#   · CAT#TIPOACTIVO   los 23 tipos (solo los que falten; nunca pisa uno editado)
#   · CAT#PERIODICIDAD texto → semanas       · CAT#AREA  las áreas normalizadas
#   · CAT#MODULO/MOD#mantenimiento  el módulo (conserva `administradores`)
#   · CAT#ACTIVO       un activo por equipo, con código nuevo TIPO-SUC-##
#   · MP#…             un vencimiento por celda pintada (estatus «programada»)
#   · MTTO#ACTA        el acta con lo que no pudo resolver solo
#
# Reglas (docs/mantenimiento/INSTRUCCIONES.md §7 y DECISIONES.md):
#   · La SUCURSAL sale de la columna E, nunca del color; el color solo se cruza (acta).
#   · Idempotente: upsert por codigo#anio#semana. NUNCA borra un vencimiento con captura ni
#     un activo dado de alta en el módulo (lo marca enExcel=false).
#   · Traspaletas, carritos y diablos: UNA PIEZA = UN ACTIVO. La cantidad por sucursal se
#     toma del Tablero de Seguimiento de la app (metas de los formularios «transpaletas»,
#     «carritos», «diablitos»), no de la columna «Serie» del Excel.
#   · El texto de las celdas (OK, SERV, MP…) NO se traduce a estatus (decisión #5).
#
# Uso (CloudShell; primero sube el Excel con Actions → Upload file):
#   cd ~/Eco-Admin/Operaciones-GPA
#   pip install openpyxl -q
#   python3 seed/importar_plan_mtto.py --xlsx ~/CALENDARIO\ MANTENIMIENTO\ 2025\ SCS.xlsx \
#           --stack gpa-operaciones-prod --region us-east-1            # simula y muestra el acta
#   python3 seed/importar_plan_mtto.py --xlsx ~/CALENDARIO\ MANTENIMIENTO\ 2025\ SCS.xlsx \
#           --stack gpa-operaciones-prod --region us-east-1 --aplicar  # escribe
# Local sin AWS (solo lectura y cifras):  --xlsx <ruta> --sin-aws
#
# Cifras que deben salir LEYENDO el archivo actual (si cambian, algo se leyó mal y el
# script se detiene): 233 filas de activo · 546 celdas pintadas · 3 sin semana · 57 hallazgos.
# Después de expandir las piezas, activos y vencimientos suben (se reportan aparte).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse
import collections
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from mantenimiento import logica as L            # noqa: E402


def _modulo_vecino(nombre):
    """Carga seed/<nombre>.py por ruta: la carpeta seed/ no es paquete y `import seed`
    resolvería seed/seed.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(nombre, Path(__file__).with_name(nombre + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tipos = _modulo_vecino("mtto_tipos")
TIPOS, PROTOCOLO_SUPERVISION = _tipos.TIPOS, _tipos.PROTOCOLO_SUPERVISION

HOJA = "CALENDARIO 2026"
COL_SEM_INI, COL_SEM_FIN = 9, 61      # I..BI = semanas 1..52 (+1 duplicada)
FILA_SEMANAS = 6
FILA_INI, FILA_FIN = 10, 272
ESPERADO = {"filas": 233, "marcas": 546, "sinSemana": 3, "hallazgos": 57}

# Secciones del Excel que nombran un SITIO, no un área: sus filas van a SERVICIOS GENERALES.
SECCION_SITIO = {"GDL CEDIS": "GDL", "GDL CALZADA": "CZD", "NAVE MEX": "MEX", "NAVE MTY": "MTY",
                 "NAVE CANCUN": "CAN", "NAVE PV": "PVR", "NAVE LOS CABOS": "CBS"}
AREA_LIMPIA = {
    "EQUIPO DE CARGA PESADO ALMACENES": "Equipo de carga pesado",
    "EQUIPO DE CARGA LIGERO ALMACNES": "Equipo de carga ligero",
    "MINI SPLIT GDL": "Mini splits", "MINI SPLIT MTY": "Mini splits", "MINI SPLIT CABOS": "Mini splits",
    "MINI SPLIT VALLARTA": "Mini splits", "MINI SPLIT CANCUN": "Mini splits", "MINI SPLIT MEXICO": "Mini splits",
    "SERVICIOS GENERALES": "Servicios generales", "PINTURA EN GENERAL": "Pintura",
    "MANTENIMIENTO A ESTRUCTUCTURAS": "Estructuras", "CISTERNA O ALGIVE": "Cisternas y tinacos",
    "MOBILIARIO OFICINAS EN GENERAL": "Mobiliario de oficina", "EXTRACTORES": "Extractores",
    "FUMIGACION": "Fumigación", "BASCULAS": "Básculas", "SISTEMA DE OSMOSIS": "Ósmosis",
    "EXTINTORES SUCURSALES": "Extintores", "ALARMA": "Alarma", "JARDINERIA": "Jardinería",
    "PLANTAS DE LUZ": "Plantas de luz"}
PREFIJO_REGLAS = [("MONT", "MON"), ("TRASP", "TRA"), ("CARR", "CAR"), ("DIAB", "DIA"), ("AIR", "AIR"),
                  ("ELC-TAB", "TAB"), ("ELC-INT", "ELE"), ("FONT", "FON"), ("ILUM", "ILU"), ("PINT", "PIN"),
                  ("IMPER", "IMP"), ("LIMPI", "CNL"), ("BAJAN", "BAJ"), ("INMO", "MOB"), ("EXTR", "VEN"),
                  ("FUMI", "FUM"), ("BASC", "BAS"), ("HOSMO", "OSM"), ("EXTIN", "EXT")]
NO_CODIGO = {"TRIMESTRAL", "1 TINACO", "CISTERNA (2)TINACOS"}
TIPO_NOMBRE = {t["pref"]: t["nombre"] for t in TIPOS}
# Formularios del Tablero cuyas metas dan la cantidad de piezas por sucursal.
PIEZAS = {"TRA": "transpaleta", "CAR": "carrito", "DIA": "diablito"}


# ── utilidades de texto ──────────────────────────────────────────
def sinacento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")


def aplana(t):
    return re.sub(r"\s+", " ", sinacento(t).upper().replace(",", " ")).strip()


def sitio(t):
    u = aplana(t)
    if "CEDIS" in u:
        return "GDL"
    if "CALZADA" in u:
        return "CZD"
    if "TISA" in u or u == "TIS":
        return "TIS"
    if "CABOS" in u or u in ("CBS", "CAB"):
        return "CBS"
    if "VALLARTA" in u or u in ("PV", "PVR", "VALL"):
        return "PVR"
    if "CANCUN" in u or u in ("CAN", "CUN"):
        return "CAN"
    if "MONTERREY" in u or u in ("MTY", "MTR"):
        return "MTY"
    if "MEXICO" in u or u == "MEX":
        return "MEX"
    if "GUADALAJARA" in u or u == "GDL":
        return "GDL"
    return None


def prefijo(cod, area):
    c = sinacento(cod).upper()
    for viejo, nuevo in PREFIJO_REGLAS:
        if c.startswith(viejo):
            return nuevo
    if "ALGIV" in c or "CISTER" in c or "TINAC" in c:
        return "CIS"
    a = sinacento(area).upper()
    for k, v in (("ALARMA", "ALA"), ("PLANTAS DE LUZ", "PLZ"), ("JARDIN", "JAR"), ("CISTERNA", "CIS"), ("EXTINTOR", "EXT")):
        if k in a:
            return v
    return None


def tono(celda):
    """Identificador estable del relleno, o None si la celda no está pintada (blanco no cuenta)."""
    f = celda.fill
    if f is None or f.fill_type != "solid":
        return None
    col = f.start_color
    try:
        if col.type == "rgb":
            v = str(col.rgb)
            return None if v in ("00000000", "FFFFFFFF") else v
        if col.type == "theme":
            t = getattr(col, "tint", 0) or 0
            if col.theme == 0 and abs(t) < 0.01:
                return None
            return "theme%s/%+.2f" % (col.theme, t)
        if col.type == "indexed":
            return None if col.indexed in (64, 65) else "idx%s" % col.indexed
    except Exception:
        return None
    return None


# ── 1. leer el Excel ─────────────────────────────────────────────
def leer(xlsx) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx)
    ws = wb[HOJA]
    semana_de_col = {}
    for c in range(COL_SEM_INI, COL_SEM_FIN + 1):
        v = ws.cell(row=FILA_SEMANAS, column=c).value
        if isinstance(v, (int, float)):
            semana_de_col[c] = int(v)
    faltan = [c for c in range(COL_SEM_INI, COL_SEM_FIN + 1) if c not in semana_de_col]
    if faltan:
        raise SystemExit(f"Sin número de semana en las columnas: {faltan}")
    dups = sorted(w for w, n in collections.Counter(semana_de_col.values()).items() if n > 1)
    avisos = []
    if dups:
        avisos.append(f"El encabezado repite la semana {dups}: se toma la primera columna.")
    # Igual que el lector de referencia: las DOS columnas de la semana repetida cuentan
    # como semana 52 (hay celdas pintadas solo en la segunda); al armar los vencimientos
    # cada semana entra una sola vez por activo.

    filas, area = [], ""
    texto_sin_color = 0
    for r in range(FILA_INI, FILA_FIN + 1):
        def val(c):
            v = ws.cell(row=r, column=c).value
            return str(v).strip() if v is not None else ""
        desc, modelo, serie = val(2), val(3), val(4)
        ubic, cod, per, resp = val(5), val(6), val(7), val(8)
        if desc and not any([modelo, serie, ubic, cod, per, resp]):
            area = desc
            continue
        if not (desc or cod or ubic):
            continue
        suc = SECCION_SITIO.get(aplana(area))
        area_norm = "SERVICIOS GENERALES" if suc else area
        if not suc:
            suc = sitio(ubic) or sitio(area) or sitio(cod)
        marcas = []
        for c in range(COL_SEM_INI, COL_SEM_FIN + 1):
            cell = ws.cell(row=r, column=c)
            t = tono(cell)
            if t:
                marcas.append((semana_de_col[c], t, str(cell.value).strip() if cell.value not in (None, "") else ""))
            elif cell.value not in (None, "") and t is None:
                texto_sin_color += 1
        filas.append({"fila": r, "area": area, "area_norm": area_norm, "desc": desc, "modelo": modelo,
                      "serie": serie, "ubic": ubic, "cod": cod, "per": per, "resp": resp, "suc": suc,
                      "marcas": marcas})
    if texto_sin_color:
        avisos.append(f"{texto_sin_color} celdas con texto pero sin color: se registró algo en una semana no "
                      "programada (puede ser trabajo extra o tecleo en la celda equivocada). No se importan.")
    return {"filas": filas, "avisos": avisos}


# ── 2. recodificar (TIPO-SUC-##) ─────────────────────────────────
def recodificar(filas) -> None:
    repetidos = collections.Counter(f["cod"] for f in filas if f["cod"])
    for f in filas:
        f["pre"] = prefijo(f["cod"], f["area_norm"])
        c = f["cod"]
        if not c:
            f["motivo"] = "No tenía código"
        elif c.upper() in NO_CODIGO:
            f["motivo"] = "No era un código: decía " + c
        elif repetidos[c] > 1:
            f["motivo"] = f"Código repetido en {repetidos[c]} filas"
        elif "/" in c:
            f["motivo"] = "Carácter inválido en el código (/)"
        else:
            resto = "-".join(c.split("-")[1:]) or c
            sc = sitio(resto)
            f["motivo"] = (f"El código decía {sc} y el equipo está en {f['suc']}"
                           if sc and f["suc"] and sc != f["suc"] else "Formato normalizado")
    cont = collections.Counter()
    for f in filas:
        if not f["pre"] or not f["suc"]:
            f["nuevo"] = ""
            continue
        k = (f["pre"], f["suc"])
        cont[k] += 1
        f["nuevo"] = "%s-%s-%02d" % (f["pre"], f["suc"], cont[k])
        if not f["desc"]:
            f["desc"] = TIPO_NOMBRE.get(f["pre"], f["pre"])
            f["motivo"] += " + descripción tomada del área"


# ── 3. acta ──────────────────────────────────────────────────────
def acta_de(filas) -> list:
    por_suc = collections.defaultdict(collections.Counter)
    for f in filas:
        for _, t, _ in f["marcas"]:
            por_suc[f["suc"]][t] += 1
    dom = {s: c.most_common(1)[0][0] for s, c in por_suc.items() if c}
    acta = []
    for f in filas:
        if not f["marcas"]:
            acta.append({"codigo": f["nuevo"], "sucursal": f["suc"], "semana": None,
                         "hallazgo": "Sin ninguna semana marcada", "dato": f["per"]})
        for w, t, _ in f["marcas"]:
            if dom.get(f["suc"]) != t:
                otra = [s for s, d in dom.items() if d == t]
                if otra and otra[0] != f["suc"]:
                    acta.append({"codigo": f["nuevo"], "sucursal": f["suc"], "semana": w,
                                 "hallazgo": f"Celda con el tono de {otra[0]}", "dato": t})
    for f in filas:
        p = L.semanas_periodo(f["per"])
        e = L.marcas_esperadas(p)
        if e is None:
            continue
        n = len(f["marcas"])          # celdas pintadas, como el lector de referencia (57 hallazgos)
        if n != e:
            acta.append({"codigo": f["nuevo"], "sucursal": f["suc"], "semana": None,
                         "hallazgo": f"Periodicidad pide {e} marcas, hay {n}", "dato": f["per"]})
    return acta


# ── 4. metas del Tablero (piezas por sucursal) ───────────────────
def metas_de_tabla(tabla) -> dict:
    """{tipo: {sucursal_app: cantidad}} leyendo las plantillas del Tablero de Seguimiento."""
    from boto3.dynamodb.conditions import Key
    out = {}
    resp = tabla.query(KeyConditionExpression=Key("PK").eq("CAT#PLANTILLA"))
    for p in resp.get("Items", []):
        nombre = sinacento(p.get("nombre") or "").lower()
        for pref, palabra in PIEZAS.items():
            if palabra in nombre and p.get("metas"):
                out[pref] = {k: int(v) for k, v in p["metas"].items() if v}
    return out


def metas_respaldo() -> dict:
    """Las metas con que se sembró el Tablero (seed/metas_seguridad.py), por si no hay tabla."""
    HERRAMIENTAS = _modulo_vecino("metas_seguridad").HERRAMIENTAS
    return {"TRA": HERRAMIENTAS["transpaletas"], "CAR": HERRAMIENTAS["carritos"], "DIA": HERRAMIENTAS["diablitos"]}


# ── 5. armar activos y vencimientos ──────────────────────────────
def armar(filas, anio, sucursal_app, metas, acta) -> tuple[list, list]:
    activos, mps = [], []
    cont = collections.Counter()
    for f in filas:
        if not f["nuevo"]:
            acta.append({"codigo": f["cod"], "sucursal": f["suc"], "semana": None,
                         "hallazgo": "REVISAR: no se pudo determinar tipo o sucursal", "dato": f["desc"]})
            continue
        pre, suc = f["pre"], f["suc"]
        per = L.norm_periodicidad(f["per"])
        area = " ".join(f["area_norm"].upper().split())
        area = AREA_LIMPIA.get(area, f["area_norm"].title() if f["area_norm"] else "Sin área")
        base = {"tipo": pre, "sucursal": sucursal_app.get(suc, suc), "sucCodigo": suc, "area": area,
                "descripcion": re.sub(r"\s+", " ", f["desc"])[:120], "modelo": f["modelo"][:80],
                "serie": f["serie"][:80], "periodicidad": per, "semPeriodo": L.semanas_periodo(per),
                "responsabilidad": "EXTERNO" if f["resp"].upper().startswith("EXT") else "INTERNO",
                "codigoAnterior": f["cod"], "motivoCodigo": f["motivo"], "filaExcel": f["fila"],
                "origen": "excel", "enExcel": True, "activo": True}
        n = 1
        if pre in PIEZAS:
            meta = (metas.get(pre) or {}).get(base["sucursal"])
            if meta:
                n = int(meta)
            else:
                n = int(f["serie"]) if f["serie"].isdigit() and int(f["serie"]) > 0 else 1
                acta.append({"codigo": f["nuevo"], "sucursal": suc, "semana": None,
                             "hallazgo": f"Sin meta en el Tablero para {PIEZAS[pre]}s: se usaron {n} pieza(s) del Excel",
                             "dato": base["sucursal"]})
        semanas = sorted({w for w, _, _ in f["marcas"] if 1 <= w <= 52})
        textos = {w: txt for w, _, txt in f["marcas"] if txt}
        for i in range(1, n + 1):
            cont[(pre, suc)] += 1
            codigo = "%s-%s-%02d" % (pre, suc, cont[(pre, suc)])
            a = {**base, "codigo": codigo}
            if n > 1:
                a["pieza"] = i
                a["piezas"] = n
                a["piezaDe"] = f["nuevo"]
                a["serie"] = ""            # la «serie» del Excel era la cantidad, no un número de serie
            activos.append(a)
            for w in semanas:
                mp = {"codigo": codigo, "anio": anio, "semana": w, "sucursal": a["sucursal"], "area": area,
                      "origen": "importado", "estatus": "programada", "publicado": True}
                if textos.get(w):
                    mp["textoExcel"] = textos[w][:40]
                mps.append(mp)
    return activos, mps


# ── 6. escribir ──────────────────────────────────────────────────
def escribir(D, E, activos, mps, acta, avisos, anio, sucursal_app, args) -> dict:
    res = collections.Counter()
    existentes_tipos = {t["pref"] for t in D.tipos()}
    for t in TIPOS:
        if t["pref"] in existentes_tipos and not args.tipos_forzar:
            res["tiposConservados"] += 1
            continue
        D.guardar_tipo(dict(t))
        res["tiposEscritos"] += 1
    for texto, sem in L.PERIODICIDAD_BASE:
        D.guardar_periodicidad(texto, sem)
    for a in {x["area"] for x in activos}:
        D.guardar_area(a)
    mod = D.modulo()
    E.guardar_modulo({**mod, "clave": D.CLAVE_MODULO, "nombre": mod.get("nombre") or "Plan Mtto",
                      "orden": mod.get("orden", 35), "activo": mod.get("activo", True),
                      "administradores": mod.get("administradores") or [], "sucursales": sucursal_app})
    # protocolo de supervisión de proveedor: se guarda en el módulo (texto editable a futuro)
    D._t().update_item(Key={"PK": "CAT#MODULO", "SK": f"MOD#{D.CLAVE_MODULO}"},
                       UpdateExpression="SET protocoloSupervision = :p",
                       ExpressionAttributeValues={":p": PROTOCOLO_SUPERVISION})
    previos = {a["codigo"]: a for a in D.activos()}
    for a in activos:
        prev = previos.get(a["codigo"])
        if prev:
            for k in ("titular", "reprog", "activo", "bajaPor", "bajaEn"):
                if k in prev:
                    a[k] = prev[k]
            res["activosActualizados"] += 1
        else:
            res["activosNuevos"] += 1
        D.guardar_activo(a)
    codigos = {a["codigo"] for a in activos}
    for cod, prev in previos.items():
        if cod not in codigos and prev.get("enExcel") is not False:
            D.guardar_activo({**prev, "enExcel": False})
            res["activosFueraDelExcel"] += 1
    por_cod = {a["codigo"]: a for a in activos}
    for mp in mps:
        rid = L.rid_mp(mp["codigo"], mp["anio"], mp["semana"])
        prev = D.get_mp(rid)
        if not prev:
            D.poner_mp(mp, por_cod.get(mp["codigo"]))
            res["mpNuevos"] += 1
        elif (prev.get("estatus") or "programada") == "programada" and not prev.get("hist"):
            D.parchar_mp(rid, {k: mp[k] for k in ("sucursal", "area") if k in mp})
            res["mpRefrescados"] += 1
        else:
            res["mpConCaptura"] += 1
    D.guardar_acta({"anio": anio, "archivo": os.path.basename(args.xlsx), "hallazgos": acta, "avisos": avisos,
                    "resumen": dict(res), "activos": len(activos), "vencimientos": len(mps)})
    return res


def main():
    ap = argparse.ArgumentParser(description="Importa el plan anual de mantenimiento al módulo Plan Mtto")
    ap.add_argument("--xlsx", required=True, help="COPIA del CALENDARIO MANTENIMIENTO … .xlsx")
    ap.add_argument("--anio", type=int, default=2026)
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"))
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--aplicar", action="store_true", help="ESCRIBIR (sin esto solo simula)")
    ap.add_argument("--sin-aws", action="store_true", help="No tocar AWS ni para leer (metas de respaldo)")
    ap.add_argument("--metas-json", help="Archivo JSON {tipo:{sucursal:cantidad}} en vez de leer la tabla")
    ap.add_argument("--tipos-forzar", action="store_true", help="Sobrescribir los tipos ya editados")
    ap.add_argument("--sin-cifras", action="store_true", help="No detenerse si las cifras de lectura difieren")
    ap.add_argument("--json", help="Guardar activos, vencimientos y acta en este archivo (simulación)")
    args = ap.parse_args()

    print("── Importador del plan de mantenimiento ·", "⚠️  EJECUCIÓN REAL" if args.aplicar else "SIMULACIÓN (no escribe nada)", "──")
    print(f"   Archivo: {args.xlsx}   Año: {args.anio}")
    lectura = leer(args.xlsx)
    filas, avisos = lectura["filas"], lectura["avisos"]
    recodificar(filas)
    marcas = sum(len(f["marcas"]) for f in filas)
    sin_sem = sum(1 for f in filas if not f["marcas"])
    acta = acta_de(filas)
    cifras = {"filas": len(filas), "marcas": marcas, "sinSemana": sin_sem, "hallazgos": len(acta)}
    print("\n1) LECTURA DEL EXCEL (deben salir 233 / 546 / 3 / 57)")
    for k in ("filas", "marcas", "sinSemana", "hallazgos"):
        ok = "✓" if cifras[k] == ESPERADO[k] else "✗ esperado %d" % ESPERADO[k]
        print(f"   {k:<10} {cifras[k]:>5}  {ok}")
    for a in avisos:
        print("   aviso:", a)
    if cifras != ESPERADO and not args.sin_cifras:
        print("\n✗ Las cifras de lectura no coinciden con el archivo conocido. Me detengo (usa --sin-cifras si el archivo cambió a propósito).")
        sys.exit(1)

    # tabla / metas
    tabla = None
    if not args.sin_aws and (args.stack or args.tabla):
        import boto3
        session = boto3.Session(region_name=args.region)
        if args.stack and not args.tabla:
            cf = session.client("cloudformation")
            outs = cf.describe_stacks(StackName=args.stack)["Stacks"][0].get("Outputs", [])
            args.tabla = {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")
        if not args.tabla:
            sys.exit("No se pudo resolver la tabla (--stack o --tabla)")
        os.environ["DYNAMO_TABLE"] = args.tabla
        tabla = session.resource("dynamodb").Table(args.tabla)
        print(f"   Tabla: {args.tabla}   Región: {args.region}")
    if args.metas_json:
        metas = json.load(open(args.metas_json, encoding="utf-8"))
        origen_metas = "archivo " + args.metas_json
    elif tabla is not None:
        metas = metas_de_tabla(tabla)
        origen_metas = "Tablero de Seguimiento (tabla)"
    else:
        metas = metas_respaldo()
        origen_metas = "RESPALDO seed/metas_seguridad.py (no se leyó la tabla)"
    sucursal_app = dict(L.SUCURSAL_APP)
    activos, mps = armar(filas, args.anio, sucursal_app, metas, acta)

    print(f"\n2) PIEZAS (metas de: {origen_metas})")
    for pre, pal in PIEZAS.items():
        m_ = metas.get(pre) or {}
        print(f"   {pre} {pal + 's':<13} " + "  ".join(f"{s}={n}" for s, n in sorted(m_.items())) if m_ else f"   {pre}: sin metas")
    print("\n3) PLAN EXPANDIDO")
    print(f"   activos       {len(activos):>5}   (233 filas → una pieza = un activo)")
    print(f"   vencimientos  {len(mps):>5}   (celdas únicas por activo y semana: {sum(len({w for w, _, _ in f['marcas']}) for f in filas)} en el Excel)")
    print(f"   hallazgos     {len(acta):>5}   (57 del Excel + avisos de piezas)")
    por_suc = collections.Counter(a["sucursal"] for a in activos)
    print("   por sucursal: " + "  ".join(f"{s}={n}" for s, n in sorted(por_suc.items())))
    if tabla is not None:
        from boto3.dynamodb.conditions import Key
        en_app = {s["nombre"] for s in tabla.query(KeyConditionExpression=Key("PK").eq("CAT#SUCURSAL")).get("Items", [])}
        for cod, nom in sucursal_app.items():
            if nom not in en_app and any(a["sucCodigo"] == cod for a in activos):
                msg = f"La sucursal «{nom}» ({cod}) no existe en la app: sus activos solo los verá el administrador hasta que se dé de alta"
                avisos.append(msg)
                print("   aviso:", msg)
    print("\n4) ACTA (primeros 12 de %d)" % len(acta))
    for h in acta[:12]:
        print(f"   {h['codigo'] or '—':<12} {h['sucursal'] or '—':<4} sem {str(h['semana'] or '—'):<3} {h['hallazgo']}  [{h['dato']}]")
    tipos_acta = collections.Counter(re.sub(r"\d+", "N", h["hallazgo"]) for h in acta)
    for k, n in tipos_acta.most_common():
        print(f"   {n:>3}  {k}")

    if args.json:
        json.dump({"activos": activos, "vencimientos": mps, "acta": acta, "avisos": avisos, "cifras": cifras},
                  open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        print("\n   Guardado:", args.json)
    if not args.aplicar:
        print("\nSimulación terminada. Nada se escribió. Repite con --aplicar para importar.")
        return
    if tabla is None:
        sys.exit("Para --aplicar hace falta --stack o --tabla (y credenciales de AWS)")
    from mantenimiento import datos as D
    import db.escritura as E
    D._table = None
    res = escribir(D, E, activos, mps, acta, avisos, args.anio, sucursal_app, args)
    print("\n5) ESCRITO")
    for k, v in sorted(res.items()):
        print(f"   {k:<22} {v:>5}")
    print("\n✓ Importación aplicada. Abre Plan Mtto en la app: la agenda debe mostrar la semana actual.")


if __name__ == "__main__":
    main()
