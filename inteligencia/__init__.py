# inteligencia/ — la ficha comercial del prospecto.
# ─────────────────────────────────────────────────────────────────
# Arma lo que pidió Dirección: dónde está el negocio, qué competencia tiene
# alrededor, qué dice su sitio, y un resumen de qué tan afín es a GPA.
# Ver docs/ESPECIFICACION-inteligencia-comercial.md.
#
# DOS REGLAS QUE MANDAN AQUÍ:
#
# 1. Esto NUNCA bloquea al cliente. Si el mapa no responde, el expediente se
#    envía igual y la ficha queda pendiente. Un servicio de terceros no puede
#    dejar a un cliente atorado a media captura.
#
# 2. El cliente NO ve nada de esto. La ficha vive en campos que la lista blanca
#    de _vista_cliente no incluye, igual que los comentarios del comité.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from db.modelos import iso_mx, legible_mx
from .criterios import arma_criterios, veredicto, normaliza
from .resumen import redacta
from catalogos import GIRO_DIRECTO

from .amazon import Amazon
from .google import Google

TIEMPO_LIMITE = 6          # segundos por llamada a un tercero
MAX_BYTES_WEB = 400_000    # con el <head> basta; no bajamos sitios enteros


def proveedores() -> list:
    """Por orden de preferencia. Google primero cuando esté configurado; Amazon
    siempre detrás, como respaldo, que es justo para lo que se eligió."""
    lista = []
    if os.environ.get("GOOGLE_MAPS_KEY"):
        lista.append(Google())
    lista.append(Amazon())
    return lista


