# auth_cognito.py — usuarios internos de GPA Alta de Clientes.
# ─────────────────────────────────────────────────────────────────
# El rol vive en el GRUPO de Cognito (es la autoridad). Los niveles de firma
# viven en atributos propios: custom:n1 y custom:n2.
# El cliente externo NO pasa por aquí: entra con liga + clave (ver portal.py).
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os

import boto3
from botocore.exceptions import ClientError

from catalogos import (GRUPO_A_ROL, ROL_A_GRUPO, ROLES, ROL_ADMIN, ROL_COMITE,
                       ROL_CONSULTA)

_IDP = None

# Los fallos de Cognito que un administrador puede corregir, dichos en su idioma.
_FALLOS_COGNITO = {
    "AliasExistsException":    "Ese correo ya está ocupado por otra cuenta.",
    "UserNotFoundException":   "Esa cuenta ya no existe en el sistema.",
    "InvalidParameterException": "Cognito rechazó uno de los datos de la cuenta.",
    "InvalidPasswordException": "La contraseña no cumple la política: mínimo 10 caracteres, "
                                "con mayúscula, minúscula y número.",
    "UsernameExistsException": "Ya existe una cuenta con ese correo.",
    "NotAuthorizedException":  "AWS no autorizó la operación sobre esa cuenta.",
    "LimitExceededException":  "Demasiados intentos seguidos. Espere un momento y reintente.",
}


def idp():
    global _IDP
    if _IDP is None:
        _IDP = boto3.client("cognito-idp")
    return _IDP


def pool() -> str:
    return os.environ["USER_POOL_ID"]


class CuentaInvalida(Exception):
    """Datos de cuenta que no se pueden aplicar; el mensaje va al administrador."""


def _attr(atributos: list, nombre: str, defecto: str = "") -> str:
    for a in atributos or []:
        if a.get("Name") == nombre:
            return a.get("Value", defecto)
    return defecto


def _rol_de_grupos(grupos: list) -> str:
    """Si alguien quedó en varios grupos, manda el de más autoridad."""
    for grupo in ("admin", "comite", "ventas", "consulta"):
        if grupo in grupos:
            return GRUPO_A_ROL[grupo]
    return ROL_CONSULTA


def usuario_de_claims(claims: dict) -> dict:
    """Quién es el que llama, según su token. Nunca se confía en el cuerpo del request."""
    grupos = claims.get("cognito:groups") or []
    if isinstance(grupos, str):
        grupos = [g for g in grupos.strip("[]").replace(",", " ").split() if g]
    return {
        "correo": claims.get("email") or claims.get("username") or claims.get("cognito:username", ""),
        "nombre": claims.get("custom:nombre") or claims.get("email", ""),
        "rol": _rol_de_grupos(grupos),
        "n1": str(claims.get("custom:n1", "0")) == "1",
        "n2": str(claims.get("custom:n2", "0")) == "1",
    }


def _arma_usuario(u: dict) -> dict:
    correo = _attr(u.get("Attributes") or u.get("UserAttributes"), "email", u.get("Username", ""))
    grupos = []
    try:
        r = idp().admin_list_groups_for_user(UserPoolId=pool(), Username=u["Username"])
        grupos = [g["GroupName"] for g in r.get("Groups", [])]
    except Exception:                                   # pragma: no cover
        grupos = []
    atributos = u.get("Attributes") or u.get("UserAttributes") or []
    return {
        "correo": correo,
        "nombre": _attr(atributos, "custom:nombre", correo),
        "rol": _rol_de_grupos(grupos),
        "n1": _attr(atributos, "custom:n1", "0") == "1",
        "n2": _attr(atributos, "custom:n2", "0") == "1",
        "activo": bool(u.get("Enabled", True)),
        "estatus": u.get("UserStatus", ""),
    }


def listar_usuarios() -> list:
    usuarios, token = [], None
    while True:
        kw = {"UserPoolId": pool(), "Limit": 60}
        if token:
            kw["PaginationToken"] = token
        r = idp().list_users(**kw)
        usuarios.extend(_arma_usuario(u) for u in r.get("Users", []))
        token = r.get("PaginationToken")
        if not token:
            break
    usuarios.sort(key=lambda u: (ROLES.index(u["rol"]) if u["rol"] in ROLES else 9, u["nombre"]))
    return usuarios


def get_usuario(correo: str) -> dict | None:
    try:
        r = idp().admin_get_user(UserPoolId=pool(), Username=correo)
    except idp().exceptions.UserNotFoundException:
        return None
    return _arma_usuario({"Username": r["Username"], "UserAttributes": r["UserAttributes"],
                          "Enabled": r.get("Enabled", True), "UserStatus": r.get("UserStatus", "")})


def elegibles(nivel: int) -> list:
    """Quién puede firmar ese nivel: Comité de Crédito o Administrador, activo y habilitado."""
    campo = "n1" if nivel == 1 else "n2"
    return [u for u in listar_usuarios()
            if u["activo"] and u["rol"] in (ROL_COMITE, ROL_ADMIN) and u[campo]]


