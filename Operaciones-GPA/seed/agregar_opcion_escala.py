#!/usr/bin/env python3
# seed/agregar_opcion_escala.py — Agrega una opción a una pregunta de escala — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Agrega una opción (p. ej. «N/A») a una pregunta de tipo «escala» de una
# plantilla que YA está en uso, sin tener que volver a importar el Excel.
#
# POR QUÉ SE AGREGA AL FINAL (y no se puede cambiar el orden):
#   Cada respuesta se guarda como la POSICIÓN de la opción elegida (0, 1, 2…),
#   no como su texto. Si una opción nueva se metiera antes, todos los registros
#   ya capturados quedarían apuntando a otra respuesta. Por eso este script
#   SOLO agrega al final y nunca reordena ni borra.
#
# Valor por omisión: el caso pedido — «Ruedas en buen estado (si aplica)» de la
# Bitácora de Revisión de Extintores, con la opción N/A en verde.
#
# SEGURO POR DEFECTO: sin --confirm solo simula.
#
# Uso (CloudShell):
#   cd ~/Eco-Admin/Operaciones-GPA
#   python3 seed/agregar_opcion_escala.py --stack gpa-operaciones-prod --region us-east-1
#   python3 seed/agregar_opcion_escala.py --stack gpa-operaciones-prod --region us-east-1 --confirm
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse
import os
import sys

SEV_LBL = {"ok": "verde (no es hallazgo)",
           "warn": "ámbar (requiere atención)",
           "bad": "rojo (fuera de servicio, pide evidencia)"}


def resolver_tabla(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def buscar_item(plantilla, item_id):
    for sec in plantilla.get("secciones") or []:
        for it in sec.get("items") or []:
            if it.get("id") == item_id:
                return sec, it
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Agrega una opción a una pregunta de escala")
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"))
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--plantilla", default="extintores", help="clave de la plantilla")
    ap.add_argument("--item", default="ruedas_en_buen_estado_si_aplica", help="id de la pregunta")
    ap.add_argument("--texto", default="N/A", help="texto de la opción nueva")
    ap.add_argument("--sev", default="ok", choices=["ok", "warn", "bad"],
                    help="ok = verde · warn = ámbar · bad = rojo")
    ap.add_argument("--confirm", action="store_true", help="EJECUTAR (sin esto solo simula)")
    args = ap.parse_args()

    import boto3
    session = boto3.Session(region_name=args.region)
    if args.stack and not args.tabla:
        args.tabla = resolver_tabla(session, args.stack)
    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    modo = "SIMULACIÓN (no escribe nada)" if not args.confirm else "⚠️  EJECUCIÓN REAL"
    print(f"── Agregar opción a una escala · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}")

    tabla = session.resource("dynamodb").Table(args.tabla)
    llave = {"PK": "CAT#PLANTILLA", "SK": f"PLT#{args.plantilla}"}
    plt = tabla.get_item(Key=llave).get("Item")
    if not plt:
        sys.exit(f"No existe la plantilla '{args.plantilla}' en la tabla.")
    print(f"   Plantilla: {args.plantilla} · {plt.get('nombre')}")

    sec, it = buscar_item(plt, args.item)
    if not it:
        print(f"\n✗ No se encontró la pregunta '{args.item}'. Las que hay:")
        for s in plt.get("secciones") or []:
            for x in s.get("items") or []:
                print(f"     {x.get('id'):42} {x.get('type'):9} {str(x.get('label'))[:50]}")
        sys.exit(1)
    if it.get("type") != "escala":
        sys.exit(f"La pregunta '{args.item}' es de tipo '{it.get('type')}', no 'escala'.")

    opts = list(it.get("opts") or [])
    print(f"   Sección : {sec.get('title')}")
    print(f"   Pregunta: {it.get('label')}")
    print("\n   Opciones ACTUALES (la posición es lo que se guarda en cada registro):")
    for i, o in enumerate(opts):
        print(f"     [{i}] {str(o.get('t')):24} {SEV_LBL.get(o.get('sev') or 'ok')}")

    ya = [str(o.get("t") or "").strip().lower() for o in opts]
    if args.texto.strip().lower() in ya:
        print(f"\n○ La opción «{args.texto}» ya existe. No hay nada que hacer.")
        return

    nuevas = opts + [{"t": args.texto, "sev": args.sev}]
    print(f"\n   Opciones DESPUÉS (la nueva va al FINAL, para no mover el histórico):")
    for i, o in enumerate(nuevas):
        marca = "  ← NUEVA" if i == len(nuevas) - 1 else ""
        print(f"     [{i}] {str(o.get('t')):24} {SEV_LBL.get(o.get('sev') or 'ok')}{marca}")
    print("\n   Los registros ya capturados NO cambian de significado: los que")
    print("   respondieron [0] o [1] siguen apuntando a la misma respuesta.")

    if not args.confirm:
        print("\n○ Simulación terminada. Para aplicar: agrega --confirm")
        return

    it["opts"] = nuevas
    tabla.put_item(Item=plt)
    print(f"\n✓ Listo. La opción «{args.texto}» ya aparece en la app.")
    print("  Recarga la app en el celular (o ciérrala y ábrela) para verla.")


if __name__ == "__main__":
    main()
