#!/usr/bin/env python3
# seed/seed.py — Carga inicial de GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# 1) Sube catálogos (vehículos, responsables, sucursales, config) a DynamoDB.
# 2) Crea cuentas de inicio de sesión en Cognito.
#
# Requisitos: boto3 y credenciales de AWS configuradas (aws configure).
#
# Uso recomendado (resuelve tabla y pool solo, desde los Outputs del stack):
#   python seed/seed.py --stack gpa-operaciones-dev --region us-east-1 --operadores
#
#   La contraseña inicial NO va en el comando: se toma de la variable
#   GPA_SEED_PASSWORD o, si no existe, se pregunta de forma segura (no queda en el
#   historial de la terminal). También puedes forzarla con --password "…".
#   Por defecto la contraseña es TEMPORAL: cada usuario define la suya en el primer
#   ingreso (más seguro). Usa --permanente solo si quieres una clave definitiva.
#
# Uso manual (sin --stack):
#   python seed/seed.py --tabla gpa_operaciones_dev --pool-id us-east-1_XXXX
#
# Variables de entorno admitidas: STACK_NAME, DYNAMO_TABLE, USER_POOL_ID,
# AWS_REGION, GPA_SEED_PASSWORD.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, json, os, sys
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

AQUI = Path(__file__).parent


def _to_dec(o):
    if isinstance(o, float):
        return Decimal(str(o))
    if isinstance(o, dict):
        return {k: _to_dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_to_dec(v) for v in o]
    return o


def cargar_catalogos(tabla):
    data = json.loads((AQUI / "catalogos.json").read_text(encoding="utf-8"))
    with tabla.batch_writer() as bw:
        for v in data["vehicles"]:
            bw.put_item(Item=_to_dec({"PK": "CAT#VEHICLE", "SK": f"VEH#{v['id']}", **v}))
        for u in data["users"]:
            bw.put_item(Item=_to_dec({"PK": "CAT#USER", "SK": f"USR#{u['id']}", **u}))
        for s in data["sucursales"]:
            bw.put_item(Item={"PK": "CAT#SUCURSAL", "SK": f"SUC#{s}", "nombre": s})
    tabla.put_item(Item={"PK": "CONFIG", "SK": "CONFIG", **data["config"]})
    print(f"✓ Catálogos: {len(data['vehicles'])} vehículos, "
          f"{len(data['users'])} responsables, {len(data['sucursales'])} sucursales")
    cargar_formularios(tabla)
    return data


def cargar_formularios(tabla):
    """Carga módulos y plantillas del motor de formularios (seed/plantillas.json).
    Opcional: si el archivo no existe, no hace nada."""
    ruta = AQUI / "plantillas.json"
    if not ruta.exists():
        return
    data = json.loads(ruta.read_text(encoding="utf-8"))
    mods = data.get("modulos", [])
    plts = data.get("plantillas", [])
    with tabla.batch_writer() as bw:
        for m in mods:
            clave = str(m["clave"]).strip().lower()
            bw.put_item(Item=_to_dec({"PK": "CAT#MODULO", "SK": f"MOD#{clave}", **m, "clave": clave}))
        for p in plts:
            clave = str(p["clave"]).strip().lower()
            bw.put_item(Item=_to_dec({"PK": "CAT#PLANTILLA", "SK": f"PLT#{clave}", **p, "clave": clave}))
    if mods or plts:
        print(f"✓ Formularios: {len(mods)} módulo(s), {len(plts)} plantilla(s)")


DOMINIO = os.environ.get("DOMINIO_PERMITIDO", "gpa.com.mx").lower()


def crear_usuario(cog, pool_id, email, nombre, rol, sucursal, password, forzar_cambio=False):
    email = (email or "").strip().lower()
    if not email.endswith("@" + DOMINIO):
        print(f"  · omitido (dominio no permitido): {email}")
        return False
    attrs = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "custom:rol", "Value": rol},
        {"Name": "custom:sucursal", "Value": sucursal or ""},
        {"Name": "custom:sucursales", "Value": sucursal or ""},
        {"Name": "custom:nombre", "Value": nombre or ""},
    ]
    try:
        cog.admin_create_user(UserPoolId=pool_id, Username=email,
                              UserAttributes=attrs, MessageAction="SUPPRESS")
    except cog.exceptions.UsernameExistsException:
        cog.admin_update_user_attributes(UserPoolId=pool_id, Username=email, UserAttributes=attrs)
    # Permanent=False → la contraseña es TEMPORAL: el usuario debe cambiarla en su
    # primer ingreso (Cognito devuelve NEW_PASSWORD_REQUIRED, que la app ya maneja).
    # Permanent=True → contraseña definitiva (alta rápida, menos segura).
    cog.admin_set_user_password(UserPoolId=pool_id, Username=email,
                                Password=password, Permanent=not forzar_cambio)
    # Agregar al grupo del rol
    try:
        cog.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=rol)
    except ClientError:
        pass
    return True


