#!/usr/bin/env python3
# tools/probar_textract.py
# ─────────────────────────────────────────────────────────────────
# Diagnóstico LOCAL del OCR (Textract) + motor, con un PDF real.
# Corre Textract de VERDAD usando tus credenciales AWS; no escribe en
# DynamoDB ni despliega nada (solo lee el PDF y evalúa).
#
# Requisitos:
#   pip install boto3 pymupdf
#   Credenciales AWS configuradas (aws configure  ó variables de entorno)
#   Permiso textract:AnalyzeDocument
#
# Uso:
#   python tools/probar_textract.py "ruta\al\documento.pdf"
#   python tools/probar_textract.py "ruta.pdf" --region us-east-1 --backend textract
# ─────────────────────────────────────────────────────────────────
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser(description="Prueba local de OCR (Textract) + motor")
    ap.add_argument("pdf", help="Ruta al PDF a analizar")
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--backend", default="textract", choices=["textract", "bedrock"])
    args = ap.parse_args()

    os.environ["AWS_DEFAULT_REGION"] = args.region
    os.environ["OCR_BACKEND"] = args.backend

    from s3.ocr_extractor import (render_paginas_pdf, ocr_pagina, emparejar_casos,
                                   caso_a_solicitud, clasificar_por_rfc)
    from handler import _build_solicitud_input
    from motor.evaluador import evaluar

    if not os.path.exists(args.pdf):
        print(f"No existe el archivo: {args.pdf}"); sys.exit(1)

    with open(args.pdf, "rb") as f:
        pdf = f.read()
    print(f"PDF: {os.path.basename(args.pdf)} ({len(pdf)//1024} KB) | backend={args.backend} "
          f"| region={args.region}")

    print("\n== OCR por página ==")
    paginas = []
    for i, img in enumerate(render_paginas_pdf(pdf), start=1):
        try:
            d = ocr_pagina(img)
        except Exception as exc:
            print(f"  pág {i}: ERROR OCR → {exc}")
            d = {"tipoDocumento": "OTRO"}
        clase = clasificar_por_rfc(d.get("rfcEmisor"), d.get("rfcReceptor"))
        print(f"  pág {i}: {clase:6} | folio={d.get('folio')} | "
              f"emisor={d.get('rfcEmisor')} receptor={d.get('rfcReceptor')} | "
              f"subtotal={d.get('subtotal')} {d.get('moneda') or ''} | "
              f"partidas={len(d.get('partidas') or [])}")
        paginas.append(d)

    res = emparejar_casos(paginas, folio_archivo=os.path.basename(args.pdf).rsplit(".", 1)[0])
    print(f"\n== Casos: {len(res['casos'])} | CP={res['totalCP']} FV={res['totalFV']} "
          f"| FV sin CP={res['fvsSinCP']} | páginas ajenas={res['paginasAjenas']} ==")

    for caso in res["casos"]:
        if caso.get("status") != "OK":
            print(f"\n  CP {caso.get('folioCP')}: ⚠️ {caso.get('error')} — {caso.get('detalle','')}")
            continue
        sol = caso_a_solicitud(caso)
        try:
            r = evaluar(_build_solicitud_input(sol))
            cats = [p.categoria for fv in [_build_solicitud_input(sol).facturas_venta[0]] for p in fv.partidas]
            print(f"\n  CASO {caso['folioCP']}  (FV {caso['foliosFV']}, sucursal={sol['origenSucursal']})")
            print(f"    flete={caso['fleteSinIvaMXN']} MXN | venta={caso['montoVentaFV']} {caso['monedaFV']}"
                  f" | destino={sol['destinoEstado']} | categorías={cats}")
            print(f"    => {r.codigo_motor} ({r.concepto_motor}) | {r.estado} | flete={r.pct_flete*100:.1f}%")
        except Exception as exc:
            print(f"\n  CASO {caso['folioCP']}: ERROR al evaluar → {exc}")


if __name__ == "__main__":
    main()