def guardar_usuario(datos: dict) -> dict:
    """Crea o actualiza una cuenta interna: rol, niveles de firma y alta/baja.

    Traduce los fallos de Cognito: si no, cualquiera de ellos cae en el «except
    Exception» del handler y el administrador solo ve «algo falló del lado de
    GPA», sin manera de saber qué corregir.
    """
    try:
        return _guardar_usuario(datos)
    except ClientError as e:
        error = e.response.get("Error", {})
        codigo = error.get("Code", "")
        detalle = _FALLOS_COGNITO.get(codigo) or error.get("Message") or codigo
        raise CuentaInvalida(f"No se pudo guardar la cuenta. {detalle} ({codigo})") from e


def _guardar_usuario(datos: dict) -> dict:
    correo = str(datos.get("correo", "")).strip().lower()
    if "@" not in correo:
        raise CuentaInvalida("El correo no es válido.")
    rol = datos.get("rol")
    if rol not in ROLES:
        raise CuentaInvalida(f"El rol debe ser uno de: {', '.join(ROLES)}.")
    nombre = str(datos.get("nombre", "")).strip() or correo
    n1 = "1" if datos.get("n1") else "0"
    n2 = "1" if datos.get("n2") else "0"
    activo = datos.get("activo", True)

    # Solo el Comité de Crédito y el Administrador pueden llevar nivel de firma:
    # así el panel no puede dejar a Ventas firmando por descuido.
    if rol not in (ROL_COMITE, ROL_ADMIN):
        n1 = n2 = "0"

    # Lo único que este panel cambia de una cuenta ya creada.
    perfil = [
        {"Name": "custom:nombre", "Value": nombre},
        {"Name": "custom:n1", "Value": n1},
        {"Name": "custom:n2", "Value": n2},
    ]

    existente = get_usuario(correo)

    # El sistema no puede quedarse sin Administradores: si eso pasara, ya no
    # habría quien diera de alta usuarios ni quien deshiciera el error.
    if (existente and existente["rol"] == ROL_ADMIN and existente["activo"]
            and (rol != ROL_ADMIN or not activo)):
        otros = [u for u in listar_usuarios()
                 if u["rol"] == ROL_ADMIN and u["activo"] and u["correo"] != correo]
        if not otros:
            raise CuentaInvalida(
                "Es el único Administrador activo. Nombre antes a otro Administrador; "
                "si no, nadie podría volver a entrar a administrar usuarios.")

    creado = False
    if existente is None:
        # En el alta sí se manda el correo: aquí es donde nace el usuario.
        kw = {"UserPoolId": pool(), "Username": correo,
              "UserAttributes": [{"Name": "email", "Value": correo},
                                 {"Name": "email_verified", "Value": "true"}] + perfil,
              "DesiredDeliveryMediums": ["EMAIL"]}
        temporal = str(datos.get("password") or "").strip()
        if temporal:
            kw["TemporaryPassword"] = temporal
            kw["MessageAction"] = "SUPPRESS"     # el correo de Cognito aún no está configurado
        idp().admin_create_user(**kw)
        creado = True
    else:
        # NO se reenvía «email»: en este pool el correo ES el nombre de usuario
        # (UsernameAttributes: [email]). Reasignarlo hace que Cognito responda
        # AliasExistsException y el cambio de rol o de nivel de firma se pierde.
        idp().admin_update_user_attributes(UserPoolId=pool(), Username=correo,
                                           UserAttributes=perfil)
        nueva = str(datos.get("password") or "").strip()
        if nueva:
            idp().admin_set_user_password(UserPoolId=pool(), Username=correo,
                                          Password=nueva, Permanent=True)

    # Un solo grupo por persona: se quitan los demás para que el rol no quede ambiguo.
    actuales = {g["GroupName"] for g in
                idp().admin_list_groups_for_user(UserPoolId=pool(), Username=correo).get("Groups", [])}
    destino = ROL_A_GRUPO[rol]
    for g in actuales - {destino}:
        idp().admin_remove_user_from_group(UserPoolId=pool(), Username=correo, GroupName=g)
    if destino not in actuales:
        idp().admin_add_user_to_group(UserPoolId=pool(), Username=correo, GroupName=destino)

    if activo:
        idp().admin_enable_user(UserPoolId=pool(), Username=correo)
    else:
        idp().admin_disable_user(UserPoolId=pool(), Username=correo)

    resultado = get_usuario(correo) or {}
    resultado["creado"] = creado
    return resultado


def salud_firmas() -> dict:
    """¿Alcanza la gente para autorizar? Se revisa aquí para poder avisarlo en pantalla."""
    e1, e2 = elegibles(1), elegibles(2)
    problemas = []
    if len(e1) < 1:
        problemas.append("Nadie puede firmar el nivel 1: ningún crédito podrá autorizarse.")
    if len(e2) < 2:
        problemas.append(f"El nivel 2 pide dos firmas y solo hay {len(e2)} usuario(s) habilitado(s).")
    return {"nivel1": [u["nombre"] for u in e1], "nivel2": [u["nombre"] for u in e2],
            "problemas": problemas}
