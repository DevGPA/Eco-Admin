# INSTRUCCIONES — Módulo de Mantenimiento dentro de Operaciones-GPA

**Para:** la sesión que trabaja en `CLAUDE\wt-operaciones\Operaciones-GPA` (rama `operaciones-gpa`).
**De:** la sesión de diseño del módulo (carpeta `CLAUDE\mantenimiento-gpa\`).
**Fecha:** 25 de septiembre de 2026.

Esta sesión no tiene el contexto de las conversaciones de diseño. Todo lo que necesita está
en archivos; este documento dice cuáles, en qué orden, y qué construir.

---

## 0. Reglas que mandan sobre todo lo demás

1. **Aplica `CLAUDE\PROTOCOLO-desarrollos.md`** antes de tocar nada, y su sección 0-BIS al
   reportar: nunca «listo» ni «verificado» sin nombrar el nivel alcanzado y lo que quedó sin
   verificar.
2. **No se despliega.** Se construye en una rama nueva con worktree propio. El usuario decide
   cuándo y qué se despliega, y lo hace él en CloudShell. No prepares `sam deploy` salvo que
   te lo pida.
3. **No romper lo que funciona.** Todo lo del módulo es **aditivo**: rutas nuevas, prefijos de
   llave nuevos, archivos nuevos. La lista de lo que **no se toca** está en §9. Antes de
   modificar cualquier archivo compartido, `grep` de todos sus usos y radio de impacto.
4. **El manual sale en el mismo commit** que el cambio visible (`frontend/manual.html`).
5. **No resuelvas solo las decisiones pendientes** (§10). Pregunta al usuario.
6. **Ni un catálogo en el código.** Áreas, sucursales, tipos, periodicidades, procedimientos,
   materiales, herramienta, técnicos y asignaciones son datos configurables.

---

## 1. Lee primero, en este orden

| # | Archivo | Qué es |
|---|---|---|
| 1 | `CLAUDE\mantenimiento-gpa\ESPECIFICACION.md` (v1.3) | **La fuente de verdad del diseño.** Modelo, estatus, asignación, correctivos, motor, importador, permisos, fases, decisiones abiertas |
| 2 | `CLAUDE\mantenimiento-gpa\PROCEDIMIENTOS-PROPUESTOS.md` | Procedimientos por tipo para los 13 tipos que ningún archivo de GPA describe. **Son propuestas**: la app debe permitir editarlos, no fijarlos |
| 3 | `CLAUDE\mantenimiento-gpa\CATALOGO-CODIGOS-mantenimiento-GPA.xlsx` | Los 233 activos con código nuevo `TIPO-SUC-##`, el anterior y el motivo del cambio |
| 4 | `CLAUDE\mantenimiento-gpa\PLAN-2026-semanas-limite.xlsx` | Hoja **Ejecuciones**: las 546 filas `código · sucursal · semana` que el importador crea. Hoja **Acta de importación**: los 57 hallazgos |
| 5 | `CLAUDE\mantenimiento-gpa\agenda-mantenimiento-GPA.html` | **Referencia funcional probada.** Pantallas del técnico y la jefatura, cálculo de semana, estatus derivados, asignación titular/excepción, correctivo con reinicio de reloj, kit de material y herramienta. **Porta la lógica; no incrustes el archivo.** Todo pasa por un objeto `almacen` de 4 funciones: ese es el corte donde entra la API |
| 6 | `CLAUDE\mantenimiento-gpa\herramientas\README.md` y sus 4 scripts | El lector del plan que ya funciona: cómo se leen los colores, las trampas de la hoja, las cifras que deben salir |

Si algo de este documento contradice a `ESPECIFICACION.md`, **manda la especificación**.

---

## 2. Lo que ya existe en el repo y se reusa sin tocarlo

Verificado leyendo el código de la rama `operaciones-gpa`:

| Pieza | Dónde | Cómo se usa |
|---|---|---|
| Identidad: rol, sucursales (varias), módulos, nombre | `handler.py` `_claims()` líneas 77–91 | Se lee del JWT. `sucursales=[]` significa todas; `modulos=[]` significa todos |
| Permiso por módulo | `handler.py` `_modulo_ok()` 93–101 | Registrar la clave `mantenimiento` en el mapa `MODULO` |
| Alcance por rol al listar | `db/queries.py` `listar_registros()` 28–50 | admin/analista todos (GSI1) · supervisor sus sucursales (GSI2) · operador lo suyo (GSI3) |
| Llaves de un registro | `db/modelos.py` `registro_keys()` 48–59 | `PK={tipo}#{rid}`, `SK=META`, GSI1 `{tipo}`/fecha, GSI2 `{tipo}#{sucursal}`/fecha, GSI3 `{tipo}#{cuenta}`/fecha |
| Registro de módulo | `db/escritura.py` `guardar_modulo()` | `PK=CAT#MODULO`, `SK=MOD#{clave}` con `clave, nombre, icono, orden, activo` |
| Fotos a S3 | `POST /evidencias/url-subida`, `s3/evidencias.py` | URL prefirmada de subida; `url_lectura(key)` para mostrar |
| Tabla única con 3 índices | `template.yaml` 297–333 | `gpa_operaciones_${Env}`: `tipo-fecha-idx`, `sucursal-fecha-idx`, `cuenta-fecha-idx` |
| Panel de cuentas | `frontend/index.html` ~1853 | Botones por módulo y por sucursal (selección múltiple) |
| Panel de módulos | `frontend/index.html` ~1859 | Sección `modulos` del panel admin |

**La única ruta que lista cuentas, `GET /admin/cuentas`, exige rol `admin`** (`handler.py`
210–214). Por eso el módulo lleva su propia ruta de lectura (§5).

---

## 3. Rama y worktree

Desde la raíz del repo `Eco-Admin` (no desde `wt-operaciones`):

```
git worktree add ../wt-mantenimiento -b mantenimiento operaciones-gpa
```

Trabaja únicamente en `CLAUDE\wt-mantenimiento\Operaciones-GPA\`. No toques `wt-operaciones`.
Commits pequeños y frecuentes; el primero, antes de escribir código, con este documento y la
especificación copiados a `Operaciones-GPA/docs/mantenimiento/` para que el repo se explique solo.

---

## 4. Modelo de datos en la tabla única

Todo con prefijos nuevos. Ningún ítem existente cambia de forma.

### Catálogos

| Ítem | PK | SK | Campos |
|---|---|---|---|
| Activo (233) | `CAT#ACTIVO` | `ACT#{codigo}` | `codigo, descripcion, modelo, serie, sucursal, area, tipo, periodicidad, semPeriodo, responsabilidad (INTERNO/EXTERNO), titular (cuenta o null), activo (bool), origen (excel/modulo), codigoAnterior` |
| Tipo de activo (23) | `CAT#TIPOACTIVO` | `TIPO#{pref}` | `pref, nombre, procedimiento, puntos[], materiales[], herramienta[], esPropuesta (bool)` |
| Periodicidad | `CAT#PERIODICIDAD` | `PER#{texto}` | `texto, semanas` (0 = Variable, no se calcula) |
| Módulo | `CAT#MODULO` | `MOD#mantenimiento` | los campos de siempre **+ `administradores: [cuentas]`** |

`sucursal` y `area` reutilizan `CAT#SUCURSAL` y un `CAT#AREA` nuevo con los 16 nombres
normalizados. Los 8 códigos de sucursal (`GDL, CZD, MEX, MTY, CAN, PVR, CBS, TIS`) están en
la especificación §2.

### Programación — un ítem por vencimiento (546 en 2026)

Tipo de registro nuevo **`MP`** (mantenimiento programado). Verifica antes que `MP` no esté
en uso: hoy existen `SOL`, `CL`, `MC` y `FRM#*`.

```
rid    = {codigo}#{anio}#{semana}            → PK = MP#TRA-GDL-01#2026#38
fecha  = fecha límite de la semana (sábado, ISO)   → GSI1SK / GSI2SK / GSI3SK
GSI2PK = MP#{sucursal}                        → "qué vence esta semana en Cedis" en una consulta
GSI3PK = MP#{cuenta asignada efectiva}        → "lo mío" del técnico
```

Usa `registro_keys("MP", rid, sucursal, cuenta, fecha)` tal cual. Campos:
`codigo, anio, semana, sucursal, area, estatus, asignadoA (excepción, o null), tecnico,
inicio, fin, desc, checks[], incidencias[], faltantes[], fotos[] (keys de S3), motivo,
hist[], reprogramadaA, origen (importado/generado/correctivo)`.

**Asignado efectivo** = `MP.asignadoA` si existe, si no `activo.titular`. Al asignar o
reasignar hay que **reescribir `GSI3PK`** del ítem para que el índice por cuenta siga
sirviendo.

**Vencida no se guarda**: se deriva en el servidor (`fecha < hoy` y estatus abierto) y se
devuelve calculada.

### Correctivo — tipo **`MPC`**

```
rid = {codigo}#{timestamp}   → PK = MPC#AIR-GDL-22#1758812345
```

Campos: `codigo, sucursal, semana, falla, desc, refacciones, resp, conPreventivo,
fotos[], tecnico, fin, semanasRetiradas[]`. Si `conPreventivo` y el activo tiene
`semPeriodo > 0`: borrar los `MP` futuros del activo en ese año que no coincidan con el
nuevo calendario y crear los nuevos desde `semana + semPeriodo`. **Los `MP` con fecha
pasada no se tocan.** Guardar en el activo `reprog = {base, por}`.

---

## 5. Rutas nuevas

Todas bajo `/mantenimiento`. Todas verifican `_modulo_ok(cl, "mantenimiento")`.

| Ruta | Quién | Qué |
|---|---|---|
| `GET /mantenimiento` | todos con el módulo | Agenda según alcance (§6) + `nivel` calculado + semana actual |
| `GET /mantenimiento/activos` | todos con el módulo | Catálogo de activos de su alcance |
| `GET /mantenimiento/asignables` | supervisor en adelante | Cuentas con el módulo y la sucursal: **solo id, nombre y sucursales**. No emails de terceros a operadores, no roles |
| `POST /mantenimiento/{rid}/estado` | asignado o administrador | Cambia estatus con motivo; guarda `hist` |
| `POST /mantenimiento/{rid}/asignar` | administrador | Excepción de una semana |
| `POST /mantenimiento/correctivo` | asignado, supervisor de la sucursal o administrador | Crea `MPC`; aplica reinicio si procede |
| `POST /mantenimiento/admin/activo` | administrador | Alta/edición/baja lógica de activo; propone código |
| `POST /mantenimiento/admin/tipo` | administrador | Procedimiento, puntos, material, herramienta |
| `POST /mantenimiento/admin/titular` | administrador | Titular de un activo o de un área completa |
| `POST /mantenimiento/admin/importar` | administrador | Importa el plan; **dry-run por omisión** (§7) |
| `POST /mantenimiento/admin/generar` | administrador | Arma el año siguiente como Propuesta |
| `POST /mantenimiento/admin/publicar` | administrador | Publica la propuesta |

`POST /evidencias/url-subida` se reutiliza para las fotos, con `tipo="mantenimiento"`.

---

## 6. Permisos: el nivel se deriva, no se captura

Léelo completo en `ESPECIFICACION.md` §5. Resumen operativo:

```
administra  ← cl.email ∈ CAT#MODULO/MOD#mantenimiento.administradores
consulta    ← cl.rol == "analista"
ejecuta     ← tiene el módulo y rol operador o supervisor
```

| Nivel | Ve | Ejecuta | Reprograma | Asigna / catálogos / plan |
|---|---|---|---|---|
| Técnico asignado (`operador`) | lo suyo | lo suyo | pide | — |
| `supervisor` con el módulo | su sucursal | **solo lo asignado a él** | pide | — |
| `analista` con el módulo | todo | — | — | — |
| Administrador del módulo | todo | todo | sí | sí |

Las dos celdas en negrita son **reglas del módulo, distintas al resto de la app**, y están
**pendientes de confirmación** (decisión #7 de la especificación). Implementa la
comprobación pero pregúntale al usuario antes de cerrarla.

El administrador del módulo ve todas las sucursales **solo dentro de `/mantenimiento`**.
En combustible o reparto su rol sigue mandando. No se toca `_claims` ni `_modulo_ok`.

La lista `administradores` la edita el admin de la app desde Panel → Módulos: agrega el campo
al formulario existente de módulos.

---

## 7. Importador

Script en `seed/importar_plan_mtto.py`, patrón de `seed/seed.py` y `seed/reasignar_unidad.py`
(dry-run por omisión, `--aplicar` para escribir).

- **Fuente:** `herramientas/leer_colores.py` porta tal cual la lectura. Las trampas de la
  hoja están en `herramientas/README.md`; no las redescubras.
- **Idempotente:** hace upsert por `codigo#anio#semana`. **Nunca borra** ejecuciones con
  captura. **Nunca elimina** activos con `origen=modulo`: los marca `enExcel=false`.
- **Acta:** devuelve la lista de hallazgos (periodicidad vs marcas, tono de otra sucursal,
  sin semana) y la escribe como ítem `MTTO#ACTA#{fecha}` para que la jefatura la vea. No
  corrige nada por su cuenta.
- **Estatus al importar:** todo `programada`. El texto de la celda (`OK`, `SERV`, `MP`, `NR`,
  `SI`, `NO`) se conserva en `textoExcel`; **no** se traduce a estatus sin que el usuario lo
  confirme (es historia de 2025 mezclada con 2026).
- Cifras que deben salir con el archivo actual: 233 activos, 546 `MP`, 3 sin semana, 57
  hallazgos. Si salen otras, detente y reporta.

---

## 8. Frontend

Una pestaña nueva en el React existente, clave `mantenimiento`, registrada en los dos mapas de
módulos (`frontend/index.html` ~556 y ~2227) y en los botones del panel de cuentas (~1853).

Porta de `agenda-mantenimiento-GPA.html`:

- Cálculo de semana con la fórmula del Excel (`1 ene − WEEKDAY(1 ene, 12)`; la semana 1 de
  2026 empieza el 29-dic-2025). Vive en el servidor y el cliente la recibe.
- Tres listas: **esta semana · atrasadas · próximas**, y el filtro **mías / toda la sucursal**
  con lo *sin asignar* visible para todos.
- Detalle: vence, frecuencia, área, asignada a, procedimiento (o el aviso de que el tipo no lo
  tiene), **material y herramienta con marcado de faltantes antes de iniciar**.
- Ejecución: puntos, foto antes/después con `url-subida`, descripción obligatoria,
  incidencias; cerrar / pendiente / reprogramar (pide) / no realizada, con motivo.
- Botón **Reportar una falla** siempre visible; la incidencia «requiere correctivo» lo abre
  con el activo puesto; casilla «se hizo el preventivo» que muestra qué semanas se retiran
  antes de guardar.
- Jefatura: tablero (cumplimiento sobre lo exigible, por sucursal, por área, **por
  técnico**), calendario de 52 semanas, evidencias, asignación (área completa → titular →
  excepción por semana), acta.

En lo `EXTERNO`, el botón no dice «Completar» sino **«Registrar supervisión»**, y el texto
del kit describe qué supervisar. Para GPA el trabajo de proveedor es responsabilidad de
seguimiento, no un trámite.

---

## 9. Lo que NO se toca

- `_claims`, `_modulo_ok`, `listar_registros`, `registro_keys` (se usan, no se cambian).
- Cualquier ruta o ítem de `SOL`, `CL`, `MC`, `FRM#*`.
- Los candados `rol == "admin"` de `/admin/*`.
- Cognito: ni atributos nuevos ni cambios al User Pool. Nada en `template.yaml` salvo, si
  hiciera falta, permisos IAM para el nuevo tipo (no debería: es la misma tabla y el mismo
  bucket).
- `samconfig.toml` y cualquier cosa de despliegue.
- El Excel original del plan. Solo se lee una copia.

Los **únicos** archivos compartidos que se editan, y de forma aditiva: `handler.py` (una
clave en `MODULO` y el enrutado a un módulo nuevo `mantenimiento/`), `frontend/index.html`
(pestaña + los dos mapas + botón del panel), `frontend/manual.html`.

---

## 10. Decisiones que debes preguntar, no resolver

De `ESPECIFICACION.md` §14, más lo que surja:

1. ¿El correctivo del técnico queda firme al guardar, o la jefatura lo autoriza antes de que
   mueva el calendario?
2. ¿Ejecutar exige estar asignado, y reprogramar es solo del administrador? (§6 de este
   documento)
3. `EXT` extintores: ¿la actividad es la gestión interna o el servicio del proveedor?
4. `TRA/CAR/DIA`: un activo por sucursal con varias piezas, ¿se dan de alta por pieza?
5. ¿Se traduce el texto de las celdas del Excel a estatus, o se conserva solo como historia?
6. Los `⟨confirmar⟩` de `PROCEDIMIENTOS-PROPUESTOS.md`: son de Mantenimiento, no tuyos.

---

## 11. Verificación mínima antes de entregar

- `pytest` verde con pruebas nuevas para: cálculo de semana (29-dic-2025), derivación de
  `vencida`, asignado efectivo (excepción sobre titular), reinicio de reloj por correctivo
  (3 casos: 6 meses en sem 39 retira la 46 y conserva la 8; 2 meses en sem 20 retira 33 y 46
  y agrega 28, 36, 44, 52; `Variable` no recalcula), nivel derivado por los 4 casos, y que
  un `supervisor` **no** obtiene `administra`.
- Importador en dry-run contra la copia real: **233 / 546 / 3 / 57**.
- Recorrido completo por código: entrar → esta semana → abrir → marcar faltante → iniciar →
  foto → cerrar → aparece en tablero y en evidencias. Cada paso revisado, no solo el tocado.
- Radio de impacto: `grep` de cada símbolo compartido que hayas tocado, con la lista de
  pantallas revisadas y las que no.

Reporta con la escala de 0-BIS: **compila / probado en simulación / probado contra el
servicio / sin verificar**, y qué quedó sin verificar y quién puede verificarlo.

---

## 12. Al terminar

- Actualiza `Operaciones-GPA/docs/mantenimiento/` y el manual.
- Escribe en `CLAUDE\mantenimiento-gpa\ESPECIFICACION.md` un cambio en el registro
  (`## Cambios`) con lo que quedó construido y lo que no, y sube la versión.
- Cualquier error nuevo que hayas vivido va a la sección 9 de `PROTOCOLO-desarrollos.md`.
- **No despliegues.** Deja los comandos listos solo si el usuario los pide.
