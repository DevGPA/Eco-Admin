# inteligencia/criterios.py — qué tan afín es un prospecto al mercado de GPA.
# ─────────────────────────────────────────────────────────────────
# Lógica pura: no habla con ningún servicio. Recibe lo que trajo el proveedor
# de mapas y devuelve los cinco criterios del punto 5 de la especificación.
#
# Regla que manda aquí: un dato que no se pudo comprobar se reporta como
# PENDIENTE, nunca como «no». No es lo mismo «el local no exhibe producto» que
# «no pudimos ver si exhibe producto», y confundirlos le costaría un cliente
# bueno a GPA.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import re
import unicodedata

from catalogos import GIRO_DIRECTO, GIRO_INDIRECTO, GIRO_NO_COMPETENCIA

SI, NO, PENDIENTE = "si", "no", "pendiente"


def normaliza(texto: str) -> str:
    """Texto comparable: sin acentos, minúsculas, sin puntuación."""
    s = "".join(ch for ch in unicodedata.normalize("NFD", str(texto or ""))
                if unicodedata.category(ch) != "Mn").lower()
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", s).split())


def afinidad(nombre: str, categorias: list | None = None, extra: str = "") -> dict:
    """¿Este negocio es de lo nuestro?

    Se miran el nombre del lugar, sus categorías según el mapa y lo que el
    cliente declaró de su propio giro. Cualquiera de los tres delata a un
    negocio de albercas; pedir que coincidan los tres dejaría fuera a la mitad.
    """
    texto = normaliza(" ".join([nombre or "", " ".join(categorias or []), extra or ""]))
    directas = sorted({p for p in GIRO_DIRECTO if normaliza(p) in texto})
    indirectas = sorted({p for p in GIRO_INDIRECTO if normaliza(p) in texto})
    if directas:
        nivel = "directo"
    elif indirectas:
        nivel = "indirecto"
    else:
        nivel = "ninguno"
    return {"nivel": nivel, "directas": directas, "indirectas": indirectas}


def nombres_categoria(categorias) -> list:
    """Las categorías llegan como texto o como diccionario según el proveedor.

    Amazon las entrega ya convertidas a texto; Google, y la respuesta cruda de
    Amazon, las traen como {"Name": ...}. Aceptar las dos evita que el conteo de
    competencia se caiga callado con un proveedor y funcione con el otro.
    """
    salida = []
    for c in categorias or []:
        if isinstance(c, str):
            salida.append(c)
        elif isinstance(c, dict):
            salida.append(c.get("Name") or c.get("nombre") or "")
    return [x for x in salida if x]


def es_competencia(lugar: dict) -> bool:
    """Un resultado del mapa solo cuenta como competencia si VENDE lo que vendemos.

    Buscar «albercas» devuelve también hoteles con alberca, gimnasios con spa y
    balnearios. Nombran nuestro mercado pero no nos compiten: si se cuentan, el
    número deja de servir para decidir. Se descartan por su giro, no por su nombre.
    """
    cats = nombres_categoria(lugar.get("categorias"))
    texto = normaliza(" ".join([lugar.get("nombre", ""), " ".join(cats)]))
    if any(normaliza(p) in texto for p in GIRO_NO_COMPETENCIA):
        return False
    return afinidad(lugar.get("nombre", ""), cats)["nivel"] == "directo"


# ── Los cinco criterios ──────────────────────────────────────────
def _criterio(cid, titulo, estado, detalle, fuente):
    return {"id": cid, "titulo": titulo, "estado": estado,
            "detalle": detalle, "fuente": fuente}


