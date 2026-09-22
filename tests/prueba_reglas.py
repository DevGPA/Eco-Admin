# tests/prueba_reglas.py — ejecuta las reglas REALES de db/escritura.py.
# Uso:  PYTHONUTF8=1 python tests/prueba_reglas.py
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DYNAMO_TABLE", "prueba")
os.environ.setdefault("DOCS_BUCKET", "prueba")
os.environ.setdefault("USER_POOL_ID", "prueba")

from tests.tabla_memoria import TablaMemoria           # noqa: E402
import db.queries as q                                  # noqa: E402
import db.escritura as e                                # noqa: E402
import db.veto as v                                     # noqa: E402
import catalogos as c                                   # noqa: E402

MEM = TablaMemoria()
# Cada módulo guarda su propia referencia a tabla(), así que hay que sustituirlas
# TODAS aquí arriba: crear_caso consulta la lista de vetados en cada alta.
q.tabla = lambda: MEM
e.tabla = lambda: MEM
v.tabla = lambda: MEM

FALLAS = []
TOTAL = 0


def ok(cond, desc):
    global TOTAL
    TOTAL += 1
    print(f"  [{'ok' if cond else 'FALLA'}] {desc}")
    if not cond:
        FALLAS.append(desc)


def rompe(fn, fragmento, desc):
    """La operación DEBE ser rechazada, y el mensaje debe explicar por qué."""
    global TOTAL
    TOTAL += 1
    try:
        fn()
    except e.ReglaRota as ex:
        bien = fragmento.lower() in str(ex).lower()
        print(f"  [{'ok' if bien else 'FALLA'}] {desc}")
        if not bien:
            FALLAS.append(f"{desc} — mensaje inesperado: {ex}")
        return
    print(f"  [FALLA] {desc} — la operación NO fue rechazada")
    FALLAS.append(f"{desc} — no fue rechazada")


ADMIN = {"correo": "lmedina@gpa.com.mx", "nombre": "Laura Medina", "rol": c.ROL_ADMIN}
VENTAS = {"correo": "cespinoza@gpa.com.mx", "nombre": "Claudia Espinoza", "rol": c.ROL_VENTAS}
FIRMA1 = {"correo": "hsalgado@gpa.com.mx", "nombre": "Héctor Salgado", "rol": c.ROL_COMITE,
          "n1": True, "n2": False, "activo": True}
FIRMA2A = {"correo": "vrios@gpa.com.mx", "nombre": "Verónica Ríos", "rol": c.ROL_COMITE,
           "n1": False, "n2": True, "activo": True}
FIRMA2B = {"correo": "dfuentes@gpa.com.mx", "nombre": "Daniel Fuentes", "rol": c.ROL_COMITE,
           "n1": False, "n2": True, "activo": True}
SIN_NIVEL = {"correo": "rlomeli@gpa.com.mx", "nombre": "Roberto Lomelí", "rol": c.ROL_CONSULTA,
             "n1": False, "n2": False, "activo": True}


def nueva(tipo="alta", regimen="601", rfc="ASV180412H23", docs=None, modulos=None):
    T = c.TIPOS[tipo]
    return {
        "tipo": tipo, "razonSocial": "Albercas y Spas del Valle, S.A. de C.V.",
        "nombreComercial": "Albercas del Valle", "rfc": rfc, "regimen": regimen,
        "contacto": "Rodrigo Cárdenas", "correo": "rcardenas@albercasdelvalle.mx",
        "celular": "33 1204 8871", "sucursal": "GDL", "giro": "ALBERCAS", "clasificacion": "2",
        "montoRequerido": "250,000",
        "modulos": modulos or {m: True for m in T["modulos"]},
        "docs": docs or {d: True for d in T["docs"]},
    }


EJEMPLOS_POR_TIPO = {"tel": "33 1234 5678", "email": "cliente@ejemplo.mx", "cp": "44110",
                     "hora": "08:00", "monto": "250000"}


