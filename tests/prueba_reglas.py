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
import catalogos as c                                   # noqa: E402

MEM = TablaMemoria()
q.tabla = lambda: MEM
e.tabla = lambda: MEM

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
        "modulos": modulos or {m: True for m in T["modulos"]},
        "docs": docs or {d: True for d in T["docs"]},
    }


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
ok(len(caso_cred["docs"]) == 13, "un crédito guarda sus 13 documentos")
ok(caso_cred["folio"] != caso_alta["folio"], "los folios no se repiten")

# Los documentos y secciones NO se eligen: van completos por tipo de solicitud.
recortado = nueva("credito")
recortado["docs"] = {"csf": True}                 # la pantalla manda solo uno
recortado["modulos"] = {"fiscal": True}           # y una sola sección
caso_r, _ = e.crear_caso(recortado, ADMIN)
ok(set(caso_r["docs"]) == set(c.TIPOS["credito"]["docs"]) and all(caso_r["docs"].values()),
   "aunque la pantalla mande 1 documento, el servidor pone los 13 del tipo")
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

print("\n== 2. Régimen del SAT decide los documentos ==")
fis = nueva("credito", regimen="612", rfc="CAGR850101AB1")
caso_fis, clave_fis = e.crear_caso(fis, VENTAS)
aplic_fis = c.docs_aplicables("credito", caso_fis["docs"], c.persona_de("612", "CAGR850101AB1"))
aplic_mor = c.docs_aplicables("credito", caso_cred["docs"], c.persona_de("601", "ASV180412H23"))
ok(len(aplic_mor) - len(aplic_fis) == 2, f"persona física pide 2 documentos menos ({len(aplic_fis)} vs {len(aplic_mor)})")
ok(all(d["id"] not in ("acta_const", "poder") for d in aplic_fis), "sin acta constitutiva ni poder notarial")
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

print("\n== 6. Envío, revisión y devolución ==")
for d in c.TIPOS["alta"]["docs"]:
    if q.get_caso(folio)["docs"].get(d):
        e.registrar_adjunto(token, clave_alta, d, f"{d}.pdf", f"{folio}/{d}-aabbccddeeff.pdf")
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
ok(g["valores"]["calle"] == "Av. Vallarta 3020", "y NO deja tocar lo que ya estaba aceptado")

rompe(lambda: e.registrar_adjunto(token, clave_alta, "comp_dom", "x.pdf", "k"),
      "ya fue aceptado", "devuelto, no deja reemplazar un documento que estaba bien")
e.registrar_adjunto(token, clave_alta, "ine_rep", "IMG_nueva.jpg", f"{folio}/ine_rep-112233445566.jpg")
ok("ine_rep" not in q.get_caso(folio)["marcas"], "al resubir, el señalamiento se borra solo")

print("\n== 7. Autorización de un ALTA: una firma ==")
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
rompe(lambda: e.firmar(folio, 2, FIRMA2A, ADMIN), "una sola firma", "un alta no admite nivel 2")
rompe(lambda: e.firmar(folio, 1, SIN_NIVEL, ADMIN), "no está habilitado", "quien no tiene nivel 1 no firma")
e.firmar(folio, 1, FIRMA1, ADMIN)
ok(q.get_caso(folio)["estado"] == "autorizada", "con una firma, el alta queda autorizada")
rompe(lambda: e.firmar(folio, 1, FIRMA1, ADMIN), "no está en autorización", "cerrada, ya no admite firmas")

print("\n== 8. Autorización de un CRÉDITO: 1 + 2 firmas ==")
fc, kc = caso_cred["folio"], clave_cred
tc = caso_cred["token"]
e.verificar_clave(tc, kc)
for d in c.docs_aplicables("credito", caso_cred["docs"], "Moral"):
    e.registrar_adjunto(tc, kc, d["id"], f"{d['id']}.pdf", f"{fc}/{d['id']}-aabbccddeeff.pdf")
e.enviar_expediente(tc, kc)
for d in c.docs_aplicables("credito", caso_cred["docs"], "Moral"):
    e.marcar_documento(fc, d["id"], True, "", ADMIN)
e.pasar_a_autorizacion(fc, ADMIN)
rompe(lambda: e.firmar(fc, 2, FIRMA2A, ADMIN), "falta la firma de nivel 1",
      "el nivel 2 no puede firmarse antes que el nivel 1")
e.firmar(fc, 1, FIRMA1, ADMIN)
ok(q.get_caso(fc)["estado"] == "por_autorizar", "con nivel 1 el crédito sigue sin autorizarse")
rompe(lambda: e.firmar(fc, 1, FIRMA2A, ADMIN), "ya está firmado", "el nivel 1 no se firma dos veces")
rompe(lambda: e.firmar(fc, 2, FIRMA1, ADMIN), "ya firmó", "quien firmó nivel 1 no puede firmar nivel 2")
rompe(lambda: e.firmar(fc, 2, SIN_NIVEL, ADMIN), "no está habilitado", "sin nivel 2 no firma")
e.firmar(fc, 2, FIRMA2A, ADMIN)
ok(q.get_caso(fc)["estado"] == "por_autorizar", "con una firma de nivel 2 todavía no basta")
rompe(lambda: e.firmar(fc, 2, FIRMA2A, ADMIN), "ya firmó", "la misma persona no cubre las dos firmas del nivel 2")
e.firmar(fc, 2, FIRMA2B, ADMIN)
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

print("\n" + "=" * 62)
if FALLAS:
    print(f"FALLAS ({len(FALLAS)}) de {TOTAL} comprobaciones:")
    for i, f in enumerate(FALLAS, 1):
        print(f"  {i}. {f}")
    sys.exit(1)
print(f"Sin fallas. {TOTAL} comprobaciones sobre la lógica real.")
