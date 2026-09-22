# db/veto.py — clientes a los que GPA no les da de alta.
# ─────────────────────────────────────────────────────────────────
# Lista de veto: cartera incobrable, fraude, juicio, relación terminada.
# Al crear una pre-solicitud se comparan RFC, razón social, nombre comercial,
# correo y celular contra esta lista.
#
# Dos niveles de coincidencia, a propósito:
#   EXACTA    (ya normalizado)  → bloquea. Solo un Administrador puede levantarla,
#                                 escribiendo el motivo, que queda para siempre.
#   PARECIDA  (nombre similar)  → avisa, no bloquea. «Albercas del Valle» y
#                                 «Albercas del Valle del Norte» pueden ser dos
#                                 empresas distintas; bloquear sin salida cuesta
#                                 un cliente legítimo.
#
# Normalizar antes de comparar es lo que hace útil la lista: sin eso,
# ASV180412H23 y ASV-180412-H23 pasarían como clientes distintos.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import secrets
import unicodedata
from difflib import SequenceMatcher

from boto3.dynamodb.conditions import Key

from . import tabla, sin_decimales
from .modelos import iso_mx, legible_mx, limpia_texto

PK_VETO = "VETO"
# Qué tan parecidos tienen que ser dos nombres para avisar. 0.86 deja pasar
# diferencias de una o dos letras sin inundar de avisos falsos.
UMBRAL_PARECIDO = 0.86

# Formas societarias: no distinguen a una empresa de otra, así que estorban
# al comparar. «Albercas del Valle S.A. de C.V.» y «Albercas del Valle S. de R.L.»
# son el mismo nombre para este propósito.
SUFIJOS = [
    "SAPI DE CV", "S A P I DE C V", "SA DE CV", "S A DE C V",
    "S DE RL DE CV", "S DE R L DE C V", "S DE RL", "S DE R L",
    "SC DE RL", "SAS DE CV", "SAS", "SPR DE RL", "SCP",
    "SA", "SC", "AC", "IAP", "SNC", "SCS", "SRL",
]


def sin_acentos(texto: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", str(texto or ""))
                   if unicodedata.category(ch) != "Mn")


def norm_nombre(texto: str) -> str:
    """Nombre comparable: sin acentos, sin puntuación y sin forma societaria."""
    s = sin_acentos(texto).upper()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    s = " ".join(s.split())
    cambio = True
    while cambio:                       # «... SA DE CV SA» también se limpia
        cambio = False
        for suf in SUFIJOS:
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                cambio = True
    return s


def norm_rfc(texto: str) -> str:
    return "".join(ch for ch in str(texto or "").upper() if ch.isalnum())


def norm_correo(texto: str) -> str:
    return str(texto or "").strip().lower()


def norm_tel(texto: str) -> str:
    """Últimos 10 dígitos: así 33 1204 8871 y +52 33 1204 8871 son el mismo."""
    d = "".join(ch for ch in str(texto or "") if ch.isdigit())
    return d[-10:] if len(d) >= 10 else d


def parecido(a: str, b: str) -> float:
    """Qué tan parecidos son dos nombres ya normalizados, de 0 a 1.

    Se miden dos cosas y se toma la mayor, porque cada una atrapa un engaño
    distinto:

      - Parecido de texto: cambiar una letra o un acento.
        «Albercas del Balle» vs «Albercas del Valle».

      - Palabras compartidas: agregarle palabras al nombre para colarse.
        «Albercas y Spas del Valle del Norte» comparte TODAS las palabras del
        vetado, pero el parecido de texto solo da 83 % porque uno es más largo.
        Sin esta segunda medida, ese caso pasaba sin avisar.

    La segunda solo cuenta si el nombre más corto tiene al menos dos palabras:
    con una sola, cualquier «Comercializadora» dispararía avisos.
    """
    if not a or not b:
        return 0.0
    texto = SequenceMatcher(None, a, b).ratio()
    pa, pb = set(a.split()), set(b.split())
    contencion = 0.0
    if pa and pb and min(len(pa), len(pb)) >= 2:
        contencion = len(pa & pb) / min(len(pa), len(pb))
    return max(texto, contencion)


# ── Altas y bajas de la lista ────────────────────────────────────
def listar(solo_activos: bool = True) -> list:
    r = tabla().query(
        KeyConditionExpression=Key("PK").eq(PK_VETO) & Key("SK").begins_with("V#"),
        Limit=500,
    )
    items = sin_decimales(r.get("Items") or [])
    if solo_activos:
        items = [i for i in items if i.get("activo", True)]
    return sorted(items, key=lambda i: i.get("cuando", ""), reverse=True)