def llena_todo(token, clave):
    """Llena todo lo obligatorio con valores válidos, como lo haría el cliente."""
    caso = q.caso_por_token(token)
    valores, tablas = {}, {}
    for m in c.modulos_activos(caso["tipo"], caso["modulos"]):
        for f in c.campos_de(m):
            if f.get("fijo") or not f.get("req"):
                continue
            valores[f["k"]] = True if f.get("tipo") == "check" else (
                f["opts"][0] if f.get("opts") else
                EJEMPLOS_POR_TIPO.get(f.get("tipo"), "Dato de prueba"))
        for t in m.get("tablas", []):
            if t.get("req"):
                tablas[t["k"] + "_0_0"] = "Proveedor de prueba"
    e.guardar_captura(token, clave, valores, tablas)
    persona = c.persona_de(caso["regimen"], caso["rfc"])
    for i, d in enumerate(c.docs_aplicables(caso["tipo"], caso["docs"], persona)):
        if not (q.get_caso(caso["folio"])["adjuntos"] or {}).get(d["id"]):
            e.registrar_adjunto(token, clave, d["id"], f"{d['id']}.pdf",
                                f"{caso['folio']}/{d['id']}-aabbccddeeff.pdf",
                                tam=10000 + i * 137)


print("\n== 1. Crear pre-solicitud ==")
caso_alta, clave_alta = e.crear_caso(nueva("alta"), VENTAS)
ok(caso_alta["folio"].startswith("GS-"), f"folio consecutivo generado: {caso_alta['folio']}")
ok(caso_alta["estado"] == "enviada", "nace en estado «Enviada»")
guardado = MEM.get_item({"PK": f"CASO#{caso_alta['folio']}", "SK": "META"})["Item"]
ok("claveHash" in guardado and "claveSal" in guardado, "en la base solo queda la huella de la clave")
ok(guardado.get("claveHash") != c.__dict__.get("x") and clave_alta not in str(guardado),
   "la clave en claro NO se guarda en ningún campo")
ok("claveHash" not in caso_alta and "claveSal" not in caso_alta,
   "la huella tampoco sale hacia el frontend")
ok(len(clave_alta) == 9 and clave_alta[4] == "-", f"la clave es dictable por teléfono: {clave_alta}")
ok(set(caso_alta["docs"]) == set(c.TIPOS["alta"]["docs"]),
   f"un alta solo guarda sus {len(c.TIPOS['alta']['docs'])} documentos")
ok("edos_cuenta" not in caso_alta["docs"], "un alta no puede pedir estados de cuenta bancarios")

caso_cred, clave_cred = e.crear_caso(nueva("credito"), ADMIN)
ok(len(caso_cred["docs"]) == 8, "un crédito guarda sus 8 documentos")
ok(caso_cred["folio"] != caso_alta["folio"], "los folios no se repiten")

# Los documentos y secciones NO se eligen: van completos por tipo de solicitud.
recortado = nueva("credito")
recortado["docs"] = {"csf": True}                 # la pantalla manda solo uno
recortado["modulos"] = {"fiscal": True}           # y una sola sección
caso_r, _ = e.crear_caso(recortado, ADMIN)
ok(set(caso_r["docs"]) == set(c.TIPOS["credito"]["docs"]) and all(caso_r["docs"].values()),
   "aunque la pantalla mande 1 documento, el servidor pone los 8 del tipo")
ok(set(caso_r["modulos"]) == set(c.TIPOS["credito"]["modulos"]) and all(caso_r["modulos"].values()),
   "y las 3 secciones completas, no la que mandó la pantalla")
vacio = nueva("alta")
vacio["docs"] = {}
vacio["modulos"] = {}
caso_v, _ = e.crear_caso(vacio, ADMIN)
ok(all(caso_v["docs"].values()) and len(caso_v["docs"]) == 5,
   "y si no manda ninguno, tampoco: un alta siempre pide sus 5")

rompe(lambda: e.crear_caso({**nueva(), "rfc": "ABC"}, VENTAS), "12 caracteres", "rechaza un RFC corto")
rompe(lambda: e.crear_caso({**nueva(), "correo": "no-es-correo"}, VENTAS), "correo", "rechaza un correo inválido")
rompe(lambda: e.crear_caso({**nueva(), "razonSocial": ""}, VENTAS), "razón social", "rechaza sin razón social")
rompe(lambda: e.crear_caso({**nueva(), "tipo": "otra"}, VENTAS), "alta", "rechaza un tipo inventado")
rompe(lambda: e.crear_caso({**nueva(), "celular": "3312"}, VENTAS), "10 dígitos",
      "rechaza un celular de contacto incompleto")
rompe(lambda: e.crear_caso({**nueva(), "celular": ""}, VENTAS), "celular",
      "y exige celular: por ahí se entrega la clave")