def arma_criterios(ficha: dict, caso: dict) -> list:
    """Los cinco criterios del punto 5, cada uno con su evidencia y su fuente."""
    lugar = ficha.get("lugar") or {}
    proveedor = ficha.get("proveedor", "")
    crit = []

    # 1 · Afinidad de giro
    if lugar:
        af = afinidad(lugar.get("nombre", ""), nombres_categoria(lugar.get("categorias")),
                      caso.get("giro", ""))
        if af["nivel"] == "directo":
            crit.append(_criterio(
                "afinidad", "Afinidad de giro", SI,
                "Es de nuestro mercado: " + ", ".join(af["directas"][:4]),
                f"Nombre y categorías del lugar ({proveedor})"))
        elif af["nivel"] == "indirecto":
            crit.append(_criterio(
                "afinidad", "Afinidad de giro", PENDIENTE,
                "Afinidad indirecta (" + ", ".join(af["indirectas"][:3]) +
                "). Puede vender lo nuestro entre otras cosas; hay que preguntarle.",
                f"Nombre y categorías del lugar ({proveedor})"))
        else:
            crit.append(_criterio(
                "afinidad", "Afinidad de giro", NO,
                f"Ni el nombre ni el giro del negocio («{lugar.get('nombre', '')}») "
                "mencionan nada de nuestro mercado.",
                f"Nombre y categorías del lugar ({proveedor})"))
    else:
        crit.append(_criterio(
            "afinidad", "Afinidad de giro", PENDIENTE,
            "No se pudo ubicar el negocio en el mapa, así que no hay giro que revisar.",
            "—"))

    # 2 · Exhibe producto (necesita fotos: etapa 2)
    fotos = ficha.get("fotos") or []
    if fotos:
        crit.append(_criterio(
            "exhibe", "Exhibe producto en el local", SI,
            f"{len(fotos)} foto(s) del local publicadas en el mapa.",
            f"Fotos del lugar ({proveedor})"))
    elif ficha.get("fotosDisponibles") is False:
        crit.append(_criterio(
            "exhibe", "Exhibe producto en el local", PENDIENTE,
            "El proveedor actual no publica fotos de negocios. Se resuelve al "
            "conectar Google (etapa 2). Mientras, valen las fotos que sube el cliente.",
            "—"))
    else:
        crit.append(_criterio(
            "exhibe", "Exhibe producto en el local", PENDIENTE,
            "El negocio no tiene fotos publicadas en el mapa.",
            f"Fotos del lugar ({proveedor})"))

    # 3 · Letrero afuera (deseable, necesita imagen de fachada: etapa 2)
    fachada = ficha.get("fachada")
    if fachada:
        crit.append(_criterio(
            "letrero", "Letrero alusivo afuera (deseable)", PENDIENTE,
            f"Hay imagen de la fachada, de {fachada.get('fecha', 'fecha desconocida')}. "
            "Ábrala y vea si el letrero menciona nuestro mercado.",
            f"Imagen de calle ({proveedor})"))
    else:
        crit.append(_criterio(
            "letrero", "Letrero alusivo afuera (deseable)", PENDIENTE,
            "No hay imagen de la fachada. Se resuelve al conectar Google (etapa 2), "
            "o con la foto del negocio que sube el cliente.",
            "—"))

    # 4 · Presencia digital
    web = ficha.get("web") or {}
    redes = [r for r in (ficha.get("redes") or []) if r.get("url")]
    if web.get("ok") and web.get("menciona"):
        crit.append(_criterio(
            "digital", "Presencia digital", SI,
            f"Su sitio habla de nuestro mercado: {', '.join(web['menciona'][:4])}." +
            (f" Además declara {len(redes)} red(es) social(es)." if redes else ""),
            web.get("url", "")))
    elif web.get("ok"):
        crit.append(_criterio(
            "digital", "Presencia digital", PENDIENTE,
            "Su sitio responde, pero no menciona nada de nuestro mercado. "
            "Conviene abrirlo." + (f" Declara {len(redes)} red(es)." if redes else ""),
            web.get("url", "")))
    elif redes:
        crit.append(_criterio(
            "digital", "Presencia digital", PENDIENTE,
            f"Declaró {len(redes)} red(es) social(es). Facebook e Instagram no se "
            "pueden leer automáticamente: ábralas usted.",
            "Ligas declaradas por el cliente"))
    else:
        crit.append(_criterio(
            "digital", "Presencia digital", NO,
            "No declaró sitio web ni redes sociales." +
            (f" Su sitio no respondió: {web.get('error')}" if web.get("error") else ""),
            "Formulario del cliente"))

    # 5 · Competencia alrededor
    comp = ficha.get("competencia") or {}
    if comp:
        partes = [f"{comp[r]['total']} a {r} m" for r in sorted(comp, key=int)]
        cercanos = comp.get(str(min(int(r) for r in comp)), {}).get("total", 0)
        crit.append(_criterio(
            "competencia", "Competencia alrededor",
            NO if cercanos else SI,
            "Negocios de nuestro giro cerca: " + " · ".join(partes) + ". " +
            ("Tiene competencia pegada." if cercanos else
             "No hay competencia inmediata."),
            f"Búsqueda por giro en el radio ({proveedor})"))
    else:
        crit.append(_criterio(
            "competencia", "Competencia alrededor", PENDIENTE,
            "No se pudo medir la competencia: falta ubicar el negocio en el mapa.",
            "—"))

    return crit


def veredicto(criterios: list) -> dict:
    """Un conteo, no una decisión. Quien autoriza lee la evidencia, no el número."""
    return {
        "favorables": sum(1 for c in criterios if c["estado"] == SI),
        "contrarios": sum(1 for c in criterios if c["estado"] == NO),
        "pendientes": sum(1 for c in criterios if c["estado"] == PENDIENTE),
        "total": len(criterios),
    }
