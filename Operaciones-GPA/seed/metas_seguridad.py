#!/usr/bin/env python3
# seed/metas_seguridad.py — Carga inicial de METAS de seguimiento (Seguridad) — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Carga UNA sola vez, a partir del archivo "seguridad.xlsx", el PERÍODO
# (pestaña Temporalidad) y las METAS por sucursal (pestaña "Herramientas por
# sucursal") de los formularios de Seguridad Industrial ya creados. Después,
# el admin edita las cantidades en la app (Admin → Metas seguim.).
#
# Empata cada plantilla por su NOMBRE (por palabra clave), le fija:
#   · periodicidad (mensual / trimestral)
#   · metas = {sucursal: cantidad}  (solo formularios de equipo; los demás
#     quedan con metas vacío = 1 por sucursal, el comportamiento por defecto).
# Regla de negocio: llenar de más NO cambia la meta ni el período (el tablero
# mide X de N con la N del archivo; los extras cuentan como válidos).
#
# SEGURO POR DEFECTO: sin --confirm solo simula (dry-run) y no escribe nada.
#
# Uso (CloudShell):
#   python3 seed/metas_seguridad.py --stack gpa-operaciones-prod --region us-east-1              # simula
#   python3 seed/metas_seguridad.py --stack gpa-operaciones-prod --region us-east-1 --confirm    # aplica
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, os, sys, unicodedata
from boto3.dynamodb.conditions import Key

PK_PLANTILLA = "CAT#PLANTILLA"
PK_SUCURSAL  = "CAT#SUCURSAL"

# ── Datos del Excel "seguridad.xlsx" (embebidos; normalizados a los nombres
#    de sucursal del sistema). Celda 0 o vacía = no aplica (no se cuenta). ──
# Herramientas por sucursal → cantidad de formularios por tipo de equipo.
HERRAMIENTAS = {
    "eslingas":     {"Cancun": 4, "Cabos": 0, "Ciudad de Mexico": 2, "Monterrey": 1, "Vallarta": 0, "Guadalajara": 3, "Cedis": 0},
    "transpaletas": {"Cancun": 4, "Cabos": 4, "Ciudad de Mexico": 1, "Monterrey": 5, "Vallarta": 3, "Guadalajara": 7, "Cedis": 6},
    "extractores":  {"Cancun": 3, "Cabos": 2, "Ciudad de Mexico": 1, "Monterrey": 4, "Vallarta": 1, "Guadalajara": 2, "Cedis": 0},
    "carritos":     {"Cancun": 3, "Cabos": 2, "Ciudad de Mexico": 3, "Monterrey": 3, "Vallarta": 3, "Guadalajara": 5, "Cedis": 2},
    "diablitos":    {"Cancun": 5, "Cabos": 2, "Ciudad de Mexico": 5, "Monterrey": 5, "Vallarta": 2, "Guadalajara": 8, "Cedis": 1},
    "escaleras":    {"Cancun": 4, "Cabos": 3, "Ciudad de Mexico": 1, "Monterrey": 4, "Vallarta": 2, "Guadalajara": 0, "Cedis": 0},  # Guadalajara venía en blanco → 0 (ajústalo en Admin si aplica)
    "arnes":        {"Cancun": 2, "Cabos": 2, "Ciudad de Mexico": 1, "Monterrey": 1, "Vallarta": 2, "Guadalajara": 2, "Cedis": 2},
    # Extintores: la columna venía vacía en el Excel → sin metas (1 por sucursal).
}

# Reglas: (palabras clave en el NOMBRE de la plantilla, periodicidad, tipo_equipo|None).
# Primer match en orden gana. tipo_equipo None = sin conteo por equipo (1 por sucursal).
REGLAS = [
    (("extintor",),                          "mensual",    None),
    (("estructural",),                       "trimestral", None),
    (("transpaleta",),                       "trimestral", "transpaletas"),
    (("carrito",),                           "trimestral", "carritos"),
    (("diablito",),                          "trimestral", "diablitos"),
    (("extractor",),                         "trimestral", "extractores"),
    (("eslinga",),                           "trimestral", "eslingas"),
    (("arnes", "linea de vida"),             "trimestral", "arnes"),
    (("escalera",),                          "trimestral", "escaleras"),
    (("ventilaci",),                         "trimestral", None),
    (("detector", "humo"),                   "trimestral", None),
    (("lampara", "emergencia"),              "trimestral", None),
    (("electric", "tablero"),                "trimestral", None),
    # "Revisión montacargas de gas-gasolina" (Diario) se OMITE: lo cubre el
    # módulo Montacargas (diario por unidad); los formularios dinámicos no
    # manejan periodicidad diaria.
]


