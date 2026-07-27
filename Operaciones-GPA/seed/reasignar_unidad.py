#!/usr/bin/env python3
# seed/reasignar_unidad.py — Re-atribuir registros de una unidad a otra — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Caso de uso: por error se capturaron registros bajo la unidad equivocada
# (p. ej. combustible de la R04 quedó registrado en la 52). Este script reasigna
# esos registros a la unidad correcta.
#
# MODELO (espeja la reasignación de la app, db.escritura.reasignar_registro_unidad):
# por cada registro se CREA uno NUEVO en la unidad correcta (con los mismos datos
# del evento —km, litros, fotos, firma— y la MISMA fecha/estado originales) y el
# viejo queda en status "Anulado". Así el puente propaga automáticamente a Fleet
# Command el alta del nuevo y el «Anulado» del viejo, sin corrección manual.
# NO se borra nada (prod tiene protección de borrado / PITR). Si además quieres
# copiar las características de la unidad destino (combustible/producto/tanque/
# precio) al registro nuevo, usa --incluir-caracteristicas (revisa el dry-run).
#
# SEGURO POR DEFECTO: sin --confirm solo simula (dry-run) y no escribe nada.
# Respalda cada item original (JSONL) antes de modificarlo.
#
# Uso (CloudShell):
#   # 1) Ver qué se movería (no escribe nada):
#   python3 seed/reasignar_unidad.py --stack gpa-operaciones-prod \
#       --origen 52 --destino R04 --hasta 2026-07-16
#   # 2) Ejecutar la re-atribución:
#   python3 seed/reasignar_unidad.py --stack gpa-operaciones-prod \
#       --origen 52 --destino R04 --hasta 2026-07-16 --confirm
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta

MX_TZ = timezone(timedelta(hours=-6))   # Ciudad de México (UTC-6 fijo)

# Campos de IDENTIDAD de la unidad que viven desnormalizados en cada registro.
CAMPOS_IDENTIDAD = ["vehicleId", "economico", "placas", "subMarca",
                    "sucursal", "areaResponsable"]
# Características de la unidad (opcionales; por defecto NO se tocan).
CAMPOS_CARACTERISTICAS = ["combustible", "producto", "tanque", "precio"]

# Claves internas / de identidad del registro que NO se copian al registro nuevo.
_KEYS_DYNAMO = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"}
_NO_COPIAR = _KEYS_DYNAMO | {"id", "tipo_reg", "fecha", "sucursal", "accountId",
                             "reasignacion", "reasignadoA", "reasignadoDe"}


def _now_iso() -> str:
    return datetime.now(MX_TZ).isoformat()


def _registro_keys(tipo, rid, sucursal, account_id, fecha):
    return {"PK": f"{tipo}#{rid}", "SK": "META",
            "GSI1PK": tipo, "GSI1SK": fecha,
            "GSI2PK": f"{tipo}#{sucursal}", "GSI2SK": fecha,
            "GSI3PK": f"{tipo}#{account_id}", "GSI3SK": fecha}


def reasignar_item(tabla, item: dict, destino: dict, incluir_caracteristicas: bool = False) -> str:
    """Reasigna como REGISTRO NUEVO (espeja db.escritura.reasignar_registro_unidad):
    crea un registro nuevo en la unidad destino (datos + fecha/estado originales) y
    deja el viejo en status "Anulado". Ambas escrituras cruzan el stream → el puente
    propaga alta(nuevo)+cambio_estado(viejo). Devuelve el id del registro nuevo."""
    import uuid
    tipo = str(item.get("tipo_reg") or str(item.get("PK", "")).split("#", 1)[0])
    negocio = {k: v for k, v in item.items() if k not in _NO_COPIAR}
    negocio["vehicleId"] = destino["id"]
    for c in ("economico", "placas", "subMarca", "sucursal"):
        if destino.get(c) is not None:
            negocio[c] = destino.get(c)
    if destino.get("responsable") is not None and "areaResponsable" in item:
        negocio["areaResponsable"] = destino.get("responsable")
    if incluir_caracteristicas:
        for c in CAMPOS_CARACTERISTICAS:
            if destino.get(c) is not None:
                negocio[c] = destino.get(c)
    fecha = item.get("fecha") or _now_iso()
    sucursal = destino.get("sucursal") or item.get("sucursal") or "SIN_SUCURSAL"
    account_id = item.get("accountId") or ""
    new_id = uuid.uuid4().hex[:12]
    negocio["reasignadoDe"] = {
        "id": item.get("id"), "folio": f"{tipo}-{item.get('id')}".upper(),
        "vehicleId": item.get("vehicleId"), "economico": item.get("economico"),
        "placas": item.get("placas"), "sucursal": item.get("sucursal"),
        "por": "seed/reasignar_unidad", "en": _now_iso()}
    nuevo = {**_registro_keys(tipo, new_id, sucursal, account_id, fecha), **negocio,
             "id": new_id, "tipo_reg": tipo, "fecha": fecha,
             "sucursal": sucursal, "accountId": account_id}
    tabla.put_item(Item=nuevo)
    tabla.update_item(
        Key={"PK": item["PK"], "SK": item["SK"]},
        UpdateExpression="SET #s = :s, reasignadoA = :ra",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "Anulado", ":ra": {
            "id": new_id, "folio": f"{tipo}-{new_id}".upper(),
            "vehicleId": destino["id"], "economico": destino.get("economico"),
            "sucursal": sucursal, "por": "seed/reasignar_unidad", "en": _now_iso()}},
    )
    return new_id


