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
# Bedrock se prueba aparte, en la seccion 9: aqui no se llama.
I.redacta = lambda ficha, caso_: ("", [])


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
print("\n8. La llave de Google NUNCA llega al navegador")
# ═══════════════════════════════════════════════════════════════
# Google no se ejecuta aquí (no hay cuenta todavía), pero sí se revisa su
# CONTRATO: nada de lo que este proveedor entrega a la pantalla puede llevar la
# llave dentro. Una llave en el código de una página es cuota ajena gastándose
# sola, y el que paga es GPA.
import inteligencia.google as G                              # noqa: E402

LLAVE = "LLAVE-SECRETA-DE-PRUEBA"
os.environ["GOOGLE_MAPS_KEY"] = LLAVE

CRUDO = {"fotosCrudas": [
    {"name": "places/ABC/photos/XYZ",
     "authorAttributions": [{"displayName": "Juan Pérez"}],
     "googleMapsUri": "https://maps.google.com/?cid=1"},
]}
g = G.Google()
fotos = g.fotos(CRUDO)
ok(len(fotos) == 1, "devuelve la foto del local")
ok(LLAVE not in str(fotos), "y NO trae la llave dentro")
ok("url" not in fotos[0], "no entrega una liga armada, sino una referencia")
ok(fotos[0]["ref"] == "places/ABC/photos/XYZ", "la referencia es la que dio Google")
ok(fotos[0]["atribucion"] == "Juan Pérez",
   "con la atribución del autor, que los términos exigen mostrar")

pedidos = []


class RespuestaFalsa:
    def __init__(self, cuerpo):
        self.cuerpo = cuerpo

    def read(self):
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def urlopen_falso(pet, timeout=None):
    url = pet.full_url if hasattr(pet, "full_url") else pet
    pedidos.append({"url": url, "cabeceras": dict(getattr(pet, "headers", {}) or {})})
    if "skipHttpRedirect" in url:
        return RespuestaFalsa(b'{"photoUri":"https://lh3.googleusercontent.com/temporal"}')
    if "metadata" in url:
        return RespuestaFalsa(b'{"status":"OK","date":"2025-03"}')
    return RespuestaFalsa(b"PNG-de-la-fachada")


G.urllib.request.urlopen = urlopen_falso
liga = g.url_foto("places/ABC/photos/XYZ")
ok(liga == "https://lh3.googleusercontent.com/temporal",
   "lo que sí puede abrir el navegador es un photoUri temporal de Google")
ok(LLAVE not in liga, "y esa liga no lleva la llave")
ok(LLAVE not in pedidos[-1]["url"], "la llave tampoco va en la dirección que pide el servidor")
ok(pedidos[-1]["cabeceras"].get("X-goog-api-key") == LLAVE,
   "va en la cabecera, que se queda de este lado")

print("\n   La fachada tampoco entrega ligas con llave:")
fach = g.fachada(20.67, -103.35)
ok(fach["fecha"] == "2025-03", "trae la fecha de captura, que es lo que fecha el local")
ok(LLAVE not in str(fach), "y NO trae la llave")
ok("url" not in fach, "no entrega liga: da coordenadas, y la imagen la trae el servidor")
ok(g.imagen_fachada(20.67, -103.35) == b"PNG-de-la-fachada",
   "la imagen llega como bytes, traída desde el servidor")

print("\n   Y nadie puede pedir una foto que no esté en el expediente:")
ficha_falsa = {"fotos": [{"ref": "places/ABC/photos/XYZ"}]}
ok(I.url_foto_de(ficha_falsa, 0) != "", "el índice 0 sí existe y se resuelve")
ok(I.url_foto_de(ficha_falsa, 5) == "", "un índice fuera de la lista no devuelve nada")
ok(I.url_foto_de(ficha_falsa, -1) == "", "uno negativo tampoco")
ok(I.url_foto_de({}, 0) == "", "y una ficha sin fotos, menos")

os.environ.pop("GOOGLE_MAPS_KEY", None)
# ═══════════════════════════════════════════════════════════════
print("\n9. El resumen que redacta Bedrock")
# ═══════════════════════════════════════════════════════════════
import inteligencia.resumen as R                              # noqa: E402