ok(c.CAT["uso"] == ["G01 · Adquisición de mercancías", "G03 · Gastos en general",
                    "S01 · Sin efectos fiscales"],
   "el uso del CFDI usa las claves del SAT: G01, G03 y S01")
ok(all(u[:3] in ("G01", "G03", "S01") and u[3:6] == " · " for u in c.CAT["uso"]),
   "y todas traen la clave por delante, para no adivinarla al facturar")

# ── Vigencia de la liga ──
ok(bool(caso_alta.get("vence")), "la liga nace con fecha de vencimiento")
from db.modelos import ya_vencio                                # noqa: E402
import datetime as _dt                                          # noqa: E402
dias = (_dt.datetime.fromisoformat(caso_alta["vence"]) -
        _dt.datetime.fromisoformat(caso_alta["creado"])).days
ok(dias == 15, f"y dura 15 días naturales (dura {dias})")
ok(not ya_vencio(caso_alta["vence"]), "recién creada, no está vencida")
ok(ya_vencio("2020-01-01T00:00:00-06:00"), "una fecha pasada sí se detecta como vencida")
ok(not ya_vencio(None), "un expediente sin fecha no se da por vencido")

# ── El monto lo fija GPA, no el cliente ──
rompe(lambda: e.crear_caso({**nueva("credito"), "montoRequerido": ""}, ADMIN),
      "monto de crédito requerido", "un crédito sin monto no se puede crear")
e.crear_caso({**nueva("alta"), "montoRequerido": ""}, ADMIN)
ok(True, "un alta sí se crea sin monto: no aplica")
ok(c.valores_fijos({"tipo": "credito", "modulos": {"fiscal": 1, "credito": 1, "buro": 1},
                    "montoRequerido": "250,000"}).get("monto") == "250,000",
   "el monto capturado por GPA llega al formulario del cliente como dato fijo")

# ── De quién es cada documento ──
sin_grupo = [d["id"] for d in c.DOCUMENTOS if d.get("de") not in c.ORDEN_GRUPOS]
ok(not sin_grupo, f"los {len(c.DOCUMENTOS)} documentos dicen de quién son (sin grupo: {sin_grupo})")
ok(c.documento("ine_rep")["de"] == "representante" and c.documento("ine_aval")["de"] == "aval",
   "el INE del representante y el del aval quedan en grupos distintos")
ok(len({c.GRUPOS_DOC[g]["c"] for g in c.ORDEN_GRUPOS}) == 3,
   "cada grupo tiene su propio color")

print("\n== 2. Régimen del SAT decide los documentos ==")
fis = nueva("credito", regimen="612", rfc="CAGR850101AB1")
caso_fis, clave_fis = e.crear_caso(fis, VENTAS)
aplic_fis = c.docs_aplicables("credito", caso_fis["docs"], c.persona_de("612", "CAGR850101AB1"))
aplic_mor = c.docs_aplicables("credito", caso_cred["docs"], c.persona_de("601", "ASV180412H23"))
ok(len(aplic_mor) - len(aplic_fis) == 1,
   f"persona física pide un documento menos: el acta constitutiva ({len(aplic_fis)} vs {len(aplic_mor)})")
ok(all(d["id"] != "acta_const" for d in aplic_fis), "a persona física no se le pide acta constitutiva")
ok(c.persona_de("626", "ASV180412H23") == "Moral" and c.persona_de("626", "CAGR850101AB1") == "Física",
   "en RESICO (626) el RFC decide el tipo de persona")
ok(bool(c.conflicto_regimen_rfc("601", "CAGR850101AB1")), "avisa si el régimen y el RFC no concuerdan")

print("\n== 3. Entrada del cliente: liga + clave ==")
folio = caso_alta["folio"]
token = caso_alta["token"]
vista = e.verificar_clave(token, clave_alta)
ok(vista["estado"] == "captura", "con la clave correcta el expediente pasa a «En captura»")
ok(e.verificar_clave(token, clave_alta.lower().replace("-", " "))["folio"] == folio,
   "la clave funciona en minúsculas, con espacios o sin guiones")
rompe(lambda: e.verificar_clave("no-existe-nada", clave_alta), "no existe", "una liga inventada no abre nada")
for i in range(4):
    try:
        e.verificar_clave(token, "MALA-MALA")
    except e.ReglaRota:
        pass
