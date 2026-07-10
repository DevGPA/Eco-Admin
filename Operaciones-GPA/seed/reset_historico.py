#!/usr/bin/env python3
# seed/reset_historico.py — Reset del histórico para el go-live — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Deja el histórico de capturas EN CERO conservando catálogos (vehículos,
# sucursales, módulos, formularios/plantillas, responsables de alertas, config)
# y las cuentas de Cognito. Opcionalmente vacía el bucket S3 de evidencias.
#
# Qué borra: SOLO items con SK == "META" (combustible SOL#, reparto CL#,
# montacargas MC# y formularios dinámicos FRM#...). Doble seguro: nunca toca
# PK que empiece con "CAT#" ni el item CONFIG.
#
# Además, al confirmar fija CONFIG.fechaInicio = día del reset (hora de México):
# el Tablero de Seguimiento y las alertas solo exigen lo que corresponde A PARTIR
# de ese día — lo que no se hizo antes queda atrás.
#
# SEGURO POR DEFECTO: sin --confirm solo simula (dry-run) y no borra nada.
#
# Uso (CloudShell):
#   # 1) Ver qué se borraría (no borra nada):
#   python3 seed/reset_historico.py --stack gpa-operaciones-prod --region us-east-1
#   # 2) Ejecutar el reset (borra capturas + vacía fotos S3):
#   python3 seed/reset_historico.py --stack gpa-operaciones-prod --region us-east-1 --confirm --con-evidencias
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, os, sys
from collections import Counter
from datetime import datetime, timezone, timedelta

import boto3

MX_TZ = timezone(timedelta(hours=-6))   # Ciudad de México (UTC-6 fijo)


def es_registro(pk: str, sk: str, solo_tipo: str | None = None) -> bool:
    """True si el item es un registro operativo borrable (nunca catálogo/config)."""
    if sk != "META":
        return False
    if pk.startswith("CAT#") or pk == "CONFIG":   # doble seguro
        return False
    if solo_tipo:
        return pk.startswith(solo_tipo + "#")
    return True


def tipo_de(pk: str) -> str:
    """Prefijo legible para el resumen: SOL/CL/MC o FRM#<clave>."""
    partes = pk.split("#")
    if partes[0] == "FRM" and len(partes) >= 2:
        return f"FRM#{partes[1]}"
    return partes[0]


def resolver_outputs(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    o = {x["OutputKey"]: x["OutputValue"] for x in outs}
    return o.get("TableName"), o.get("EvidenciasBucketName")


def escanear(tabla, solo_tipo):
    """Recorre la tabla (solo PK/SK) y separa registros borrables de catálogos."""
    borrar, conteo, catalogos = [], Counter(), Counter()
    kwargs = {"ProjectionExpression": "PK, SK"}
    while True:
        resp = tabla.scan(**kwargs)
        for it in resp.get("Items", []):
            pk, sk = str(it.get("PK", "")), str(it.get("SK", ""))
            if es_registro(pk, sk, solo_tipo):
                borrar.append({"PK": pk, "SK": sk})
                conteo[tipo_de(pk)] += 1
            elif pk.startswith("CAT#") or pk == "CONFIG":
                catalogos[pk.split("#")[0] if pk != "CONFIG" else "CONFIG"] += 1
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return borrar, conteo, catalogos


def borrar_registros(tabla, claves):
    with tabla.batch_writer() as bw:
        for k in claves:
            bw.delete_item(Key=k)


def vaciar_bucket(s3, bucket, dry_run):
    """Cuenta (y si no es dry-run, borra) todos los objetos del bucket de evidencias."""
    total = 0
    paginador = s3.get_paginator("list_objects_v2")
    for pagina in paginador.paginate(Bucket=bucket):
        objetos = [{"Key": o["Key"]} for o in pagina.get("Contents", [])]
        if not objetos:
            continue
        total += len(objetos)
        if not dry_run:
            # delete_objects acepta máx 1000 por llamada (el paginador ya pagina a 1000)
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objetos, "Quiet": True})
    return total


def fijar_fecha_inicio(tabla, fecha):
    """Merge sobre CONFIG (no borra el resto de la config)."""
    tabla.update_item(
        Key={"PK": "CONFIG", "SK": "CONFIG"},
        UpdateExpression="SET fechaInicio = :f",
        ExpressionAttributeValues={":f": fecha},
    )


