#!/usr/bin/env python3
# seed/epp_articulos.py — Catálogo de artículos de EPP y uniforme — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Carga los artículos del vale «Entrega EPP.xlsx» al catálogo que usan las
# entradas (factura) y las salidas (vale de entrega) del módulo EPP.
#
# El inventario se lleva POR ARTÍCULO, no por talla: `conTalla` solo indica si
# el vale debe pedir la talla —queda impresa en el vale— sin partir el saldo.
#
# Después se administran en Admin → EPP (alta, baja y edición), así que este
# script es solo la carga inicial.
#
# SEGURO POR DEFECTO: sin --confirm solo simula.
#
# Uso (CloudShell):
#   cd ~/Eco-Admin/Operaciones-GPA
#   python3 seed/epp_articulos.py --stack gpa-operaciones-prod --region us-east-1
#   python3 seed/epp_articulos.py --stack gpa-operaciones-prod --region us-east-1 --confirm
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse
import os
import sys

# (id, nombre, grupo, pide talla)
ARTICULOS = [
    ("playera",        "Playera",                              "Uniforme", True),
    ("pantalon",       "Pantalón",                             "Uniforme", True),
    ("chaleco_ingreso", "Chaleco de nuevo ingreso",            "Uniforme", True),
    ("uniforme_otros", "Otros (uniforme)",                     "Uniforme", True),

    ("calzado_casquillo", "Calzado con casquillo",             "Equipo de Protección", True),
    ("faja",           "Faja",                                 "Equipo de Protección", True),
    ("mascarilla_completa", "Mascarilla completa",             "Equipo de Protección", True),
    ("mascarilla_media", "Mascarilla 1/2",                     "Equipo de Protección", True),
    ("lentes",         "Lentes de seguridad",                  "Equipo de Protección", False),
    ("guantes",        "Guantes",                              "Equipo de Protección", True),
    ("guantes_pvc",    "Guantes PVC",                          "Equipo de Protección", True),
    ("casco",          "Casco",                                "Equipo de Protección", False),

    ("tarjeta_almacen", "Tarjeta electrónica de acceso al Almacén", "Otros", False),
    ("herramientas",   "Herramientas de trabajo / Otros",      "Otros", False),
]


def resolver_tabla(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def main():
    ap = argparse.ArgumentParser(description="Catálogo inicial de artículos de EPP")
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"))
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--confirm", action="store_true", help="EJECUTAR (sin esto solo simula)")
    args = ap.parse_args()

    import boto3
    session = boto3.Session(region_name=args.region)
    if args.stack and not args.tabla:
        args.tabla = resolver_tabla(session, args.stack)
    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    modo = "SIMULACIÓN (no escribe nada)" if not args.confirm else "⚠️  EJECUCIÓN REAL"
    print(f"── Catálogo de EPP · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}")

    tabla = session.resource("dynamodb").Table(args.tabla)
    grupo_actual = None
    nuevos = existentes = 0
    for i, (aid, nombre, grupo, talla) in enumerate(ARTICULOS, 1):
        if grupo != grupo_actual:
            grupo_actual = grupo
            print(f"\n   {grupo}")
        previo = tabla.get_item(Key={"PK": "CAT#EPPART", "SK": f"ART#{aid}"}).get("Item")
        if previo:
            existentes += 1
        else:
            nuevos += 1
        marca = "ya existe (se respeta)" if previo else "NUEVO"
        print(f"     - {aid:22} {nombre[:38]:40} {'talla' if talla else '     '}  {marca}")
        if args.confirm and not previo:
            tabla.put_item(Item={"PK": "CAT#EPPART", "SK": f"ART#{aid}",
                                 "id": aid, "nombre": nombre, "grupo": grupo,
                                 "conTalla": talla, "orden": i, "activo": True})

    print(f"\n   {len(ARTICULOS)} artículos · {nuevos} por dar de alta · {existentes} ya existen")
    print("   Los que ya existen NO se tocan: si les cambiaste el nombre en Admin, se respeta.")
    if not args.confirm:
        print("\n○ Simulación terminada. Para aplicar: agrega --confirm")
        return
    print("\n✓ Catálogo cargado. Recarga la app: aparece el módulo EPP.")
    print("  Se agregan o editan más artículos en Admin → EPP.")


if __name__ == "__main__":
    main()
