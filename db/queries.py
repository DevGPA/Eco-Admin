# db/queries.py — lecturas de GPA Alta de Clientes.
from __future__ import annotations

from boto3.dynamodb.conditions import Key

from . import tabla, sin_decimales
from .modelos import SK_META, pk_caso, dias_desde

# Campos que jamás salen de la Lambda hacia ningún cliente.
SECRETOS = ("claveHash", "claveSal")


def _publico(caso: dict | None) -> dict | None:
    """Quita la huella de la clave antes de devolver un caso."""
    if not caso:
        return None
    return {k: v for k, v in caso.items() if k not in SECRETOS}


def get_caso(folio: str, con_secretos: bool = False) -> dict | None:
    r = tabla().get_item(Key={"PK": pk_caso(folio), "SK": SK_META})
    caso = sin_decimales(r.get("Item"))
    if not caso:
        return None
    return caso if con_secretos else _publico(caso)


def caso_por_token(token: str, con_secretos: bool = False) -> dict | None:
    """Busca el expediente al que apunta una liga. Índice GSI2."""
    if not token:
        return None
    r = tabla().query(
        IndexName="token-idx",
        KeyConditionExpression=Key("GSI2PK").eq(f"TOKEN#{token}") & Key("GSI2SK").eq(SK_META),
        Limit=1,
    )
    items = sin_decimales(r.get("Items") or [])
    if not items:
        return None
    return items[0] if con_secretos else _publico(items[0])


def listar_casos(estado: str = "", limite: int = 200) -> list:
    """Expedientes más recientes primero. Si se da estado, usa el índice por estado."""
    if estado:
        r = tabla().query(
            IndexName="estado-fecha-idx",
            KeyConditionExpression=Key("GSI3PK").eq(f"EST#{estado}"),
            ScanIndexForward=False,
            Limit=limite,
        )
    else:
        r = tabla().query(
            IndexName="tipo-fecha-idx",
            KeyConditionExpression=Key("GSI1PK").eq("CASO"),
            ScanIndexForward=False,
            Limit=limite,
        )
    return [_publico(c) for c in sin_decimales(r.get("Items") or [])]


def bitacora(folio: str, limite: int = 200) -> list:
    """Quién hizo qué y cuándo, del más reciente al más viejo."""
    r = tabla().query(
        KeyConditionExpression=Key("PK").eq(pk_caso(folio)) & Key("SK").begins_with("LOG#"),
        ScanIndexForward=False,
        Limit=limite,
    )
    return sin_decimales(r.get("Items") or [])


def resumen_bandeja(casos: list) -> list:
    """Lo que la bandeja necesita por renglón, sin arrastrar el expediente completo."""
    from catalogos import TIPOS, docs_aplicables, persona_de, FIRMAS_REQUERIDAS

    filas = []
    for c in casos:
        tipo = TIPOS.get(c.get("tipo")) or TIPOS["alta"]
        persona = persona_de(c.get("regimen"), c.get("rfc"))
        aplic = docs_aplicables(c.get("tipo"), c.get("docs") or {}, persona)
        adjuntos = c.get("adjuntos") or {}
        marcas = c.get("marcas") or {}
        señalados = [k for k, v in marcas.items() if isinstance(v, dict) and v.get("motivo")]
        filas.append({
            "folio": c.get("folio"),
            "tipo": c.get("tipo"),
            "razonSocial": c.get("razonSocial"),
            "rfc": c.get("rfc"),
            "regimen": c.get("regimen"),
            "sucursal": c.get("sucursal"),
            "creadoPor": c.get("creadoPor"),
            "estado": c.get("estado"),
            "dias": dias_desde(c.get("creado")),
            "pedidos": len(aplic),
            "ok": sum(1 for d in aplic if adjuntos.get(d["id"])),
            "marcados": len(señalados),
            "firmas": len(c.get("autorizaciones") or []),
            "firmasRequeridas": FIRMAS_REQUERIDAS[tipo["autoriza"]],
        })
    return filas