# ═══════════════════════════════════════════════════════════════
# El sitio web declarado
# ═══════════════════════════════════════════════════════════════
def _url_publica(url: str) -> str:
    """Normaliza y rechaza lo que no debe consultarse desde el servidor.

    La dirección la escribe el cliente, así que puede apuntar a donde sea:
    a la red interna de AWS, a localhost o al servicio de metadatos. Pedirla a
    ciegas sería dejarle al cliente un botón para que la Lambda toque cosas
    nuestras. Solo se permiten direcciones públicas.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    partes = urllib.parse.urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return ""
    try:
        for info in socket.getaddrinfo(partes.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return ""
    except (socket.gaierror, ValueError):
        return ""
    return url


_RE_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_RE_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)


def lee_web(url: str) -> dict:
    """Qué dice el sitio del cliente y si habla de nuestro mercado."""
    limpia = _url_publica(url)
    if not limpia:
        return {"url": url, "ok": False, "error": "No es una dirección de internet válida."}
    try:
        pet = urllib.request.Request(limpia, headers={
            "User-Agent": "GPA-AltaClientes/1.0 (+expediente de alta de cliente)"})
        with urllib.request.urlopen(pet, timeout=TIEMPO_LIMITE) as r:
            crudo = r.read(MAX_BYTES_WEB).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return {"url": limpia, "ok": False, "error": f"El sitio respondió {e.code}."}
    except Exception as e:                                  # red, DNS, TLS, tiempo
        return {"url": limpia, "ok": False,
                "error": f"No respondió ({type(e).__name__})."}

    titulo = (_RE_TITULO.search(crudo) or [None, ""])[1] if _RE_TITULO.search(crudo) else ""
    desc = _RE_DESC.search(crudo)
    texto = normaliza(re.sub(r"<[^>]+>", " ", crudo))
    menciona = sorted({p for p in GIRO_DIRECTO if normaliza(p) in texto})
    return {
        "url": limpia, "ok": True,
        "titulo": re.sub(r"\s+", " ", titulo).strip()[:160],
        "descripcion": re.sub(r"\s+", " ", desc.group(1)).strip()[:300] if desc else "",
        "menciona": menciona,
    }


def redes_de(valores: dict) -> list:
    """Las redes que declaró, listas para abrirse. No se leen: Facebook e
    Instagram bloquean la lectura automatizada y sus términos la prohíben."""
    salida = []
    for campo, etiqueta, base in (("facebook", "Facebook", "https://facebook.com/"),
                                  ("instagram", "Instagram", "https://instagram.com/")):
        crudo = str((valores or {}).get(campo) or "").strip()
        if not crudo:
            continue
        if crudo.lower().startswith(("http://", "https://")):
            url = crudo
        else:
            url = base + crudo.lstrip("@/")
        salida.append({"red": etiqueta, "url": url, "declarado": crudo})
    return salida


# ═══════════════════════════════════════════════════════════════
# La ficha
# ═══════════════════════════════════════════════════════════════
def arma_ficha(caso: dict) -> dict:
    """Junta todo. Nunca lanza: lo que falle se reporta como aviso dentro de la ficha."""
    valores = caso.get("valores") or {}
    consulta = str(valores.get("mapa_url") or "").strip()
    respaldo = ", ".join(x for x in (valores.get("calle"), valores.get("colonia"),
                                     valores.get("ciudad"), valores.get("estado_dom")) if x)

    ficha = {
        "cuando": iso_mx(), "cuandoLegible": legible_mx(),
        "consulta": consulta, "respaldo": respaldo,
        "inicioOps": str(valores.get("inicio_ops") or ""),
        "proveedor": "", "lugar": None, "competencia": {},
        "fotos": [], "fotosDisponibles": None, "fachada": None,
        "web": {}, "redes": redes_de(valores),
        "criterios": [], "conteo": {}, "resumen": "", "avisos": [],
    }

    if not consulta and not respaldo:
        ficha["avisos"].append("El cliente no capturó la ubicación de su negocio.")

    for prov in proveedores():
        try:
            if not prov.disponible():
                continue
            ficha["proveedor"] = prov.nombre
            ficha["fotosDisponibles"] = prov.da_fotos
            lugar = prov.buscar_lugar(consulta, respaldo)
            if not lugar:
                ficha["avisos"].append(
                    f"{prov.nombre} no encontró el negocio con lo que capturó el cliente.")
                break
            ficha["lugar"] = lugar
            if lugar.get("lat") is not None:
                ficha["competencia"] = prov.competencia(lugar["lat"], lugar["lon"])
            if prov.da_fotos:
                ficha["fotos"] = prov.fotos(lugar)
            if prov.da_fachada and lugar.get("lat") is not None:
                ficha["fachada"] = prov.fachada(lugar["lat"], lugar["lon"])
            break
        except Exception as e:
            # Se intenta con el siguiente proveedor: Amazon es el respaldo de Google.
            ficha["avisos"].append(f"{prov.nombre} falló ({type(e).__name__}).")
            ficha["proveedor"] = ""
            continue

    if not ficha["proveedor"]:
        ficha["avisos"].append("Ningún proveedor de mapas respondió. La ficha quedó "
                               "incompleta; se puede volver a armar desde el expediente.")

    web = str(valores.get("web") or "").strip()
    if web:
        ficha["web"] = lee_web(web)

    ficha["criterios"] = arma_criterios(ficha, caso)
    ficha["conteo"] = veredicto(ficha["criterios"])

    # El párrafo va al final, cuando ya están los cinco criterios: el modelo
    # redacta sobre lo medido, no sobre datos a medias.
    ficha["resumen"], mas = redacta(ficha, caso)
    ficha["avisos"].extend(mas)
    ficha["resumenEsBorrador"] = True
    return ficha


def url_foto_de(ficha: dict, indice: int) -> str:
    """La liga de una foto del local, resuelta al momento de verla.

    El índice se busca DENTRO de la ficha guardada: nunca se acepta una
    referencia que venga de la pantalla. Si se aceptara, cualquiera con sesión
    podría hacer que gastáramos nuestra cuota trayendo fotos de donde quisiera.
    """
    fotos = (ficha or {}).get("fotos") or []
    if not (0 <= int(indice) < len(fotos)):
        return ""
    ref = fotos[int(indice)].get("ref", "")
    for prov in proveedores():
        try:
            if prov.disponible():
                return prov.url_foto(ref)
        except Exception:
            continue
    return ""


def imagen_fachada_de(ficha: dict) -> bytes | None:
    """Los bytes de la fachada. La llave de Google nunca sale del servidor."""
    fachada = (ficha or {}).get("fachada") or {}
    if fachada.get("lat") is None:
        return None
    for prov in proveedores():
        try:
            if prov.disponible():
                return prov.imagen_fachada(fachada["lat"], fachada["lon"])
        except Exception:
            continue
    return None


def mapa_de(ficha: dict) -> bytes | None:
    """El PNG del mapa. Se genera al verlo, no se guarda: cuesta centavos y así
    nunca se muestra un mapa viejo de una zona que ya cambió."""
    lugar = (ficha or {}).get("lugar") or {}
    if lugar.get("lat") is None:
        return None
    # Sin repetir: el competidor que cae dentro de los 150 m también está en los
    # 500 m, y se dibujaría dos veces sobre el mismo punto.
    vecinos = {}
    for datos in (ficha.get("competencia") or {}).values():
        for lug in datos.get("lugares") or []:
            vecinos.setdefault(lug.get("id") or lug.get("nombre"), lug)
    vecinos = list(vecinos.values())
    for prov in proveedores():
        try:
            if prov.disponible():
                return prov.mapa(lugar["lat"], lugar["lon"], vecinos)
        except Exception:
            continue
    return None
