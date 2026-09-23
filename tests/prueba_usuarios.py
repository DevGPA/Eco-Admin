# tests/prueba_usuarios.py — ejecuta el panel de usuarios REAL (auth_cognito.py).
# Uso:  PYTHONUTF8=1 python tests/prueba_usuarios.py
# ─────────────────────────────────────────────────────────────────
# Cognito se sustituye por un doble que se comporta como el de verdad en lo que
# aquí importa: en un pool con UsernameAttributes=[email], reasignar el atributo
# «email» de una cuenta que ya existe responde AliasExistsException.
# Lo que esto NO prueba: permisos de IAM, ni el retraso real de list_users.
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("USER_POOL_ID", "prueba")

from botocore.exceptions import ClientError                # noqa: E402
import auth_cognito as a                                   # noqa: E402
from catalogos import ROL_ADMIN, ROL_COMITE, ROL_VENTAS    # noqa: E402

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
    except a.CuentaInvalida as ex:
        bien = fragmento.lower() in str(ex).lower()
        print(f"  [{'ok' if bien else 'FALLA'}] {desc}")
        if not bien:
            FALLAS.append(f"{desc} — decía: {ex}")
        return
    print(f"  [FALLA] {desc} — no la rechazó")
    FALLAS.append(f"{desc} — no la rechazó")


# ═══════════════════════════════════════════════════════════════
# Doble de Cognito
# ═══════════════════════════════════════════════════════════════
class _NoExiste(Exception):
    pass


class _Excepciones:
    UserNotFoundException = _NoExiste


def _error(codigo, mensaje):
    return ClientError({"Error": {"Code": codigo, "Message": mensaje}}, "CognitoIdp")


class CognitoFalso:
    def __init__(self):
        self.cuentas = {}        # correo -> {"attrs": {}, "enabled": bool, "grupos": set()}
        self.exceptions = _Excepciones()
        self.updates = []        # cada admin_update_user_attributes, para poder revisarlo

    def _cuenta(self, correo):
        if correo not in self.cuentas:
            raise _NoExiste(correo)
        return self.cuentas[correo]

    # ── lectura ──
    def admin_get_user(self, UserPoolId, Username):
        c = self._cuenta(Username)
        return {"Username": Username, "Enabled": c["enabled"], "UserStatus": "CONFIRMED",
                "UserAttributes": [{"Name": k, "Value": v} for k, v in c["attrs"].items()]}

    def list_users(self, UserPoolId, Limit=None, PaginationToken=None):
        return {"Users": [
            {"Username": correo, "Enabled": c["enabled"], "UserStatus": "CONFIRMED",
             "Attributes": [{"Name": k, "Value": v} for k, v in c["attrs"].items()]}
            for correo, c in self.cuentas.items()]}

    def admin_list_groups_for_user(self, UserPoolId, Username):
        return {"Groups": [{"GroupName": g} for g in sorted(self._cuenta(Username)["grupos"])]}

    # ── escritura ──
    def admin_create_user(self, UserPoolId, Username, UserAttributes, **_):
        if Username in self.cuentas:
            raise _error("UsernameExistsException", "ya existe")
        self.cuentas[Username] = {"attrs": {a["Name"]: a["Value"] for a in UserAttributes},
                                  "enabled": True, "grupos": set()}
        return {}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        c = self._cuenta(Username)
        self.updates.append([a["Name"] for a in UserAttributes])
        # Así reacciona Cognito cuando el correo es el nombre de usuario.
        if any(a["Name"] == "email" for a in UserAttributes):
            raise _error("AliasExistsException",
                         "An account with the email already exists.")
        c["attrs"].update({a["Name"]: a["Value"] for a in UserAttributes})
        return {}

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):
        self._cuenta(Username)
        return {}

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):
        self._cuenta(Username)["grupos"].add(GroupName)
        return {}

    def admin_remove_user_from_group(self, UserPoolId, Username, GroupName):
        self._cuenta(Username)["grupos"].discard(GroupName)
        return {}

    def admin_enable_user(self, UserPoolId, Username):
        self._cuenta(Username)["enabled"] = True
        return {}

    def admin_disable_user(self, UserPoolId, Username):
        self._cuenta(Username)["enabled"] = False
        return {}


FALSO = CognitoFalso()
a.idp = lambda: FALSO
a.pool = lambda: "pool-de-prueba"


def alta(correo, nombre, rol, n1=False, n2=False, activo=True):
    return a.guardar_usuario({"correo": correo, "nombre": nombre, "rol": rol,
                              "n1": n1, "n2": n2, "activo": activo,
                              "password": "Provisional10"})


# ═══════════════════════════════════════════════════════════════
print("\n1. Crear cuentas")
# ═══════════════════════════════════════════════════════════════
oscar = alta("oscar@gpa.com.mx", "Oscar Cabrera", ROL_ADMIN, n1=True, n2=True)
ok(oscar["creado"] is True, "la cuenta nueva se marca como creada")
ok(oscar["rol"] == ROL_ADMIN, "el rol queda en el grupo de Cognito")
ok(oscar["n1"] and oscar["n2"], "los niveles de firma quedan guardados")
ok(FALSO.cuentas["oscar@gpa.com.mx"]["attrs"]["email"] == "oscar@gpa.com.mx",
   "al crear SÍ se manda el correo: es donde nace la cuenta")

ceci = alta("cecilia@gpa.com.mx", "Cecilia Medrano", ROL_VENTAS)
ok(ceci["rol"] == ROL_VENTAS, "la segunda cuenta entra como Ventas")

