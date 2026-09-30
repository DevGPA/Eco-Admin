# Módulo «Plan Mtto» (plan anual de mantenimiento) — cómo está construido

Rama `mantenimiento` de DevGPA/Eco-Admin (carpeta `Operaciones-GPA/`). **Sin desplegar** por
decisión del usuario. La fuente viva del diseño sigue en `CLAUDE\mantenimiento-gpa\`; si algo
difiere, manda `ESPECIFICACION.md`.

| Archivo | Qué es |
|---|---|
| `INSTRUCCIONES.md` | Traspaso con el que se construyó: modelo en la tabla única, rutas, permisos, importador, lo que no se toca |
| `ESPECIFICACION.md` | Fuente de verdad del diseño (v1.4, con el registro de lo construido) |
| `DECISIONES.md` | Las respuestas del usuario a las preguntas abiertas y cómo se aplicaron; supuestos no preguntados |
| `PROCEDIMIENTOS-PROPUESTOS.md` | Los 13 procedimientos que ningún archivo de GPA describe (se cargan como propuesta editable) |
| `LECTOR-DEL-PLAN.md` | Cómo se lee el Excel del plan (colores, filas, trampas) y las cifras que deben salir |

## Dónde vive cada cosa en el código

| Pieza | Archivo | Notas |
|---|---|---|
| Reglas puras (semanas, estatus derivado, asignación, nivel, reinicio del reloj, año siguiente) | `mantenimiento/logica.py` | Sin boto3; todo recibe `hoy` explícito |
| Lectura/escritura en la tabla única | `mantenimiento/datos.py` | Prefijos `CAT#ACTIVO`, `CAT#TIPOACTIVO`, `CAT#PERIODICIDAD`, `CAT#AREA`, `MP`, `MPC`, `MTTO#ACTA`; `CAT#MODULO/MOD#mantenimiento` lleva `administradores` y `sucursales` |
| Rutas `/mantenimiento/*` | `mantenimiento/rutas.py` | `handler.py` solo enruta (`mtto_rutas.manejar`) y pasa sus ayudantes; sin import circular |
| Eventos del HTTP API | `template.yaml` | 11 rutas nuevas (sin ellas API Gateway da 404) |
| Cambios compartidos (aditivos) | `handler.py` (`MODULO`, `_TIPOS_EVID`, enrutado), `db/modelos.py` (constantes), `db/escritura.py` (`guardar_modulo` conserva `administradores`/`sucursales`), `frontend/gpa-api.js` (`TIPO_EVID.mantenimiento="MP"` + 11 métodos) | Ver el radio de impacto abajo |
| Pestaña Plan Mtto | `frontend/index.html` (`ModPlanMtto`, `MttoAgenda`, `MttoTarjeta`, `MttoDetalle`, `MttoCorrectivo`, `MttoTablero`, `MttoAsignacion`, `MttoCatalogos`, `MttoAdminsEditor`) | Antes del bloque del motor de formularios; se pinta solo si el módulo `mantenimiento` existe y está activo |
| Manual | `frontend/manual.html` v3.1, sección «6+ Plan Mtto» | Mismo commit que la pestaña |
| Tipos de activo (23) | `seed/mtto_tipos.py` | Datos de carga inicial; el importador NO pisa los ya editados |
| Importador del plan | `seed/importar_plan_mtto.py` | Dry-run por omisión; `--aplicar` escribe; requiere `openpyxl` y la COPIA del Excel |

## Cómo se carga el plan (cuando el usuario decida desplegar)

1. Desplegar el servidor (`sam build` + `sam deploy`) con esta rama; Amplify publica la app.
2. En CloudShell subir la copia del Excel (Actions → Upload file) y correr:
   ```
   cd ~/Eco-Admin/Operaciones-GPA
   pip install openpyxl -q
   python3 seed/importar_plan_mtto.py --xlsx ~/CALENDARIO\ MANTENIMIENTO\ 2025\ SCS.xlsx --stack gpa-operaciones-prod --region us-east-1
   ```
   Debe decir **233 / 546 / 3 / 57** en la lectura; si no, se detiene. Revisar el acta en pantalla.
