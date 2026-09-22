# tests/tabla_memoria.py — DynamoDB en memoria para probar las reglas de negocio.
# ─────────────────────────────────────────────────────────────────
# NO reemplaza a DynamoDB: solo guarda y consulta lo mínimo que usa el código,
# para poder ejecutar db/escritura.py TAL CUAL (no una copia de sus reglas).
# Lo que esto NO prueba: permisos de IAM, índices reales, límites de tamaño.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import re


class ErrorCondicion(Exception):
    pass


class _Excepciones:
    ConditionalCheckFailedException = ErrorCondicion


def _evalua(cond, item) -> bool:
    """Evalúa una condición de boto3 (Key('x').eq(...), &, begins_with) contra un item."""
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        return all(_evalua(v, item) for v in vals)
    campo = vals[0].name
    esperado = vals[1]
    actual = item.get(campo)
    if op == "=":
        return actual == esperado
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(esperado)
    raise NotImplementedError(f"operador no soportado en la prueba: {op}")


_SET_RE = re.compile(r"(#?\w+)\s*=\s*(:\w+)")


class TablaMemoria:
    """Implementa get_item / put_item / update_item / query."""

    def __init__(self):
        self.items = {}          # (PK, SK) -> dict
        self.exceptions = _Excepciones()

    # ── lectura ──
    def get_item(self, Key):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression, IndexName=None, ScanIndexForward=True,
              Limit=None, **_):
        encontrados = [dict(i) for i in self.items.values()
                       if _evalua(KeyConditionExpression, i)]
        orden = {"tipo-fecha-idx": "GSI1SK", "token-idx": "GSI2SK",
                 "estado-fecha-idx": "GSI3SK"}.get(IndexName, "SK")
        encontrados.sort(key=lambda i: str(i.get(orden, "")), reverse=not ScanIndexForward)
        if Limit:
            encontrados = encontrados[:Limit]
        return {"Items": encontrados}

    # ── escritura ──
    def put_item(self, Item, ConditionExpression=None):
        llave = (Item["PK"], Item["SK"])
        if ConditionExpression is not None and llave in self.items:
            raise ErrorCondicion("ya existe")
        self.items[llave] = dict(Item)
        return {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None,
                    ExpressionAttributeNames=None, ReturnValues=None):
        llave = (Key["PK"], Key["SK"])
        item = self.items.setdefault(llave, {"PK": Key["PK"], "SK": Key["SK"]})
        nombres = ExpressionAttributeNames or {}
        valores = ExpressionAttributeValues or {}
        expr = UpdateExpression.strip()
        nuevos = {}

        if expr.upper().startswith("ADD"):
            _, campo, marcador = expr.split()
            real = nombres.get(campo, campo)
            item[real] = int(item.get(real, 0)) + int(valores[marcador])
            nuevos[real] = item[real]
        elif expr.upper().startswith("SET"):
            for campo, marcador in _SET_RE.findall(expr[3:]):
                real = nombres.get(campo, campo)
                item[real] = valores[marcador]
                nuevos[real] = item[real]
        else:
            raise NotImplementedError(f"expresión no soportada: {expr}")

        if not ReturnValues:
            return {}
        # ALL_NEW devuelve el item completo; UPDATED_NEW solo lo que cambió.
        return {"Attributes": dict(item) if str(ReturnValues).startswith("ALL_") else nuevos}

    # ── ayuda para las pruebas ──
    def casos(self):
        return [i for i in self.items.values() if i.get("SK") == "META"]

    def logs(self, folio):
        return sorted((i for i in self.items.values()
                       if i["PK"] == f"CASO#{folio}" and i["SK"].startswith("LOG#")),
                      key=lambda i: i["SK"])
