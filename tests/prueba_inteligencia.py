# tests/prueba_inteligencia.py — ejecuta la ficha comercial REAL.
# Uso:  PYTHONUTF8=1 python tests/prueba_inteligencia.py
# ─────────────────────────────────────────────────────────────────
# Amazon Location se sustituye por un doble que devuelve las MISMAS formas que
# la API de verdad (verificadas en el modelo de boto3: ResultItems con PlaceId,
# Title, Address.Label, Position en [lon, lat] y Categories[].Name).
#
# Lo que esto NO prueba: que AWS conteste, que el rol de IAM tenga los permisos,
# ni que Google funcione — ese proveedor no se ha ejecutado nunca.
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DYNAMO_TABLE", "prueba")
os.environ.setdefault("DOCS_BUCKET", "prueba")
os.environ.setdefault("USER_POOL_ID", "prueba")
os.environ.pop("GOOGLE_MAPS_KEY", None)        # etapa 1: sin Google

import inteligencia as I                                    # noqa: E402
import inteligencia.amazon as A                             # noqa: E402
from inteligencia.criterios import afinidad, es_competencia  # noqa: E402

FALLAS, TOTAL = [], 0


def ok(cond, desc):
    global TOTAL
    TOTAL += 1
    print(f"  [{'ok' if cond else 'FALLA'}] {desc}")
    if not cond:
        FALLAS.append(desc)


# ═══════════════════════════════════════════════════════════════
# Doble de Amazon Location, con las formas reales de la API
# ═══════════════════════════════════════════════════════════════
def _item(pid, titulo, cats, lat, lon, dist=0):
    return {"PlaceId": pid, "Title": titulo, "Address": {"Label": f"{titulo}, Guadalajara"},
            "Position": [lon, lat], "Distance": dist,
            "Categories": [{"Name": c} for c in cats]}


# El vecindario de prueba: el prospecto y lo que tiene alrededor.
VECINDARIO = [
    _item("P1", "Albercas y Piscinas del Valle", ["Pool supply store"], 20.67, -103.35, 0),
    _item("C1", "Piscinas Jalisco", ["Pool supply store"], 20.671, -103.351, 120),
    _item("C2", "Purificadora El Manantial", ["Water purification"], 20.672, -103.352, 300),
    _item("C3", "Bombas y Equipos Hidráulicos", ["Pump supplier"], 20.673, -103.353, 450),
    # Trampas: salen al buscar "albercas" pero NO son competencia.
    _item("X1", "Hotel Real con Alberca", ["Hotel"], 20.6705, -103.3505, 100),
    _item("X2", "Gimnasio Aqua Fitness", ["Gym"], 20.6712, -103.3512, 200),
]


class PlacesFalso:
    def __init__(self):
        self.llamadas = []

    def search_text(self, QueryText=None, MaxResults=None, IntendedUse=None,
                    Filter=None, BiasPosition=None):
        self.llamadas.append({"op": "search_text", "q": QueryText,
                              "uso": IntendedUse, "filtro": Filter})
        if Filter and "Circle" in Filter:
            radio = Filter["Circle"]["Radius"]
            dentro = [i for i in VECINDARIO if i["PlaceId"] != "P1" and i["Distance"] <= radio]
            return {"ResultItems": dentro, "PricingBucket": "x"}
        return {"ResultItems": [VECINDARIO[0]], "PricingBucket": "x"}

    def reverse_geocode(self, QueryPosition=None, MaxResults=None, IntendedUse=None):
        self.llamadas.append({"op": "reverse_geocode", "pos": QueryPosition,
                              "uso": IntendedUse})
        return {"ResultItems": [VECINDARIO[0]], "PricingBucket": "x"}


class MapasFalso:
    def __init__(self):
        self.ultimo = None

    def get_static_map(self, **kw):
        self.ultimo = kw
        return {"Blob": b"\x89PNG-de-mentiras", "ContentType": "image/png",
                "PricingBucket": "x"}


PLACES, MAPAS = PlacesFalso(), MapasFalso()
A._places = lambda: PLACES
A._mapas = lambda: MAPAS
I.lee_web = lambda url: {"url": url, "ok": True, "titulo": "Albercas del Valle",
                         "descripcion": "Venta de bombas y químicos para alberca",
                         "menciona": ["alberca", "bomba de agua", "cloro"]}


def caso(**extra):
    base = {"folio": "ALTA-2609-0001", "tipo": "alta", "giro": "Albercas",
            "valores": {"mapa_url": "https://maps.app.goo.gl/abc",
                        "inicio_ops": "2021-03", "web": "albercasdelvalle.mx",
                        "facebook": "albercasvalle", "instagram": "@albercasvalle",
                        "calle": "Av. Vallarta 1234", "colonia": "Centro",
                        "ciudad": "Guadalajara", "estado_dom": "Jalisco"}}
    base["valores"].update(extra.pop("valores", {}))
    base.update(extra)
    return base