estado = q.get_caso(folio)
ok(int(estado["intentos"]) == 4, "cuenta los intentos fallidos")
rompe(lambda: e.verificar_clave(token, "MALA-MALA"), "bloque", "al quinto intento fallido bloquea la liga")
rompe(lambda: e.verificar_clave(token, clave_alta), "bloque", "bloqueada, ni la clave correcta abre")
clave_alta = e.regenerar_clave(folio, ADMIN)
ok(e.verificar_clave(token, clave_alta)["folio"] == folio, "una clave nueva desbloquea la liga")
ok(int(q.get_caso(folio)["intentos"]) == 0, "y el contador de intentos vuelve a cero")

print("\n== 4. Captura: el servidor decide qué se guarda ==")
e.guardar_captura(token, clave_alta,
                  {"calle": "Av. Vallarta 3020", "cp": "44110",
                   "monto": "999999", "razonSocial": "OTRA EMPRESA"}, {})
guardado = q.get_caso(folio)
ok(guardado["valores"].get("calle") == "Av. Vallarta 3020", "guarda un campo que sí le toca")
ok("monto" not in guardado["valores"], "descarta «monto»: es de crédito y este caso es un alta")
ok("razonSocial" not in guardado["valores"], "descarta la razón social: el cliente no la puede cambiar")
ok(q.get_caso(folio)["razonSocial"] == "Albercas y Spas del Valle, S.A. de C.V.",
   "y el dato fijo queda intacto")

print("\n== 5. Documentos ==")
e.registrar_adjunto(token, clave_alta, "ine_rep", "IMG_4471.jpg", f"{folio}/ine_rep-aabbccddeeff.jpg")
ok(q.get_caso(folio)["adjuntos"].get("ine_rep"), "registra el documento subido")
rompe(lambda: e.registrar_adjunto(token, clave_alta, "edos_cuenta", "x.pdf", "k"),
      "no se le pidió", "rechaza un documento que no se pidió en esta solicitud")
rompe(lambda: e.registrar_adjunto(token, clave_alta, "../../secreto", "x", "k"),
      "inválido", "rechaza un identificador con caracteres de ruta")

print("\n== 6. País fijo, formatos y archivos repetidos ==")
ok(q.get_caso(folio)["valores"].get("pais") == "México", "el País se pone solo en México al crear")
e.guardar_captura(token, clave_alta, {"pais": "Guatemala"}, {})
ok(q.get_caso(folio)["valores"].get("pais") == "México", "y el cliente no lo puede cambiar")

e.guardar_captura(token, clave_alta, {"telefono": "33123"}, {})
probs = c.revisa_captura(q.get_caso(folio))
ok("10 dígitos" in probs.get("telefono", ""), "un teléfono de 5 dígitos se marca como incompleto")
e.guardar_captura(token, clave_alta, {"lv_ini": "8 de la mañana"}, {})
ok("08:00" in c.revisa_captura(q.get_caso(folio)).get("lv_ini", ""),
   "una hora mal escrita también se marca")
rompe(lambda: e.enviar_expediente(token, clave_alta), "Faltan",
      "con campos incompletos NO deja enviar")

e.registrar_adjunto(token, clave_alta, "comp_dom", "mismo.pdf",
                    f"{folio}/comp_dom-aa11bb22cc33.pdf", tam=5000)
rompe(lambda: e.registrar_adjunto(token, clave_alta, "fotos_negocio", "mismo.pdf",
                                  f"{folio}/fotos_negocio-dd44ee55ff66.jpg", tam=5000),
      "ya lo adjuntó", "el mismo archivo no sirve para dos documentos distintos")

# ── Documento libre: lo que el cliente crea útil y no esté en la lista ──
rompe(lambda: e.registrar_adjunto(token, clave_alta, "otro", "carta.pdf", f"{folio}/otro-aa.pdf",
                                  tam=3000),
      "de qué se trata", "el documento adicional exige decir de qué se trata")
e.registrar_adjunto(token, clave_alta, "otro", "carta_banco.pdf", f"{folio}/otro-bb11cc22.pdf",
                    tam=3000, descripcion="Carta de mi banco")
libres = e.otros_de(q.get_caso(folio))
ok(len(libres) == 1 and libres[0]["descripcion"] == "Carta de mi banco",
   "se guarda con su descripción")
ok(libres[0]["id"].startswith("otro:"), "y con identificador propio, sin chocar con los de la lista")
ok(c.avance(q.get_caso(folio))["total"] ==
   c.avance({**q.get_caso(folio), "adjuntos": {}})["total"],
   "los adicionales NO cuentan para el avance: son opcionales")
