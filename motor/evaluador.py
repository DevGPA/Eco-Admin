# motor/evaluador.py
# Motor de fletes GPA v2.4 — 6 capas de evaluación
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal

from .catalogos import (
    MONTO_MIN_GENERAL, MONTO_MIN_COSTAL, MONTO_MIN_EQUIPO_COSTAL,
    MONTO_MIN_ACCESORIOS, PROP_MIN_ELEGIBLE,
    UMBRAL_FLETE_WARN, UMBRAL_FLETE_CRIT, UMBRAL_FLETE_BORDERLINE,
    UMBRAL_CARGO_ENVIO, UMBRAL_TARIFA_DISP, BACKORDER_ENABLED,
    CARGO_ENVIO_POR_SAP, TIPO_CAMBIO_DEFAULT,
    SAPS_DISPERSION, SAP_CARGO_ENVIO, SAP_BACKORDER,
    SUCURSALES_VALIDAS, SUCURSAL_ORIGEN_DISPERSION, RECEPTORES_INTERNOS_GPA,
    FLETERAS_AUTORIZADAS, R_CONCEPTOS, ESTADO_POR_CODIGO,
    evaluar_destino, categoria_partida, es_cargo_envio,
)


# ── Modelos de entrada ────────────────────────────────────────────

@dataclass
class Partida:
    sku: str
    descripcion: str
    cantidad: float
    precio_unitario_usd: float
    peso_unitario_kg: float = 0.0
    volumen_unitario_l: float = 0.0

    @property
    def importe_usd(self) -> float:
        return self.cantidad * self.precio_unitario_usd

    @property
    def categoria(self) -> str:
        return categoria_partida(self.descripcion, self.peso_unitario_kg,
                                  self.volumen_unitario_l)


@dataclass
class FacturaVenta:
    folio: str
    subtotal_sin_iva: float
    currency: str                 # 'USD' | 'MXN'
    tipo_cambio_doc: float
    campo_entrega: str            # 'ENTREGA_DOMICILIO' | otros
    partidas: list[Partida] = field(default_factory=list)
    sku_id: Optional[str] = None  # Para GS0248
    descripcion: Optional[str] = None

    @property
    def subtotal_usd(self) -> float:
        if self.currency == "USD":
            return self.subtotal_sin_iva
        tc = self.tipo_cambio_doc if (self.tipo_cambio_doc or 0) > 0 else TIPO_CAMBIO_DEFAULT
        return self.subtotal_sin_iva / tc


@dataclass
class LineaCargo:
    codigo: str       # 78101802 flete, 78101801 entrega, 78101700 ferry
    descripcion: str
    importe: float
    currency: str = "MXN"


@dataclass
class CartaPorte:
    folio: str
    transportista_rfc: str
    destinatario_rfc: str
    codigo_sap: str               # GS0229, GS0230, GS0231, GS0248
    tipo_servicio_cp: str         # 'OCURRE' | 'ENTREGA_DOMICILIO' — informativo
    destino_ciudad: str
    destino_estado: str
    origen_sucursal: str          # GDL | CDMX | MTY | CUN | PVR | SJD
    tipo_vehiculo: str            # PALLET | TORTON | TRAILER | CAJA
    numero_pallets: int = 0
    lineas_cargo: list[LineaCargo] = field(default_factory=list)
    currency: str = "MXN"
    tipo_cambio_doc: float = TIPO_CAMBIO_DEFAULT
    # PTX / GCCR
    es_gccr: bool = False
    codigo_rastreo: Optional[str] = None  # folioCP alternativo para PTX
    # CFDI 4.0
    es_cfdi40: bool = False

    @property
    def subtotal_sin_impuestos(self) -> float:
        """Suma TODAS las líneas: flete + entrega + combustible + ferry + maniobras."""
        return sum(l.importe for l in self.lineas_cargo)

    @property
    def folio_efectivo(self) -> str:
        """Para PTX, el folio es el código de rastreo."""
        return self.codigo_rastreo or self.folio


@dataclass
class SolicitudInput:
    facturas_venta: list[FacturaVenta]
    carta_porte: CartaPorte
    fecha_emision: str            # yyyy-mm-dd


# ── Resultado del motor ───────────────────────────────────────────

@dataclass
class CriterioDetalle:
    criterio: str
    resultado: str   # 'PASS' | 'FAIL' | 'WARN' | 'SKIP' | 'INFO'
    valor: str
    detalle: str


