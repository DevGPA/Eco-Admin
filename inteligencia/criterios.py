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

from catalogos import GIRO_DIRECTO, GIRO_INDIRECTO, GIRO_USUARIO_FINAL

SI, NO, PENDIENTE = "si", "no", "pendiente"


def normaliza(texto: str) -> str:
    """Texto comparable: sin acentos, minúsculas, sin puntuación."""
    s = "".join(ch for ch in unicodedata.normalize("NFD", str(texto or ""))
                if unicodedata.category(ch) != "Mn").lower()
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", s).split())


def afinidad(nombre: str, categorias: list | None = None, extra: str = "") -> dict:
    """¿Este negocio es de lo nuestro, y en qué papel?

    GPA vende de negocio a negocio, así que no basta con que el prospecto tenga
    que ver con albercas: importa si REVENDE o si solo consume. Un hotel con
    alberca menciona todas nuestras palabras y no es un distribuidor.

    Se miran el nombre, las categorías del mapa y el giro que declaró el
    cliente. Cualquiera de los tres delata al negocio; pedir que coincidan los
    tres dejaría fuera a la mitad.

    Devuelve «tipo»:
      distribuidor  — vende lo nuestro. Es el cliente que buscamos.
      usuario_final — lo usa pero no lo revende (hotel, gimnasio, balneario).
      indirecto     — puede venderlo entre otras cosas (ferretería, plomería).
      ninguno       — nada que ver.
    """
    texto = normaliza(" ".join([nombre or "", " ".join(categorias or []), extra or ""]))
    directas = sorted({p for p in GIRO_DIRECTO if normaliza(p) in texto})
    indirectas = sorted({p for p in GIRO_INDIRECTO if normaliza(p) in texto})
    finales = sorted({p for p in GIRO_USUARIO_FINAL if normaliza(p) in texto})

    if finales:
        # Manda sobre lo demás: «Hotel Real con Alberca» nombra nuestro mercado,
        # pero sigue siendo un hotel.
        tipo = "usuario_final"
    elif directas:
        tipo = "distribuidor"
    elif indirectas:
        tipo = "indirecto"
    else:
        tipo = "ninguno"
    return {"tipo": tipo, "directas": directas, "indirectas": indirectas,
            "finales": finales}


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
    """Solo cuenta como competencia del prospecto quien VENDE lo que él vendería.

    Buscar «albercas» devuelve también hoteles con alberca, gimnasios con spa y
    balnearios. Nombran nuestro mercado pero no le compiten a un distribuidor:
    si se cuentan, el número deja de servir para decidir.
    """
    cats = nombres_categoria(lugar.get("categorias"))
    return afinidad(lugar.get("nombre", ""), cats)["tipo"] == "distribuidor"


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
    fuente_lugar = f"Nombre y categorías del lugar ({proveedor})"
    if lugar:
        af = afinidad(lugar.get("nombre", ""), nombres_categoria(lugar.get("categorias")),
                      caso.get("giro", ""))
        if af["tipo"] == "distribuidor":
            crit.append(_criterio(
                "afinidad", "Vende lo que vendemos", SI,
                "Es de nuestro mercado: " + ", ".join(af["directas"][:4]),
                fuente_lugar))
        elif af["tipo"] == "usuario_final":
            crit.append(_criterio(
                "afinidad", "Vende lo que vendemos", NO,
                f"Parece usuario final, no distribuidor ({', '.join(af['finales'][:3])}). "
                "Tiene alberca o sistema de agua, pero no revende. Puede comprarnos para "
                "su propio uso; darlo de alta como distribuidor es otra conversación.",
                fuente_lugar))
        elif af["tipo"] == "indirecto":
            crit.append(_criterio(
                "afinidad", "Vende lo que vendemos", PENDIENTE,
                "Vende de lo nuestro entre otras cosas (" +
                ", ".join(af["indirectas"][:3]) + "). Hay que preguntarle qué tanto "
                "peso tiene nuestra línea en su venta.",
                fuente_lugar))
        else:
            crit.append(_criterio(
                "afinidad", "Vende lo que vendemos", NO,
                f"Ni el nombre ni el giro del negocio («{lugar.get('nombre', '')}») "
                "mencionan nada de nuestro mercado.",
                fuente_lugar))
    else:
        crit.append(_criterio(
            "afinidad", "Vende lo que vendemos", PENDIENTE,
            "No se pudo ubicar el negocio en el mapa, así que no hay giro que revisar.",
            "—"))

    # 2 · Exhibe producto (necesita fotos: etapa 2)
    fotos = ficha.get("fotos") or []
    if fotos:
        crit.append(_criterio(
            "exhibe", "Exhibe producto en el local", SI,
            f"{len(fotos)} foto(s) del local publicadas en el mapa. Ábralas y vea si "
            "tiene mostrador o exhibición: un distribuidor que exhibe, vende.",
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

    # 5 · Mercado alrededor
    #
    # En B2B esto NO se lee como «entre menos competencia, mejor». Que haya
    # distribuidores de nuestro giro en la zona significa que ahí hay demanda;
    # una zona vacía puede ser territorio virgen o puede no tener mercado. Por
    # eso se reporta el número con sus dos lecturas y no se declara ganador:
    # quien conoce la plaza decide, no el sistema.
    comp = ficha.get("competencia") or {}
    if comp:
        radios = sorted(comp, key=int)
        cerca, lejos = radios[0], radios[-1]
        n_cerca = comp[cerca]["total"]
        n_lejos = comp[lejos]["total"]
        cuenta = " · ".join(f"{comp[r]['total']} a {r} m" for r in radios)
        if n_lejos == 0:
            estado = PENDIENTE
            lectura = ("No hay un solo distribuidor de nuestro giro en la zona. "
                       "Puede ser territorio virgen o puede ser que ahí no haya mercado; "
                       "eso lo sabe quien conoce la plaza.")
        elif n_cerca == 0:
            estado = SI
            lectura = ("Hay mercado en la zona y ningún competidor pegado al local.")
        else:
            estado = PENDIENTE
            lectura = (f"Tiene {n_cerca} competidor(es) a menos de {cerca} m. "
                       "Puede significar demanda concentrada o plaza disputada; "
                       "conviene revisarlo con el vendedor de la zona.")
        crit.append(_criterio(
            "competencia", "Mercado y competencia alrededor", estado,
            f"Distribuidores de nuestro giro cerca: {cuenta}. {lectura}",
            f"Búsqueda por giro en el radio ({proveedor})"))
    else:
        crit.append(_criterio(
            "competencia", "Mercado y competencia alrededor", PENDIENTE,
            "No se pudo medir: falta ubicar el negocio en el mapa.",
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
