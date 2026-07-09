# Proyecto: Combinación y extracción masiva de PDFs de facturas (GPA)

Contexto para Claude Code. Este archivo documenta el estado actual, las decisiones
de diseño ya validadas y las reglas del proyecto. Léelo antes de modificar nada.

## Objetivo

Automatizar dos tareas sobre PDFs de facturas:
1. **Combinar** varios PDFs por fila de un Excel en un solo PDF con nombre definido.
2. **Extraer** masivamente PDFs contenidos en múltiples archivos ZIP.

Entorno del usuario: Windows + Microsoft 365. Python ya instalado con
`pypdf`, `pandas`, `openpyxl`. Perfil del usuario: ejecutivo de finanzas/ops,
no es programador; prioriza control, trazabilidad y no romper lo que funciona.

## Estructura del proyecto

```
facturas-pdf/
├── CLAUDE.md              # este archivo
├── README.md             # instrucciones de uso paso a paso
├── requirements.txt      # dependencias
├── core.py               # LOGICA compartida (combinar + extraer) — fuente unica de verdad
├── combinar_pdfs.py      # script CLI 1: combinar (llama a core)
├── extraer_pdfs.py       # script CLI 2: extraer de ZIPs (llama a core)
├── app.py                # interfaz web local (Flask) — llama a core
├── Iniciar interfaz.bat  # lanzador de doble clic para app.py
├── pdfs/                 # (input CLI) PDFs origen para combinar
├── zips/                 # (input CLI) archivos .zip para extraer
├── combinados/           # (output CLI) se crea solo — PDFs combinados
├── pdfs_extraidos/       # (output CLI) se crea solo — PDFs extraídos de ZIPs
└── trabajos/             # (output web) carpeta temporal por ejecución; se autolimpia (máx 20)
```

## Arquitectura (IMPORTANTE)

La lógica de negocio vive SOLO en `core.py` (`combinar()` y `extraer_zips()`,
que devuelven diccionarios y no imprimen nada). Tanto los scripts CLI como la
interfaz web la consumen. **No dupliques lógica**: cualquier cambio de reglas se
hace en `core.py` y aplica a ambos caminos.

La interfaz web (`app.py`) usa Flask + waitress y sirve en `0.0.0.0:5000` (elige
puerto libre si está ocupado). Todo el HTML/CSS/JS está embebido en `app.py`
(`PAGINA`) para portabilidad. Tiene DOS modos por operación:

- **Subir** (`modo=subir`): sube archivos por el navegador, se guardan en una
  subcarpeta de `trabajos/`, se ejecuta `core`, y el resultado se devuelve como
  `.zip` descargable. Límite 20 GB (Flask `MAX_CONTENT_LENGTH` + waitress
  `max_request_body_size`).
- **Carpeta** (`modo=carpeta`): NO sube nada; recibe rutas del disco local
  (`ruta_excel`/`carpeta_pdfs`/`carpeta_salida` o `carpeta_zips`), `core` lee y
  escribe directo en disco. Sin límite de tamaño → **es el modo para lotes
  grandes**. Devuelve la ruta de salida; el botón *Abrir carpeta* llama a
  `/abrir` (usa `os.startfile`, solo Windows/local).

Robustez: manejadores de error devuelven SIEMPRE JSON legible (413/500), hay
endpoint `/salud` (el front avisa si el servidor está caído), y `app.log` guarda
trazas. `trabajos/` se autolimpia (máx 20 ejecuciones).

## Empaquetado como .exe (PyInstaller)

Para correr en otros equipos SIN Python (y que *Explorar…* abra las carpetas del
equipo cliente), se empaqueta con PyInstaller `--onedir`. Detalles clave del
código para que funcione empaquetado:

- `_dir_base()`: si `sys.frozen`, usa la carpeta del `.exe` (escritura: trabajos/,
  app.log, defaults). Si no, la de `app.py`.
- `_dir_recursos()`: usa `sys._MEIPASS` para el logo empaquetado.
- **Diálogo Explorar**: NO se puede usar `sys.executable -c "codigo"` (en un .exe,
  `sys.executable` es el propio exe, no python). Solución: el exe/script se
  **relanza a sí mismo con `--elegir <tipo>`**; el bloque `__main__` detecta la
  bandera, muestra el diálogo tkinter (`_mostrar_dialogo`) e imprime la ruta en
  UTF-8, sin arrancar el servidor. `/elegir` arma el comando según `sys.frozen`.
- Build: `pyinstaller --noconfirm --onedir --clean --name "Facturas PDF"
  --add-data "Logo GPA.png;." --hidden-import waitress app.py`.
- Entregable: `Facturas-PDF-para-otro-equipo.zip` (comprime `dist/Facturas PDF/`).
  `Logo GPA.png` se copió al proyecto para poder empaquetarlo.

## Convención de nombres de los PDFs (CRÍTICO)

⚠️ La carpeta real del usuario tiene nombres en VARIOS formatos MEZCLADOS
(verificado 2026-07-03 sobre 22,080 archivos):

- **Solo el folio** (lo más común): `10029998.pdf`, `ACRED3340.pdf`,
  `GDL4081.pdf`, `M850440.pdf`, `GDL1A-21858.pdf` (¡el folio puede traer LETRAS
  y GUION `-`!).