@dataclass
class ResultadoMotor:
    codigo_motor: str
    concepto_motor: str
    estado: str
    tipo_operacion: str
    criterios: list[CriterioDetalle] = field(default_factory=list)
    folio_cp: str = ""
    folios_fv: list[str] = field(default_factory=list)
    origen_sucursal: str = ""
    fleta_rfc: str = ""
    destino_estado: str = ""
    destino_ciudad: str = ""
    monto_base_usd: float = 0.0
    flete_base_usd: float = 0.0
    pct_flete: float = 0.0
    tipo_cambio_ref: float = TIPO_CAMBIO_DEFAULT
    incluye_ferry: bool = False
    delta_cargo_envio: Optional[float] = None
    delta_pct: Optional[float] = None
    fecha_emision: str = ""


# ── MOTOR PRINCIPAL ────────────────────────────────────────────────

def evaluar(sol: SolicitudInput) -> ResultadoMotor:
    """
    Ejecuta las 6 capas del motor v2.4 en secuencia fail-fast.
    Nota: La Capa 0 (R-091/092) se ejecuta ANTES de llamar a esta
    función, en la capa de base de datos (db/validaciones.py).
    """
    cp  = sol.carta_porte
    fvs = sol.facturas_venta
    criterios: list[CriterioDetalle] = []

    # Datos comunes
    tipo_cambio_ref = fvs[0].tipo_cambio_doc if fvs else cp.tipo_cambio_doc
    # Guarda anti división-por-cero: un TC ausente/0/negativo cae al respaldo.
    # (La validación dura del valor se hace en handler.py antes de evaluar.)
    if not tipo_cambio_ref or tipo_cambio_ref <= 0:
        tipo_cambio_ref = TIPO_CAMBIO_DEFAULT
    folio_cp   = cp.folio_efectivo
    folios_fv  = [fv.folio for fv in fvs]

    def _res(codigo: str, criterios_extra=None) -> ResultadoMotor:
        concepto = R_CONCEPTOS.get(codigo, codigo)
        estado   = ESTADO_POR_CODIGO.get(codigo, "EN_REVISION")
        return ResultadoMotor(
            codigo_motor   = codigo,
            concepto_motor = concepto,
            estado         = estado,
            tipo_operacion = _detectar_tipo(cp, fvs),
            criterios      = criterios + (criterios_extra or []),
            folio_cp       = folio_cp,
            folios_fv      = folios_fv,
            origen_sucursal= cp.origen_sucursal,
            fleta_rfc      = cp.transportista_rfc,
            destino_estado = cp.destino_estado,
            destino_ciudad = cp.destino_ciudad,
            monto_base_usd = _monto_base_usd(fvs, tipo_cambio_ref),
            flete_base_usd = cp.subtotal_sin_impuestos / tipo_cambio_ref,
            pct_flete      = _pct_flete(fvs, cp, tipo_cambio_ref),
            tipo_cambio_ref= tipo_cambio_ref,
            incluye_ferry  = _tiene_ferry(cp),
            fecha_emision  = sol.fecha_emision,
        )

    # ── CAPA 1a — DISPERSIÓN INTERNA (GS0231 semanal / GS0232 express) ──
    if cp.codigo_sap in SAPS_DISPERSION or _es_receptor_gpa(cp.destinatario_rfc):
        criterios.append(CriterioDetalle(
            "Capa 1a · GS0231", "INFO", cp.codigo_sap,
            "DISPERSION_INTERNA detectada"
        ))
        # Validar origen: solo GDL
        if cp.origen_sucursal != SUCURSAL_ORIGEN_DISPERSION:
            criterios.append(CriterioDetalle(
                "C4 Sucursal", "FAIL", cp.origen_sucursal,
                f"Dispersiones solo desde GDL. Origen actual: {cp.origen_sucursal}"
            ))
            return _res("R-401-D")
        return _evaluar_dispersion(cp, tipo_cambio_ref, criterios, _res)

    # ── CAPA 1b — GS0248 CARGO POR ENVÍO (legacy, off por defecto) ──
    # La clasificación oficial evalúa GS0248 como VENTA; esta capa solo corre
    # si el negocio la reactiva con CARGO_ENVIO_POR_SAP=true.
    if (CARGO_ENVIO_POR_SAP
            and cp.codigo_sap == SAP_CARGO_ENVIO
            and fvs
            and es_cargo_envio(fvs[0].sku_id, fvs[0].descripcion)):
        criterios.append(CriterioDetalle(
            "Capa 1b · GS0248", "INFO", cp.codigo_sap,
            "CARGO_POR_ENVIO detectado"
        ))
        return _evaluar_cargo_envio(fvs[0], cp, tipo_cambio_ref, criterios, _res)

    # ── CAPA 2 — GS0229 BACK ORDER ────────────────────────────────
    is_backorder = (
        BACKORDER_ENABLED
        and (cp.codigo_sap == SAP_BACKORDER
             or any("BACK ORDER" in (fv.descripcion or "").upper()
                    for fv in fvs))
    )
    if is_backorder:
        criterios.append(CriterioDetalle(
            "Capa 2 · GS0229", "INFO", cp.codigo_sap,
            f"BACK_ORDER desde {cp.origen_sucursal}"
        ))
        if not (cp.destino_estado or "").strip():
            criterios.append(CriterioDetalle(
                "C3 Destino", "WARN", "no identificado",
                "Back Order con destino no legible → revisión manual"
            ))
            res = _res("R-301")
            res.estado = "EN_REVISION"
            return res
        dest_result = evaluar_destino(cp.destino_estado, cp.destino_ciudad)
        criterios.append(CriterioDetalle(
            "C3 Destino", "PASS" if dest_result == "OK" else "FAIL",
            cp.destino_estado,
            f"Back Order solo evalúa C3. Destino: {dest_result}"
        ))
        if dest_result == "OK":
            return _res("R-050")
        if dest_result == "R-302":
            return _res("R-302")
        return _res("R-301")

    # ── CAPA 3 — MOTOR C1–C5 VENTA CLIENTE ───────────────────────
    criterios.append(CriterioDetalle(
        "Tipo operación", "INFO", "VENTA_CLIENTE",
        "Sin señal especial → evalúa C1–C5"
    ))
    return _evaluar_venta_cliente(sol, tipo_cambio_ref, criterios, _res)