def construir_cambio(item: dict, origen: dict, destino: dict,
                     incluir_caracteristicas: bool = False) -> dict:
    """Función PURA (testeable sin AWS): dado un registro y las unidades
    origen/destino del catálogo, devuelve {campo: valor_nuevo} SOLO con los
    campos que realmente cambian. Recalcula GSI2PK con la sucursal destino.
    """
    campos = list(CAMPOS_IDENTIDAD)
    if incluir_caracteristicas:
        campos += CAMPOS_CARACTERISTICAS
    cambio = {}
    for c in campos:
        # vehicleId destino = id (llave inmutable) de la unidad destino
        nuevo = destino["id"] if c == "vehicleId" else destino.get(c)
        if nuevo is None:
            continue                      # el destino no define ese campo
        if c not in item:
            continue                      # el registro no traía ese campo: no lo inventamos
        if item.get(c) != nuevo:
            cambio[c] = nuevo
    # Índice por sucursal: GSI2PK = "{TIPO}#{sucursal}"
    tipo = str(item.get("tipo_reg") or str(item.get("PK", "")).split("#", 1)[0])
    nuevo_gsi2 = f"{tipo}#{destino.get('sucursal')}"
    if item.get("GSI2PK") and item.get("GSI2PK") != nuevo_gsi2 and destino.get("sucursal"):
        cambio["GSI2PK"] = nuevo_gsi2
    return cambio


def resolver_outputs(session, stack):
    cf = session.client("cloudformation")
    try:
        outs = cf.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    except Exception as e:
        sys.exit(f"No se pudieron leer los Outputs del stack '{stack}': {e}")
    return {x["OutputKey"]: x["OutputValue"] for x in outs}.get("TableName")