# ═══════════════════════════════════════════════════════════════
print("\n1. Afinidad: quién es de nuestro mercado")
# ═══════════════════════════════════════════════════════════════
ok(afinidad("Albercas y Piscinas del Valle")["tipo"] == "distribuidor",
   "una tienda de albercas es distribuidor: el cliente que buscamos")
ok(afinidad("Purificadora El Manantial")["tipo"] == "distribuidor", "una purificadora también")
ok(afinidad("Bombas y Equipos Hidráulicos")["tipo"] == "distribuidor", "y las bombas de agua")
ok(afinidad("Ferretería La Central")["tipo"] == "indirecto",
   "una ferretería vende lo nuestro entre otras cosas: afinidad indirecta")
ok(afinidad("Tacos El Güero")["tipo"] == "ninguno", "una taquería no es de lo nuestro")
ok(afinidad("PISCINAS JALISCO")["tipo"] == "distribuidor", "en mayúsculas igual")
ok(afinidad("Purificación de agua")["tipo"] == "distribuidor", "y con acentos igual")
ok(afinidad("Distribuidora del Centro", ["Pool supply store"], "albercas")["tipo"] == "distribuidor",
   "si el nombre no lo dice, lo delata el giro que declaró el cliente")

print("\n   B2B: vendemos a quien REVENDE, no a quien consume")
ok(afinidad("Hotel Real con Alberca", ["Hotel"])["tipo"] == "usuario_final",
   "un hotel con alberca es usuario final, no distribuidor")
ok(afinidad("Balneario Los Manantiales")["tipo"] == "usuario_final", "un balneario tampoco revende")
ok(afinidad("Gimnasio Aqua Fitness", ["Gym"])["tipo"] == "usuario_final", "ni un gimnasio con spa")
ok(afinidad("Condominio Vista Azul")["tipo"] == "usuario_final",
   "ni un condominio, aunque tenga alberca")
ok(afinidad("Albercas del Hotel Center")["tipo"] == "usuario_final",
   "la palabra «hotel» manda aunque el nombre empiece con «Albercas»")

print("\n   Y las trampas del buscador:")
ok(not es_competencia({"nombre": "Hotel Real con Alberca", "categorias": [{"Name": "Hotel"}]}),
   "un hotel con alberca NO es competencia, aunque salga al buscar «albercas»")
ok(not es_competencia({"nombre": "Gimnasio Aqua Fitness", "categorias": [{"Name": "Gym"}]}),
   "un gimnasio tampoco")
ok(es_competencia({"nombre": "Piscinas Jalisco", "categorias": [{"Name": "Pool supply store"}]}),
   "una tienda de piscinas sí")

# ═══════════════════════════════════════════════════════════════
print("\n2. La ficha completa, con Amazon Location")
# ═══════════════════════════════════════════════════════════════
f = I.arma_ficha(caso())
ok(f["proveedor"] == "Amazon Location", "usa Amazon: no hay llave de Google")
ok(f["lugar"]["nombre"] == "Albercas y Piscinas del Valle", "ubicó el negocio")
ok(f["lugar"]["lat"] == 20.67 and f["lugar"]["lon"] == -103.35,
   "y las coordenadas quedaron derechas, no invertidas")

print("\n   Competencia en los dos radios:")
ok(f["competencia"]["150"]["total"] == 1, "a 150 m hay 1 competidor")
ok(f["competencia"]["500"]["total"] == 3, "a 500 m hay 3")
nombres = [x["nombre"] for x in f["competencia"]["500"]["lugares"]]
ok("Hotel Real con Alberca" not in nombres, "el hotel NO se contó como competencia")
ok("Gimnasio Aqua Fitness" not in nombres, "el gimnasio tampoco")

print("\n   Se declara que los resultados se guardan:")
ok(all(ll["uso"] == "Storage" for ll in PLACES.llamadas),
   "todas las llamadas van con IntendedUse=Storage, que es la tarifa correcta")

# ═══════════════════════════════════════════════════════════════
print("\n3. Los cinco criterios")
# ═══════════════════════════════════════════════════════════════
por_id = {c["id"]: c for c in f["criterios"]}
ok(len(f["criterios"]) == 5, "son cinco, los del punto 5 de la especificación")
ok(por_id["afinidad"]["estado"] == "si", "vende lo que vendemos: sí")
ok(por_id["competencia"]["estado"] == "pendiente",
   "mercado y competencia: con un rival pegado NO se declara malo solo,")
ok("demanda concentrada" in por_id["competencia"]["detalle"],
   "   porque en B2B un competidor cerca también puede significar que ahí hay demanda")
