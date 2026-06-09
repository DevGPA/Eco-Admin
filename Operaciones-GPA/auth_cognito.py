# auth_cognito.py — Administración de cuentas en Cognito — GPA Operaciones
# ─────────────────────────────────────────────────────────────────
# Usado por el panel admin para dar de alta/editar logins, asignar rol y
# sucursal, resetear contraseña y activar/desactivar usuarios.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3

POOL = os.environ.get("USER_POOL_ID", "")
ROLES = ("admin", "analista", "supervisor", "operador")
MODULOS = ("combustible", "checklist", "montacargas", "admin")
# Solo se permiten cuentas de este dominio de correo
DOMINIO = os.environ.get("DOMINIO_PERMITIDO", "gpa.com.mx").lower()
_cli = None


def _csv_to_list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _list_to_csv(v):
    if isinstance(v, str):
        return v
    return ",".join(str(x).strip() for x in (v or []) if str(x).strip())


def _c():
    global _cli
    if _cli is None:
        _cli = boto3.client("cognito-idp")
    return _cli


def _attr(user_attrs, name, default=""):
    for a in user_attrs:
        if a["Name"] == name:
            return a["Value"]
    return default


def _map(u) -> dict:
    attrs = u.get("Attributes") or u.get("UserAttributes") or []
    return {
        "email":      _attr(attrs, "email") or u.get("Username", ""),
        "nombre":     _attr(attrs, "custom:nombre"),
        "rol":        _attr(attrs, "custom:rol", "operador"),
        "sucursal":   _attr(attrs, "custom:sucursal"),
        "sucursales": _csv_to_list(_attr(attrs, "custom:sucursales")),
        "modulos":    _csv_to_list(_attr(attrs, "custom:modulos")),
        "activo":     u.get("Enabled", True),
        "estado":     u.get("UserStatus", ""),
    }


def listar_cuentas() -> list:
    """Devuelve todas las cuentas del pool (paginado)."""
    out, token = [], None
    while True:
        kw = {"UserPoolId": POOL, "Limit": 60}
        if token:
            kw["PaginationToken"] = token
        resp = _c().list_users(**kw)
        out.extend(_map(u) for u in resp.get("Users", []))
        token = resp.get("PaginationToken")
        if not token:
            break
    return sorted(out, key=lambda x: x["email"])


def guardar_cuenta(d: dict) -> dict:
    """
    Crea o actualiza una cuenta. Campos:
      email (obligatorio), nombre, rol, sucursal, password (opcional), activo (opcional)
    """
    email = (d.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("Correo inválido")
    if not email.endswith("@" + DOMINIO):
        raise ValueError(f"Solo se permiten correos @{DOMINIO}")
    rol = d.get("rol", "operador")
    if rol not in ROLES:
        raise ValueError("Rol inválido")

    sucursales = _list_to_csv(d.get("sucursales", d.get("sucursal", "")))
    modulos    = _list_to_csv(d.get("modulos", ""))
    # 'sucursal' (singular) se conserva por compatibilidad: la 1ª de la lista
    sucursal_1 = sucursales.split(",")[0] if sucursales else (d.get("sucursal") or "")

    c = _c()
    attrs = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "custom:rol", "Value": rol},
        {"Name": "custom:sucursal", "Value": sucursal_1},
        {"Name": "custom:sucursales", "Value": sucursales},
        {"Name": "custom:modulos", "Value": modulos},
        {"Name": "custom:nombre", "Value": d.get("nombre") or ""},
    ]

    pwd = d.get("password")

    # ¿La cuenta ya existe? (decide alta vs edición)
    try:
        c.admin_get_user(UserPoolId=POOL, Username=email)
        existe = True
    except c.exceptions.UserNotFoundException:
        existe = False

    creado = False
    if not existe:
        # ALTA: Cognito GENERA una contraseña temporal automáticamente y la envía en el
        # correo de invitación. La cuenta queda en FORCE_CHANGE_PASSWORD, por lo que se
        # exige crear una contraseña propia en el primer ingreso. (Si el admin manda una
        # contraseña, se respeta como temporal; normalmente no se envía ninguna.)
        kwargs = dict(UserPoolId=POOL, Username=email, UserAttributes=attrs,
                      DesiredDeliveryMediums=["EMAIL"])
        if pwd:
            kwargs["TemporaryPassword"] = pwd
        c.admin_create_user(**kwargs)
        creado = True
    else:
        # EDICIÓN: actualizar atributos; si viene contraseña, es un reset directo del admin.
        c.admin_update_user_attributes(UserPoolId=POOL, Username=email, UserAttributes=attrs)
        if pwd:
            c.admin_set_user_password(UserPoolId=POOL, Username=email, Password=pwd, Permanent=True)

    # Rol → grupo: dejar solo el grupo del rol vigente
    grupos = c.admin_list_groups_for_user(UserPoolId=POOL, Username=email).get("Groups", [])
    for g in grupos:
        if g["GroupName"] != rol:
            c.admin_remove_user_from_group(UserPoolId=POOL, Username=email, GroupName=g["GroupName"])
    c.admin_add_user_to_group(UserPoolId=POOL, Username=email, GroupName=rol)

    # Activo / inactivo
    if "activo" in d:
        (c.admin_enable_user if d["activo"] else c.admin_disable_user)(UserPoolId=POOL, Username=email)

    return {"ok": True, "email": email, "creado": creado}
