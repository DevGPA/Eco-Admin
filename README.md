# Facturas PDF — Combinar y Extraer

Dos utilidades para automatizar el manejo de PDFs de facturas.
Se pueden usar de dos formas: **interfaz web (recomendada, sin CMD)** o scripts de terminal.

## Requisitos (una sola vez)

Python instalado con las librerias:
```
pip install -r requirements.txt
```
(equivale a: `pip install pypdf pandas openpyxl flask waitress`)

---

## ⭐ Forma fácil — Interfaz web (sin CMD, sin Claude)

Para que cualquier persona la use solo con un enlace, sin escribir comandos.

1. Haz **doble clic en `Iniciar interfaz.bat`**.
2. Se abre solo en tu navegador (`http://localhost:5000`).
   - Deja abierta la ventana negra mientras la uses; ciérrala para apagarla.
3. Cada tarjeta tiene dos modos (pestañas):
   - **Subir archivos** — arrastras los archivos. Cómodo para lotes pequeños/medianos.
     El resultado se descarga como `.zip`. (Límite de 20 GB por envío.)
   - **Usar carpeta del equipo** — en vez de subir, eliges la carpeta/archivo con
     el botón **Explorar…** (abre el Explorador de Windows) o pegas la ruta a mano.
     El servidor los lee del disco: **sin límite de tamaño**, ideal para lotes
     grandes. El resultado queda en la carpeta que indiques y puedes abrirla con
     el botón *Abrir carpeta*.
     · Nota: *Explorar…* y *Abrir carpeta* solo funcionan en el equipo donde corre
       la interfaz. Si entras por red desde otra máquina, pega la ruta a mano.
4. Cada ejecución muestra cuántos se generaron y, si hubo problemas, el detalle
   exacto (qué fila o qué ZIP falló). Revisa siempre ese aviso.

> **¿Lote de varios GB?** Usa el modo **Usar carpeta del equipo**. Subir gigabytes
> por el navegador es lento y frágil; leer del disco es instantáneo.

**Compartir con otra persona en la misma red:** que abra en su navegador
`http://LA-IP-DE-ESTE-EQUIPO:5000` (mientras la ventana negra siga abierta).
Los archivos nunca salen del equipo/red — todo se procesa localmente.

---

## 🖥️ Correr en OTRO equipo (sin instalar Python) — Ejecutable .exe

Para que la herramienta corra de forma independiente en otra computadora (y ahí
el botón *Explorar…* abra las carpetas de ESE equipo, no del tuyo):

1. Copia el archivo **`Facturas-PDF-para-otro-equipo.zip`** al otro equipo.
2. Descomprímelo (clic derecho → Extraer todo). Queda la carpeta **`Facturas PDF`**.
3. Doble clic en **`Facturas PDF.exe`**. Se abre solo en el navegador.
   - Si Windows SmartScreen avisa "editor desconocido": *Más información → Ejecutar
     de todas formas* (es porque el .exe no está firmado; es seguro).
4. Mantén junta toda la carpeta (el .exe necesita la subcarpeta `_internal`).

No necesita Python ni internet: todo corre localmente en ese equipo.

### Regenerar el .exe (solo para el desarrollador)
```
pip install pyinstaller
pyinstaller --noconfirm --onedir --clean --name "Facturas PDF" ^
  --add-data "Logo GPA.png;." --hidden-import waitress app.py
```
El resultado queda en `dist/Facturas PDF/`.

---

## Forma alterna — Scripts de terminal

Útil para lotes grandes o automatizar. Requiere abrir una terminal en la carpeta.

## Script 1 — Combinar PDFs por fila de Excel

Une varios PDFs en uno solo, segun lo indicado en un Excel.

**Preparar:**
1. Coloca tu `facturas.xlsx` en esta carpeta.
2. Coloca todos los PDFs origen dentro de la subcarpeta `pdfs/`.
3. En el Excel: cada fila lista los folios a combinar en las primeras columnas,
   y en la ULTIMA columna (antes de Estado) el nombre que tendra el PDF resultante.

   | Folio 1  | Folio 2  | Folio 3  | Nombre final | Estado                |
   |----------|----------|----------|--------------|-----------------------|
   | 10321876 | 10321877 |          | FACT-001     | Creado 2026-07-01 12:30 |
   | 10330011 | 10330012 | 10330013 | FACT-002     |                       |

### Control para no duplicar (columna Estado)

- La columna **Estado** es el control. Si no la tienes, la herramienta **la crea sola**.
- Cuando se genera un PDF, esa fila se marca con **`Creado <fecha y hora>`**.
- En la siguiente corrida, **toda fila que ya tenga algo en Estado se omite** (no
  se vuelve a generar). Así el Excel es tu bitácora y no duplicas trabajo.
- ¿Necesitas regenerar una fila? **Borra su celda Estado** y vuelve a combinar.
- Importante: **cierra el Excel** antes de combinar (si está abierto, no se puede
  guardar la marca). Requiere que el Excel tenga fila de títulos (encabezado).

**Correr:**
```
python combinar_pdfs.py
```
Resultado en la carpeta `combinados/`.

## Script 2 — Extraer PDFs de ZIPs

Saca todos los PDFs contenidos en varios archivos ZIP.

**Preparar:**
1. Coloca todos los `.zip` dentro de la subcarpeta `zips/`.

**Correr:**
```
python extraer_pdfs.py
```
Resultado en la carpeta `pdfs_extraidos/`.

Opcion: en el script, `APLANAR = False` crea una subcarpeta por cada ZIP
(util para trazabilidad de origen).

## Interpretar resultados

Ambos scripts terminan con una linea `OK: N ...` y, si hubo problemas, un bloque
`ADVERTENCIA:` que detalla exactamente que fila o que ZIP fallo, sin detener el
proceso. Revisa siempre ese bloque antes de dar el trabajo por terminado.

## Notas

Ver `CLAUDE.md` para el detalle de decisiones de diseno, convencion de nombres
y reglas de control.
