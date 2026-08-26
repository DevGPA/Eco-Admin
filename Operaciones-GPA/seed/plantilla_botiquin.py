#!/usr/bin/env python3
# seed/plantilla_botiquin.py — Alta del formulario GRL-SH-FO-11 (botiquín) — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Crea (o actualiza) la plantilla del formato «Programa de revisión mensual de
# botiquín de primeros auxilios» (GRL-SH-FO-11 Rev. 1) en el módulo Seguridad.
#
# Es la MISMA plantilla que produce la carga por Excel desde Admin → Formularios;
# este script es la vía alterna cuando esa pantalla falla. Escribe un solo item de
# catálogo (PK=CAT#PLANTILLA), no toca registros ni evidencias.
#
# SEGURO POR DEFECTO: sin --confirm solo simula.
#
# Uso (CloudShell):
#   cd ~/Eco-Admin/Operaciones-GPA
#   python3 seed/plantilla_botiquin.py --stack gpa-operaciones-prod --region us-east-1
#   python3 seed/plantilla_botiquin.py --stack gpa-operaciones-prod --region us-east-1 --confirm
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, os, sys

CLAVE = "botiquin"
NOMBRE = "Revisión mensual de botiquín (GRL-SH-FO-11)"
MODULO = "seguridad"

# Escala del concepto: Completo (ok) · Incompleto (atención) · Faltante (fuera).
# «Faltante» es severidad bad, así que la app exige FOTO de evidencia y nota, y el
# concepto aparece solo en «Puntos en mal estado» del PDF y en el Tablero.
ESCALA = [{"t": "Completo", "sev": "ok"},
          {"t": "Incompleto", "sev": "warn"},
          {"t": "Faltante", "sev": "bad"}]

# Los 11 conceptos del formato, con su cantidad mínima (va en la etiqueta).
CONCEPTOS = [
    ("algodon",    "Paquete de algodón plisado", 1),
    ("alcohol",    "Alcohol etílico", 1),
    ("microdacyn", "Microdacyn", 1),
    ("gasas",      "Gasas 10 x 10", 5),
    ("venda_5",    "Venda elástica 5 cm", 2),
    ("venda_10",   "Venda elástica 10 cm", 2),
    ("curitas",    "Curitas", 10),
    ("micropore",  "Tela adhesiva tipo micropore", 1),
    ("cubrebocas", "Cubrebocas", 5),
    ("guantes",    "Guantes látex", 4),
    ("termometro", "Termómetro", 1),
]

LINEAMIENTOS = [
    "1.- El presente formato deberá llenarse de manera mensual, asegurando su correcto y completo llenado.",
    "2.- El personal designado a la realización de la lista de verificación se compromete a revisar de manera "
    "visual y física las existencias descritas en este formato, una vez que realiza la validación.",
    "3.- El personal responsable del llenado de este formato se compromete a dar seguimiento a las incidencias "
    "o faltantes encontrados durante la revisión, reportándolo de inmediato con servicio médico para levantar "
    "las solicitudes de compra.",
]


def plantilla() -> dict:
    return {
        "clave": CLAVE,
        "modulo": MODULO,
        "nombre": NOMBRE,
        "requiereFirma": True,          # «Firma de quien verifica» del formato
        "requiereAutorizacion": False,  # el formato solo pide firma
        "periodicidad": "mensual",      # revisión mensual (Tablero de Seguimiento)
        "metas": {},                    # vacío = 1 botiquín por sucursal
        "activo": True,
        "secciones": [
            {"id": "datos", "title": "Datos generales", "items": [
                {"id": "area", "label": "Área donde está el botiquín", "type": "text", "req": True},
                {"id": "ubicacion", "label": "Ubicación exacta (referencia)", "type": "text"},
            ]},
            {"id": "existencias", "title": "Existencias del botiquín", "items": [
                {"id": cid, "label": f"{nom} — mínimo {cant}", "type": "escala",
                 "opts": ESCALA, "req": True, "nota": True}
                for cid, nom, cant in CONCEPTOS
            ]},
            {"id": "cierre", "title": "Cierre", "items": [
                {"id": "faltantes_reportados",
                 "label": "¿Se reportaron los faltantes a servicio médico?", "type": "si_no"},
                {"id": "foto_botiquin", "label": "Foto del botiquín", "type": "photo"},
                {"id": "observaciones", "label": "Observaciones", "type": "textarea"},
            ]},
            {"id": "lineamientos", "title": "Lineamientos", "items": [
                {"id": "lineamientos", "label": "Lineamientos generales",
                 "type": "aviso", "opts": LINEAMIENTOS},
            ]},
        ],
    }


def resolver_tabla(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def main():
    ap = argparse.ArgumentParser(description="Alta del formulario de botiquín (GRL-SH-FO-11)")
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

    p = plantilla()
    n = sum(len(s["items"]) for s in p["secciones"])
    modo = "SIMULACIÓN (no escribe nada)" if not args.confirm else "⚠️  EJECUCIÓN REAL"
    print(f"── Alta de plantilla · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}")
    print(f"   Clave: {p['clave']} · Módulo: {p['modulo']} · Periodicidad: {p['periodicidad']}")
    print(f"   Firma: {'sí' if p['requiereFirma'] else 'no'} · "
          f"Autorización: {'sí' if p['requiereAutorizacion'] else 'no'}")
    for s in p["secciones"]:
        print(f"   · {s['title']} ({len(s['items'])})")
        for it in s["items"]:
            print(f"       - {it['id']:22} {it['type']:9} {it['label'][:52]}")
    print(f"\n   Total: {n} campos")

    tabla = session.resource("dynamodb").Table(args.tabla)
    previo = tabla.get_item(Key={"PK": "CAT#PLANTILLA", "SK": f"PLT#{CLAVE}"}).get("Item")
    print("   Ya existe una plantilla con esa clave: " + ("SÍ (se reemplaza)" if previo else "no"))

    if not args.confirm:
        print("\n○ Simulación terminada. Para aplicar: agrega --confirm")
        return
    tabla.put_item(Item={"PK": "CAT#PLANTILLA", "SK": f"PLT#{CLAVE}", **p})
    print("\n✓ Plantilla guardada. Recarga la app: aparece en el módulo Seguridad.")
    print("  Ajusta la periodicidad o las cantidades esperadas en Admin → Formularios / Metas seguim.")


if __name__ == "__main__":
    main()