def cargar_unidad(tabla, clave: str) -> dict:
    """Busca una unidad en CAT#VEHICLE por id exacto o por económico."""
    from boto3.dynamodb.conditions import Key
    items, kwargs = [], {"KeyConditionExpression": Key("PK").eq("CAT#VEHICLE")}
    while True:
        resp = tabla.query(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    por_id  = [v for v in items if str(v.get("id")) == str(clave)]
    por_eco = [v for v in items if str(v.get("economico")) == str(clave)]
    cand = por_id or por_eco
    if not cand:
        sys.exit(f"No existe la unidad '{clave}' en el catálogo. "
                 f"Créala primero en el panel Admin.")
    if len(cand) > 1:
        detalle = ", ".join(f"id={v.get('id')}/eco={v.get('economico')}" for v in cand)
        sys.exit(f"'{clave}' es ambiguo ({len(cand)} coincidencias: {detalle}). "
                 f"Usa el id exacto.")
    return cand[0]


def buscar_registros(tabla, tipo: str, origen_id: str, hasta: str) -> list[dict]:
    """Registros del tipo dado atribuidos a origen_id con fecha <= hasta (YYYY-MM-DD)."""
    from boto3.dynamodb.conditions import Key
    out, kwargs = [], {"IndexName": "tipo-fecha-idx",
                       "KeyConditionExpression": Key("GSI1PK").eq(tipo)}
    while True:
        resp = tabla.query(**kwargs)
        for it in resp.get("Items", []):
            if str(it.get("vehicleId")) != str(origen_id):
                continue
            fecha = str(it.get("fecha") or it.get("GSI1SK") or "")
            if fecha[:10] <= hasta:
                out.append(it)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return out


def main():
    ap = argparse.ArgumentParser(description="Re-atribuir registros de una unidad a otra — GPA Operaciones")
    ap.add_argument("--stack", default=os.environ.get("STACK_NAME"),
                    help="Nombre del stack (ej. gpa-operaciones-prod). Resuelve la tabla sola.")
    ap.add_argument("--tabla", default=os.environ.get("DYNAMO_TABLE"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--origen", required=True, help="Unidad MAL atribuida (id o económico), ej. 52")
    ap.add_argument("--destino", required=True, help="Unidad CORRECTA (id o económico), ej. R04")
    ap.add_argument("--hasta", required=True, help="Mueve registros con fecha <= este día (YYYY-MM-DD, inclusive)")
    ap.add_argument("--tipo", default="SOL", choices=["SOL", "CL", "MC"],
                    help="Tipo de registro (por defecto SOL = combustible).")
    ap.add_argument("--incluir-caracteristicas", action="store_true",
                    help="Además copiar combustible/producto/tanque/precio del destino.")
    ap.add_argument("--confirm", action="store_true",
                    help="EJECUTAR los cambios (sin esto, solo simula).")
    args = ap.parse_args()

    try:
        datetime.strptime(args.hasta, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"--hasta inválida: '{args.hasta}' (formato YYYY-MM-DD)")

    import boto3
    session = boto3.Session(region_name=args.region)
    if args.stack and not args.tabla:
        args.tabla = resolver_outputs(session, args.stack)
    if not args.tabla:
        sys.exit("Falta --tabla (o --stack, o DYNAMO_TABLE)")

    dry_run = not args.confirm
    tabla = session.resource("dynamodb").Table(args.tabla)

    origen  = cargar_unidad(tabla, args.origen)
    destino = cargar_unidad(tabla, args.destino)
    if str(origen["id"]) == str(destino["id"]):
        sys.exit("Origen y destino son la MISMA unidad; nada que hacer.")

    modo = "SIMULACIÓN (no escribe nada)" if dry_run else "⚠️  EJECUCIÓN REAL"
    print(f"── Re-atribución de unidad · {modo} ──")
    print(f"   Tabla: {args.tabla}   Región: {args.region}   Tipo: {args.tipo}")
    print(f"   ORIGEN  (mal): id={origen['id']} eco={origen.get('economico')} "
          f"placas={origen.get('placas')} sucursal={origen.get('sucursal')}")
    print(f"   DESTINO (ok):  id={destino['id']} eco={destino.get('economico')} "
          f"placas={destino.get('placas')} sucursal={destino.get('sucursal')}")
    print(f"   Corte: registros con fecha <= {args.hasta} (inclusive)")

    # Aviso si las CARACTERÍSTICAS difieren (para decidir --incluir-caracteristicas)
    difs = [c for c in CAMPOS_CARACTERISTICAS if origen.get(c) != destino.get(c)]
    if difs and not args.incluir_caracteristicas:
        print("\n   Nota: origen y destino difieren en " + ", ".join(difs) +
              ". Por defecto NO se tocan (se conserva el dato del evento). "
              "Usa --incluir-caracteristicas si quieres copiarlas del destino.")

    registros = buscar_registros(tabla, args.tipo, origen["id"], args.hasta)
    print(f"\nRegistros {args.tipo} atribuidos a la {args.origen} con fecha <= {args.hasta}: {len(registros)}")
    if not registros:
        print("Nada que mover. (Revisa --origen/--tipo/--hasta.)")
        return

    respaldo = f"respaldo_reasignacion_{args.origen}_a_{args.destino}_{datetime.now(MX_TZ).strftime('%Y%m%d_%H%M%S')}.jsonl"
    folios, movidos, sin_cambio = [], 0, 0
    fh = None if dry_run else open(respaldo, "w", encoding="utf-8")
    try:
        for it in sorted(registros, key=lambda x: str(x.get("fecha"))):
            cambio = construir_cambio(it, origen, destino, args.incluir_caracteristicas)
            fid = it.get("id"); fecha = str(it.get("fecha"))[:19]
            formato = it.get("formato") or "solicitud"
            if str(it.get("status") or "") == "Anulado":
                sin_cambio += 1
                print(f"   = {fecha}  id={fid}  ({formato})  ya está ANULADO, se omite")
                continue
            if str(it.get("vehicleId")) == str(destino["id"]):
                sin_cambio += 1
                print(f"   = {fecha}  id={fid}  ({formato})  ya está en la {args.destino}, sin cambio")
                continue
            folios.append(f"OPS-{fid}")
            resumen = "  ".join(f"{k}:{it.get(k)}→{v}" for k, v in cambio.items() if k != "GSI2PK")
            if dry_run:
                print(f"   ○ {fecha}  id={fid}  km={it.get('km')}  ({formato})  → registro NUEVO en {args.destino}; este quedará ANULADO   {resumen}")
            else:
                fh.write(json.dumps(it, ensure_ascii=False, default=str) + "\n")
                new_id = reasignar_item(tabla, it, destino, args.incluir_caracteristicas)
                movidos += 1
                print(f"   ✓ {fecha}  id={fid}→{new_id}  km={it.get('km')}  ({formato})  nuevo en {args.destino}; viejo ANULADO")
    finally:
        if fh:
            fh.close()

    print()
    if dry_run:
        print(f"○ Simulación: se reasignarían {len(registros) - sin_cambio} registro(s) "
              f"de la {args.origen} a la {args.destino} ({sin_cambio} ya estaban ok/anulados).")
        print("○ Cada uno crea un registro NUEVO en la unidad correcta y deja el viejo ANULADO.")
        print("○ Para ejecutar de verdad agrega: --confirm")
    else:
        print(f"✓ {movidos} registro(s) reasignados a la {args.destino} "
              f"(nuevo en la unidad correcta + viejo ANULADO). "
              f"Respaldo de los originales: {respaldo}")

    # El puente propaga AUTOMÁTICAMENTE cada reasignación: alta del registro nuevo
    # (folio nuevo, unidad correcta) + cambio de estado del viejo a «Anulado».
    print("\n── Fleet Command ──")
    print("   El puente propaga solo la reasignación (alta del nuevo + «Anulado» del viejo).")
    print("   Confirma que estos folios VIEJOS quedaron anulados del lado Fleet Command:")
    print("   " + " ".join(folios))


if __name__ == "__main__":
    main()