# ── EVALUADORES POR TIPO ──────────────────────────────────────────

def _evaluar_dispersion(cp, tc_ref, criterios, _res):
    """Capa 4: Compara contra tarifas 2026."""
    # Importar tarifas (evitar import circular)
    from .tarifas import TARIFAS_DISPERSIONES
    fletera = cp.transportista_rfc
    vehiculo = cp.tipo_vehiculo
    destino  = cp.destino_estado

    tarifa_ref = TARIFAS_DISPERSIONES.get(fletera, {}).get(vehiculo, {}).get(destino)
    flete_real = cp.subtotal_sin_impuestos  # MXN

    if not tarifa_ref:
        criterios.append(CriterioDetalle(
            "C4 Tarifa", "WARN", f"{fletera}/{vehiculo}/{destino}",
            "Ruta/vehículo no encontrado en tabla de tarifas 2026"
        ))
        res = _res("R-801")
        res.tipo_operacion = "DISPERSION_INTERNA"
        return res

    if vehiculo == "PALLET" and cp.numero_pallets > 0:
        tarifa_ref = tarifa_ref * cp.numero_pallets

    limite_superior = tarifa_ref * (1 + UMBRAL_TARIFA_DISP)
    if flete_real > limite_superior:
        criterios.append(CriterioDetalle(
            "C4 Tarifa", "WARN",
            f"${flete_real:,.2f} > ${limite_superior:,.2f}",
            f"Flete excede tarifa ref ${tarifa_ref:,.2f} + {UMBRAL_TARIFA_DISP*100:.0f}%"
        ))
        res = _res("R-802")
        res.tipo_operacion = "DISPERSION_INTERNA"
        return res

    criterios.append(CriterioDetalle(
        "C4 Tarifa", "PASS",
        f"${flete_real:,.2f} ≤ ${limite_superior:,.2f}",
        f"Tarifa ref: ${tarifa_ref:,.2f} · delta {(flete_real/tarifa_ref - 1)*100:.1f}%"
    ))
    res = _res("R-800")
    res.tipo_operacion = "DISPERSION_INTERNA"
    return res