rompe(lambda: e.quitar_adjunto(token, clave_alta, "comp_dom"), "solo se pueden quitar",
      "un documento de la lista no se quita, se reemplaza")
e.quitar_adjunto(token, clave_alta, libres[0]["id"])
ok(not e.otros_de(q.get_caso(folio)), "el adicional sí se puede quitar si se subió por error")

print("\n== 7. Envío, revisión y devolución ==")
llena_todo(token, clave_alta)
e.enviar_expediente(token, clave_alta)
ok(q.get_caso(folio)["estado"] == "recibida", "al enviar, el expediente queda «Recibida»")
rompe(lambda: e.guardar_captura(token, clave_alta, {"calle": "otra"}, {}),
      "no admite cambios", "ya enviado, el cliente no puede seguir escribiendo")

rompe(lambda: e.pasar_a_autorizacion(folio, ADMIN), "sin revisar",
      "no pasa a firmas si los documentos no están revisados")
e.marcar_documento(folio, "ine_rep", False, "La foto está cortada.", VENTAS)
ok(q.get_caso(folio)["marcas"]["ine_rep"]["motivo"] == "La foto está cortada.", "guarda el motivo del señalamiento")
rompe(lambda: e.marcar_documento(folio, "comp_dom", False, "", VENTAS), "motivo",
      "no deja señalar sin escribir el motivo")
e.devolver(folio, VENTAS)
ok(q.get_caso(folio)["estado"] == "devuelta", "devuelve el expediente al cliente")

permitidos = e.campos_permitidos(q.get_caso(folio))
ok(permitidos == set(), "devuelto por un documento, ningún campo queda editable")
e.señalar_campo(folio, "telefono", "El teléfono no contesta.", VENTAS)
ok(e.campos_permitidos(q.get_caso(folio)) == {"telefono"}, "señalado un campo, solo ese queda editable")
e.guardar_captura(token, clave_alta, {"telefono": "33 1111 2222", "calle": "intento de cambio"}, {})
g = q.get_caso(folio)
ok(g["valores"]["telefono"] == "33 1111 2222", "acepta el campo señalado")
ok(g["valores"]["calle"] != "intento de cambio", "y NO deja tocar lo que ya estaba aceptado")

rompe(lambda: e.registrar_adjunto(token, clave_alta, "comp_dom", "x.pdf", "k"),
      "ya fue aceptado", "devuelto, no deja reemplazar un documento que estaba bien")
rechazado = q.get_caso(folio)["adjuntos"]["ine_rep"]
rompe(lambda: e.registrar_adjunto(token, clave_alta, "ine_rep", rechazado["nombre"],
                                  f"{folio}/ine_rep-999888777666.jpg", tam=rechazado["tam"]),
      "mismo archivo que le señalamos",
      "no acepta de vuelta exactamente el archivo que se rechazó")
e.registrar_adjunto(token, clave_alta, "ine_rep", "IMG_nueva.jpg",
                    f"{folio}/ine_rep-112233445566.jpg", tam=777777)
ok("ine_rep" not in q.get_caso(folio)["marcas"], "al resubir uno distinto, el señalamiento se borra solo")

print("\n== 8. Autorización de un ALTA: una firma ==")
llena_todo(token, clave_alta)
e.enviar_expediente(token, clave_alta)
for d in q.get_caso(folio)["docsAplicables"] if "docsAplicables" in q.get_caso(folio) else []:
    pass
for d in c.docs_aplicables("alta", q.get_caso(folio)["docs"], "Moral"):
    e.marcar_documento(folio, d["id"], True, "", ADMIN)
e.señalar_campo(folio, "telefono", "aún pendiente", ADMIN)
rompe(lambda: e.pasar_a_autorizacion(folio, ADMIN), "señalado", "un campo señalado frena el paso a firmas")
marcas = q.get_caso(folio)["marcas"]
marcas.pop("campo:telefono")
e._fija_campos(folio, {"marcas": marcas}, q.get_caso(folio))
e.pasar_a_autorizacion(folio, ADMIN)
ok(q.get_caso(folio)["estado"] == "por_autorizar", "con todo revisado, pasa a firmas")
rompe(lambda: e.firmar(folio, 2, FIRMA2A, ADMIN, "Motivo de prueba de la firma"), "una sola firma", "un alta no admite nivel 2")
rompe(lambda: e.firmar(folio, 1, SIN_NIVEL, ADMIN, "Motivo de prueba de la firma"), "no está habilitado", "quien no tiene nivel 1 no firma")
e.firmar(folio, 1, FIRMA1, ADMIN, "Motivo de prueba de la firma")
ok(q.get_caso(folio)["estado"] == "autorizada", "con una firma, el alta queda autorizada")
rompe(lambda: e.firmar(folio, 1, FIRMA1, ADMIN, "Motivo de prueba de la firma"), "no está en autorización", "cerrada, ya no admite firmas")

