# db/__init__.py — acceso a DynamoDB para GPA Alta de Clientes.
from __future__ import annotations
import os
from decimal import Decimal

import boto3

_TABLA = None


def tabla():
    """Recurso de la tabla, creado una sola vez por contenedor de Lambda."""
    global _TABLA
    if _TABLA is None:
        _TABLA = boto3.resource("dynamodb").Table(os.environ["DYNAMO_TABLE"])
    return _TABLA


def sin_decimales(obj):
    """DynamoDB devuelve Decimal; json.dumps no sabe serializarlo."""
    if isinstance(obj, list):
        return [sin_decimales(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sin_decimales(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        entero = int(obj)
        return entero if obj == entero else float(obj)
    return obj