ok(por_id["digital"]["estado"] == "si", "presencia digital: su sitio habla del giro")

print("\n   Lo que Amazon no puede ver queda PENDIENTE, nunca «no»:")
ok(por_id["exhibe"]["estado"] == "pendiente", "exhibe producto: pendiente")
ok("Google" in por_id["exhibe"]["detalle"], "y dice que se resuelve conectando Google")
ok(por_id["letrero"]["estado"] == "pendiente", "letrero afuera: pendiente")
ok(f["conteo"] == {"favorables": 2, "contrarios": 0, "pendientes": 3, "total": 5},
   "el conteo cuadra: 2 a favor, 0 en contra, 3 pendientes")
ok(sum(v for k, v in f["conteo"].items() if k != "total") == f["conteo"]["total"],
   "y las partes suman el total, sin contar ningun criterio dos veces")

print("\n   Cada criterio dice de dónde salió:")
ok(all(c.get("fuente") for c in f["criterios"]), "los cinco traen su fuente")

# ═══════════════════════════════════════════════════════════════
print("\n4. Las redes se preparan, no se leen")
# ═══════════════════════════════════════════════════════════════
redes = {r["red"]: r["url"] for r in f["redes"]}
ok(redes["Facebook"] == "https://facebook.com/albercasvalle", "Facebook queda como liga")
ok(redes["Instagram"] == "https://instagram.com/albercasvalle",
   "Instagram también, y se le quita la arroba")
ok(I.redes_de({"facebook": "https://fb.com/ya-es-liga"})[0]["url"] == "https://fb.com/ya-es-liga",
   "si ya venía como liga, se respeta")
ok(I.redes_de({}) == [], "sin redes declaradas, no inventa ninguna")

# ═══════════════════════════════════════════════════════════════
print("\n5. Nada de esto puede tumbar el envío del cliente")
# ═══════════════════════════════════════════════════════════════
def revienta(*a, **k):
    raise RuntimeError("AWS se cayó")


original = A._places
A._places = lambda: type("Roto", (), {"search_text": revienta,
                                      "reverse_geocode": revienta})()
f2 = I.arma_ficha(caso())
ok(isinstance(f2, dict), "con el mapa caído, la ficha se arma igual y no lanza")
ok(any("falló" in a for a in f2["avisos"]), "y lo dice en los avisos")
ok(len(f2["criterios"]) == 5, "los cinco criterios siguen ahí")
ok(all(c["estado"] != "no" or c["id"] == "digital" for c in f2["criterios"]),
   "sin datos, nada se marca como «no» por error")
A._places = original

print("\n   Y si el cliente no capturó su ubicación:")
f3 = I.arma_ficha({"folio": "X", "tipo": "alta", "valores": {}})
ok(any("no capturó" in a for a in f3["avisos"]), "lo dice con todas sus letras")
ok(f3["conteo"]["total"] == 5, "y aun así entrega los cinco criterios")

# ═══════════════════════════════════════════════════════════════
print("\n6. El sitio web del cliente no puede apuntar a nuestra red")
# ═══════════════════════════════════════════════════════════════
import inteligencia as I2                                   # noqa: E402
for malo, desc in [("http://localhost/admin", "localhost"),
                   ("http://127.0.0.1/", "la dirección de loopback"),
                   ("http://169.254.169.254/latest/meta-data/", "los metadatos de AWS"),
                   ("http://10.0.0.5/", "la red interna"),
                   ("ftp://algo.mx", "un protocolo que no es web")]:
    ok(I2._url_publica(malo) == "", f"se rechaza {desc}")
ok(I2._url_publica("gpa.com.mx").startswith("https://"),
   "a un dominio normal se le completa el https")

# ═══════════════════════════════════════════════════════════════
print("\n7. El mapa se genera al verlo, no se guarda")
# ═══════════════════════════════════════════════════════════════
png = I.mapa_de(f)
ok(png == b"\x89PNG-de-mentiras", "devuelve la imagen")
ok(MAPAS.ultimo["Center"] == "-103.35,20.67",
   "el centro va en «longitud,latitud», como lo pide AWS")
geo = MAPAS.ultimo["GeoJsonOverlay"]
ok('"tipo": "prospecto"' in geo, "el prospecto va marcado")
ok(geo.count('"competencia"') == 3,
   "y sus 3 competidores, sin repetir al que cae en los dos radios")
ok("mapa" not in str(f), "la ficha guardada NO trae la imagen dentro")
ok(I.mapa_de({"lugar": {}}) is None, "sin coordenadas no intenta dibujar nada")

# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
if FALLAS:
    print(f"{len(FALLAS)} falla(s) de {TOTAL}:")
    for x in FALLAS:
        print("  · " + x)
    sys.exit(1)
print(f"Sin fallas. {TOTAL} comprobaciones sobre la ficha comercial real.")