print("\n== 9. Autorización de un CRÉDITO: 1 + 2 firmas ==")
fc, kc = caso_cred["folio"], clave_cred
tc = caso_cred["token"]
e.verificar_clave(tc, kc)
llena_todo(tc, kc)
e.enviar_expediente(tc, kc)
for d in c.docs_aplicables("credito", caso_cred["docs"], "Moral"):
    e.marcar_documento(fc, d["id"], True, "", ADMIN)
e.pasar_a_autorizacion(fc, ADMIN)
rompe(lambda: e.firmar(fc, 2, FIRMA2A, ADMIN, "Motivo de prueba de la firma"), "falta la firma de nivel 1",
      "el nivel 2 no puede firmarse antes que el nivel 1")
e.firmar(fc, 1, FIRMA1, ADMIN, "Motivo de prueba de la firma")
ok(q.get_caso(fc)["estado"] == "por_autorizar", "con nivel 1 el crédito sigue sin autorizarse")
rompe(lambda: e.firmar(fc, 1, FIRMA2A, ADMIN, "Motivo de prueba de la firma"), "ya está firmado", "el nivel 1 no se firma dos veces")
rompe(lambda: e.firmar(fc, 2, FIRMA1, ADMIN, "Motivo de prueba de la firma"), "ya firmó", "quien firmó nivel 1 no puede firmar nivel 2")
rompe(lambda: e.firmar(fc, 2, SIN_NIVEL, ADMIN, "Motivo de prueba de la firma"), "no está habilitado", "sin nivel 2 no firma")
e.firmar(fc, 2, FIRMA2A, ADMIN, "Motivo de prueba de la firma")
ok(q.get_caso(fc)["estado"] == "por_autorizar", "con una firma de nivel 2 todavía no basta")
rompe(lambda: e.firmar(fc, 2, FIRMA2A, ADMIN, "Motivo de prueba de la firma"), "ya firmó", "la misma persona no cubre las dos firmas del nivel 2")
e.firmar(fc, 2, FIRMA2B, ADMIN, "Motivo de prueba de la firma")
ok(q.get_caso(fc)["estado"] == "autorizada", "con 1 + 2 firmas el crédito queda autorizado")
ok(len(q.get_caso(fc)["autorizaciones"]) == 3, "quedan registradas las tres firmas")
ok(all(a.get("fecha") and a.get("nombre") for a in q.get_caso(fc)["autorizaciones"]),
   "cada firma guarda quién y cuándo")

print("\n== 9. Rechazo y bitácora ==")
caso_r, clave_r = e.crear_caso(nueva("alta"), VENTAS)
rompe(lambda: e.rechazar(caso_r["folio"], "", ADMIN), "motivo", "no deja rechazar sin motivo")
e.rechazar(caso_r["folio"], "Las referencias no confirmaron la relación.", ADMIN)
ok(q.get_caso(caso_r["folio"])["estado"] == "rechazada", "el rechazo cierra el expediente")
rompe(lambda: e.verificar_clave(caso_r["token"], clave_r), "cerró", "cerrado, el cliente ya no entra")

logs = MEM.logs(folio)
acciones = [l["accion"] for l in logs]
ok("creada" in acciones and "acceso" in acciones and "acceso-fallido" in acciones,
   "la bitácora registra creación, accesos y fallos")
ok("devuelta" in acciones and "firma" in acciones, "y también devoluciones y firmas")
ok(any(l["accion"] == "captura-parcial" for l in logs),
   "deja constancia de los campos descartados, no los tira en silencio")
ok(all(l.get("cuandoLegible") and "/" in l["cuandoLegible"] for l in logs),
   "cada renglón trae la hora de México en formato legible")

print("\n== 10. Avance ==")
a = c.avance(q.get_caso(fc))
ok(0 < a["pct"] <= 100, f"el avance del crédito completo es creíble: {a['hechos']}/{a['total']} = {a['pct']}%")
vacio = c.avance(q.get_caso(caso_r["folio"]))
ok(vacio["pct"] == 0, "un expediente recién creado arranca en 0%")

