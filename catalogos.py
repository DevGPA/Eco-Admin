# catalogos.py — GPA Alta de Clientes
# Fuente ÚNICA de verdad de: régimen fiscal del SAT, tipos de solicitud,
# módulos con sus campos, y documentos. El frontend los pide por GET /catalogos
# y arma las pantallas con esto; nunca los duplica.
# ─────────────────────────────────────────────────────────────────
# Origen de los datos:
#   - REGIMENES: catálogo c_RegimenFiscal del SAT (Anexo 20).
#   - MODULOS y DOCUMENTOS: formatos vigentes de GPA
#       PNO-VE01-F3        Solicitud Alta Cliente Distribuidor
#       CYC-FT-001 Rev.03  Solicitud de Crédito
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

# ── Régimen fiscal (SAT · c_RegimenFiscal) ───────────────────────
# t: "F" solo persona física · "M" solo persona moral · "FM" ambas
REGIMENES = [
    {"c": "601", "n": "General de Ley Personas Morales", "t": "M"},
    {"c": "603", "n": "Personas Morales con Fines no Lucrativos", "t": "M"},
    {"c": "605", "n": "Sueldos y Salarios e Ingresos Asimilados a Salarios", "t": "F"},
    {"c": "606", "n": "Arrendamiento", "t": "F"},
    {"c": "607", "n": "Régimen de Enajenación o Adquisición de Bienes", "t": "F"},
    {"c": "608", "n": "Demás ingresos", "t": "F"},
    {"c": "610", "n": "Residentes en el Extranjero sin Establecimiento Permanente en México", "t": "FM"},
    {"c": "611", "n": "Ingresos por Dividendos (socios y accionistas)", "t": "F"},
    {"c": "612", "n": "Personas Físicas con Actividades Empresariales y Profesionales", "t": "F"},
    {"c": "614", "n": "Ingresos por intereses", "t": "F"},
    {"c": "615", "n": "Régimen de los ingresos por obtención de premios", "t": "F"},
    {"c": "616", "n": "Sin obligaciones fiscales", "t": "F"},
    {"c": "620", "n": "Sociedades Cooperativas de Producción que optan por diferir sus ingresos", "t": "M"},
    {"c": "621", "n": "Incorporación Fiscal", "t": "F"},
    {"c": "622", "n": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras", "t": "M"},
    {"c": "623", "n": "Opcional para Grupos de Sociedades", "t": "M"},
    {"c": "624", "n": "Coordinados", "t": "M"},
    {"c": "625", "n": "Actividades Empresariales con ingresos a través de Plataformas Tecnológicas", "t": "F"},
    {"c": "626", "n": "Régimen Simplificado de Confianza", "t": "FM"},
    {"c": "628", "n": "Hidrocarburos", "t": "M"},
    {"c": "629", "n": "Regímenes Fiscales Preferentes y Empresas Multinacionales", "t": "M"},
    {"c": "630", "n": "Enajenación de acciones en bolsa de valores", "t": "F"},
]
_REG_POR_CODIGO = {r["c"]: r for r in REGIMENES}


def regimen(codigo: str) -> dict | None:
    return _REG_POR_CODIGO.get(str(codigo or "").strip())


def persona_por_rfc(rfc: str) -> str:
    """El RFC manda: 12 caracteres = moral, 13 = física."""
    limpio = "".join(ch for ch in str(rfc or "") if ch.isalnum())
    if len(limpio) == 12:
        return "Moral"
    if len(limpio) == 13:
        return "Física"
    return ""


def persona_de(regimen_codigo: str, rfc: str) -> str:
    """Tipo de persona del cliente. En regímenes mixtos (610, 626) decide el RFC."""
    reg = regimen(regimen_codigo)
    if reg and reg["t"] == "M":
        return "Moral"
    if reg and reg["t"] == "F":
        return "Física"
    return persona_por_rfc(rfc) or "Moral"


def conflicto_regimen_rfc(regimen_codigo: str, rfc: str) -> str:
    """Texto del conflicto entre régimen y RFC, o cadena vacía si concuerdan."""
    reg = regimen(regimen_codigo)
    por_rfc = persona_por_rfc(rfc)
    if not reg or not por_rfc or reg["t"] == "FM":
        return ""
    por_reg = "Moral" if reg["t"] == "M" else "Física"
    if por_reg == por_rfc:
        return ""
    largo = len("".join(ch for ch in str(rfc) if ch.isalnum()))
    return (f"El régimen {reg['c']} es de persona {por_reg.lower()}, pero el RFC tiene "
            f"{largo} caracteres, que corresponde a persona {por_rfc.lower()}.")


# ── Catálogos de los formatos ────────────────────────────────────
CAT = {
    "giro": ["ALBERCAS", "TRAT. DE AGUA", "RECUBRIMIENTOS", "BOMBEO", "CALENTAMIENTO", "QUÍMICOS"],
    "clasificacion": ["1", "2", "3", "4", "5", "6"],
    "sucursal": ["GDL", "CANCÚN", "PTO VALLARTA", "CDMX", "MONTERREY", "LOS CABOS"],
    # Uso del CFDI: catálogo c_UsoCFDI del SAT, con la clave por delante para que
    # quien factura no tenga que adivinarla. De todo el catálogo solo aplican estas
    # tres al giro de GPA. S01 es el que usan los clientes que no deducen la compra.
    "uso": ["G01 · Adquisición de mercancías",
            "G03 · Gastos en general",
            "S01 · Sin efectos fiscales"],
    "forma": ["01 · Efectivo", "02 · Cheque", "03 · Transferencia",
              "04 · Tarjeta de crédito", "05 · Tarjeta de débito"],
    "metodo": ["PUE · Pago en una exhibición", "PPD · Pago en parcialidades o diferido"],
    "moneda": ["MXP", "USD"],
    "sino": ["Sí", "No"],
}

# ── Roles internos ───────────────────────────────────────────────
ROL_ADMIN = "Administrador"
ROL_COMITE = "Comité de Crédito"
ROL_VENTAS = "Ventas"
ROL_CONSULTA = "Consulta"
ROLES = [ROL_ADMIN, ROL_COMITE, ROL_VENTAS, ROL_CONSULTA]

# Grupo de Cognito → rol. El grupo es la autoridad; el atributo es informativo.
GRUPO_A_ROL = {
    "admin": ROL_ADMIN,
    "comite": ROL_COMITE,
    "ventas": ROL_VENTAS,
    "consulta": ROL_CONSULTA,
}
ROL_A_GRUPO = {v: k for k, v in GRUPO_A_ROL.items()}

PERMISOS = {
    "crear":     {ROL_ADMIN, ROL_VENTAS, ROL_COMITE},
    "revisar":   {ROL_ADMIN, ROL_VENTAS, ROL_COMITE},
    "autorizar": {ROL_ADMIN, ROL_COMITE},
    # Ventas conoce al cliente y suele tener contexto util, asi que comenta y
    # anexa, pero sigue sin poder firmar.
    "comentar":  {ROL_ADMIN, ROL_COMITE, ROL_VENTAS},
    "usuarios":  {ROL_ADMIN},
}


def puede(rol: str, accion: str) -> bool:
    return rol in PERMISOS.get(accion, set())


# ── Módulos del formulario ───────────────────────────────────────
# w: ancho en la cuadrícula de 6 columnas — full(6) · half(3) · third(2)
MODULOS = [
    {
        "id": "fiscal",
        "nombre": "Fiscal y facturación",
        "desc": "Domicilio fiscal, contacto de facturación y datos del CFDI.",
        "campos": [
            {"k": "correo_fact", "l": "Correo para facturación", "w": "half", "req": True,
             "ph": "facturacion@empresa.mx", "tipo": "email"},
            {"k": "calle", "l": "Calle y número", "w": "full", "req": True},
            {"k": "colonia", "l": "Colonia", "w": "half", "req": True},
            {"k": "cp", "l": "C.P.", "w": "third", "req": True, "mono": True, "tipo": "cp"},
            {"k": "ciudad", "l": "Ciudad", "w": "third", "req": True},
            {"k": "municipio", "l": "Municipio", "w": "third"},
            {"k": "estado_dom", "l": "Estado", "w": "third", "req": True},
            {"k": "pais", "l": "País", "w": "third", "fijo": "México"},
            {"k": "telefono", "l": "Teléfono", "w": "third", "req": True, "mono": True, "tipo": "tel",
             "ph": "33 1234 5678"},
            {"k": "telefono2", "l": "Teléfono 2", "w": "third", "mono": True, "tipo": "tel"},
            {"k": "web", "l": "Página web", "w": "third"},
            {"k": "uso", "l": "Uso del CFDI", "w": "third", "req": True, "opts": CAT["uso"]},
            {"k": "forma", "l": "Forma de pago", "w": "third", "req": True, "opts": CAT["forma"]},
            {"k": "metodo", "l": "Método de pago", "w": "third", "req": True, "opts": CAT["metodo"]},
        ],
    },
    {
        "id": "entrega",
        "nombre": "Entrega y horarios",
        "desc": "Dónde, a qué hora y con quién se entrega la mercancía.",
        "campos": [
            {"k": "mismo_dom", "l": "El domicilio de entrega es el mismo que el fiscal",
             "w": "full", "tipo": "check"},
            {"k": "e_calle", "l": "Calle y número", "w": "full"},
            {"k": "e_colonia", "l": "Colonia", "w": "half"},
            {"k": "e_municipio", "l": "Municipio", "w": "half"},
            {"k": "e_cp", "l": "C.P.", "w": "third", "mono": True, "tipo": "cp"},
            {"k": "e_ciudad", "l": "Ciudad", "w": "third"},
            {"k": "e_estado", "l": "Estado", "w": "third"},
            {"k": "e_contacto", "l": "Nombre del contacto que recibe", "w": "half", "req": True},
            {"k": "e_celular", "l": "Celular de contacto", "w": "half", "req": True,
             "mono": True, "tipo": "tel"},
            {"k": "e_email", "l": "Correo del contacto", "w": "half", "tipo": "email"},
            {"k": "lv_ini", "l": "Entrega L–V desde", "w": "third", "req": True, "tipo": "hora"},
            {"k": "lv_fin", "l": "Entrega L–V hasta", "w": "third", "req": True, "tipo": "hora"},
            {"k": "comida_ini", "l": "Comida desde", "w": "third", "tipo": "hora"},
            {"k": "comida_fin", "l": "Comida hasta", "w": "third", "tipo": "hora"},
            {"k": "sab_ini", "l": "Sábado desde", "w": "third", "tipo": "hora"},
            {"k": "sab_fin", "l": "Sábado hasta", "w": "third", "tipo": "hora"},
        ],
    },
    {
        "id": "contactos",
        "nombre": "Contactos",
        "desc": "Las personas con las que GPA trata todos los días.",
        "roles": ["Director general", "Encargado de garantías", "Encargado de compras",
                  "Gerente o encargado de ventas", "Encargado de pagos",
                  "Quién especifica producto y marca"],
    },
    {
        "id": "credito",
        "nombre": "Crédito",
        "desc": "Monto solicitado, bancos, referencias comerciales y perfil del negocio.",
        "campos": [
            # Lo captura GPA en la pre-solicitud. El cliente lo ve, no lo cambia.
            {"k": "monto", "l": "Monto de crédito requerido", "w": "half",
             "mono": True, "fijoDe": "montoRequerido"},
            {"k": "moneda", "l": "Moneda", "w": "third", "req": True, "opts": CAT["moneda"]},
            {"k": "dias_pago", "l": "Días de pago", "w": "third", "ph": "Martes y jueves"},
            {"k": "revision_fact", "l": "Revisión de facturas", "w": "third", "ph": "Lunes de 9 a 14 h"},
            {"k": "sucursales", "l": "No. de sucursales", "w": "third", "mono": True},
            {"k": "empleados", "l": "No. de empleados", "w": "third", "mono": True},
            {"k": "extranjero", "l": "¿Compra en el extranjero?", "w": "third", "opts": CAT["sino"]},
            {"k": "extranjero_pct", "l": "% de sus compras", "w": "third", "mono": True},
            {"k": "personal_ventas", "l": "Personal de ventas", "w": "third", "mono": True},
            {"k": "tecnicos", "l": "Técnicos", "w": "third", "mono": True},
            {"k": "marcas", "l": "Marcas con las que trabaja hoy (al menos 6)",
             "w": "full", "tipo": "area", "req": True},
        ],
        "tablas": [
            {"k": "bancos", "l": "Bancos con los que opera",
             "cols": ["Banco", "No. de cuenta", "Sucursal", "Ciudad"], "n": 2},
            {"k": "proveedores", "l": "¿Con quién compra a crédito hoy?",
             "cols": ["Proveedor", "Teléfono", "Persona que atiende", "Ciudad"], "n": 3, "req": True},
            {"k": "obligados", "l": "Obligados solidarios",
             "cols": ["Nombre", "Domicilio", "Teléfono"], "n": 2},
        ],
    },
    {
        "id": "buro",
        "nombre": "Autorización de buró de crédito",
        "desc": "Consulta en Trans Union de México y Dun & Bradstreet. Vigencia de 5 años.",
        "campos": [
            {"k": "b_rep", "l": "Nombre del representante legal que firma", "w": "full", "req": True},
            {"k": "b_acepto",
             "l": ("Autorizo a GPA a consultar mi historial crediticio en Trans Union de México "
                   "y Dun & Bradstreet, y reconozco que esta autorización estará vigente 5 años."),
             "w": "full", "tipo": "check", "req": True},
        ],
    },
]
_MOD_POR_ID = {m["id"]: m for m in MODULOS}


def modulo(mid: str) -> dict | None:
    return _MOD_POR_ID.get(mid)


def campos_de(mod: dict) -> list:
    """Campos reales de un módulo. 'contactos' se expande a 6 roles x 3 campos."""
    if mod["id"] != "contactos":
        return mod.get("campos", [])
    out = []
    for i, rol in enumerate(mod["roles"]):
        out.append({"k": f"c{i}_nombre", "l": rol, "w": "half", "req": i < 3})
        out.append({"k": f"c{i}_cel", "l": "Celular", "w": "third", "mono": True, "tipo": "tel"})
        out.append({"k": f"c{i}_mail", "l": "Correo", "w": "third", "tipo": "email"})
    return out


# ── Documentos (15 únicos: 5 del alta + 13 del crédito − 3 repetidos) ──
# "de" dice de QUIÉN es el documento. El cliente confundía el INE del
# representante con el del aval; agrupados y con color se distinguen de un vistazo.
DOCUMENTOS = [
    # ── De la empresa ──
    {"id": "alta_hacienda", "n": "Alta de Hacienda o modificación de alta", "t": "PDF", "de": "empresa"},
    {"id": "comp_dom", "n": "Comprobante de domicilio fiscal", "t": "PDF", "de": "empresa"},
    {"id": "fotos_negocio", "n": "Fotos del negocio e interiores", "t": "JPG", "de": "empresa"},
    {"id": "publicidad", "n": "Publicidad, cuando no hay exhibición", "t": "JPG", "de": "empresa"},
    {"id": "csf", "n": "Constancia de Situación Fiscal, no mayor a 3 meses", "t": "PDF", "de": "empresa"},
    {"id": "acta_const", "n": "Acta constitutiva", "t": "PDF", "pm": True, "de": "empresa"},
    {"id": "edos_cuenta", "n": "Estados de cuenta bancarios de los últimos 3 meses",
     "t": "PDF", "de": "empresa"},
    # ── Del apoderado o representante legal ──
    {"id": "ine_rep", "n": "INE del apoderado y/o representante legal", "t": "JPG", "de": "representante"},
    {"id": "comp_dom_dueno",
     "n": "Comprobante de domicilio del apoderado y/o representante legal",
     "t": "PDF", "de": "representante"},
    # ── Del obligado solidario (aval) ──
    {"id": "ine_aval", "n": "INE del obligado solidario (aval)", "t": "JPG", "de": "aval"},
    {"id": "comp_dom_aval", "n": "Comprobante de domicilio del obligado solidario (aval)",
     "t": "PDF", "de": "aval"},
]
_DOC_POR_ID = {d["id"]: d for d in DOCUMENTOS}


def documento(did: str) -> dict | None:
    return _DOC_POR_ID.get(did)


# ── De quién es cada documento ───────────────────────────────────
# El nombre del grupo va escrito; el color solo lo refuerza.
GRUPOS_DOC = {
    "empresa":       {"n": "De la empresa", "c": "#185FA5",
                      "d": "Papeles del negocio y de su domicilio."},
    "representante": {"n": "Del dueño o representante legal", "c": "#6D4AA0",
                      "d": "De la persona que firma por la empresa."},
    "aval":          {"n": "Del aval y obligados solidarios", "c": "#0D6E6E",
                      "d": "De quienes responden si el cliente no paga."},
}
ORDEN_GRUPOS = ["empresa", "representante", "aval"]

# Documento libre: para lo que el cliente crea util y no este en la lista.
ID_OTRO = "otro"
OTRO = {"id": ID_OTRO, "n": "Otro documento", "t": "PDF", "de": "empresa", "opcional": True}


# ── Tipos de solicitud: alta y crédito van SIEMPRE por separado ──
TIPOS = {
    "alta": {
        "id": "alta",
        "nombre": "Alta de cliente",
        "corto": "ALTA",
        "formato": "PNO-VE01-F3",
        "desc": "Datos maestros del cliente para facturarle y entregarle.",
        "modulos": ["fiscal", "entrega", "contactos"],
        "docs": ["alta_hacienda", "ine_rep", "comp_dom", "fotos_negocio", "publicidad"],
        "autoriza": "simple",      # 1 firma del Comité de Crédito
    },
    "credito": {
        "id": "credito",
        "nombre": "Solicitud de crédito",
        "corto": "CRÉDITO",
        "formato": "CYC-FT-001 Rev.03",
        "desc": "Línea de crédito: referencias, bancos, avales y buró.",
        "modulos": ["fiscal", "credito", "buro"],
        # Los 8 del expediente de crédito, en el orden en que los pide GPA.
        "docs": ["csf", "comp_dom", "acta_const", "ine_rep", "ine_aval",
                 "comp_dom_dueno", "comp_dom_aval", "edos_cuenta"],
        "autoriza": "dosNiveles",  # nivel 1: 1 firma · nivel 2: 2 firmas distintas
    },
}

FIRMAS_REQUERIDAS = {"simple": 1, "dosNiveles": 3}

# ── Estados del expediente ───────────────────────────────────────
ESTADOS = {
    "borrador":      {"t": "Borrador",     "c": "p-borrador"},
    "enviada":       {"t": "Enviada",      "c": "p-enviada"},
    "captura":       {"t": "En captura",   "c": "p-captura"},
    "recibida":      {"t": "Recibida",     "c": "p-recibida"},
    "devuelta":      {"t": "Devuelta",     "c": "p-devuelta"},
    "por_autorizar": {"t": "Por autorizar", "c": "p-autorizar"},
    "autorizada":    {"t": "Autorizada",   "c": "p-autorizada"},
    "rechazada":     {"t": "Rechazada",    "c": "p-rechazada"},
}
ESTADOS_CERRADOS = {"autorizada", "rechazada"}
# El cliente solo puede escribir cuando el caso está en uno de estos estados.
ESTADOS_ABIERTOS_AL_CLIENTE = {"enviada", "captura", "devuelta"}


def docs_aplicables(tipo_id: str, docs_pedidos: dict, persona: str) -> list:
    """Documentos que de verdad se le piden a este cliente, en el orden del tipo."""
    tipo = TIPOS.get(tipo_id) or TIPOS["alta"]
    out = []
    for did in tipo["docs"]:
        d = documento(did)
        if not d or not docs_pedidos.get(did):
            continue
        if d.get("pm") and persona == "Física":
            continue
        out.append(d)
    return out


def modulos_activos(tipo_id: str, modulos_pedidos: dict) -> list:
    tipo = TIPOS.get(tipo_id) or TIPOS["alta"]
    return [modulo(mid) for mid in tipo["modulos"] if modulos_pedidos.get(mid)]


def avance(caso: dict) -> dict:
    """Puntos cubiertos / puntos pedidos. Cuenta campos obligatorios y documentos."""
    total = hechos = 0
    valores = caso.get("valores") or {}
    tablas = caso.get("tablasVal") or {}
    adjuntos = caso.get("adjuntos") or {}
    for m in modulos_activos(caso.get("tipo"), caso.get("modulos") or {}):
        for f in campos_de(m):
            if not f.get("req"):
                continue
            total += 1
            v = valores.get(f["k"])
            lleno = (v is True) if f.get("tipo") == "check" else bool(str(v or "").strip())
            if lleno:
                hechos += 1
        for t in m.get("tablas", []):
            if not t.get("req"):
                continue
            total += 1
            if str(tablas.get(f"{t['k']}_0_0") or "").strip():
                hechos += 1
    persona = persona_de(caso.get("regimen"), caso.get("rfc"))
    for d in docs_aplicables(caso.get("tipo"), caso.get("docs") or {}, persona):
        total += 1
        if adjuntos.get(d["id"]):
            hechos += 1
    return {"total": total, "hechos": hechos,
            "pct": round(hechos / total * 100) if total else 0}


def catalogos_publicos() -> dict:
    """Lo que el frontend necesita para dibujar las pantallas."""
    return {
        "regimenes": REGIMENES,
        "cat": CAT,
        "roles": ROLES,
        "grupoARol": GRUPO_A_ROL,
        "modulos": MODULOS,
        "documentos": DOCUMENTOS,
        "gruposDoc": GRUPOS_DOC,
        "ordenGrupos": ORDEN_GRUPOS,
        "otro": OTRO,
        "tipos": TIPOS,
        "estados": ESTADOS,
        "firmasRequeridas": FIRMAS_REQUERIDAS,
    }


# ── Validacion de lo que captura el cliente ──────────────────────
# Vive aqui, junto a la definicion de los campos, para que no se separen.
import re as _re

_RE_CORREO = _re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def solo_digitos(valor) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def revisa_campo(f: dict, valor) -> str:
    """Devuelve el problema del valor, o cadena vacia si esta bien.

    El mensaje se le muestra tal cual a quien captura, asi que explica que
    corregir, no que regla se rompio.
    """
    tipo = f.get("tipo", "")
    texto = "" if valor is None else str(valor).strip()

    if tipo == "check":
        return "" if valor is True or not f.get("req") else "Falta marcar esta casilla."
    if not texto:
        return "Falta llenar este dato." if f.get("req") else ""

    if tipo == "tel":
        d = solo_digitos(texto)
        if len(d) < 10:
            return f"El teléfono va con 10 dígitos, incluida la clave de la ciudad. Escribió {len(d)}."
        if len(d) > 13:
            return "Ese teléfono trae demasiados dígitos."
    elif tipo == "email":
        if not _RE_CORREO.match(texto):
            return "Ese correo no parece válido. Revise que lleve arroba y dominio."
    elif tipo == "cp":
        d = solo_digitos(texto)
        if len(d) != 5:
            return f"El código postal va con 5 dígitos. Escribió {len(d)}."
    elif tipo == "hora":
        if not _re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", texto):
            return "La hora va como 08:00 o 17:30."
    elif tipo == "monto":
        if not solo_digitos(texto):
            return "El monto va en números."
    return ""


def revisa_captura(caso: dict) -> dict:
    """Todos los problemas del expediente: {clave del campo: que corregir}."""
    problemas = {}
    valores = caso.get("valores") or {}
    for m in modulos_activos(caso.get("tipo"), caso.get("modulos") or {}):
        for f in campos_de(m):
            if campo_fijo(f):
                continue
            problema = revisa_campo(f, valores.get(f["k"]))
            if problema:
                problemas[f["k"]] = problema
    return problemas


def etiquetas_campos(caso: dict) -> dict:
    """{clave del campo: su etiqueta}. Para poder nombrar lo que falta."""
    out = {}
    for m in modulos_activos(caso.get("tipo"), caso.get("modulos") or {}):
        for f in campos_de(m):
            out[f["k"]] = f["l"]
    return out


def campo_fijo(f: dict) -> bool:
    """¿Lo pone el sistema en vez del cliente?"""
    return bool(f.get("fijo") or f.get("fijoDe"))


def valores_fijos(caso: dict) -> dict:
    """Campos que el sistema fija solo y el cliente no puede cambiar.

    "fijo" es un valor constante (País = México). "fijoDe" toma el valor de un
    dato del propio expediente que captura GPA (el monto requerido del crédito).
    """
    fijos = {}
    for m in modulos_activos(caso.get("tipo"), caso.get("modulos") or {}):
        for f in campos_de(m):
            if f.get("fijo"):
                fijos[f["k"]] = f["fijo"]
            elif f.get("fijoDe"):
                valor = caso.get(f["fijoDe"])
                if valor not in (None, ""):
                    fijos[f["k"]] = valor
    return fijos
