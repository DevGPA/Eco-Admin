# cotizador.py — Cotizador de vuelos — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────
# Presenta las mejores opciones de vuelo para una solicitud de viáticos.
# Criterio acordado: DIRECTO primero → PRECIO más bajo → HORARIO cómodo.
#
# Diseñado para que el ORIGEN de los precios sea intercambiable:
#   - ProveedorManual : Compras captura las opciones a mano (arranque).
#   - ProveedorDuffel : búsqueda automática vía api.duffel.com
#                       (Volaris y Aeroméxico; Viva aún no está en Duffel).
#     Se activa solo con la variable de entorno DUFFEL_TOKEN.
#
# El ranking es el mismo venga de donde venga la opción, de modo que
# pasar de manual → Duffel (→ otro proveedor) no cambia el flujo.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import json
import os
import logging
import urllib.request
import urllib.error

logger = logging.getLogger()

DUFFEL_TOKEN = os.environ.get("DUFFEL_TOKEN", "")
DUFFEL_URL   = "https://api.duffel.com/air/offer_requests?return_offers=true"
MAX_OFERTAS  = 40          # ofertas del proveedor que vale la pena rankear
HORA_COMODA  = (6, 21)     # salida "cómoda": entre 06:00 y 21:59


# ── Modelo de una opción de vuelo ────────────────────────────────
def normalizar_opcion(d: dict, fuente: str = "manual") -> dict:
    """Lleva una opción (manual o de API) al modelo común del sistema."""
    try:
        precio = round(float(d.get("precio") or 0), 2)
    except (TypeError, ValueError):
        precio = 0.0
    escalas = d.get("escalas")
    if escalas is None:
        escalas = 0 if d.get("directo", True) else 1
    return {
        "aerolinea": (d.get("aerolinea") or "").strip() or "—",
        "vuelo":     (d.get("vuelo") or "").strip(),
        "origen":    (d.get("origen") or "").strip().upper(),
        "destino":   (d.get("destino") or "").strip().upper(),
        "salida":    (d.get("salida") or "").strip(),   # "HH:MM" o ISO
        "llegada":   (d.get("llegada") or "").strip(),
        "escalas":   int(escalas),
        "directo":   int(escalas) == 0,
        "equipaje":  (d.get("equipaje") or "").strip(),
        "precio":    precio,
        "moneda":    (d.get("moneda") or "MXN").strip().upper(),
        "fuente":    fuente,
    }


def _hora(s: str) -> int | None:
    """Hora de salida (0-23) a partir de 'HH:MM' o ISO '...T HH:MM...'."""
    try:
        hhmm = s.split("T")[1] if "T" in s else s
        h = int(hhmm.split(":")[0])
        return h if 0 <= h <= 23 else None
    except (IndexError, ValueError, AttributeError):
        return None


# ── Ranking: directo → precio → horario ──────────────────────────
def rankear(opciones: list, limite: int = 3) -> list:
    """
    Ordena las opciones con el criterio acordado y anota por qué.
    Devuelve TODAS ordenadas; las primeras `limite` traen top=True y
    la primera recomendada=True.
    """
    ops = [normalizar_opcion(o, o.get("fuente", "manual")) for o in opciones
           if o and (o.get("precio") or 0)]

    def llave(o):
        h = _hora(o["salida"])
        incomodo = 0 if (h is not None and HORA_COMODA[0] <= h <= HORA_COMODA[1]) else 1
        return (o["escalas"], o["precio"], incomodo, o["salida"] or "~")

    ops.sort(key=llave)

    mas_barata = min((o["precio"] for o in ops), default=0)
    for i, o in enumerate(ops):
        h = _hora(o["salida"])
        motivos = []
        motivos.append("Directo" if o["directo"] else f"{o['escalas']} escala(s)")
        if o["precio"] == mas_barata:
            motivos.append("Más barata")
        if h is not None and HORA_COMODA[0] <= h <= HORA_COMODA[1]:
            motivos.append("Horario cómodo")
        o["rank"] = i + 1
        o["top"] = i < limite
        o["recomendada"] = i == 0
        o["motivos"] = motivos
    return ops


# ── Proveedores ──────────────────────────────────────────────────
class ProveedorManual:
    """Sin búsqueda automática: Compras captura las opciones a mano."""
    nombre = "manual"

    def buscar(self, origen, destino, fecha, regreso=None):
        return {"opciones": [],
                "aviso": ("Sin proveedor automático configurado: captura las "
                          "opciones manualmente (Volaris / Viva / Aeroméxico).")}


class ProveedorDuffel:
    """Búsqueda automática en Duffel (cubre Volaris y Aeroméxico; Viva no)."""
    nombre = "duffel"

    def buscar(self, origen, destino, fecha, regreso=None):
        slices = [{"origin": origen, "destination": destino, "departure_date": fecha}]
        if regreso:
            slices.append({"origin": destino, "destination": origen,
                           "departure_date": regreso})
        cuerpo = json.dumps({"data": {
            "slices": slices,
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }}).encode()

        req = urllib.request.Request(DUFFEL_URL, data=cuerpo, method="POST", headers={
            "Authorization": f"Bearer {DUFFEL_TOKEN}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detalle = e.read().decode()[:400]
            logger.warning("Duffel HTTP %s: %s", e.code, detalle)
            raise ValueError(f"El proveedor de vuelos respondió {e.code}. "
                             "Captura las opciones manualmente.")
        except Exception as e:
            logger.warning("Duffel sin respuesta: %s", e)
            raise ValueError("No se pudo consultar el proveedor de vuelos. "
                             "Captura las opciones manualmente.")

        ofertas = (data.get("data") or {}).get("offers") or []
        opciones = []
        for of in ofertas[:MAX_OFERTAS]:
            try:
                opciones.append(self._a_opcion(of))
            except Exception:      # una oferta rara no debe tirar la búsqueda
                continue
        return {"opciones": opciones, "aviso": ""}

    @staticmethod
    def _a_opcion(of: dict) -> dict:
        sl = of["slices"][0]                     # tramo de ida
        segs = sl["segments"]
        vuelos = "/".join(f"{s['marketing_carrier'].get('iata_code','')}"
                          f"{s.get('marketing_carrier_flight_number','')}" for s in segs)
        return normalizar_opcion({
            "aerolinea": (of.get("owner") or {}).get("name", "—"),
            "vuelo":     vuelos,
            "origen":    (segs[0].get("origin") or {}).get("iata_code", ""),
            "destino":   (segs[-1].get("destination") or {}).get("iata_code", ""),
            "salida":    segs[0].get("departing_at", ""),
            "llegada":   segs[-1].get("arriving_at", ""),
            "escalas":   len(segs) - 1,
            "precio":    of.get("total_amount"),
            "moneda":    of.get("total_currency", "MXN"),
        }, fuente="duffel")


def proveedor_activo():
    return ProveedorDuffel() if DUFFEL_TOKEN else ProveedorManual()


# ── Punto de entrada del handler ─────────────────────────────────
def buscar_vuelos(origen: str, destino: str, fecha: str, regreso: str = "") -> dict:
    """Busca con el proveedor activo y devuelve las opciones ya rankeadas."""
    if not origen or not destino or not fecha:
        raise ValueError("Faltan datos de búsqueda (origen, destino y fecha)")
    prov = proveedor_activo()
    res = prov.buscar(origen.upper(), destino.upper(), fecha, regreso or None)
    return {"proveedor": prov.nombre,
            "opciones": rankear(res["opciones"]),
            "aviso": res.get("aviso", "")}