print("\n== 11. Análisis interno: comentarios y anexos ==")
COMITE = {"correo": "hsalgado@gpa.com.mx", "nombre": "Héctor Salgado", "rol": c.ROL_COMITE}
fa = caso_alta["folio"]

rompe(lambda: e.agregar_comentario(fa, "   ", COMITE), "escriba el comentario",
      "un comentario vacío se rechaza")
e.agregar_comentario(fa, "Hablé con dos referencias: 3 años sin atrasos.", COMITE)
hilo = q.comentarios(fa)
ok(any("dos referencias" in m["texto"] for m in hilo), "el comentario queda en el hilo")
ok(all(m.get("nombre") and m.get("rol") and m.get("cuandoLegible") for m in hilo),
   "cada comentario dice quién, con qué rol y cuándo")

# Ventas comenta aunque no pueda firmar.
ok(c.puede(c.ROL_VENTAS, "comentar") and not c.puede(c.ROL_VENTAS, "autorizar"),
   "Ventas comenta y anexa, pero no firma")
ok(not c.puede(c.ROL_CONSULTA, "comentar"), "Consulta sigue siendo solo lectura")

rompe(lambda: e.agregar_anexo(fa, "buro.pdf", f"{fa}/interno-aabbccddeeff.pdf", 9000, "", COMITE),
      "escriba qué es", "un anexo sin descripción se rechaza")
e.agregar_anexo(fa, "buro.pdf", f"{fa}/interno-aabbccddeeff.pdf", 9000,
                "Reporte de buró de crédito", COMITE)
caso_fa = q.get_caso(fa)
ok(len(e.anexos_de(caso_fa)) == 1, "el anexo interno se guarda")

# LA regla que importa: el anexo interno NO puede acabar entre los adjuntos,
# porque la vista del cliente entrega ese mapa completo, con enlaces de descarga.
ok(not any(k.startswith("anexo:") for k in (caso_fa.get("adjuntos") or {})),
   "los anexos internos NO están en «adjuntos»: el cliente no los puede ver")
ok("anexos" in caso_fa and isinstance(caso_fa["anexos"], dict),
   "viven en su propio campo «anexos»")

aid = e.anexos_de(caso_fa)[0]["id"]
e.quitar_anexo(fa, aid, COMITE)
ok(not e.anexos_de(q.get_caso(fa)), "un anexo se puede quitar si se subió por error")

print("\n== 12. La firma exige su motivo ==")
caso_f, clave_f = e.crear_caso(nueva("credito"), ADMIN)
tf, ff = caso_f["token"], caso_f["folio"]
e.verificar_clave(tf, clave_f)
llena_todo(tf, clave_f)
e.enviar_expediente(tf, clave_f)
for d in c.docs_aplicables("credito", caso_f["docs"], "Moral"):
    e.marcar_documento(ff, d["id"], True, "", ADMIN)
e.pasar_a_autorizacion(ff, ADMIN)

rompe(lambda: e.firmar(ff, 1, FIRMA1, ADMIN, ""), "motivo de su firma",
      "no se puede firmar sin escribir el motivo")
rompe(lambda: e.firmar(ff, 1, FIRMA1, ADMIN, "   "), "motivo de su firma",
      "ni con espacios en blanco")
e.firmar(ff, 1, FIRMA1, ADMIN, "Línea de 250,000 contra pagaré; revisar a los 6 meses.")
firma = q.get_caso(ff)["autorizaciones"][0]
ok(firma.get("comentario", "").startswith("Línea de 250,000"),
   "el motivo queda pegado a la firma")
hilo_f = q.comentarios(ff)
ok(any(m.get("tipo") == "firma-n1" for m in hilo_f),
   "y la firma también entra al hilo, para leer el expediente de corrido")

e.rechazar(ff, "Las referencias no confirmaron la relación.", ADMIN)
ok(any(m.get("tipo") == "rechazo" for m in q.comentarios(ff)),
   "el rechazo también queda en el hilo, con su motivo")

print("\n== 13. Clientes que no se pueden dar de alta ==")



ok(c.puede(c.ROL_ADMIN, "veto") and not c.puede(c.ROL_COMITE, "veto"),
   "solo el Administrador administra la lista de vetados")