def _evaluar_cargo_envio(fv, cp, tc_ref, criterios, _res):
    """Capa 1b: Compara FV vs CP ±1%."""
    valor_fv_mxn = fv.subtotal_sin_iva if fv.currency == "MXN" else fv.subtotal_sin_iva * tc_ref
    valor_cp_mxn = cp.subtotal_sin_impuestos

    delta     = abs(valor_fv_mxn - valor_cp_mxn)
    tolerancia = valor_cp_mxn * UMBRAL_CARGO_ENVIO
    delta_pct  = (delta / valor_cp_mxn * 100) if valor_cp_mxn else 0

    criterios.append(CriterioDetalle(
        "C1b Delta FV vs CP",
        "PASS" if delta <= tolerancia else "WARN",
        f"FV ${valor_fv_mxn:.2f} · CP ${valor_cp_mxn:.2f} · Δ ${delta:.2f} ({delta_pct:.1f}%)",
        f"Umbral {UMBRAL_CARGO_ENVIO*100:.0f}%"
    ))

    codigo = "R-060" if delta <= tolerancia else "R-061"
    res = _res(codigo)
    res.tipo_operacion   = "CARGO_POR_ENVIO"
    res.delta_cargo_envio = delta
    res.delta_pct         = delta_pct
    return res


