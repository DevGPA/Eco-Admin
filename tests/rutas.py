"""Comprueba que template.yaml, handler.py y el frontend hablen de las MISMAS rutas.
Una ruta declarada que nadie atiende devuelve 404; una que el frontend llama y no
está declarada nunca llega. Ninguna de las dos se nota hasta producción."""
import re, sys, pathlib, yaml

RAIZ = pathlib.Path(__file__).resolve().parent.parent


class L(yaml.SafeLoader):
    pass


L.add_multi_constructor("!", lambda l, s, n: None)


def rutas_template():
    d = yaml.load((RAIZ / "template.yaml").read_text(encoding="utf-8"), Loader=L)
    todas, publicas = set(), set()
    for ev in d["Resources"]["AltaFn"]["Properties"]["Events"].values():
        p = ev["Properties"]
        r = f"{p['Method']} {p['Path']}"
        todas.add(r)
        if str((p.get("Auth") or {}).get("Authorizer", "")).upper() == "NONE":
            publicas.add(r)
    return todas, publicas


def rutas_handler():
    h = (RAIZ / "handler.py").read_text(encoding="utf-8")
    rutas = set(re.findall(r'ruta == "([A-Z]+ [^"]+)"', h))
    # el bloque de portal se despacha por prefijo
    if 'ruta.startswith("POST /portal/")' in h:
        rutas |= set(re.findall(r'ruta == "(POST /portal/[^"]+)"', h))
    return rutas


def rutas_frontend():
    js = (RAIZ / "frontend" / "gpa-api.js").read_text(encoding="utf-8")
    out = set()
    for metodo, cruda in re.findall(r'_http\(\s*"(GET|POST)"\s*,\s*[`"]([^`"]+)[`"]', js):
        ruta = re.sub(r"\$\{[^}]*\}", "{folio}", cruda)
        ruta = ruta.split("?")[0].rstrip("/") or "/"
        out.add(f"{metodo} {ruta}")
    for ruta in re.findall(r'this\._http\(\s*"(/portal/[^"]+)"', js):
        out.add(f"POST {ruta}")
    if "/catalogos" in js:
        out.add("GET /catalogos")
    return out


def main():
    tpl, publicas = rutas_template()
    han = rutas_handler()
    fro = rutas_frontend()
    problemas = []

    print(f"template.yaml: {len(tpl)} rutas · handler.py: {len(han)} · frontend: {len(fro)}\n")

    sin_atender = tpl - han
    print("Declaradas sin atender (darían 404):", sorted(sin_atender) or "ninguna")
    if sin_atender:
        problemas.append(f"rutas declaradas sin atender: {sorted(sin_atender)}")

    fantasma = han - tpl
    print("Atendidas sin declarar (nunca llegan):", sorted(fantasma) or "ninguna")
    if fantasma:
        problemas.append(f"rutas atendidas sin declarar: {sorted(fantasma)}")

    huerfanas = fro - tpl
    print("Llamadas por el frontend sin declarar:", sorted(huerfanas) or "ninguna")
    if huerfanas:
        problemas.append(f"el frontend llama rutas inexistentes: {sorted(huerfanas)}")

    print("Declaradas que el frontend no usa:", sorted(tpl - fro) or "ninguna")
    print("\nRutas públicas, sin Cognito (el cliente externo no tiene cuenta):")
    for r in sorted(publicas):
        print("   ", r)

    esperadas = {"GET /health", "GET /catalogos", "POST /portal/entrar", "POST /portal/guardar",
                 "POST /portal/url-subida", "POST /portal/adjuntar", "POST /portal/quitar",
                 "POST /portal/enviar"}
    if publicas != esperadas:
        problemas.append(f"las rutas públicas no son las esperadas: sobran {sorted(publicas - esperadas)}, "
                         f"faltan {sorted(esperadas - publicas)}")
    privadas_con_portal = {r for r in tpl - publicas if "/portal/" in r}
    if privadas_con_portal:
        problemas.append(f"rutas del portal que quedaron detrás de Cognito: {sorted(privadas_con_portal)}")

    # La vista del cliente se arma por lista blanca. Si algún día alguien mete
    # ahí un campo interno, el cliente vería cosas que son solo de GPA: quién
    # está vetado, qué comentó el comité, o el hash de su propia clave.
    print("\nLo que el cliente NO debe ver:")
    handler_txt = (RAIZ / "handler.py").read_text(encoding="utf-8")
    cuerpo = handler_txt.split("def _vista_cliente")[1].split("\ndef ")[0]
    prohibidos = ["avisosObligados", "avisosVeto", "vetoOmitido", "anexos",
                  "comentarios", "autorizaciones", "claveHash", "claveSal",
                  "creadoPor", "rechazo"]
    filtrados = [p for p in prohibidos if f'"{p}"' in cuerpo]
    if filtrados:
        problemas.append(f"la vista del cliente expone campos internos: {filtrados}")
        print("    FALLA — se filtran:", filtrados)
    else:
        print("    ninguno de los", len(prohibidos), "campos internos se asoma en _vista_cliente")

    # El manual se despliega junto a la app y se actualiza con ella. Si no está
    # en el paquete, o nadie lo enlaza, es como si no existiera.
    print("\nManual:")
    manual = RAIZ / "frontend" / "manual.html"
    indice = (RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
    if not manual.exists():
        problemas.append("falta frontend/manual.html")
        print("    FALLA — no existe frontend/manual.html")
    elif 'href="manual.html"' not in indice:
        problemas.append("el manual existe pero nada lo enlaza desde index.html")
        print("    FALLA — el manual existe pero nadie lo enlaza")
    else:
        v = re.search(r"versión (\d+\.\d+)", manual.read_text(encoding="utf-8"))
        print("    manual v" + (v.group(1) if v else "?") + ", enlazado desde el portal")

    # Firma quien tiene la sesión abierta. Si alguna capa vuelve a mandar o a
    # aceptar un firmante en el cuerpo, se podría firmar a nombre de otro y el
    # acta de autorización dejaría de valer.
    print("\nQuién firma:")
    culpables = [n for n in ("handler.py", "frontend/app.js", "frontend/gpa-api.js")
                 if "correoFirmante" in (RAIZ / n).read_text(encoding="utf-8")]
    if culpables:
        problemas.append(f"se volvió a pasar el firmante en el cuerpo, en: {culpables}")
        print("    FALLA — el firmante vuelve a venir del cuerpo:", culpables)
    else:
        print("    el firmante sale del token, no del cuerpo de la petición")

    print()
    if problemas:
        print("PROBLEMAS:")
        for p in problemas:
            print("  -", p)
        sys.exit(1)
    print("Las tres capas declaran las mismas rutas, y solo el portal es público.")


if __name__ == "__main__":
    main()
