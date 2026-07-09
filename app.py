"""
Interfaz web local para combinar y extraer PDFs de facturas.

La persona abre un enlace en el navegador (ej. http://localhost:5000), y trabaja
de una de dos formas:

  * SUBIR ARCHIVOS: arrastra sus archivos (comodo para lotes pequenos/medianos).
  * USAR CARPETA DEL EQUIPO: indica la carpeta donde ya estan los archivos y el
    servidor los lee directo del disco (sin limite de tamano, ideal para lotes
    grandes). Solo funciona en el equipo donde corre la interfaz.

No necesita CMD ni conocer Python. Reutiliza la logica de core.py.
Arranca con:  python app.py   (o doble clic en "Iniciar interfaz.bat")

Ver CLAUDE.md para el contexto completo y las decisiones de diseno.
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

from flask import (Flask, request, jsonify, send_file, render_template_string,
                   send_from_directory, abort)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import core

def _dir_base():
    """Carpeta de trabajo (escritura): junto al .exe si está empaquetado,
    o junto a app.py si corre como script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _dir_recursos():
    """Carpeta de recursos empaquetados de solo lectura (logo).
    PyInstaller los extrae en sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else _dir_base()


BASE = _dir_base()
TRABAJOS = BASE / "trabajos"                    # carpeta temporal de subidas
LOGO = _dir_recursos() / "Logo GPA.png"         # logo (empaquetado o local)

# Umbral: en modo carpeta, si el resultado pesa mas que esto NO se comprime a
# .zip (seria lento); se deja en la carpeta y se ofrece "Abrir carpeta".
UMBRAL_ZIP = 300 * 1024 * 1024        # 300 MB

logging.basicConfig(
    filename=str(BASE / "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

app = Flask(__name__)
# Limite de la subida por navegador (modo SUBIR). Para lotes mas grandes se usa
# el modo CARPETA, que no sube nada.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 * 1024  # 20 GB


# --------------------------------------------------------------------------- #
# Manejo de errores: SIEMPRE responder JSON legible.
# --------------------------------------------------------------------------- #

@app.errorhandler(413)
def _muy_grande(e):
    return jsonify(error="La subida supera el limite de 20 GB. Para lotes tan "
                         "grandes usa el modo 'Usar carpeta del equipo'."), 413


@app.errorhandler(Exception)
def _no_controlado(e):
    if isinstance(e, HTTPException):
        return jsonify(error=f"{e.code} {e.name}"), e.code
    app.logger.exception("Error no controlado")
    return jsonify(error=f"Error interno del servidor: {e}"), 500


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _nuevo_trabajo():
    token = uuid.uuid4().hex[:12]
    carpeta = TRABAJOS / token
    carpeta.mkdir(parents=True, exist_ok=True)
    return token, carpeta


def _tam_carpeta(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())


def _zip_resultado(token, carpeta_salida, nombre_zip):
    """Comprime la carpeta de salida en un .zip descargable. Devuelve el nombre
    del zip o None si no habia archivos."""
    salida = Path(carpeta_salida)
    if not any(salida.rglob("*")):
        return None
    destino_base = TRABAJOS / token / nombre_zip
    shutil.make_archive(str(destino_base), "zip", root_dir=salida)
    return f"{nombre_zip}.zip"


def _limpiar_trabajos_viejos(maximo=20):
    if not TRABAJOS.exists():
        return
    carpetas = sorted(TRABAJOS.iterdir(), key=lambda p: p.stat().st_mtime,
                      reverse=True)
    for vieja in carpetas[maximo:]:
        shutil.rmtree(vieja, ignore_errors=True)


def _limpiar_ruta(valor):
    """Normaliza una ruta pegada por el usuario (quita comillas y espacios)."""
    return (valor or "").strip().strip('"').strip("'")


# --------------------------------------------------------------------------- #
# Rutas basicas
# --------------------------------------------------------------------------- #

@app.route("/")
def inicio():
    return render_template_string(
        PAGINA,
        tiene_logo=LOGO.exists(),
        def_pdfs=str(BASE / "pdfs"),
        def_excel=str(BASE / "facturas.xlsx"),
        def_comb=str(BASE / "combinados"),
        def_zips=str(BASE / "zips"),
        def_ext=str(BASE / "pdfs_extraidos"),
    )


@app.route("/salud")
def salud():
    return jsonify(ok=True)


@app.route("/logo")
def logo():
    if LOGO.exists():
        return send_from_directory(LOGO.parent, LOGO.name)
    abort(404)


def _mostrar_dialogo(tipo):
    """Abre el diálogo nativo (tkinter) e imprime la ruta elegida en UTF-8.
    Se ejecuta en un PROCESO propio (ver /elegir) para tener su hilo principal."""
    import tkinter as tk
    from tkinter import filedialog

    sys.stdout.reconfigure(encoding="utf-8")
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    if tipo == "excel":
        ruta = filedialog.askopenfilename(
            title="Selecciona el Excel",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Todos", "*.*")])
    else:
        ruta = filedialog.askdirectory(title="Selecciona la carpeta")
    raiz.destroy()
    print(ruta or "")


@app.route("/elegir", methods=["POST"])
def elegir():
    """Abre el explorador NATIVO de Windows y devuelve la ruta elegida.

    El diálogo aparece en el equipo DONDE CORRE la interfaz (por eso ahora la
    herramienta se puede correr como .exe en cada equipo). Para usuarios que
    entran por red, el campo de texto sigue disponible para pegar la ruta.

    Se lanza como un proceso propio para que tkinter tenga su hilo principal
    (evita conflictos con los hilos del servidor waitress). Funciona igual
    empaquetado (.exe) o como script, usando la bandera --elegir.
    """
    tipo = request.form.get("tipo", "carpeta")  # "carpeta" o "excel"

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--elegir", tipo]         # el propio .exe
    else:
        cmd = [sys.executable, os.path.abspath(__file__), "--elegir", tipo]

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # sin consola extra
    try:
        salida = subprocess.run(cmd, capture_output=True, timeout=300,
                                creationflags=flags)
        ruta = salida.stdout.decode("utf-8", "replace").strip()
        return jsonify(ruta=ruta)
    except subprocess.TimeoutExpired:
        return jsonify(error="Se agotó el tiempo del explorador."), 400
    except Exception as e:
        app.logger.exception("Error al abrir el explorador")
        return jsonify(error=f"No se pudo abrir el explorador: {e}"), 400


@app.route("/abrir", methods=["POST"])
def abrir():
    """Abre una carpeta del equipo en el Explorador (solo local, solo Windows)."""
    ruta = Path(_limpiar_ruta(request.form.get("carpeta", "")))
    if not ruta.exists() or not ruta.is_dir():
        return jsonify(error="La carpeta no existe."), 400
    try:
        os.startfile(str(ruta))  # noqa: disponible en Windows
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=f"No se pudo abrir la carpeta: {e}"), 400


# --------------------------------------------------------------------------- #
# COMBINAR
# --------------------------------------------------------------------------- #

@app.route("/combinar", methods=["POST"])
def combinar():
    modo = request.form.get("modo", "subir")
    encabezado = request.form.get("encabezado", "true") == "true"

    # ---------- Modo CARPETA (lee del disco, sin subir) ----------
    if modo == "carpeta":
        ruta_excel = _limpiar_ruta(request.form.get("ruta_excel"))
        carpeta_pdfs = _limpiar_ruta(request.form.get("carpeta_pdfs"))
        carpeta_salida = _limpiar_ruta(request.form.get("carpeta_salida")) \
            or str(BASE / "combinados")

        if not Path(ruta_excel).is_file():
            return jsonify(error=f"No encuentro el Excel: {ruta_excel}"), 400
        if not Path(carpeta_pdfs).is_dir():
            return jsonify(error=f"No encuentro la carpeta de PDFs: "
                                 f"{carpeta_pdfs}"), 400

        r = core.combinar(ruta_excel, carpeta_pdfs, carpeta_salida, encabezado)
        return jsonify(
            ok=r["ok"],
            generados=r["generados"][:50],
            total_generados=len(r["generados"]),
            omitidos=r["omitidos"],
            control_activo=r["control_activo"],
            errores=r["errores"],
            duplicados=r["duplicados"],
            carpeta=str(Path(carpeta_salida).resolve()),
            descarga=None,
        )

    # ---------- Modo SUBIR (arrastrar archivos) ----------
    excel = request.files.get("excel")
    pdfs = request.files.getlist("pdfs")
    if not excel or excel.filename == "":
        return jsonify(error="Falta el archivo Excel."), 400
    if not pdfs or all(f.filename == "" for f in pdfs):
        return jsonify(error="No subiste ningun PDF."), 400

    token, trabajo = _nuevo_trabajo()
    carpeta_pdfs = trabajo / "pdfs"
    carpeta_pdfs.mkdir(exist_ok=True)
    carpeta_salida = trabajo / "combinados"

    ruta_excel = trabajo / secure_filename(excel.filename)
    excel.save(ruta_excel)
    for f in pdfs:
        if f.filename:
            f.save(carpeta_pdfs / secure_filename(f.filename))

    r = core.combinar(str(ruta_excel), str(carpeta_pdfs),
                      str(carpeta_salida), encabezado)

    # Incluir el Excel ACTUALIZADO (con la columna Estado marcada) en el
    # resultado, para que el usuario conserve la bitacora de control.
    if r["ok"]:
        carpeta_salida.mkdir(exist_ok=True)
        shutil.copy(ruta_excel, carpeta_salida / ruta_excel.name)

    zip_nombre = _zip_resultado(token, carpeta_salida, "PDFs_combinados")
    _limpiar_trabajos_viejos()

    return jsonify(
        ok=r["ok"],
        generados=r["generados"][:50],
        total_generados=len(r["generados"]),
        omitidos=r["omitidos"],
        control_activo=r["control_activo"],
        errores=r["errores"],
        duplicados=r["duplicados"],
        carpeta=None,
        descarga=f"/descargar/{token}/{zip_nombre}" if zip_nombre else None,
    )


# --------------------------------------------------------------------------- #
# EXTRAER
# --------------------------------------------------------------------------- #

@app.route("/extraer", methods=["POST"])
def extraer():
    modo = request.form.get("modo", "subir")
    aplanar = request.form.get("aplanar", "true") == "true"

    # ---------- Modo CARPETA ----------
    if modo == "carpeta":
        carpeta_zips = _limpiar_ruta(request.form.get("carpeta_zips"))
        carpeta_salida = _limpiar_ruta(request.form.get("carpeta_salida")) \
            or str(BASE / "pdfs_extraidos")

        if not Path(carpeta_zips).is_dir():
            return jsonify(error=f"No encuentro la carpeta de ZIPs: "
                                 f"{carpeta_zips}"), 400

        r = core.extraer_zips(carpeta_zips, carpeta_salida, aplanar)
        return jsonify(
            total=r["total"],
            num_zips=r["num_zips"],
            errores=r["errores"],
            carpeta=str(Path(carpeta_salida).resolve()),
            descarga=None,
        )

    # ---------- Modo SUBIR ----------
    zips = request.files.getlist("zips")
    if not zips or all(f.filename == "" for f in zips):
        return jsonify(error="No subiste ningun archivo ZIP."), 400

    token, trabajo = _nuevo_trabajo()
    carpeta_zips = trabajo / "zips"
    carpeta_zips.mkdir(exist_ok=True)
    carpeta_salida = trabajo / "pdfs_extraidos"

    for f in zips:
        if f.filename:
            f.save(carpeta_zips / secure_filename(f.filename))

    r = core.extraer_zips(str(carpeta_zips), str(carpeta_salida), aplanar)
    zip_nombre = _zip_resultado(token, carpeta_salida, "PDFs_extraidos")
    _limpiar_trabajos_viejos()

    return jsonify(
        total=r["total"],
        num_zips=r["num_zips"],
        errores=r["errores"],
        carpeta=None,
        descarga=f"/descargar/{token}/{zip_nombre}" if zip_nombre else None,
    )


@app.route("/descargar/<token>/<nombre>")
def descargar(token, nombre):
    ruta = TRABAJOS / secure_filename(token) / secure_filename(nombre)
    if not ruta.exists():
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=nombre)


# --------------------------------------------------------------------------- #
# Pagina (HTML + CSS + JS embebidos para que el proyecto sea portable)
# --------------------------------------------------------------------------- #

PAGINA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facturas PDF — GPA</title>
<style>
  :root{--azul:#1f4e79;--azul2:#2e6da4;--verde:#2e7d32;--rojo:#c0392b;
        --gris:#f4f6f8;--borde:#d9dee3;--texto:#233;}
  *{box-sizing:border-box}
  body{margin:0;font-family:Segoe UI,system-ui,Arial,sans-serif;background:var(--gris);color:var(--texto)}
  header{background:var(--azul);color:#fff;padding:18px 26px;display:flex;align-items:center;gap:16px}
  header img{height:38px;background:#fff;border-radius:6px;padding:3px}
  header h1{font-size:19px;margin:0;font-weight:600}
  header span{opacity:.8;font-size:13px;display:block;font-weight:400}
  main{max-width:960px;margin:26px auto;padding:0 16px;display:grid;grid-template-columns:1fr 1fr;gap:20px}
  @media(max-width:780px){main{grid-template-columns:1fr}}
  .card{background:#fff;border:1px solid var(--borde);border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
  .card h2{margin:0 0 4px;font-size:17px;color:var(--azul)}
  .card p.sub{margin:0 0 14px;font-size:13px;color:#667}
  .tabs{display:flex;gap:6px;margin-bottom:14px;background:var(--gris);padding:4px;border-radius:9px}
  .tabs button{flex:1;border:0;background:transparent;padding:8px;border-radius:6px;font-size:13px;cursor:pointer;color:#556;font-weight:600}
  .tabs button.act{background:#fff;color:var(--azul);box-shadow:0 1px 2px rgba(0,0,0,.08)}
  .panel{display:none}.panel.act{display:block}
  .drop{border:2px dashed var(--borde);border-radius:10px;padding:16px;text-align:center;cursor:pointer;transition:.15s;background:#fafbfc}
  .drop:hover,.drop.over{border-color:var(--azul2);background:#eef4fb}
  .drop b{color:var(--azul2)} .drop small{display:block;color:#889;margin-top:4px}
  .files{list-style:none;margin:10px 0 0;padding:0;max-height:120px;overflow:auto;font-size:12.5px}
  .files li{padding:3px 8px;background:var(--gris);border-radius:5px;margin-bottom:3px;display:flex;justify-content:space-between}
  .files li span{color:#889}
  .campo{margin:10px 0} .campo label{display:block;font-size:12.5px;color:#556;margin-bottom:3px;font-weight:600}
  .fila{display:flex;gap:8px}
  .campo input[type=text]{flex:1;min-width:0;padding:9px;border:1px solid var(--borde);border-radius:7px;font-size:12.5px;font-family:Consolas,monospace}
  button.expl{flex:0 0 auto;border:1px solid var(--azul2);background:#eef4fb;color:var(--azul);border-radius:7px;padding:0 12px;font-size:12.5px;font-weight:600;cursor:pointer;white-space:nowrap}
  button.expl:hover{background:#dce8f6} button.expl:disabled{opacity:.6;cursor:progress}
  .hint{font-size:11.5px;color:#99a;margin-top:8px;line-height:1.4}
  label.check{display:flex;align-items:center;gap:8px;font-size:13px;margin:14px 0 4px;color:#556}
  button.run{margin-top:14px;width:100%;background:var(--azul);color:#fff;border:0;border-radius:8px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;transition:.15s}
  button.run:hover{background:var(--azul2)} button.run:disabled{background:#9bb;cursor:progress}
  .result{margin-top:16px;font-size:13.5px;display:none} .result.show{display:block}
  .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-weight:600;font-size:13px}
  .badge.ok{background:#e6f4ea;color:var(--verde)} .badge.warn{background:#fdeceb;color:var(--rojo)}
  .errlist{margin:10px 0 0;padding:10px 12px;background:#fff8f6;border:1px solid #f3d6d1;border-radius:8px;max-height:160px;overflow:auto;font-size:12.5px;white-space:pre-wrap}
  a.dl,button.dl{display:inline-block;margin-top:12px;margin-right:8px;background:var(--verde);color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600;font-size:14px;border:0;cursor:pointer}
  a.dl:hover,button.dl:hover{filter:brightness(.94)}
  .rutaout{margin-top:10px;font-size:12.5px;background:var(--gris);padding:8px 10px;border-radius:7px;font-family:Consolas,monospace;word-break:break-all}
  .foot{max-width:960px;margin:8px auto 40px;padding:0 16px;font-size:12px;color:#99a}
</style>
</head>
<body>
<header>
  {% if tiene_logo %}<img src="/logo" alt="GPA">{% endif %}
  <div><h1>Facturas PDF <span>Combinar y extraer — GPA Administración</span></h1></div>
</header>

<div id="alerta" style="display:none;background:#fdeceb;color:#c0392b;padding:12px 26px;font-size:13.5px;border-bottom:1px solid #f3d6d1">
  ⚠ No hay conexión con el servidor local. Asegúrate de que la ventana negra
  (<b>Iniciar interfaz.bat</b>) siga abierta y recarga esta página.
</div>

<main>
  <!-- ===================== COMBINAR ===================== -->
  <section class="card">
    <h2>1 · Combinar PDFs por Excel</h2>
    <p class="sub">Une varios PDFs en uno solo según cada fila de tu Excel.</p>

    <div class="tabs">
      <button class="act" data-t="cSubir">Subir archivos</button>
      <button data-t="cCarpeta">Usar carpeta del equipo</button>
    </div>

    <!-- subir -->
    <div class="panel act" id="cSubir">
      <div class="drop" id="dropExcel"><b>Excel</b> — arrastra o haz clic
        <small>facturas.xlsx (folios + nombre final)</small>
        <input type="file" id="excel" accept=".xlsx,.xls" hidden></div>
      <ul class="files" id="listExcel"></ul>
      <div class="drop" id="dropPdfs" style="margin-top:12px"><b>PDFs origen</b> — arrastra o haz clic
        <small>puedes seleccionar muchos a la vez</small>
        <input type="file" id="pdfs" accept=".pdf" multiple hidden></div>
      <ul class="files" id="listPdfs"></ul>
    </div>

    <!-- carpeta -->
    <div class="panel" id="cCarpeta">
      <div class="campo"><label>Archivo Excel</label>
        <div class="fila"><input type="text" id="rExcel" value="{{ def_excel }}">
          <button type="button" class="expl" onclick="explorar('excel','rExcel',this)">Explorar…</button></div></div>
      <div class="campo"><label>Carpeta con los PDFs origen</label>
        <div class="fila"><input type="text" id="rPdfs" value="{{ def_pdfs }}">
          <button type="button" class="expl" onclick="explorar('carpeta','rPdfs',this)">Explorar…</button></div></div>
      <div class="campo"><label>Carpeta donde guardar los combinados</label>
        <div class="fila"><input type="text" id="rComb" value="{{ def_comb }}">
          <button type="button" class="expl" onclick="explorar('carpeta','rComb',this)">Explorar…</button></div></div>
      <p class="hint">💡 Clic en <b>Explorar…</b> para elegir desde el Explorador de
        Windows (o pega la ruta a mano). Sin límite de tamaño.</p>
    </div>

    <label class="check"><input type="checkbox" id="encabezado" checked>
      Mi Excel tiene fila de títulos (encabezado)</label>
    <button class="run" id="btnComb">Combinar</button>
    <div class="result" id="resComb"></div>
  </section>

  <!-- ===================== EXTRAER ===================== -->
  <section class="card">
    <h2>2 · Extraer PDFs de ZIPs</h2>
    <p class="sub">Saca todos los PDFs contenidos dentro de varios archivos .zip.</p>

    <div class="tabs">
      <button class="act" data-t="eSubir">Subir archivos</button>
      <button data-t="eCarpeta">Usar carpeta del equipo</button>
    </div>

    <div class="panel act" id="eSubir">
      <div class="drop" id="dropZips"><b>Archivos ZIP</b> — arrastra o haz clic
        <small>puedes seleccionar muchos a la vez</small>
        <input type="file" id="zips" accept=".zip" multiple hidden></div>
      <ul class="files" id="listZips"></ul>
    </div>

    <div class="panel" id="eCarpeta">
      <div class="campo"><label>Carpeta con los archivos ZIP</label>
        <div class="fila"><input type="text" id="rZips" value="{{ def_zips }}">
          <button type="button" class="expl" onclick="explorar('carpeta','rZips',this)">Explorar…</button></div></div>
      <div class="campo"><label>Carpeta donde guardar los PDFs extraídos</label>
        <div class="fila"><input type="text" id="rExt" value="{{ def_ext }}">
          <button type="button" class="expl" onclick="explorar('carpeta','rExt',this)">Explorar…</button></div></div>
      <p class="hint">💡 Clic en <b>Explorar…</b> para elegir desde el Explorador de
        Windows. Sin límite de tamaño; ideal para lotes grandes.</p>
    </div>

    <label class="check"><input type="checkbox" id="aplanar" checked>
      Juntar todos los PDFs (si lo desmarcas, crea una subcarpeta por ZIP)</label>
    <button class="run" id="btnExt">Extraer</button>
    <div class="result" id="resExt"></div>
  </section>
</main>
<p class="foot">Interfaz local · los archivos no salen de tu equipo/red · GPA Administración</p>

<script>
// ---- pestañas ----
document.querySelectorAll(".tabs").forEach(tabs=>{
  tabs.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{
    tabs.querySelectorAll("button").forEach(x=>x.classList.remove("act"));
    b.classList.add("act");
    const grupo=b.closest(".card");
    grupo.querySelectorAll(".panel").forEach(p=>p.classList.remove("act"));
    grupo.querySelector("#"+b.dataset.t).classList.add("act");
  }));
});
function modoDe(card){ // "subir" o "carpeta"
  return card.querySelector(".tabs button.act").dataset.t.endsWith("Carpeta")?"carpeta":"subir";
}

// ---- drag & drop ----
function conectarDrop(dropId,inputId,listId){
  const drop=document.getElementById(dropId),input=document.getElementById(inputId),
        lista=document.getElementById(listId);
  drop.addEventListener("click",()=>input.click());
  drop.addEventListener("dragover",e=>{e.preventDefault();drop.classList.add("over")});
  drop.addEventListener("dragleave",()=>drop.classList.remove("over"));
  drop.addEventListener("drop",e=>{e.preventDefault();drop.classList.remove("over");input.files=e.dataTransfer.files;pintar();});
  input.addEventListener("change",pintar);
  function pintar(){
    lista.innerHTML="";
    [...input.files].slice(0,200).forEach(f=>{
      const li=document.createElement("li");
      li.innerHTML=`<span title="${f.name}">${f.name}</span><span>${(f.size/1024).toFixed(0)} KB</span>`;
      lista.appendChild(li);
    });
    if(input.files.length>1){const li=document.createElement("li");
      li.innerHTML=`<b>${input.files.length} archivos seleccionados</b>`;lista.prepend(li);}
  }
  return input;
}
const inExcel=conectarDrop("dropExcel","excel","listExcel");
const inPdfs =conectarDrop("dropPdfs","pdfs","listPdfs");
const inZips =conectarDrop("dropZips","zips","listZips");

// ---- render de resultados ----
function render(divId,data,tipo){
  const div=document.getElementById(divId);div.classList.add("show");
  if(data.error){div.innerHTML=`<span class="badge warn">Error</span><p>${data.error}</p>`;return;}
  let html="";
  if(tipo==="comb"){
    const n=data.total_generados!==undefined?data.total_generados:data.ok;
    html=`<span class="badge ok">${n} PDF(s) combinados</span>`;
    if(data.omitidos)
      html+=` <span class="badge" style="background:#eef4fb;color:#1f4e79">${data.omitidos} omitidos (ya creados)</span>`;
    if(data.control_activo===false)
      html+=`<p style="color:#b8860b;margin:8px 0 0">Nota: para el control de duplicados, activa la casilla "Mi Excel tiene fila de títulos".</p>`;
    if(data.duplicados&&data.duplicados.length)
      html+=`<p style="color:#b8860b;margin:8px 0 0">Aviso: ${data.duplicados.length} folio(s) repetidos en la carpeta origen.</p>`;
  }else{
    html=`<span class="badge ok">${data.total} PDF(s) extraídos de ${data.num_zips} ZIP</span>`;
  }
  if(data.errores&&data.errores.length){
    html+=`<div style="margin-top:10px"><span class="badge warn">${data.errores.length} con problemas</span>`;
    html+=`<div class="errlist">${data.errores.join("\n")}</div></div>`;
  }
  if(data.carpeta){
    html+=`<div class="rutaout">📁 Resultados en:<br>${data.carpeta}</div>`;
    html+=`<button class="dl" onclick="abrirCarpeta('${data.carpeta.replace(/\\/g,'\\\\')}')">Abrir carpeta</button>`;
  }
  if(data.descarga){
    html+=`<div><a class="dl" href="${data.descarga}">⬇ Descargar resultado (.zip)</a></div>`;
  }
  if(!data.carpeta&&!data.descarga)
    html+=`<p style="color:#889;margin-top:10px">No se generó ningún archivo.</p>`;
  div.innerHTML=html;
}

async function abrirCarpeta(ruta){
  const fd=new FormData();fd.append("carpeta",ruta);
  try{await fetch("/abrir",{method:"POST",body:fd});}catch(_){}
}

// Abre el explorador nativo de Windows (en el equipo que corre la interfaz)
// y rellena el campo con la ruta elegida.
async function explorar(tipo,inputId,btn){
  const original=btn.textContent;btn.disabled=true;btn.textContent="…";
  try{
    const fd=new FormData();fd.append("tipo",tipo);
    const r=await fetch("/elegir",{method:"POST",body:fd});
    const data=await r.json();
    if(data.error){alert(data.error);}
    else if(data.ruta){document.getElementById(inputId).value=data.ruta;}
  }catch(e){
    alert("No se pudo abrir el explorador. Esta función solo funciona en el "
      +"equipo donde corre la interfaz; si entraste por red, pega la ruta a mano.");
  }finally{ btn.disabled=false;btn.textContent=original; }
}

// ---- envío ----
async function enviar(url,form,btn,divId,tipo){
  const original=btn.textContent;btn.disabled=true;btn.textContent="Procesando…";
  let resp;
  try{ resp=await fetch(url,{method:"POST",body:form}); }
  catch(e){ mostrarAlerta(true);
    render(divId,{error:"El servidor local no respondió. ¿Cerraste la ventana negra? "
      +"Vuelve a abrir 'Iniciar interfaz.bat' y recarga la página."},tipo);
    btn.disabled=false;btn.textContent=original;return; }
  try{
    const texto=await resp.text();let data;
    try{ data=JSON.parse(texto); }
    catch(_){ data={error:`El servidor respondió con un error (HTTP ${resp.status}). Revisa app.log en la carpeta.`}; }
    render(divId,data,tipo);
  }catch(e){ render(divId,{error:"No se pudo leer la respuesta del servidor."},tipo); }
  finally{ btn.disabled=false;btn.textContent=original; }
}

document.getElementById("btnComb").addEventListener("click",()=>{
  const card=document.getElementById("btnComb").closest(".card");
  const modo=modoDe(card);const fd=new FormData();
  fd.append("modo",modo);
  fd.append("encabezado",document.getElementById("encabezado").checked);
  if(modo==="carpeta"){
    fd.append("ruta_excel",document.getElementById("rExcel").value);
    fd.append("carpeta_pdfs",document.getElementById("rPdfs").value);
    fd.append("carpeta_salida",document.getElementById("rComb").value);
  }else{
    if(!inExcel.files.length){alert("Selecciona el archivo Excel.");return;}
    if(!inPdfs.files.length){alert("Selecciona los PDFs origen.");return;}
    fd.append("excel",inExcel.files[0]);
    [...inPdfs.files].forEach(f=>fd.append("pdfs",f));
  }
  enviar("/combinar",fd,document.getElementById("btnComb"),"resComb","comb");
});

document.getElementById("btnExt").addEventListener("click",()=>{
  const card=document.getElementById("btnExt").closest(".card");
  const modo=modoDe(card);const fd=new FormData();
  fd.append("modo",modo);
  fd.append("aplanar",document.getElementById("aplanar").checked);
  if(modo==="carpeta"){
    fd.append("carpeta_zips",document.getElementById("rZips").value);
    fd.append("carpeta_salida",document.getElementById("rExt").value);
  }else{
    if(!inZips.files.length){alert("Selecciona los archivos ZIP.");return;}
    [...inZips.files].forEach(f=>fd.append("zips",f));
  }
  enviar("/extraer",fd,document.getElementById("btnExt"),"resExt","ext");
});

// ---- salud ----
function mostrarAlerta(v){document.getElementById("alerta").style.display=v?"block":"none";}
async function chequeoSalud(){
  try{const r=await fetch("/salud",{cache:"no-store"});mostrarAlerta(!r.ok);}
  catch(_){mostrarAlerta(true);}
}
chequeoSalud();setInterval(chequeoSalud,15000);
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #

def _puerto_libre(preferido=5000):
    for p in range(preferido, preferido + 15):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return preferido


if __name__ == "__main__":
    # Modo diálogo: el .exe/script se relanza a sí mismo con --elegir para
    # mostrar el explorador nativo y devolver la ruta (ver endpoint /elegir).
    if len(sys.argv) >= 3 and sys.argv[1] == "--elegir":
        _mostrar_dialogo(sys.argv[2])
        sys.exit(0)

    import threading
    import webbrowser

    from waitress import serve

    TRABAJOS.mkdir(exist_ok=True)
    puerto = _puerto_libre(5000)
    url = f"http://localhost:{puerto}"

    print("=" * 56)
    print("  Interfaz Facturas PDF - GPA")
    print(f"  Abre en tu navegador:  {url}")
    print("  (Para compartir en la red local: http://TU-IP:%d )" % puerto)
    print("  NO cierres esta ventana mientras uses la interfaz.")
    print("=" * 56)

    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        # max_request_body_size alineado con Flask (20 GB) para el modo SUBIR.
        serve(app, host="0.0.0.0", port=puerto,
              max_request_body_size=20 * 1024 * 1024 * 1024)
    except Exception as e:
        print("\nERROR al iniciar el servidor:", e)
        input("Presiona Enter para cerrar...")