def agregar(datos: dict, usuario: dict) -> dict:
    """Mete un cliente a la lista. El motivo es obligatorio: sin él, nadie sabrá
    dentro de un año por qué está ahí."""
    razon = limpia_texto(datos.get("razonSocial"))
    rfc = norm_rfc(datos.get("rfc"))
    motivo = limpia_texto(datos.get("motivo"), area=True)
    if not razon and not rfc:
        raise ValueError("Ponga al menos la razón social o el RFC.")
    if not motivo:
        raise ValueError("Escriba por qué no se le puede dar de alta. "
                         "Sin motivo, nadie sabrá después si sigue vigente.")

    item = {
        "PK": PK_VETO, "SK": "V#" + secrets.token_hex(6),
        "id": secrets.token_hex(6),
        "razonSocial": razon,
        "nombreComercial": limpia_texto(datos.get("nombreComercial")),
        "rfc": rfc,
        "correo": norm_correo(datos.get("correo")),
        "celular": limpia_texto(datos.get("celular")),
        "motivo": motivo,
        "activo": True,
        "quien": usuario.get("correo", ""), "nombreQuien": usuario.get("nombre", ""),
        "cuando": iso_mx(), "cuandoLegible": legible_mx(),
    }
    item["id"] = item["SK"][2:]
    tabla().put_item(Item=item)
    return item


def quitar(veto_id: str, motivo: str, usuario: dict) -> dict:
    """Saca a un cliente de la lista. No se borra: se marca inactivo, con quién
    y por qué, para poder explicarlo después."""
    motivo = limpia_texto(motivo, area=True)
    if not motivo:
        raise ValueError("Escriba por qué se saca de la lista.")
    r = tabla().update_item(
        Key={"PK": PK_VETO, "SK": "V#" + veto_id},
        UpdateExpression=("SET activo=:no, motivoBaja=:m, quienBaja=:q, "
                          "cuandoBaja=:c, cuandoBajaLegible=:cl"),
        ExpressionAttributeValues={
            ":no": False, ":m": motivo, ":q": usuario.get("correo", ""),
            ":c": iso_mx(), ":cl": legible_mx(),
        },
        ReturnValues="ALL_NEW",
    )
    return sin_decimales(r.get("Attributes") or {})


# ── La revisión ──────────────────────────────────────────────────
CAMPOS = [
    ("rfc", "RFC", norm_rfc),
    ("correo", "correo", norm_correo),
    ("celular", "celular", norm_tel),
    ("razonSocial", "razón social", norm_nombre),
    ("nombreComercial", "nombre comercial", norm_nombre),
]


def revisa(datos: dict, lista: list | None = None) -> dict:
    """Compara los datos del prospecto contra la lista de veto.

    Devuelve {"bloqueos": [...], "avisos": [...]}. Un bloqueo es una coincidencia
    exacta ya normalizada; un aviso es un nombre parecido pero no idéntico.
    """
    entradas = listar() if lista is None else lista
    bloqueos, avisos = [], []

    for entrada in entradas:
        for campo, etiqueta, norma in CAMPOS:
            valor = norma(datos.get(campo))
            if not valor:
                continue

            # Un nombre se compara contra los dos nombres de la entrada: una
            # empresa vetada puede venir de vuelta con su nombre comercial.
            if campo in ("razonSocial", "nombreComercial"):
                contra = [(norma(entrada.get("razonSocial")), "razón social"),
                          (norma(entrada.get("nombreComercial")), "nombre comercial")]
            else:
                contra = [(norma(entrada.get(campo)), etiqueta)]

            for referencia, etiqueta_ref in contra:
                if not referencia:
                    continue
                if valor == referencia:
                    bloqueos.append({
                        "campo": campo, "etiqueta": etiqueta, "valor": datos.get(campo),
                        "coincide": "exacta", "contra": etiqueta_ref,
                        "vetado": entrada.get("razonSocial") or entrada.get("rfc"),
                        "motivo": entrada.get("motivo", ""),
                        "desde": entrada.get("cuandoLegible", ""),
                        "vetoId": entrada.get("id", ""),
                    })
                elif campo in ("razonSocial", "nombreComercial"):
                    ratio = parecido(valor, referencia)
                    if ratio >= UMBRAL_PARECIDO:
                        avisos.append({
                            "campo": campo, "etiqueta": etiqueta, "valor": datos.get(campo),
                            "coincide": "parecida", "similitud": round(ratio * 100),
                            "vetado": entrada.get("razonSocial") or entrada.get("rfc"),
                            "motivo": entrada.get("motivo", ""),
                            "desde": entrada.get("cuandoLegible", ""),
                            "vetoId": entrada.get("id", ""),
                        })

    # Un mismo cliente puede chocar por varios campos: se deja uno por campo.
    def unicos(lista_hits):
        vistos, salida = set(), []
        for h in lista_hits:
            llave = (h["vetoId"], h["campo"])
            if llave not in vistos:
                vistos.add(llave)
                salida.append(h)
        return salida

    return {"bloqueos": unicos(bloqueos), "avisos": unicos(avisos)}


def resumen(hits: dict) -> str:
    """Una línea que explica por qué se bloqueó, para el mensaje de error."""
    partes = []
    for b in hits.get("bloqueos", [])[:3]:
        partes.append(f"el {b['etiqueta']} coincide con «{b['vetado']}» ({b['motivo']})")
    return "; ".join(partes)
