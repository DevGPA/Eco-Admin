# inteligencia/amazon.py — el prospecto visto con Amazon Location Service.
# ─────────────────────────────────────────────────────────────────
# Se eligió como proveedor de arranque porque vive DENTRO de la cuenta de AWS
# que este proyecto ya usa: sin proveedor nuevo, sin tarjeta nueva, y con el
# mismo rol de IAM de la Lambda. Cuesta centavos (geocodificación $0.50 y mapas
# $0.70 por cada MIL peticiones).
#
# Lo que NO da, y por eso existe la etapa 2 con Google: fotos del negocio e
# imagen de la fachada.
#
# Guardar resultados SÍ está permitido aquí, a diferencia de Google: se declara
# con IntendedUse="Storage" y se paga la tarifa correspondiente.
#
# OJO con el orden de las coordenadas: AWS las pide [longitud, latitud], al
# revés de como las escribe todo el mundo. Se aísla en _pos() y _lonlat().
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import re

import boto3

from catalogos import BUSQUEDAS_COMPETENCIA, RADIOS_COMPETENCIA_M
from .criterios import es_competencia

_PLACES = _MAPS = None
# Se declara que los resultados se guardan en el expediente. Es la tarifa
# correcta y además lo que de verdad hacemos: la ficha queda como evidencia.
USO = "Storage"


def _places():
    global _PLACES
    if _PLACES is None:
        _PLACES = boto3.client("geo-places", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _PLACES


def _mapas():
    global _MAPS
    if _MAPS is None:
        _MAPS = boto3.client("geo-maps", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _MAPS


def _lonlat(lat, lon) -> list:
    """AWS pide [longitud, latitud]. Invertirlas manda la búsqueda a otro país."""
    return [float(lon), float(lat)]


def _pos(item: dict) -> tuple:
    """Devuelve (lat, lon) desde el Position de AWS, que viene [lon, lat]."""
    p = item.get("Position") or []
    return (float(p[1]), float(p[0])) if len(p) >= 2 else (None, None)


def _lugar(item: dict) -> dict:
    lat, lon = _pos(item)
    return {
        "id": item.get("PlaceId", ""),
        "nombre": item.get("Title", ""),
        "direccion": (item.get("Address") or {}).get("Label", ""),
        "categorias": [c.get("Name", "") for c in (item.get("Categories") or [])],
        "lat": lat, "lon": lon,
        "distancia": item.get("Distance"),
    }


class Amazon:
    """Proveedor de arranque. No tiene fotos ni fachada; lo dice, no lo finge."""

    nombre = "Amazon Location"
    clave = "amazon"
    da_fotos = False
    da_fachada = False

    def disponible(self) -> bool:
        # No lleva llave: usa el rol de IAM de la Lambda. Si falta el permiso,
        # la llamada falla y el orquestador lo reporta como aviso.
        return True

    # ── 1 · Ubicar el negocio ──
    def buscar_lugar(self, consulta: str, respaldo: str = "") -> dict | None:
        """Resuelve lo que capturó el cliente: una liga de Google Maps o una dirección.

        De una liga de Google no se puede sacar el lugar directamente, pero casi
        siempre trae las coordenadas. Si las trae, se busca por ahí; si no, se
        cae al domicilio fiscal que ya capturó, que es mejor que nada.
        """
        consulta = (consulta or "").strip()
        coords = _coords_de_liga(consulta)
        if coords:
            item = self._cerca_de(*coords)
            if item:
                return item
        texto = consulta if not consulta.lower().startswith("http") else ""
        for intento in (texto, respaldo):
            if not (intento or "").strip():
                continue
            r = _places().search_text(QueryText=intento.strip(), MaxResults=1,
                                      IntendedUse=USO)
            items = r.get("ResultItems") or []
            if items:
                return _lugar(items[0])
        return None

    def _cerca_de(self, lat, lon) -> dict | None:
        r = _places().reverse_geocode(QueryPosition=_lonlat(lat, lon), MaxResults=1,
                                      IntendedUse=USO)
        items = r.get("ResultItems") or []
        return _lugar(items[0]) if items else None

    # ── 4 · Competencia alrededor ──
    def competencia(self, lat, lon) -> dict:
        """Cuántos negocios de nuestro giro hay en cada radio, y cuáles.

        Se busca por frase (albercas, purificadora…) dentro de un círculo, y
        después se filtra: buscar «albercas» también devuelve hoteles con alberca.
        """
        salida = {}
        for radio in RADIOS_COMPETENCIA_M:
            encontrados = {}
            for frase in BUSQUEDAS_COMPETENCIA:
                r = _places().search_text(
                    QueryText=frase, MaxResults=20, IntendedUse=USO,
                    Filter={"Circle": {"Center": _lonlat(lat, lon), "Radius": radio}})
                for item in r.get("ResultItems") or []:
                    lug = _lugar(item)
                    if lug["id"] and lug["id"] not in encontrados and es_competencia(lug):
                        encontrados[lug["id"]] = lug
            lista = sorted(encontrados.values(), key=lambda x: x.get("distancia") or 0)
            salida[str(radio)] = {"total": len(lista), "lugares": lista[:10]}
        return salida

    # ── 4b · El mapa con los marcadores ──
    def mapa(self, lat, lon, competidores: list, ancho=760, alto=440) -> bytes | None:
        """PNG con el prospecto y su competencia marcada.

        No se guarda: se genera cuando alguien abre la ficha. Cuesta $0.0007 y
        así nunca se muestra un mapa viejo de una zona que ya cambió.
        """
        marcas = [{
            "type": "Feature",
            "properties": {"tipo": "prospecto"},
            "geometry": {"type": "Point", "coordinates": _lonlat(lat, lon)},
        }]
        for c in competidores:
            if c.get("lat") is None:
                continue
            marcas.append({
                "type": "Feature",
                "properties": {"tipo": "competencia", "nombre": c.get("nombre", "")},
                "geometry": {"type": "Point", "coordinates": _lonlat(c["lat"], c["lon"])},
            })
        r = _mapas().get_static_map(
            FileName="mapa",
            Center=f"{float(lon)},{float(lat)}",
            Width=ancho, Height=alto, Zoom=16.0, Style="Standard",
            GeoJsonOverlay=json.dumps({"type": "FeatureCollection", "features": marcas}),
        )
        blob = r.get("Blob")
        return blob.read() if hasattr(blob, "read") else blob

    # ── Lo que este proveedor no tiene, dicho sin rodeos ──
    def fotos(self, lugar: dict) -> list:
        return []

    def url_foto(self, ref: str, ancho: int = 800) -> str:
        return ""

    def fachada(self, lat, lon) -> dict | None:
        return None

    def imagen_fachada(self, lat, lon, ancho=640, alto=400) -> bytes | None:
        return None


_RE_COORDS = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
_RE_BANG = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")


def _coords_de_liga(url: str) -> tuple | None:
    """Saca latitud y longitud de una liga de Google Maps, si las trae.

    Las ligas largas traen «@lat,lon» o «!3dlat!4dlon». Las cortas
    (maps.app.goo.gl) no traen nada hasta que se siguen, y seguirlas desde la
    Lambda es una petición a un tercero que puede tardar o fallar; por eso, si
    no hay coordenadas, se resuelve por la dirección y ya.
    """
    if not url or not url.lower().startswith("http"):
        return None
    for patron in (_RE_BANG, _RE_COORDS):
        m = patron.search(url)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
    return None