- **Patrón con guiones bajos**: `GPA8402219Y1_FA_10322157_FOCA000109KD3.pdf`
  → `RFC_emisor _ tipo _ FOLIO _ RFC_receptor`. Tipos vistos: FA, CA, FLC, FM,
  MTY, PV. El folio es el segmento numérico.
- **Duplicados** con sufijo `_1`, `_2`, … del mismo folio.

El Excel trae el folio "corto" (ej. `10322157`, `M850440`), no el nombre completo.

### Regla de match de folio (decisión de diseño — REEMPLAZÓ a la anterior)
La suposición vieja ("folio = segmento puramente numérico más largo") ERA FALSA:
rompía con folios alfanuméricos (M…, DL…, GDL…, ACRED…). Ahora en `core.py`:

- `_claves_archivo(stem)` genera las claves candidatas de cada archivo, en
  MAYÚSCULAS: **el nombre completo** (cubre `folio.pdf` y `GDL1A-21858.pdf`) **y
  cada segmento partido por `_`** (cubre el patrón GPA → extrae `10322157`).
  NO se parte por `-` (es parte de folios como GDL1A-21858).
- `construir_indice` arma `{clave: ruta}` recorriendo la carpeta 1 vez (~0.2 s
  para 22k archivos) y un set `multiples` (claves en >1 archivo).
- El match es EXACTO e insensible a mayúsculas (`folio.upper()`), evitando falsos
  positivos por substring.
- El aviso de "duplicados" solo lista folios USADOS que están en `multiples`
  (no los segmentos compartidos como RFC/tipo).

Nota: folios que NO estén como archivo se reportan como faltantes (correcto). Ej.
real: el Excel decía `DL4127` pero el archivo es `GDL4127.pdf` (typo en Excel);
y varios folios simplemente no estaban en la carpeta.

## Reglas del Excel (combinar)

- **Columna de CONTROL** (`Estado` / `Combinado` / `Status` / etc., detectada por
  nombre de encabezado). Si no existe y el Excel tiene encabezado, se crea una
  llamada `Estado`.
- De las columnas restantes: la **última es el nombre de salida**; las demás son
  los folios a combinar. Número de folios por fila VARIABLE; celdas vacías se
  ignoran; se unen en orden izquierda→derecha.
- Lectura/escritura con **openpyxl** (ya no pandas). `_celda_str()` normaliza
  números a texto (evita el `.0` y el problema de folios como número).

### Control de duplicados (bitácora en el Excel)
- Si la celda `Estado` de una fila YA tiene algo → la fila se **OMITE** (no se
  regenera). Contador `omitidos` en el resultado.
- Al generar un PDF se escribe `Creado AAAA-MM-DD HH:MM` en su `Estado` y se
  **guarda el Excel**. En modo carpeta se actualiza el archivo real; en modo
  subir, el Excel actualizado se incluye en el `.zip` de descarga.
- Filas con folios faltantes NO se marcan (se reintentan en la próxima corrida).
- Requiere encabezado (`tiene_encabezado=True`); si no, `control_activo=False` y
  se comporta como antes (sin control). El usuario puede borrar una celda
  `Estado` para forzar regenerar esa fila.
- **Guardar falla si el Excel está abierto** en otro programa → se lanza
  `PermissionError` con mensaje claro ("ciérralo y reintenta").

## Reglas de control (NO cambiar sin avisar al usuario)

- **Nunca generar un PDF combinado incompleto.** Si a una fila le falta aunque
  sea un folio, esa fila NO se genera; se registra en el log con los folios
  faltantes. Para facturas es inaceptable producir documentos parciales en
  silencio.
- **Nunca sobrescribir.** El script de extracción renombra duplicados
  (`factura.pdf`, `factura_1.pdf`) en vez de pisar archivos.
- **Nunca detener el proceso por un error individual.** Se captura, se reporta
  con número de fila / nombre de ZIP, y se continúa. Al final se imprime un log
  de excepciones.
- Folios repetidos en la carpeta de PDFs se avisan por consola.

## Casos aún NO cubiertos (extender solo si el usuario lo pide)

- ZIP protegidos con contraseña.
- ZIP anidados (ZIP dentro de ZIP).
- Formatos .rar / .7z (zipfile no los lee).
- Normalización de ceros a la izquierda (hoy no aplica: usuario confirmó sin ceros).

## Principios de trabajo en este proyecto

- Cambios incrementales, no reconstrucciones.
- No hardcodear estructuras estáticas; mantener parametrizable y escalable.
- Validar impacto antes de tocar lógica que ya funciona.
- Explicar al usuario en términos ejecutivos, no solo técnicos.

## Próximos pasos posibles (backlog)

- ~~Operación sin CMD~~ ✅ HECHO: interfaz web local (`app.py` + `Iniciar interfaz.bat`).
- Empaquetar como .exe (PyInstaller) para no depender de Python instalado.
- Disparo automático al soltar archivos en una carpeta.
- Reporte de excepciones exportable a Excel en vez de consola.
- Integración con el flujo mensual de SAP.