def crear_cuentas(cog, pool_id, password, con_operadores, forzar_cambio=False):
    cuentas = json.loads((AQUI / "cuentas.json").read_text(encoding="utf-8"))["cuentas"]
    explicitos = {c["email"] for c in cuentas}
    n = 0
    for c in cuentas:
        if crear_usuario(cog, pool_id, c["email"], c["nombre"], c["rol"], c.get("sucursal", ""), password, forzar_cambio):
            n += 1
            print(f"  · {c['rol']:10s} {c['email']}")

    if con_operadores:
        users = json.loads((AQUI / "catalogos.json").read_text(encoding="utf-8"))["users"]
        for u in users:
            mail = u.get("mail", "").strip().lower()
            if not mail or "@" not in mail or mail in explicitos:
                continue
            if crear_usuario(cog, pool_id, mail, u["nombre"], "operador", u.get("sucursal", ""), password, forzar_cambio):
                explicitos.add(mail)
                n += 1
        print(f"  · operadores creados desde responsables")
    print(f"✓ Cuentas Cognito procesadas: {n}")


def resolver_outputs(session, stack):
    """Lee TableName y UserPoolId de los Outputs del stack de CloudFormation."""
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    o = {x["OutputKey"]: x["OutputValue"] for x in outs}
    return o.get("TableName"), o.get("UserPoolId")


def _password(args):
    """Resuelve la contraseña inicial: --password, GPA_SEED_PASSWORD o prompt seguro."""
    if args.password:
        return args.password
    env = os.environ.get("GPA_SEED_PASSWORD")
    if env:
        return env
    import getpass
    pwd = getpass.getpass("Contraseña inicial para las cuentas: ")
    if len(pwd) < 8:
        sys.exit("La contraseña debe tener al menos 8 caracteres (minúscula + número).")
    return pwd


def main():
    ap = argparse.ArgumentParser(description="Seed de GPA Operaciones")
    ap.add_argument("--stack",   default=os.environ.get("STACK_NAME"),
                    help="Nombre del stack (ej. gpa-operaciones-dev). Resuelve tabla y pool solo.")
    ap.add_argument("--tabla",   default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--pool-id", default=os.environ.get("USER_POOL_ID"))
    ap.add_argument("--region",  default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--password", default=None,
                    help="Contraseña inicial. Si se omite, usa GPA_SEED_PASSWORD o pregunta de forma segura.")
    ap.add_argument("--operadores", action="store_true", help="Crear un login por responsable")
    ap.add_argument("--permanente", action="store_true",
                    help="Contraseña definitiva (NO fuerza cambio). Por defecto la contraseña es "
                         "temporal y cada usuario define la suya en el primer ingreso (más seguro).")
    ap.add_argument("--solo-cuentas", action="store_true", help="No tocar catálogos")
    ap.add_argument("--solo-catalogos", action="store_true", help="No tocar Cognito")
    ap.add_argument("--solo-formularios", action="store_true",
                    help="Carga SOLO módulos/plantillas (seed/plantillas.json). No toca "
                         "vehículos, responsables, sucursales, config ni Cognito. Seguro en prod.")
    args = ap.parse_args()
    forzar_cambio = not args.permanente

    session = boto3.Session(region_name=args.region)

    # Si dan --stack, resolvemos tabla/pool automáticamente (lo que falte)
    if args.stack:
        tabla, pool = resolver_outputs(session, args.stack)
        args.tabla = args.tabla or tabla
        args.pool_id = args.pool_id or pool

    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    # Atajo seguro para prod: solo agrega los formularios, sin tocar nada más.
    if args.solo_formularios:
        cargar_formularios(session.resource("dynamodb").Table(args.tabla))
        print("\nListo (solo formularios). No se tocaron catálogos ni cuentas.")
        return

    if not args.solo_cuentas:
        cargar_catalogos(session.resource("dynamodb").Table(args.tabla))

    if not args.solo_catalogos:
        if not args.pool_id:
            sys.exit("Falta --pool-id (o --stack, o USER_POOL_ID) para crear cuentas")
        pwd = _password(args)
        crear_cuentas(session.client("cognito-idp"), args.pool_id, pwd, args.operadores, forzar_cambio)
        print("\nListo. Cuentas creadas.")
        if forzar_cambio:
            print("🔐 Contraseña TEMPORAL: cada usuario la cambiará por la suya en el primer ingreso.")
            print("   Comunícales la contraseña temporal; la app les pedirá una nueva al entrar.")
        else:
            print("⚠️  Contraseña definitiva y compartida. Pídeles cambiarla cuanto antes.")
    else:
        print("\nListo (solo catálogos).")


if __name__ == "__main__":
    main()