def _norm(s: str) -> str:
    """minúsculas sin acentos, para empatar nombres de forma robusta."""
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode()
    return s.lower().strip()


def regla_para(nombre: str):
    n = _norm(nombre)
    for kws, per, tipo in REGLAS:
        if any(k in n for k in kws):
            return per, tipo
    return None


def resolver_tabla(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def cargar_todos(tabla, pk):
    out, kwargs = [], {"KeyConditionExpression": Key("PK").eq(pk)}
    while True:
        resp = tabla.query(**kwargs)
        out += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return out


def main():
    ap = argparse.ArgumentParser(description="Carga inicial de metas de seguimiento (Seguridad) — GPA Operaciones")
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"),
                    help="Nombre del stack (ej. gpa-operaciones-prod). Resuelve la tabla sola.")
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--confirm", action="store_true", help="EJECUTAR los cambios (sin esto, solo simula).")
    args = ap.parse_args()

    import boto3
    session = boto3.Session(region_name=args.region)
    if args.stack and not args.tabla:
        args.tabla = resolver_tabla(session, args.stack)
    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    dry_run = not args.confirm
    tabla = session.resource("dynamodb").Table(args.tabla)

    sucursales = sorted({str(s.get("nombre")) for s in cargar_todos(tabla, PK_SUCURSAL) if s.get("nombre")})
    plantillas = cargar_todos(tabla, PK_PLANTILLA)

    # Aviso si alguna sucursal del Excel no existe en el catálogo.
    del_excel = set()
    for m in HERRAMIENTAS.values():
        del_excel |= set(m.keys())
    faltan = [s for s in del_excel if s not in sucursales]
    if faltan:
        print("⚠️  Sucursales del Excel que NO están en el catálogo (se ignoran esas cantidades): "
              + ", ".join(sorted(faltan)))

    modo = "SIMULACIÓN (no escribe nada)" if dry_run else "⚠️  EJECUCIÓN REAL"
    print(f"\n── Metas de seguimiento · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}")
    print(f"   Sucursales del sistema: {', '.join(sucursales)}\n")

    aplicados, sin_regla, usadas = 0, [], set()
    for p in sorted(plantillas, key=lambda x: str(x.get("nombre") or x.get("clave"))):
        nombre = str(p.get("nombre") or p.get("clave"))
        r = regla_para(nombre)
        if not r:
            sin_regla.append(nombre)
            continue
        per, tipo = r
        usadas.add(tipo or ("__" + _norm(nombre)))
        # Metas por sucursal (solo formularios de equipo; el resto = vacío = 1/sucursal).
        metas = {}
        if tipo and tipo in HERRAMIENTAS:
            for suc, cant in HERRAMIENTAS[tipo].items():
                if suc in sucursales and isinstance(cant, int) and cant > 0:
                    metas[suc] = cant
        resumen_metas = ("  ·  metas: " + ", ".join(f"{s}:{n}" for s, n in metas.items())) if metas else "  ·  metas: 1 por sucursal (por defecto)"
        print(f"   {'○' if dry_run else '✓'} {nombre[:52]:52}  período: {per}{resumen_metas}")
        if not dry_run:
            tabla.update_item(
                Key={"PK": PK_PLANTILLA, "SK": p["SK"]},
                UpdateExpression="SET periodicidad = :per, metas = :m",
                ExpressionAttributeValues={":per": per, ":m": metas},
            )
            aplicados += 1

    print()
    if sin_regla:
        print("   Formularios SIN regla (no se tocan): " + "; ".join(sin_regla[:30]))
    # Reglas de equipo que no empataron con ninguna plantilla (posible nombre distinto).
    no_emparejadas = [t for t in HERRAMIENTAS if t not in usadas]
    if no_emparejadas:
        print("   ⚠️  Tipos de equipo SIN formulario empatado (revisa el nombre de la plantilla): "
              + ", ".join(no_emparejadas))

    print()
    if dry_run:
        print("○ Simulación terminada. Revisa el mapeo de arriba.")
        print("○ Para aplicar de verdad agrega: --confirm")
    else:
        print(f"✓ {aplicados} formulario(s) actualizados con período y metas.")
        print("  Ajusta las cantidades cuando cambien los equipos en Admin → Metas seguim.")


if __name__ == "__main__":
    main()
