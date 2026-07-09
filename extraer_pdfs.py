"""
Extrae masivamente los PDFs contenidos en varios archivos ZIP.

Solo extrae PDFs (ignora lo demas), maneja PDFs en subcarpetas dentro del ZIP
y renombra duplicados para no sobrescribir.

La logica vive en core.py; este script solo la ejecuta desde la terminal.
Ver CLAUDE.md para el contexto completo y las decisiones de diseno.
"""

from core import extraer_zips

# === CONFIGURA ESTO ===
CARPETA_ZIPS = "zips"                 # carpeta con los .zip
CARPETA_SALIDA = "pdfs_extraidos"     # donde caen los PDFs
APLANAR = True   # True = todos los PDFs juntos / False = subcarpeta por ZIP
# ======================

r = extraer_zips(CARPETA_ZIPS, CARPETA_SALIDA, APLANAR)

print(f"OK: {r['total']} PDFs extraidos de {r['num_zips']} ZIP en "
      f"'{CARPETA_SALIDA}'")
if r["errores"]:
    print(f"\nADVERTENCIA: {len(r['errores'])} ZIP con problemas:")
    print("\n".join(r["errores"]))
