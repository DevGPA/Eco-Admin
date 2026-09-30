# mantenimiento/datos.py
# Lectura y escritura del Plan de Mantenimiento en la tabla única.
# Prefijos PROPIOS (ningún ítem existente cambia de forma):
#   CAT#ACTIVO / ACT#{codigo}        CAT#TIPOACTIVO / TIPO#{pref}
#   CAT#PERIODICIDAD / PER#{texto}   CAT#AREA / AREA#{nombre}
#   MP#{codigo}#{anio}#{semana}      MPC#{codigo}#{timestamp}
#   MTTO#ACTA / {fecha}              CAT#MODULO / MOD#mantenimiento (administradores, sucursales)
# Los MP usan registro_keys() tal cual: GSI1 por tipo, GSI2 por sucursal, GSI3 por
# cuenta asignada efectiva (o SIN_ASIGNAR#{sucursal}).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import time
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

from db import modelos as m
from db.queries import _query_todo, _limpiar
from mantenimiento import logica as L

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "gpa_operaciones_dev")
_table = None
_MX = timezone(timedelta(hours=-6))
CLAVE_MODULO = "mantenimiento"


def _t():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def ahora_iso() -> str:
    return datetime.now(_MX).isoformat(timespec="seconds")


def _items(items) -> list:
    return [_limpiar(m.from_dynamo(i)) for i in items]


def _pk(pk) -> list:
    return _items(_query_todo(_t(), KeyConditionExpression=Key("PK").eq(pk)))


# ── Módulo (administradores, equivalencia de sucursales) ──────────
def modulo() -> dict:
    it = _t().get_item(Key={"PK": m.PK_MODULO, "SK": m.sk_modulo(CLAVE_MODULO)}).get("Item")
    return _limpiar(m.from_dynamo(it)) if it else {}


def administradores() -> list:
    return [str(a).lower() for a in (modulo().get("administradores") or []) if a]


def sucursales_plan() -> dict:
    """{codigo del plan: sucursal de la app}. Lo escribe el importador; si no hay, la base."""
    return dict(modulo().get("sucursales") or L.SUCURSAL_APP)


# ── Catálogos ────────────────────────────────────────────────────
def activos(solo_activos: bool = False) -> list:
    out = _pk(m.PK_ACTIVO)
    if solo_activos:
        out = [a for a in out if a.get("activo") is not False]
    return sorted(out, key=lambda a: str(a.get("codigo") or ""))


def activo(codigo: str) -> dict | None:
    it = _t().get_item(Key={"PK": m.PK_ACTIVO, "SK": m.sk_activo(codigo)}).get("Item")
    return _limpiar(m.from_dynamo(it)) if it else None


def guardar_activo(a: dict) -> dict:
    codigo = str(a.get("codigo") or "").strip().upper()
    if not codigo:
        raise ValueError("Falta el código del activo")
    item = {k: v for k, v in a.items() if k not in ("PK", "SK")}
    item["codigo"] = codigo
    item.setdefault("activo", True)
    item["actualizadoEn"] = ahora_iso()
    _t().put_item(Item={"PK": m.PK_ACTIVO, "SK": m.sk_activo(codigo), **m.to_dynamo(item)})
    return item


def tipos() -> list:
    return sorted(_pk(m.PK_TIPOACTIVO), key=lambda t: str(t.get("pref") or ""))


def guardar_tipo(t: dict) -> dict:
    pref = str(t.get("pref") or "").strip().upper()
    if not pref:
        raise ValueError("Falta el prefijo del tipo")
    item = {k: v for k, v in t.items() if k not in ("PK", "SK")}
    item["pref"] = pref
    item["actualizadoEn"] = ahora_iso()
    _t().put_item(Item={"PK": m.PK_TIPOACTIVO, "SK": m.sk_tipo_activo(pref), **m.to_dynamo(item)})
    return item


def periodicidades() -> dict:
    """{texto normalizado: semanas}"""
    return {str(p.get("texto")): int(p.get("semanas") or 0) for p in _pk(m.PK_PERIODICIDAD) if p.get("texto")}


def guardar_periodicidad(texto: str, semanas: int) -> None:
    texto = L.norm_periodicidad(texto)
    _t().put_item(Item={"PK": m.PK_PERIODICIDAD, "SK": m.sk_periodicidad(texto),
                        "texto": texto, "semanas": int(semanas)})


def areas() -> list:
    return sorted(a.get("nombre") for a in _pk(m.PK_AREA) if a.get("nombre"))


def guardar_area(nombre: str) -> None:
    nombre = str(nombre or "").strip()
    if nombre:
        _t().put_item(Item={"PK": m.PK_AREA, "SK": m.sk_area(nombre), "nombre": nombre})


def sucursales_app() -> list:
    return sorted(s.get("nombre") for s in _pk(m.PK_SUCURSAL) if s.get("nombre"))