3. Repetir con `--aplicar`. Crea el módulo `mantenimiento` («Plan Mtto»), los tipos, las
   periodicidades, las áreas, los activos (una pieza = un activo) y los vencimientos.
4. En la app: Admin → Módulos → Plan Mtto → **Administradores**: poner el correo del Jefe de
   Mantenimiento. Admin → Cuentas: dar el módulo **Plan Mtto** y su sucursal a cada técnico.
5. Plan Mtto → Asignación: un área completa → titular; afinar por activo.

El importador es re-ejecutable: no borra vencimientos con captura ni activos dados de alta en el
módulo (los marca «no está en el Excel vigente»).

## Radio de impacto de lo compartido (revisado)

- `handler.py`: una clave en `MODULO` (solo la usan `_crear/_listar`, que el módulo no llama), `m.MP`
  en `_TIPOS_EVID` (whitelist de evidencias; el test `test_evidencias_tipos` cruza el cliente), y
  el enrutado por prefijo `/mantenimiento` **antes** del bloque `/admin/*` (no lo toca).
- `db/escritura.py::guardar_modulo`: conserva `administradores`/`sucursales` si el panel no los
  manda. Antes un `put_item` los habría borrado al activar/desactivar. Los módulos dinámicos
  existentes no tienen esos campos: para ellos no cambia nada (probado en `test_mantenimiento_rutas`).
- `frontend/index.html`: `BUILTIN_IDS`, `opModules` (+1 pestaña condicionada), render de `App`,
  fichas de módulos en Admin → Cuentas (se renombró «Mtto» a «Mtto (checklists)»), claves
  reservadas de «Nuevo módulo», lista de módulos (editor de administradores). Pantallas revisadas
  con sus pruebas: combustible, checklists, EPP, examen, permisos, insignias, botón anclar.
- `frontend/gpa-api.js`: solo agrega.

## Verificación (escala 0-BIS del protocolo)

| Qué | Nivel | Detalle |
|---|---|---|
| Lógica pura | **probado en simulación** | `tests/test_mantenimiento_logica.py` (33): semana 1 = 29-dic-2025, vencida derivada, excepción sobre titular, los 3 casos del reinicio, nivel por 4 casos, un supervisor NO administra, año siguiente, picos |
| Rutas de punta a punta | **probado en simulación** | `tests/test_mantenimiento_rutas.py` (30) por `lambda_handler` con DynamoDB simulada (tabla + 3 índices): alcance por nivel, ejecutar solo lo asignado o sin asignar, GSI3 reescrito al tomar/asignar, pedir vs aplicar reprogramación, correctivo con y sin preventivo (no toca historia ni capturas), titular por área, generar/publicar, `guardar_modulo` conserva administradores, `url-subida` acepta `MP` |
| Whitelist de evidencias vs cliente | **probado en simulación** | `tests/test_evidencias_tipos.py` lee `TIPO_EVID` del archivo real |
| Suite completa del servidor | **237 tests en verde** | `python -m unittest discover -s tests` |
| Pantalla | **probado en simulación** | `tests/frontend/test_plan_mtto.js` (73 comprobaciones) sobre los componentes reales; el resto de pruebas de pantalla siguen en verde |
| Importador contra la copia real del Excel | **probado en simulación (dry-run local)** | 233 / 546 / 3 / 57 exactos; expandido 291 activos / 720 vencimientos con las metas de RESPALDO |
| JSX | **compila** | `node _validate.js frontend/index.html` |
| Contra el servicio real, en celular, con las metas reales del Tablero, `sam build` | **sin verificar** | No hay despliegue por orden del usuario; lo verifica quien despliegue siguiendo los pasos de arriba |

## Lo que quedó fuera (a propósito)

- `POST /mantenimiento/admin/importar`: leer colores del Excel exige `openpyxl`, que no está en
  la Lambda; la importación es el script de CloudShell.
- Repartidor automático de carga: el generador del año siguiente **señala** las semanas pico y
  dos alternativas; no mueve nada. La jefatura reprograma desde la agenda.
- La sucursal `Tisa` no existe en la app: sus 3 activos los ve solo el administrador hasta que
  el admin de la app la dé de alta y se la asigne a alguien (el acta lo avisa).
- Los 12 datos técnicos ⟨confirmar⟩ siguen en los textos, marcados como propuesta.
