# auth_cognito.py — Administración de cuentas en Cognito — GPA ViaticOS
# ─────────────────────────────────────────────────────────────────
# Usado por el panel admin para dar de alta/editar logins, asignar rol y
# área, resetear contraseña y activar/desactivar usuarios.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import boto3

POOL = os.environ.get("USER_POOL_ID", "")
ROLES = ("admin", "direccion", "finanzas", "tesoreria", "compras", "supervisor", "empleado")
_cli = None


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
        "email":  _attr(attrs, "email") or u.get("Username", ""),
        "nombre": _attr(attrs, "custom:nombre"),
        "rol":    _attr(attrs, "custom:rol", "empleado"),
        "area":   _attr(attrs, "custom:area"),
        "jefe":   _attr(attrs, "custom:jefe"),
        "activo": u.get("Enabled", True),
        "estado": u.get("UserStatus", ""),
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
      email (obligatorio), nombre, rol, area, jefe, password (opcional), activo (opcional)
    """
    email = (d.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("Correo inválido")
    rol = d.get("rol", "empleado")
    if rol not in ROLES:
        raise ValueError("Rol inválido")

    c = _c()
    attrs = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "custom:rol", "Value": rol},
        {"Name": "custom:area", "Value": d.get("area") or ""},
        {"Name": "custom:nombre", "Value": d.get("nombre") or ""},
        {"Name": "custom:jefe", "Value": d.get("jefe") or ""},
    ]

    creado = False
    try:
        c.admin_create_user(UserPoolId=POOL, Username=email,
                            UserAttributes=attrs, MessageAction="SUPPRESS")
        creado = True
    except c.exceptions.UsernameExistsException:
        c.admin_update_user_attributes(UserPoolId=POOL, Username=email, UserAttributes=attrs)

    # Contraseña (en alta es obligatoria; en edición es opcional)
    pwd = d.get("password")
    if creado and not pwd:
        raise ValueError("La contraseña es obligatoria al crear una cuenta")
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