def _evaluar_venta_cliente(sol, tc_ref, criterios, _res):
    """Capa 3: C1 → C2 → C3 → C4 → C5 fail-fast."""
    cp  = sol.carta_porte
    fvs = sol.facturas_venta

    # Pre-calcular montos.
    # El MONTO del pedido es el Sub-Total de la(s) FV (regla GPA): es el dato
    # fiable del documento. Los renglones (partidas) aportan las CATEGORÍAS
    # (costal/accesorios/elegible); sus importes solo suplen el monto cuando
    # no hay subtotal. Renglones sin importe (OCR de tablas incompleto) se
    # ignoran para montos — no deben producir falsos R-101/R-202.
    todas_partidas = [p for fv in fvs for p in fv.partidas]
    partidas_v  = [p for p in todas_partidas if p.importe_usd > 0]
    monto_fv    = sum(fv.subtotal_usd for fv in fvs)
    monto_usd   = monto_fv if monto_fv > 0 else sum(p.importe_usd for p in partidas_v)
    equipo_usd = sum(p.importe_usd for p in partidas_v
                     if p.categoria in ("EQUIPO", "RECUBRIMIENTO"))
    costal_g_usd = sum(p.importe_usd for p in partidas_v
                       if p.categoria == "EXCLUIDO_GRANDE")
    accs_usd   = sum(p.importe_usd for p in partidas_v
                     if p.categoria == "EXCLUIDO_RESTRINGIDO")
    tiene_costal = costal_g_usd > 0
    tiene_accs   = accs_usd > 0
    tiene_elig   = equipo_usd > 0

    # Sin partidas con importe (no las hay, o el OCR no leyó la tabla): el
    # monto FV es la única señal → se asume elegible y C2 queda en manos del
    # subtotal (no hay evidencia de costal/accesorios para castigar).
    if not partidas_v:
        equipo_usd = monto_usd
        tiene_elig = monto_usd > 0

    flete_usd  = cp.subtotal_sin_impuestos / tc_ref
    pct_flete  = flete_usd / monto_usd if monto_usd else 0

    # ── C1 Monto ─────────────────────────────────────────────────
    if tiene_costal:
        if monto_usd < MONTO_MIN_COSTAL:
            criterios.append(CriterioDetalle(
                "C1 Monto", "FAIL",
                f"${monto_usd:.2f} < ${MONTO_MIN_COSTAL:.0f}",
                "Con EXCLUIDO_GRANDE: mínimo $1,000 USD"
            ))
            return _res("R-103")
        if equipo_usd < MONTO_MIN_EQUIPO_COSTAL:
            criterios.append(CriterioDetalle(
                "C1 Monto", "FAIL",
                f"Equipo ${equipo_usd:.2f} < ${MONTO_MIN_EQUIPO_COSTAL:.0f}",
                "Con costal: equipo mínimo $500 USD"
            ))
            return _res("R-102")
    elif tiene_accs:
        if monto_usd < MONTO_MIN_ACCESORIOS:
            criterios.append(CriterioDetalle(
                "C1 Monto", "FAIL",
                f"${monto_usd:.2f} < ${MONTO_MIN_ACCESORIOS:.0f}",
                "Con accesorios: mínimo $1,000 USD"
            ))
            return _res("R-104")
        prop_elig = equipo_usd / monto_usd if monto_usd else 0
        if prop_elig < PROP_MIN_ELEGIBLE:
            criterios.append(CriterioDetalle(
                "C1 Monto", "FAIL",
                f"Elegible {prop_elig*100:.1f}% < {PROP_MIN_ELEGIBLE*100:.0f}%",
                "Con accesorios: EQUIPO+RECUBRIMIENTO debe ser ≥50% del total"
            ))
            return _res("R-105")
    else:
        if monto_usd < MONTO_MIN_GENERAL:
            criterios.append(CriterioDetalle(
                "C1 Monto", "FAIL",
                f"${monto_usd:.2f} < ${MONTO_MIN_GENERAL:.0f}",
                "Pedido limpio: mínimo $350 USD"
            ))
            return _res("R-101")

    criterios.append(CriterioDetalle(
        "C1 Monto", "PASS",
        f"${monto_usd:.2f} USD",
        f"{'Con costal' if tiene_costal else 'Con accesorios' if tiene_accs else 'Limpio'} ✓"
    ))

    # ── C2 Producto ───────────────────────────────────────────────
    if tiene_costal and not tiene_elig:
        criterios.append(CriterioDetalle(
            "C2 Producto", "FAIL", "EXCLUIDO_GRANDE sin elegible",
            "Costal/cuñete ≥25kg sin EQUIPO ni RECUBRIMIENTO"
        ))
        return _res("R-201")
    if not tiene_elig:
        criterios.append(CriterioDetalle(
            "C2 Producto", "FAIL", "Sin elegible",
            "No hay EQUIPO ni RECUBRIMIENTO en la FV"
        ))
        return _res("R-202")

    criterios.append(CriterioDetalle(
        "C2 Producto", "PASS",
        f"Equipo+Rec ${equipo_usd:.2f} USD",
        "Producto elegible presente ✓"
    ))

    # ── C3 Destino ────────────────────────────────────────────────
    # Destino vacío = el OCR no lo leyó. No leer un dato no es violar la regla:
    # va a revisión humana (un humano confirma si el destino está cubierto), no
    # a auto-rechazo R-301. R-301 se reserva para destinos LEÍDOS y no cubiertos.
    if not (cp.destino_estado or "").strip():
        criterios.append(CriterioDetalle(
            "C3 Destino", "WARN", "no identificado",
            "Destino no legible en el documento → revisión manual"
        ))
        res = _res("R-301")
        res.estado = "EN_REVISION"
        return res
    dest_result = evaluar_destino(cp.destino_estado, cp.destino_ciudad)
    if dest_result == "R-301":
        criterios.append(CriterioDetalle(
            "C3 Destino", "FAIL", cp.destino_estado,
            f"{cp.destino_estado} no está en el catálogo del programa"
        ))
        return _res("R-301")

    # Una sola entrada C3: OK → PASS, borderline (R-302) → WARN
    criterios.append(CriterioDetalle(
        "C3 Destino",
        "PASS" if dest_result == "OK" else "WARN",
        f"{cp.destino_estado}" + (f" / {cp.destino_ciudad}" if dest_result == "R-302" else ""),
        "En catálogo ✓" if dest_result == "OK" else "Ciudad borderline → EN_REVISION"
    ))

    # ── C4a Entrega (fuente: FV, no CP) ──────────────────────────
    campo_entrega = fvs[0].campo_entrega if fvs else ""
    if "DOMICILIO" not in campo_entrega.upper() and "FLETERA" not in campo_entrega.upper():
        criterios.append(CriterioDetalle(
            "C4a Entrega", "FAIL",
            campo_entrega or "vacío",
            "FV.campoEntrega debe indicar entrega a domicilio"
        ))
        return _res("R-401")

    criterios.append(CriterioDetalle(
        "C4a Entrega", "PASS", campo_entrega, "Entrega a domicilio ✓"
    ))

    # ── C4b Sucursal ─────────────────────────────────────────────
    # Vacío = el documento no permitió determinar el origen (OCR) → eso NO es
    # una violación de la regla: va a revisión humana, no a auto-rechazo.
    if not cp.origen_sucursal:
        criterios.append(CriterioDetalle(
            "C4b Sucursal", "WARN", "no identificado",
            "Origen no legible/no mapeado a plaza GPA → revisión manual"
        ))
        res = _res("R-401-S")
        res.estado = "EN_REVISION"
        return res
    if cp.origen_sucursal not in SUCURSALES_VALIDAS:
        criterios.append(CriterioDetalle(
            "C4b Sucursal", "FAIL", cp.origen_sucursal,
            f"{cp.origen_sucursal} no está en SUCURSALES_VALIDAS"
        ))
        return _res("R-401-S")

    criterios.append(CriterioDetalle(
        "C4b Sucursal", "PASS", cp.origen_sucursal, "Sucursal GPA válida ✓"
    ))

    # ── C4c Fletera ───────────────────────────────────────────────
    if not cp.transportista_rfc:
        criterios.append(CriterioDetalle(
            "C4c Fletera", "WARN", "no identificado",
            "RFC de la fletera no legible en el documento → revisión manual"
        ))
        res = _res("R-402")
        res.estado = "EN_REVISION"
        return res
    if cp.transportista_rfc not in FLETERAS_AUTORIZADAS:
        criterios.append(CriterioDetalle(
            "C4c Fletera", "FAIL", cp.transportista_rfc,
            f"RFC {cp.transportista_rfc} no está en el catálogo de fleteras autorizadas"
        ))
        return _res("R-402")

    criterios.append(CriterioDetalle(
        "C4c Fletera", "PASS", cp.transportista_rfc, "Fletera autorizada ✓"
    ))

    # ── C5 Proporción flete / pedido ─────────────────────────────
    tiene_ferry = _tiene_ferry(cp)
    criterios.append(CriterioDetalle(
        "C5 Flete",
        "INFO",
        f"{pct_flete*100:.1f}% {'(incl. ferry)' if tiene_ferry else ''}",
        f"Flete ${flete_usd:.2f} USD / Pedido ${monto_usd:.2f} USD"
    ))

    # Combinar R-302 + C5
    if dest_result == "R-302":
        if pct_flete > UMBRAL_FLETE_WARN:
            return _res("R-601")   # Remoto + flete alto
        if pct_flete > UMBRAL_FLETE_BORDERLINE:
            return _res("R-602")   # Borderline + flete moderado
        return _res("R-302")

    if pct_flete > UMBRAL_FLETE_CRIT:
        criterios.append(CriterioDetalle(
            "C5 Proporción", "WARN",
            f"{pct_flete*100:.1f}% > {UMBRAL_FLETE_CRIT*100:.0f}%",
            "Flete crítico"
        ))
        return _res("R-502")

    if pct_flete > UMBRAL_FLETE_WARN:
        criterios.append(CriterioDetalle(
            "C5 Proporción", "WARN",
            f"{pct_flete*100:.1f}% > {UMBRAL_FLETE_WARN*100:.0f}%",
            "Flete alto"
        ))
        return _res("R-501")

    criterios.append(CriterioDetalle(
        "C5 Proporción", "PASS",
        f"{pct_flete*100:.1f}% ✓",
        f"Dentro del umbral {UMBRAL_FLETE_WARN*100:.0f}%"
    ))

    return _res("R-000")


