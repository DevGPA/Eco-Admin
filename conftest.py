# conftest.py — fixtures compartidas para la suite del Motor de Fletes v2.4
# Garantiza que la raíz del repo esté en sys.path para importar motor/, db/, s3/.
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Defaults para que los módulos que crean clientes boto3 importen sin AWS real.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DYNAMO_TABLE", "gpa_fletes_test")
os.environ.setdefault("S3_BUCKET", "gpa-documentos-test")

import pytest

from motor.evaluador import (
    SolicitudInput, CartaPorte, FacturaVenta, Partida, LineaCargo, evaluar,
)

# Constantes de apoyo
FLETERA_AUTORIZADA = "ACT68080665A"   # Tresguerras (en FLETERAS_AUTORIZADAS)
SKU_EQUIPO         = "39111611"       # Reflector LED → EQUIPO
SKU_COSTAL         = "49241712"       # Tricloro 50kg → EXCLUIDO_GRANDE
SKU_ACCESORIO      = "30111601"       # Pega Veneciana → MATERIAL_INSTALACION
TC_DEFECTO         = 17.35


@pytest.fixture
def make_partida():
    def _f(sku=SKU_EQUIPO, descripcion="Reflector LED", cantidad=1.0,
           precio=1000.0, peso=5.0, volumen=0.0):
        return Partida(sku=sku, descripcion=descripcion, cantidad=cantidad,
                       precio_unitario_usd=precio, peso_unitario_kg=peso,
                       volumen_unitario_l=volumen)
    return _f


@pytest.fixture
def make_fv(make_partida):
    def _f(partidas=None, subtotal=1000.0, currency="USD", tc=TC_DEFECTO,
           campo_entrega="ENTREGA_DOMICILIO", folio="FA10315862",
           sku_id=None, descripcion=None):
        if partidas is None:
            partidas = [make_partida()]
        return FacturaVenta(folio=folio, subtotal_sin_iva=subtotal, currency=currency,
                            tipo_cambio_doc=tc, campo_entrega=campo_entrega,
                            partidas=partidas, sku_id=sku_id, descripcion=descripcion)
    return _f


@pytest.fixture
def make_cp():
    def _f(flete_mxn=1000.0, ferry_mxn=0.0, codigo_sap="GS0230",
           destinatario_rfc="", destino_estado="Jalisco", destino_ciudad="",
           origen_sucursal="GDL", transportista_rfc=FLETERA_AUTORIZADA,
           tipo_vehiculo="PALLET", numero_pallets=1, tc=TC_DEFECTO,
           folio="116873635"):
        lineas = [LineaCargo(codigo="78101802", descripcion="FLETE",
                             importe=flete_mxn, currency="MXN")]
        if ferry_mxn:
            lineas.append(LineaCargo(codigo="78101700", descripcion="FERRY",
                                     importe=ferry_mxn, currency="MXN"))
        return CartaPorte(folio=folio, transportista_rfc=transportista_rfc,
                          destinatario_rfc=destinatario_rfc, codigo_sap=codigo_sap,
                          tipo_servicio_cp="ENTREGA_DOMICILIO",
                          destino_ciudad=destino_ciudad, destino_estado=destino_estado,
                          origen_sucursal=origen_sucursal, tipo_vehiculo=tipo_vehiculo,
                          numero_pallets=numero_pallets, lineas_cargo=lineas,
                          tipo_cambio_doc=tc)
    return _f


@pytest.fixture
def run_eval(make_fv, make_cp):
    """Evalúa una solicitud; usa los defaults de happy-path (→ R-000) salvo overrides."""
    def _f(fv=None, cp=None, fecha="2026-04-22"):
        if fv is None:
            fv = make_fv()
        if cp is None:
            cp = make_cp()
        return evaluar(SolicitudInput(facturas_venta=[fv], carta_porte=cp,
                                      fecha_emision=fecha))
    return _f


@pytest.fixture
def flete_para_pct():
    """MXN de flete necesarios para un % de flete dado (monto USD y TC dados)."""
    def _f(pct, monto_usd=1000.0, tc=TC_DEFECTO):
        return pct * monto_usd * tc
    return _f
