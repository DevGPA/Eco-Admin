#!/usr/bin/env python3
# seed/plantilla_recorridos.py — Alta del formulario «Recorridos en instalaciones» — GPA
# ─────────────────────────────────────────────────────────────────
# Crea (o actualiza) la plantilla de la «Lista de verificación de recorridos en
# instalaciones» en el módulo Seguridad, con los 36 puntos del formato en papel
# (Recorridos en instalaciones.xlsx) en su MISMO orden.
#
# Cada punto se responde Cumple / No cumple / N/A:
#   · Cumple    → verde, no es hallazgo.
#   · No cumple → rojo: la app abre el recuadro de foto y descripción, el punto
#                 sale en «Puntos en mal estado» del PDF y en el Tablero.
#   · N/A       → verde. Un recorrido cubre cosas que no existen en toda
#                 instalación (tapanco, montacargas, contratistas…), y forzar
#                 «No cumple» las marcaría como falla inexistente.
# El criterio de revisión de cada punto (la columna «Revisión» del Excel) viaja
# en el campo `ayuda` y se muestra bajo el título, para no inspeccionar de memoria.
#
# SEGURO POR DEFECTO: sin --confirm solo simula.
#
# Uso (CloudShell):
#   cd ~/Eco-Admin/Operaciones-GPA
#   python3 seed/plantilla_recorridos.py --stack gpa-operaciones-prod --region us-east-1
#   python3 seed/plantilla_recorridos.py --stack gpa-operaciones-prod --region us-east-1 --confirm
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, os, sys

CLAVE = "recorridos_instalaciones"
NOMBRE = "Lista de verificación de recorridos en instalaciones"
MODULO = "seguridad"
# El formato en papel no indica frecuencia; se asume MENSUAL. Se cambia en
# Admin → Formularios → Periodicidad sin volver a correr este script.
PERIODICIDAD = "mensual"

ESCALA = [{"t": "Cumple", "sev": "ok"},
          {"t": "No cumple", "sev": "bad"},
          {"t": "N/A", "sev": "ok"}]

# (id, etiqueta, criterio de revisión) — extraídos del Excel, en su orden.
SECCIONES = [
    ("evacuacion", "A. Evacuación, señalización y estructura", [
        ("pasillos_libres", "Pasillos libres",
         "Sin obstrucción en ningún momento del día, con posibilidad de realizar una evacuación en cualquier momento"),
        ("salidas_de_emergencia", "Salidas de emergencia",
         "Sin obstrucción en ningún momento del día, con posibilidad de realizar una evacuación en cualquier momento"),
        ("punto_de_reunion", "Punto de reunión",
         "En espacio libre de riesgos, señalizado y/o pintado, visible para todos"),
        ("senaleticas", "Señaléticas",
         "Que existan, legibles y no estén obstruidas (salidas, rutas de evacuación, prohibido comer, uso de EPP, qué hacer en caso de incendio/sismo)"),
        ("escaleras", "Escaleras",
         "Fijas: se revisa que tengan antiderrapante, barandal y sin escalones dañados\nMóviles: En condiciones de uso, sin daños visibles, etiquetadas, en lugar asignado"),
        ("racks_y_estibas", "Racks y estibas",
         "Racks sin golpes, torceduras o dañados\nEstibas derechas, sin riesgo de caída de material,  a partir de segundo nivel con emplaye"),
        ("tapanco_donde_aplique", "Tapanco (donde aplique)",
         "Condiciones de almacenaje correctos, barandales anticaídas, pisos llanos, pasillos libres, estibas sin riesgo de caída"),
    ]),
    ("emergencia", "B. Emergencia y servicios", [
        ("extintores", "Extintores",
         "Sin obstrucción, señalizados, limpios, con presión óptima de carga, a máximo 1.5 m del piso, no en el suelo."),
        ("banos", "Baños",
         "Limpios, con sanitas, papel de baño, puertas funcionando, iluminación adecuada, jaboneras y porta sanitas bien"),
        ("lamparas_de_emergencia", "Lámparas de emergencia",
         "Conectadas a la energía eléctrica, probado el automático mensualmente, no obstruidas, a no más de 2.5 metros de altura"),
        ("iluminacion_en_general", "Iluminación en general",
         "Lámparas funcionando adecuadamente, que no haya lugares oscuros para trabajar"),
        ("botiquin", "Botiquín",
         "De facil acceso, sin medicamentos, sólo materiales de curación"),
    ]),
    ("equipos_epp", "C. Equipos y equipo de protección", [
        ("montacargas", "Montacargas",
         "Limpio, con check list diario, condiciones generales funcionando (espejo, retrovisor, torreta, luces, asiento, volante, palancas)."),
        ("epp_en_general", "EPP en General",
         "Personal utilizando el EPP de manera correcta para la actividad a realizar (Mínimo botas en almacén)"),
        ("epp_brigadistas", "EPP Brigadistas",
         "EPP de brigadistas resguardado pero al alcance, señalizado (lugar específico para él)"),
        ("epp_visitas", "EPP Visitas",
         "Disponible al ingreso al almacén, punteras, casco, chaleco"),
    ]),
    ("orden", "D. Alertamiento, orden y limpieza", [
        ("alarmas_silbatos_timbre_sirenas", "Alarmas (silbatos, timbre, sirenas)",
         "Se cuenta con sistema de alertamiento automático o manual en caso de emergencia. Señalizado y con ubicación disponible para su activación"),
        ("tableros_de_seguridad", "Tableros de seguridad",
         "Se encuentren actualizados, limpios, con al menos personal de la CSH, Brigadas, Personal para manejo de montacargas, croquis, teléfonos de emergencia"),
        ("derrames_charcos_suciedad", "Derrames, charcos, suciedad",
         "No existan derrames, charcos, arena, suciedad o material que pueda causar un resbalón"),
        ("condiciones_inseguras", "Condiciones inseguras",
         "Revisión de condiciones inseguras en el centro de trabajo (pisos, puertas, lámparas, tarjas, cables, plafones, etc)"),
        ("actos_inseguros", "Actos inseguros",
         "Revisión de actos inseguros de los trabajadores (correr, subirse a segundos niveles, no usar EPP o usarlo inadecuadamente, etc)"),
        ("equipos_de_carga", "Equipos de carga",
         "Transpaletas, carritos, diablitos, extractores de tarimas"),
    ]),
    ("riesgos", "E. Riesgos, ergonomía y residuos", [
        ("arnes_y_linea_de_vida", "Arnés y línea de vida",
         "Arnés y línea de vida en funcionamiento, sin daños, ubicados en su lugar, señalizado, sin nudos"),
        ("separacion_de_residuos", "Separación de residuos",
         "Separación de cartón, plástico y madera en almacén. Así como Orgánico e Inorgánico en cocinetas"),
        ("cargas_manuales", "Cargas manuales",
         "Verificar que por ningún motivo excedan los 25 kg de carga manual.  Posturas forzadas o sobreesfuerzos"),
        ("ley_silla", "Ley silla",
         "Verificar que se cuente con las sillas, el espacio señalado, el rol de descanso y se estén haciendo los descansos"),
        ("areas_delimitadas", "Áreas delimitadas",
         "Delimitación de áreas con líneas de al menos 5 cm de ancho en amarillo"),
    ]),
    ("instalaciones", "F. Instalaciones de riesgo y terceros", [
        ("electrico", "Eléctrico",
         "Tableros libres, señalizados con riesgo eléctrico, con voltaje máximo. Contactos sin daños, no extensiones o cables de uso rudo para instalaciones fijas"),
        ("quimicos", "Químicos",
         "HDS disponibles para consulta. Todos los contenedores de químicos señalizados, Kits antiderrames disponibles"),
        ("diesel_y_aserrin", "Diesel y aserrín",
         "Verificar que el almacenamiento sea en lugar ventilado y señalizado, contenedor señalizado"),
        ("contratistas", "Contratistas",
         "Validar que el personal contratista esté siguiendo las indicaciones del GPA, áreas señalizadas a trabajar"),
        ("tanques_de_gas_para_montacargas", "Tanques de Gas para montacargas",
         "Señalizado, con guantes de carnaza, instrucrivo de cambio de tanque de gas."),
        ("cargadores_de_montacargas", "Cargadores de montacargas",
         "Señalizados, cables acomodados, instructivo de carga de montacargas"),
        ("areas_de_fumar", "Áreas de fumar",
         ""),
        ("personal_de_aseo", "Personal de aseo",
         "Sin meterse al almacén, utilizando químicos señalizados."),
        ("guardias_de_seguridad", "Guardias de seguridad",
         "En áreas peatonales, sin generar actos inseguros"),
    ]),
]