# ── Helpers ───────────────────────────────────────────────────────

def _detectar_tipo(cp: CartaPorte, fvs: list[FacturaVenta]) -> str:
    # Tabla oficial: solo GS0231/GS0232 son dispersión; el resto es VENTA.
    # Los tipos legacy (cargo envío / back order) solo si su capa está activa.
    if cp.codigo_sap in SAPS_DISPERSION or _es_receptor_gpa(cp.destinatario_rfc):
        return "DISPERSION_INTERNA"
    if CARGO_ENVIO_POR_SAP and cp.codigo_sap == SAP_CARGO_ENVIO:
        return "CARGO_POR_ENVIO"
    if BACKORDER_ENABLED and cp.codigo_sap == SAP_BACKORDER:
        return "BACK_ORDER"
    return "VENTA_CLIENTE"


def _es_receptor_gpa(rfc: str) -> bool:
    """True solo si el RFC está en la lista configurable de receptores internos GPA.

    Antes usaba startswith("GPA"), lo que secuestraba a la capa de dispersión
    cualquier operación cuyo destinatario empezara con "GPA". Ahora es igualdad
    exacta contra RECEPTORES_INTERNOS_GPA (vacío por defecto → solo dispara el
    código SAP de dispersión).
    """
    if not rfc or not RECEPTORES_INTERNOS_GPA:
        return False
    return rfc.upper() in RECEPTORES_INTERNOS_GPA


def _monto_base_usd(fvs: list[FacturaVenta], tc_ref: float) -> float:
    return sum(fv.subtotal_usd for fv in fvs)


def _pct_flete(fvs: list[FacturaVenta], cp: CartaPorte, tc_ref: float) -> float:
    monto = _monto_base_usd(fvs, tc_ref)
    if not monto:
        return 0.0
    return (cp.subtotal_sin_impuestos / tc_ref) / monto


def _tiene_ferry(cp: CartaPorte) -> bool:
    return any(
        "78101700" in l.codigo or "ferry" in l.descripcion.lower()
        for l in cp.lineas_cargo
    )