# ═══════════════════════════════════════════════════════════════
print("\n2. Cambiar el rol de una cuenta que ya existe  (el fallo reportado)")
# ═══════════════════════════════════════════════════════════════
FALSO.updates.clear()
ceci2 = a.guardar_usuario({"correo": "cecilia@gpa.com.mx", "nombre": "Cecilia Medrano",
                           "rol": ROL_COMITE, "n1": True, "n2": False, "activo": True})
ok(ceci2["creado"] is False, "no la vuelve a crear: la actualiza")
ok(ceci2["rol"] == ROL_COMITE, "el cambio de rol SÍ se aplica")
ok(ceci2["n1"] is True and ceci2["n2"] is False, "y el nivel de firma también")
ok(all("email" not in campos for campos in FALSO.updates),
   "al actualizar NO se reenvía «email»: eso es lo que rompía el guardado")
ok(FALSO.cuentas["cecilia@gpa.com.mx"]["grupos"] == {"comite"},
   "queda en un solo grupo: el rol no puede quedar ambiguo")

print("\n   Y lo que devuelve el servidor es lo que debe pintar la pantalla:")
ok(ceci2["correo"] == "cecilia@gpa.com.mx" and ceci2["nombre"] == "Cecilia Medrano",
   "la respuesta trae la cuenta completa, ya con el cambio")

# ═══════════════════════════════════════════════════════════════
print("\n3. Un fallo de Cognito tiene que llegar con nombre")
# ═══════════════════════════════════════════════════════════════
original = FALSO.admin_update_user_attributes


def update_que_falla(UserPoolId, Username, UserAttributes):
    raise _error("InvalidPasswordException", "Password did not conform with policy")


FALSO.admin_update_user_attributes = update_que_falla
rompe(lambda: a.guardar_usuario({"correo": "cecilia@gpa.com.mx", "nombre": "Cecilia",
                                 "rol": ROL_COMITE, "n1": True, "n2": True, "activo": True}),
      "contraseña no cumple",
      "el error de Cognito se traduce, no sale como «algo falló del lado de GPA»")
FALSO.admin_update_user_attributes = original

# ═══════════════════════════════════════════════════════════════
print("\n4. Solo Comité y Administrador llevan nivel de firma")
# ═══════════════════════════════════════════════════════════════
ceci3 = a.guardar_usuario({"correo": "cecilia@gpa.com.mx", "nombre": "Cecilia Medrano",
                           "rol": ROL_VENTAS, "n1": True, "n2": True, "activo": True})
ok(not ceci3["n1"] and not ceci3["n2"],
   "a Ventas se le quitan los niveles aunque el panel los mande marcados")
rompe(lambda: a.guardar_usuario({"correo": "x@gpa.com.mx", "nombre": "X",
                                 "rol": "Jefe", "n1": False, "n2": False, "activo": True}),
      "el rol debe ser uno de", "no acepta un rol inventado")
rompe(lambda: a.guardar_usuario({"correo": "sin-arroba", "nombre": "X",
                                 "rol": ROL_ADMIN, "n1": False, "n2": False, "activo": True}),
      "correo no es válido", "no acepta un correo mal escrito")

# ═══════════════════════════════════════════════════════════════
print("\n5. El sistema no se puede quedar sin Administradores")
# ═══════════════════════════════════════════════════════════════
rompe(lambda: a.guardar_usuario({"correo": "oscar@gpa.com.mx", "nombre": "Oscar Cabrera",
                                 "rol": ROL_COMITE, "n1": True, "n2": True, "activo": True}),
      "único administrador activo",
      "al único Administrador no se le puede cambiar el rol")
rompe(lambda: a.guardar_usuario({"correo": "oscar@gpa.com.mx", "nombre": "Oscar Cabrera",
                                 "rol": ROL_ADMIN, "n1": True, "n2": True, "activo": False}),
      "único administrador activo",
      "ni darlo de baja")
ok(a.get_usuario("oscar@gpa.com.mx")["rol"] == ROL_ADMIN,
   "y la cuenta quedó intacta: el rechazo fue antes de tocar nada")

alta("ana@gpa.com.mx", "Ana Ruiz", ROL_ADMIN, n1=True, n2=True)
baja = a.guardar_usuario({"correo": "oscar@gpa.com.mx", "nombre": "Oscar Cabrera",
                          "rol": ROL_COMITE, "n1": True, "n2": True, "activo": True})
ok(baja["rol"] == ROL_COMITE,
   "con otro Administrador en pie, el cambio sí procede")

# ═══════════════════════════════════════════════════════════════
print("\n6. Quién puede firmar cada nivel")
# ═══════════════════════════════════════════════════════════════
salud = a.salud_firmas()
ok(len(salud["nivel1"]) == 2, "hay dos que pueden firmar el nivel 1")
ok(len(salud["nivel2"]) == 2, "y dos para el nivel 2, que pide dos firmas")
ok(not salud["problemas"], "sin avisos pendientes")

a.guardar_usuario({"correo": "oscar@gpa.com.mx", "nombre": "Oscar Cabrera",
                   "rol": ROL_COMITE, "n1": False, "n2": False, "activo": True})
salud2 = a.salud_firmas()
ok(any("nivel 2" in p for p in salud2["problemas"]),
   "si solo queda uno, avisa que el nivel 2 no se podrá completar")

# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
if FALLAS:
    print(f"{len(FALLAS)} falla(s) de {TOTAL}:")
    for f in FALLAS:
        print("  · " + f)
    sys.exit(1)
print(f"Sin fallas. {TOTAL} comprobaciones sobre el panel de usuarios real.")