for malo, desc in [({"razonSocial": ""}, "sin nombre ni RFC"), ({"rfc": "VET010101AB1"}, "sin motivo")]:
    try:
        v.agregar(malo, ADMIN)
        ok(False, f"deja agregar {desc} <<< no debería")
    except ValueError as ex:
        ok(True, f"no deja agregar {desc}: «{str(ex)[:40]}…»")

v.agregar({"razonSocial": "Distribuidora Moroso, S.A. de C.V.",
           "nombreComercial": "Moroso", "rfc": "DMO150301XY4",
           "correo": "pagos@moroso.mx", "celular": "33 9999 8888",
           "motivo": "Cartera incobrable desde 2024, pasó a jurídico."}, ADMIN)
ok(len(v.listar()) == 1, "queda en la lista")

# ── Lo idéntico bloquea, aunque venga escrito distinto ──
def prospecto(**extra):
    return {**nueva("alta"), "razonSocial": "Empresa Cualquiera", "rfc": "ECU010101AB1", **extra}

rompe(lambda: e.crear_caso(prospecto(rfc="dmo-150301-xy4"), VENTAS), "no se pueden dar de alta",
      "el mismo RFC con guiones no pasa")
rompe(lambda: e.crear_caso(prospecto(razonSocial="DISTRIBUIDORA MOROSO S DE RL DE CV"), VENTAS),
      "no se pueden dar de alta", "el mismo nombre con otra forma societaria tampoco")
rompe(lambda: e.crear_caso(prospecto(celular="+52 33 9999 8888"), VENTAS),
      "no se pueden dar de alta", "ni el mismo celular con lada de país")
rompe(lambda: e.crear_caso(prospecto(correo="Pagos@Moroso.MX"), VENTAS),
      "no se pueden dar de alta", "ni el mismo correo en mayúsculas")

# ── Parecido: avisa, pero deja pasar ──
casi = e.crear_caso(prospecto(razonSocial="Distribuidora Moroso del Norte, S.A. de C.V."), VENTAS)[0]
ok(casi["folio"], "un nombre parecido SÍ deja crear la solicitud")
ok(casi.get("avisosVeto"), "pero queda el aviso guardado en el expediente")
ok(any(l["accion"] == "veto-aviso" for l in MEM.logs(casi["folio"])),
   "y también en la bitácora")

# ── El levantamiento es solo del Administrador, y con motivo ──
rompe(lambda: e.crear_caso({**prospecto(rfc="DMO150301XY4"), "omitirVeto": True,
                            "motivoVeto": "Yo digo que sí"}, VENTAS),
      "pídale a un administrador", "Ventas no puede levantar el bloqueo")
rompe(lambda: e.crear_caso({**prospecto(rfc="DMO150301XY4"), "omitirVeto": True}, ADMIN),
      "tiene que escribir por qué", "ni el Administrador sin escribir el motivo")

levantado = e.crear_caso({**prospecto(rfc="DMO150301XY4"), "omitirVeto": True,
                          "motivoVeto": "Homónimo confirmado con Crédito; otro domicilio."},
                         ADMIN)[0]
ok(levantado["vetoOmitido"]["motivo"].startswith("Homónimo"),
   "con motivo, el Administrador sí puede, y el motivo queda en el expediente")
ok(levantado["vetoOmitido"]["quien"] == ADMIN["correo"], "con su nombre")
ok(any(l["accion"] == "veto-omitido" for l in MEM.logs(levantado["folio"])),
   "y en la bitácora, para poder explicarlo después")

# ── Salir de la lista ──
vid = v.listar()[0]["id"]
try:
    v.quitar(vid, "", ADMIN)
    ok(False, "deja quitar sin motivo <<< no debería")
except ValueError:
    ok(True, "no deja sacar de la lista sin escribir por qué")
v.quitar(vid, "Liquidó su adeudo el 15/09/2026.", ADMIN)
ok(not v.listar(), "sale de la lista")
ok(len(v.listar(solo_activos=False)) == 1, "pero no se borra: queda el registro de la baja")
libre = e.crear_caso(prospecto(rfc="DMO150301XY4"), VENTAS)[0]
ok(libre["folio"], "y ya se le puede dar de alta con normalidad")

print("\n" + "=" * 62)
if FALLAS:
    print(f"FALLAS ({len(FALLAS)}) de {TOTAL} comprobaciones:")
    for i, f in enumerate(FALLAS, 1):
        print(f"  {i}. {f}")
    sys.exit(1)
print(f"Sin fallas. {TOTAL} comprobaciones sobre la lógica real.")
