#!/usr/bin/env python3
# seed/seed.py — Carga inicial de GPA ViaticOS
# ─────────────────────────────────────────────────────────────────
# 1) Sube catálogos (empleados, áreas, política POL-TE01, tarifas, config) a DynamoDB.
# 2) Crea cuentas de inicio de sesión en Cognito (una por rol del flujo).
#
# Requisitos: boto3 y credenciales de AWS configuradas (aws configure).
#
# Uso (toma los valores de los Outputs del stack):
#   python seed/seed.py \
#       --tabla   gpa_viaticos_dev \
#       --pool-id us-east-1_XXXXXXXXX \
#       --region  us-east-1 \
#       --password "Gpa2026!" \
#       --empleados            # opcional: crea un login por empleado del catálogo
#
# También puede leer de variables de entorno: DYNAMO_TABLE, USER_POOL_ID, AWS_REGION
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
        for e in data["empleados"]:
            bw.put_item(Item=_to_dec({"PK": "CAT#EMPLEADO", "SK": f"EMP#{e['id']}", **e}))
        for a in data["areas"]:
            bw.put_item(Item={"PK": "CAT#AREA", "SK": f"AREA#{a}", "nombre": a})
    tabla.put_item(Item=_to_dec({"PK": "CONFIG", "SK": "POLITICA", **data["politica"]}))
    tabla.put_item(Item=_to_dec({"PK": "CONFIG", "SK": "TARIFAS", **data["tarifas"]}))
    tabla.put_item(Item=_to_dec({"PK": "CONFIG", "SK": "CONFIG", **data["config"]}))
    print(f"✓ Catálogos: {len(data['empleados'])} empleados, "
          f"{len(data['areas'])} áreas, política POL-TE01 y tarifas cargadas")
    return data


def crear_usuario(cog, pool_id, email, nombre, rol, area, jefe, password):
    attrs = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "custom:rol", "Value": rol},
        {"Name": "custom:area", "Value": area or ""},
        {"Name": "custom:nombre", "Value": nombre or ""},
        {"Name": "custom:jefe", "Value": jefe or ""},
    ]
    try:
        cog.admin_create_user(UserPoolId=pool_id, Username=email,
                              UserAttributes=attrs, MessageAction="SUPPRESS")
    except cog.exceptions.UsernameExistsException:
        cog.admin_update_user_attributes(UserPoolId=pool_id, Username=email, UserAttributes=attrs)
    # Contraseña permanente (sin forzar cambio) para simplificar el alta masiva
    cog.admin_set_user_password(UserPoolId=pool_id, Username=email,
                                Password=password, Permanent=True)
    try:
        cog.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=rol)
    except ClientError:
        pass


def crear_cuentas(cog, pool_id, password, con_empleados):
    cuentas = json.loads((AQUI / "cuentas.json").read_text(encoding="utf-8"))["cuentas"]
    explicitos = {c["email"] for c in cuentas}
    n = 0
    for c in cuentas:
        crear_usuario(cog, pool_id, c["email"], c["nombre"], c["rol"],
                      c.get("area", ""), c.get("jefe", ""), password)
        n += 1
        print(f"  · {c['rol']:11s} {c['email']}")

    if con_empleados:
        emps = json.loads((AQUI / "catalogos.json").read_text(encoding="utf-8"))["empleados"]
        for e in emps:
            mail = (e.get("mail") or "").strip().lower()
            if not mail or "@" not in mail or mail in explicitos:
                continue
            crear_usuario(cog, pool_id, mail, e["nombre"], "empleado",
                          e.get("area", ""), e.get("jefe", ""), password)
            explicitos.add(mail)
            n += 1
        print("  · empleados creados desde el catálogo")
    print(f"✓ Cuentas Cognito procesadas: {n}")


def main():
    ap = argparse.ArgumentParser(description="Seed de GPA ViaticOS")
    ap.add_argument("--tabla",   default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--pool-id", default=os.environ.get("USER_POOL_ID"))
    ap.add_argument("--region",  default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--password", default="Gpa2026!", help="Contraseña inicial para todas las cuentas")
    ap.add_argument("--empleados", action="store_true", help="Crear un login por empleado del catálogo")
    ap.add_argument("--solo-cuentas", action="store_true", help="No tocar catálogos")
    ap.add_argument("--solo-catalogos", action="store_true", help="No tocar Cognito")
    args = ap.parse_args()

    if not args.tabla:
        sys.exit("Falta --tabla (o DYNAMO_TABLE)")

    session = boto3.Session(region_name=args.region)

    if not args.solo_cuentas:
        cargar_catalogos(session.resource("dynamodb").Table(args.tabla))

    if not args.solo_catalogos:
        if not args.pool_id:
            sys.exit("Falta --pool-id (o USER_POOL_ID) para crear cuentas")
        crear_cuentas(session.client("cognito-idp"), args.pool_id,
                      args.password, args.empleados)


if __name__ == "__main__":
    main()
