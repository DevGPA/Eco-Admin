"""
Combina varios PDFs por fila de un Excel en un solo PDF.

Regla del Excel: todas las columnas son folios a combinar, EXCEPTO la ultima,
que es el nombre del archivo de salida. Numero de folios por fila es variable.

La logica vive en core.py; este script solo la ejecuta desde la terminal.
Ver CLAUDE.md para el contexto completo y las decisiones de diseno.
"""

from core import combinar

# === CONFIGURA ESTO ===
EXCEL = "facturas.xlsx"          # nombre exacto de tu archivo Excel
CARPETA_PDFS = "pdfs"            # carpeta con los PDFs origen
CARPETA_SALIDA = "combinados"   # carpeta donde se guardan los resultados
TIENE_ENCABEZADO = True         # True si la fila 1 tiene titulos de columna
# ======================

r = combinar(EXCEL, CARPETA_PDFS, CARPETA_SALIDA, TIENE_ENCABEZADO)

if r["duplicados"]:
    print(f"AVISO: folios repetidos en la carpeta (se usa el ultimo): "
          f"{r['duplicados']}\n")

print(f"OK: {r['ok']} PDFs combinados en '{CARPETA_SALIDA}'")
if r["omitidos"]:
    print(f"OMITIDOS: {r['omitidos']} filas ya estaban marcadas como creadas.")
if not r["control_activo"]:
    print("NOTA: el control de duplicados requiere que el Excel tenga fila de "
          "encabezado (TIENE_ENCABEZADO = True).")
if r["errores"]:
    print(f"\nADVERTENCIA: {len(r['errores'])} filas con problemas:")
    print("\n".join(r["errores"]))