def main():
    ap = argparse.ArgumentParser(description="Reset del histórico (go-live) — GPA Operaciones")
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"),
                    help="Nombre del stack (ej. gpa-operaciones-prod). Resuelve tabla y bucket solo.")
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--bucket", default=os.environ.get("EVIDENCIAS_BUCKET"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--dry-run", action="store_true",
                    help="Solo simular (es el comportamiento por defecto).")
    ap.add_argument("--confirm", action="store_true",
                    help="EJECUTAR el borrado (sin esto, solo simula).")
    ap.add_argument("--con-evidencias", action="store_true",
                    help="También vaciar el bucket S3 de evidencias (fotos/firmas).")
    ap.add_argument("--solo-tipo", choices=["SOL", "CL", "MC", "FRM"],
                    help="Borrar solo un tipo de registro (por defecto: todos).")
    ap.add_argument("--fecha-inicio", default=None,
                    help="Fecha de inicio del cumplimiento (YYYY-MM-DD). Por defecto: hoy (hora de México).")
    args = ap.parse_args()

    dry_run = not args.confirm
    session = boto3.Session(region_name=args.region)

    if args.stack:
        tabla_n, bucket_n = resolver_outputs(session, args.stack)
        args.tabla = args.tabla or tabla_n
        args.bucket = args.bucket or bucket_n
    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    fecha_inicio = args.fecha_inicio or datetime.now(MX_TZ).strftime("%Y-%m-%d")
    try:
        datetime.strptime(fecha_inicio, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"--fecha-inicio inválida: '{fecha_inicio}' (formato YYYY-MM-DD)")

    tabla = session.resource("dynamodb").Table(args.tabla)

    modo = "SIMULACIÓN (no se borra nada)" if dry_run else "⚠️  EJECUCIÓN REAL"
    print(f"── Reset del histórico · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}")

    # 1) DynamoDB
    borrar, conteo, catalogos = escanear(tabla, args.solo_tipo)
    print(f"\nRegistros de capturas encontrados: {len(borrar)}")
    for t, n in sorted(conteo.items()):
        print(f"   · {t:24s} {n}")
    print("Catálogos que se CONSERVAN (no se tocan):")
    for t, n in sorted(catalogos.items()):
        print(f"   · {t:24s} {n}")

    if not dry_run and borrar:
        borrar_registros(tabla, borrar)
        print(f"✓ {len(borrar)} registro(s) borrados de DynamoDB")

    # 2) S3 (evidencias)
    if args.con_evidencias:
        if not args.bucket:
            sys.exit("Falta --bucket (o --stack) para vaciar evidencias")
        n_obj = vaciar_bucket(session.client("s3"), args.bucket, dry_run)
        accion = "se borrarían" if dry_run else "borrados"
        print(f"{'○' if dry_run else '✓'} Evidencias S3 ({args.bucket}): {n_obj} objeto(s) {accion}")

    # 3) Fecha de inicio del cumplimiento
    if dry_run:
        print(f"○ Al confirmar se fijará CONFIG.fechaInicio = {fecha_inicio} "
              f"(el tablero y las alertas exigen solo a partir de ese día).")
    else:
        fijar_fecha_inicio(tabla, fecha_inicio)
        print(f"✓ CONFIG.fechaInicio = {fecha_inicio} — el cumplimiento se mide desde hoy; "
              f"lo anterior queda atrás.")

    # 4) Verificación post (solo en ejecución real)
    if not dry_run:
        restantes, _, cat_post = escanear(tabla, None)
        print(f"\nVerificación: registros restantes = {len(restantes)} (esperado 0)")
        print(f"             catálogos intactos   = {sum(cat_post.values())} item(s)")
        if restantes:
            print("⚠️  Quedaron registros sin borrar; vuelve a correr con --confirm.")
        else:
            print("\n✓ Histórico en cero. Catálogos, formularios y cuentas intactos.")
    else:
        print("\n○ Simulación terminada. Para ejecutar de verdad agrega: --confirm "
              "(y --con-evidencias para vaciar las fotos).")


if __name__ == "__main__":
    main()
