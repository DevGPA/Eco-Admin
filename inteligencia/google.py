# inteligencia/google.py — ETAPA 2. Escrito, nunca ejecutado.
# ─────────────────────────────────────────────────────────────────
# ESTADO: sin verificar. Este archivo NO se ha corrido nunca contra Google,
# porque requiere una cuenta de Google Cloud con facturación que GPA todavía no
# tiene. Compila y tiene pruebas con un doble; eso no es lo mismo que funcionar.
#
# Se enciende solo cuando existe la variable GOOGLE_MAPS_KEY. Si falla, el
# orquestador se cae a Amazon Location, que es exactamente para lo que se eligió
# como respaldo.
#
# LO QUE GOOGLE APORTA Y AMAZON NO:
#   - Fotos del negocio publicadas en el mapa  → criterio «exhibe producto»
#   - Imagen de la fachada CON FECHA de captura → criterio «letrero afuera»
#
# DOS LÍMITES VERIFICADOS EN LA DOCUMENTACIÓN, que no se pueden esquivar:
#
#   1. Las fotos NO se descargan ni se guardan. La política dice: «You must not
#      pre-fetch, cache, or store Places API content beyond the allowed
#      exceptions», y la única excepción es el place ID. Por eso aquí solo se
#      guarda el identificador y se arma la liga; la imagen la sirve Google.
#
#   2. Las fotos NO traen fecha. El objeto Photo solo tiene name, widthPx,
#      heightPx, authorAttributions, flagContentUri y googleMapsUri. La
#      validación contra la fecha de inicio del negocio se hace con Street View,
#      que sí publica fecha de captura (y consultarla es gratis).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request

from catalogos import BUSQUEDAS_COMPETENCIA, RADIOS_COMPETENCIA_M
from .criterios import es_competencia

TIEMPO_LIMITE = 8
BASE_PLACES = "https://places.googleapis.com/v1"
BASE_SV = "https://maps.googleapis.com/maps/api/streetview"


def _llave() -> str:
    return os.environ.get("GOOGLE_MAPS_KEY", "")


def _post(ruta: str, cuerpo: dict, campos: str) -> dict:
    pet = urllib.request.Request(
        f"{BASE_PLACES}/{ruta}",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "X-Goog-Api-Key": _llave(),
                 "X-Goog-FieldMask": campos},
        method="POST")
    with urllib.request.urlopen(pet, timeout=TIEMPO_LIMITE) as r:
        return json.loads(r.read().decode("utf-8"))


def _lugar(p: dict) -> dict:
    loc = p.get("location") or {}
    return {
        "id": p.get("id", ""),
        "nombre": (p.get("displayName") or {}).get("text", ""),
        "direccion": p.get("formattedAddress", ""),
        "categorias": p.get("types") or [],
        "lat": loc.get("latitude"), "lon": loc.get("longitude"),
        "calificacion": p.get("rating"),
        "resenas": p.get("userRatingCount"),
        "fotosCrudas": p.get("photos") or [],
    }


class Google:
    nombre = "Google Maps"
    clave = "google"
    da_fotos = True
    da_fachada = True

    def disponible(self) -> bool:
        return bool(_llave())

    def buscar_lugar(self, consulta: str, respaldo: str = "") -> dict | None:
        campos = ("places.id,places.displayName,places.formattedAddress,places.location,"
                  "places.types,places.rating,places.userRatingCount,places.photos")
        for intento in (consulta, respaldo):
            if not (intento or "").strip():
                continue
            r = _post("places:searchText", {"textQuery": intento.strip(), "maxResultCount": 1},
                      campos)
            if r.get("places"):
                return _lugar(r["places"][0])
        return None

    def competencia(self, lat, lon) -> dict:
        campos = ("places.id,places.displayName,places.formattedAddress,places.location,"
                  "places.types")
        salida = {}
        for radio in RADIOS_COMPETENCIA_M:
            hallados = {}
            for frase in BUSQUEDAS_COMPETENCIA:
                r = _post("places:searchText", {
                    "textQuery": frase, "maxResultCount": 20,
                    "locationRestriction": {"circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": float(radio)}},
                }, campos)
                for p in r.get("places") or []:
                    lug = _lugar(p)
                    if lug["id"] and lug["id"] not in hallados and es_competencia(lug):
                        hallados[lug["id"]] = lug
            lista = list(hallados.values())
            salida[str(radio)] = {"total": len(lista), "lugares": lista[:10]}
        return salida

    def fotos(self, lugar: dict) -> list:
        """Solo la liga a la foto que sirve Google, jamás la imagen bajada.

        Guardar el archivo nos sacaría de los términos (ver el encabezado). La
        atribución del autor es obligatoria, así que viaja con cada foto.
        """
        salida = []
        for f in ((lugar or {}).get("fotosCrudas") or [])[:10]:
            nombre = f.get("name", "")
            if not nombre:
                continue
            salida.append({
                "url": (f"{BASE_PLACES}/{nombre}/media"
                        f"?maxWidthPx=800&key={urllib.parse.quote(_llave())}"),
                "atribucion": ", ".join(a.get("displayName", "")
                                        for a in (f.get("authorAttributions") or [])),
                "enGoogle": f.get("googleMapsUri", ""),
            })
        return salida

    def fachada(self, lat, lon) -> dict | None:
        """La fachada, CON su fecha de captura. Consultar la fecha es gratis."""
        consulta = urllib.parse.urlencode({"location": f"{lat},{lon}", "key": _llave()})
        with urllib.request.urlopen(f"{BASE_SV}/metadata?{consulta}",
                                    timeout=TIEMPO_LIMITE) as r:
            meta = json.loads(r.read().decode("utf-8"))
        if meta.get("status") != "OK":
            return None
        imagen = urllib.parse.urlencode({
            "size": "640x400", "location": f"{lat},{lon}", "fov": "80",
            "key": _llave()})
        return {
            # La fecha es la del paso del auto de Google, no la de la foto del
            # negocio: dice «a esta fecha el local se veía así».
            "fecha": meta.get("date", ""),
            "url": f"{BASE_SV}?{imagen}",
            "nota": "Fecha en que Google capturó la calle, no la de apertura del negocio.",
        }

    def mapa(self, lat, lon, competidores: list, ancho=760, alto=440) -> bytes | None:
        marcas = [f"markers=color:red%7C{lat},{lon}"]
        for c in competidores[:20]:
            if c.get("lat") is not None:
                marcas.append(f"markers=color:blue%7Csize:small%7C{c['lat']},{c['lon']}")
        url = ("https://maps.googleapis.com/maps/api/staticmap"
               f"?size={ancho}x{alto}&zoom=16&center={lat},{lon}&"
               + "&".join(marcas) + f"&key={urllib.parse.quote(_llave())}")
        with urllib.request.urlopen(url, timeout=TIEMPO_LIMITE) as r:
            return r.read()