# ── Vencimientos (MP) ────────────────────────────────────────────
def _mp_item(mp: dict, act: dict | None) -> dict:
    """Ítem completo con llaves. `fecha` = fecha límite (sábado) en ISO-date."""
    codigo, anio, sem = mp["codigo"], int(mp["anio"]), int(mp["semana"])
    fecha = L.fecha_limite(anio, sem).isoformat()
    rid = L.rid_mp(codigo, anio, sem)
    cuenta = L.cuenta_gsi3(mp, act)
    item = {**m.registro_keys(m.MP, rid, mp.get("sucursal") or "SIN_SUCURSAL", cuenta, fecha),
            **m.to_dynamo({k: v for k, v in mp.items() if k not in ("PK", "SK")}),
            "id": rid, "tipo_reg": m.MP, "fecha": fecha, "codigo": codigo, "anio": anio, "semana": sem}
    item.setdefault("estatus", "programada")
    item.setdefault("publicado", True)
    return item


def get_mp(rid: str) -> dict | None:
    it = _t().get_item(Key={"PK": f"{m.MP}#{rid}", "SK": "META"}).get("Item")
    return _limpiar(m.from_dynamo(it)) if it else None


def existe_mp(rid: str) -> bool:
    return bool(_t().get_item(Key={"PK": f"{m.MP}#{rid}", "SK": "META"},
                              ProjectionExpression="PK").get("Item"))


def poner_mp(mp: dict, act: dict | None) -> dict:
    """Escribe (o sobreescribe) un vencimiento completo."""
    item = _mp_item(mp, act)
    _t().put_item(Item=item)
    return _limpiar(m.from_dynamo(item))


def parchar_mp(rid: str, parche: dict) -> None:
    if not parche:
        return
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(parche.items()):
        names[f"#k{i}"] = k
        values[f":v{i}"] = m.to_dynamo(v)
        sets.append(f"#k{i} = :v{i}")
    _t().update_item(Key={"PK": f"{m.MP}#{rid}", "SK": "META"},
                     UpdateExpression="SET " + ", ".join(sets),
                     ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def borrar_mp(rid: str) -> None:
    _t().delete_item(Key={"PK": f"{m.MP}#{rid}", "SK": "META"})


def mps_todos(anio: int | None = None) -> list:
    its = _items(_query_todo(_t(), IndexName="tipo-fecha-idx",
                             KeyConditionExpression=Key("GSI1PK").eq(m.MP)))
    return [x for x in its if anio is None or int(x.get("anio") or 0) == int(anio)]


def mps_sucursal(sucursal: str, anio: int | None = None) -> list:
    its = _items(_query_todo(_t(), IndexName="sucursal-fecha-idx",
                             KeyConditionExpression=Key("GSI2PK").eq(f"{m.MP}#{sucursal}")))
    return [x for x in its if anio is None or int(x.get("anio") or 0) == int(anio)]


def mps_cuenta(cuenta: str, anio: int | None = None) -> list:
    its = _items(_query_todo(_t(), IndexName="cuenta-fecha-idx",
                             KeyConditionExpression=Key("GSI3PK").eq(f"{m.MP}#{cuenta}")))
    return [x for x in its if anio is None or int(x.get("anio") or 0) == int(anio)]


def mps_activo(codigo: str, anio: int | None = None) -> list:
    """Los vencimientos de UN activo (filtra sobre el índice por tipo; ≤ 13 por año)."""
    return [x for x in mps_todos(anio) if x.get("codigo") == codigo]


def reindexar_cuenta(mp: dict, act: dict | None) -> None:
    """Reescribe GSI3PK cuando cambia el asignado efectivo (excepción o titular)."""
    parchar_mp(mp["id"], {"GSI3PK": f"{m.MP}#{L.cuenta_gsi3(mp, act)}"})


# ── Correctivos (MPC) ────────────────────────────────────────────
def crear_mpc(datos: dict, sucursal: str, cuenta: str) -> dict:
    codigo = str(datos.get("codigo") or "")
    rid = f"{codigo}#{int(time.time() * 1000)}"
    fecha = ahora_iso()
    item = {**m.registro_keys(m.MPC, rid, sucursal or "SIN_SUCURSAL", cuenta, fecha),
            **m.to_dynamo(datos), "id": rid, "tipo_reg": m.MPC, "fecha": fecha,
            "sucursal": sucursal, "accountId": cuenta}
    _t().put_item(Item=item)
    return _limpiar(m.from_dynamo(item))


def mpcs_todos() -> list:
    return _items(_query_todo(_t(), IndexName="tipo-fecha-idx",
                              KeyConditionExpression=Key("GSI1PK").eq(m.MPC), ScanIndexForward=False))


def mpcs_sucursal(sucursal: str) -> list:
    return _items(_query_todo(_t(), IndexName="sucursal-fecha-idx",
                              KeyConditionExpression=Key("GSI2PK").eq(f"{m.MPC}#{sucursal}"),
                              ScanIndexForward=False))


# ── Acta de importación ──────────────────────────────────────────
def guardar_acta(acta: dict) -> dict:
    fecha = ahora_iso()
    item = {"PK": m.PK_MTTO_ACTA, "SK": fecha, "fecha": fecha, **m.to_dynamo(acta)}
    _t().put_item(Item=item)
    return _limpiar(m.from_dynamo(item))


def actas(limite: int = 3) -> list:
    its = _items(_query_todo(_t(), KeyConditionExpression=Key("PK").eq(m.PK_MTTO_ACTA),
                             ScanIndexForward=False))
    return its[:limite]