PARRAFO = ("Albercas y Piscinas del Valle es un distribuidor del giro, ubicado en "
           "Av. Vallarta 1234. Su sitio menciona alberca, bomba de agua y cloro. "
           "Tiene un competidor a menos de 150 m. Quedan pendientes los criterios "
           "de exhibición de producto y letrero, que requieren fotos del local.")


class BedrockFalso:
    def __init__(self, texto=PARRAFO, revienta=False):
        self.texto, self.revienta, self.llamadas = texto, revienta, []

    def converse(self, modelId=None, messages=None, inferenceConfig=None):
        if self.revienta:
            raise RuntimeError("Bedrock no contestó")
        self.llamadas.append({"modelo": modelId, "msgs": messages,
                              "config": inferenceConfig})
        return {"output": {"message": {"content": [{"text": self.texto}]}}}


bed = BedrockFalso()
ficha_r = I.arma_ficha(caso())          # se arma sin resumen (I.redacta parcheado)
texto, avisos = R.redacta(ficha_r, caso(), cliente=bed)
ok(texto == PARRAFO, "devuelve el párrafo que redactó el modelo")
ok(avisos == [], "sin avisos cuando el modelo se porta bien")
ok(bed.llamadas[0]["modelo"] == R.MODELO, "usa el modelo configurado")
ok("sonnet" in R.MODELO, "que es Sonnet, el que ya tiene habilitado la cuenta")
ok(bed.llamadas[0]["config"]["temperature"] <= 0.2,
   "con temperatura baja: es un expediente, no un texto creativo")

print("\n   Solo se le manda lo medido:")
carga = bed.llamadas[0]["msgs"][0]["content"][0]["text"]
ok("Vende lo que vendemos" in carga, "van los cinco criterios con su estado")
ok("pendiente" in carga, "y se le dice cuáles quedaron pendientes")
ok("claveHash" not in carga and "adjuntos" not in carga,
   "NO van los adjuntos ni nada del expediente que no sea del negocio")
ok("NO recomiendes autorizar" in carga, "la instrucción le prohíbe recomendar")
ok("REVENDEN" in carga, "y le explica que GPA vende B2B, a quien revende")

print("\n   Si Bedrock no contesta, el expediente sigue su curso:")
texto2, avisos2 = R.redacta(ficha_r, caso(), cliente=BedrockFalso(revienta=True))
ok(texto2 == "", "no hay párrafo")
ok(len(avisos2) == 1 and "No se pudo redactar" in avisos2[0], "y se dice por qué")
ok("criterios están completos" in avisos2[0],
   "aclarando que los cinco criterios sí quedaron: lo que falta es el párrafo")

print("\n   Y si el modelo se sale de su papel, se avisa:")
_, avisos3 = R.redacta(ficha_r, caso(),
                       cliente=BedrockFalso("El prospecto es afín. Recomiendo autorizar "
                                            "una línea de 250,000 pesos."))
ok(len(avisos3) == 1 and "recomendación" in avisos3[0],
   "se detecta que recomendó autorizar")
ok("decisión es del comité" in avisos3[0], "y se le recuerda a quien lo lee de quién es la decisión")

print("\n   El párrafo va marcado como borrador:")
guardado = I.redacta
I.redacta = lambda ficha, caso_: (PARRAFO, [])
f_con = I.arma_ficha(caso())
I.redacta = guardado
ok(f_con["resumen"] == PARRAFO, "la ficha trae el párrafo")
ok(f_con["resumenEsBorrador"] is True, "marcado como borrador, no como veredicto")
ok(len(f_con["criterios"]) == 5, "y los cinco criterios siguen al lado, con sus fuentes")





# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
if FALLAS:
    print(f"{len(FALLAS)} falla(s) de {TOTAL}:")
    for x in FALLAS:
        print("  · " + x)
    sys.exit(1)
print(f"Sin fallas. {TOTAL} comprobaciones sobre la ficha comercial real.")