def plantilla() -> dict:
    # El motor ya pide sucursal y responsable en su primer paso, así que el
    # domicilio va al principio de la primera sección: una sección aparte solo
    # para ese dato agregaría un paso entero al recorrido.
    secs = []
    for sid, titulo, puntos in SECCIONES:
        items = [{"id": pid, "label": lab, "ayuda": ayuda, "type": "escala",
                  "opts": ESCALA, "req": True, "nota": True}
                 for pid, lab, ayuda in puntos]
        if not secs:
            items.insert(0, {"id": "domicilio",
                             "label": "Domicilio o instalación recorrida",
                             "type": "text"})
        secs.append({"id": sid, "title": titulo, "items": items})
    return {
        "clave": CLAVE,
        "modulo": MODULO,
        "nombre": NOMBRE,
        "requiereFirma": True,          # «Realizó, nombre y firma» del formato
        "requiereAutorizacion": False,
        "periodicidad": PERIODICIDAD,
        "metas": {},                    # vacío = 1 recorrido por sucursal
        "activo": True,
        "secciones": secs,
    }


def resolver_tabla(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def main():
    ap = argparse.ArgumentParser(description="Alta del formulario de recorridos en instalaciones")
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
    print(f"   Firma: sí · Autorización: no")
    for s in p["secciones"]:
        print(f"\n   · {s['title']} ({len(s['items'])})")
        for it in s["items"]:
            print(f"       - {it['id'][:38]:40} {it['type']:7} {it['label'][:44]}")
    print(f"\n   Total: {n} campos ({n - 1} puntos de revisión + 1 dato general)")

    tabla = session.resource("dynamodb").Table(args.tabla)
    previo = tabla.get_item(Key={"PK": "CAT#PLANTILLA", "SK": f"PLT#{CLAVE}"}).get("Item")
    print("\n   Ya existe una plantilla con esa clave: " + ("SÍ (se reemplaza)" if previo else "no"))
    if previo:
        print("   OJO: reemplazarla NO borra los recorridos ya capturados, pero si")
        print("   cambiaron el orden de las opciones, los registros viejos se leerían mal.")

    if not args.confirm:
        print("\n○ Simulación terminada. Para aplicar: agrega --confirm")
        return
    tabla.put_item(Item={"PK": "CAT#PLANTILLA", "SK": f"PLT#{CLAVE}", **p})
    print("\n✓ Plantilla guardada. Recarga la app: aparece en el módulo Seguridad.")
    print("  La periodicidad y las cantidades esperadas se ajustan en")
    print("  Admin → Formularios y Admin → Metas seguim.")


if __name__ == "__main__":
    main()
