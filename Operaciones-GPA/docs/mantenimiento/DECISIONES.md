# Decisiones del usuario — Módulo de Mantenimiento

**Fecha:** 29 de septiembre de 2026. Preguntas de la sección 10 del traspaso
(`INSTRUCCIONES.md`), respondidas por Gerencia Administrativa antes de escribir código.
Lo que dice «respuesta» es literal; lo que dice «cómo se aplica» es la lectura que
se construyó. Si la lectura está mal, se corrige aquí y en el código.

| # | Pregunta | Respuesta | Cómo se aplica |
|---|---|---|---|
| 1 | ¿El correctivo del técnico queda firme o la jefatura lo autoriza antes de mover el calendario? | **Queda firme al guardar.** | Al guardar un correctivo con «se hizo el preventivo», el reloj del activo se reinicia en ese momento: se retiran las semanas futuras sin captura que no coinciden y se crean las nuevas. No hay estatus «Por autorizar». La jefatura lo ve en evidencias y puede reprogramar. |
| 2 | ¿Ejecutar exige estar asignado y reprogramar es solo del administrador? | **«En esta parte el supervisor solo es 1 nacional, el jefe de mantenimiento; no aplica el supervisor de sucursal.»** | El Jefe de Mantenimiento es el **administrador del módulo** (su correo va en `administradores` del módulo `mantenimiento`, Panel → Módulos). Los técnicos (rol operador) ejecutan **lo asignado a ellos y lo que está sin asignar de su sucursal**. **Reprogramar lo pide el técnico con motivo y lo aplica el administrador.** Una cuenta con rol supervisor y el módulo, si existiera, se comporta como técnico. Un administrador de la app (rol admin) también administra el módulo: es quien puede editar la lista de administradores, así que negarle el módulo no protegería nada. |
| 3 | EXT extintores: ¿la actividad es la gestión interna o el servicio del proveedor? | **«Solo es la revisión del extintor, no es la recarga. Habíamos aclarado que no mezclaras los checklists con el plan, son cosas distintas.»** | La actividad del plan para `EXT` es la **revisión del extintor por personal de GPA** (INTERNO, como está en el Excel). El procedimiento propuesto de «gestión de la recarga» se **reemplaza** por uno de revisión, marcado como propuesta editable. El plan **no se liga** a los formularios de condición del módulo Seguridad (GRL-SH-FO-5): son instrumentos distintos y el módulo no los consulta ni los cuenta. |
| 4 | Traspaletas, carritos y diablos: una fila por sucursal con varias piezas, ¿cómo se dan de alta? | **«Tiene que realizar una actividad por activo.»** y, al preguntar cómo separarlos: **«Tómalos del tablero de operaciones, ahí te dice cuántas son por sucursal.»** | **Cada pieza es un activo** con su código consecutivo (`TRA-GDL-01`, `TRA-GDL-02`…) y sus propias semanas (las del renglón del Excel). La **cantidad por sucursal se toma del Tablero de Seguimiento de la app** (metas de los formularios «transpaletas», «carritos» y «diablitos», que el admin edita en Admin → Metas seguim.), **no** de la columna «Serie» del Excel. El importador lee esas metas de la tabla al correr; si una plantilla no tiene meta para una sucursal, usa la cantidad que venía en el Excel y lo anota en el acta. Las cifras del importador dejan de ser 233 / 546: se reportan las cifras leídas del Excel (233 / 546, invariantes del lector) y aparte las del plan expandido. |
| 5 | ¿Se traducen los textos de las celdas (OK, SERV, MP, NR, SI, NO) a estatus? | **«Olvídalo.»** | **No se traducen.** Todo se importa como `programada`. El texto de la celda se conserva en `textoExcel` solo como rastro de importación; **no se muestra** en la agenda ni se usa para nada. |
| 6 | Los 12 datos técnicos ⟨confirmar⟩ de los procedimientos propuestos | **Cargarlos como propuesta editable.** | Los 13 tipos sin procedimiento nacen con el texto de `PROCEDIMIENTOS-PROPUESTOS.md`, la marca `esPropuesta: true` (la app pinta «Propuesta: por validar con Mantenimiento») y los ⟨confirmar⟩ visibles. El administrador los corrige desde el módulo. |
| 7 | (Surgió al leer el código) La pestaña «Mtto» ya existe y agrupa los checklists de reparto y montacargas. ¿Cómo se llama la del plan? | **«Plan Mtto».** | Pestaña nueva `Plan Mtto`, clave interna del módulo **`mantenimiento`**. La pestaña «Mtto» de checklists no cambia. La especificación decía que la clave `mtto` «ya existía» en `_modulo_ok`: existe, pero significa checklists, no el plan; por eso el módulo no la usa. |

## Supuestos que NO se preguntaron (revisar si algo no cuadra)

- **Equivalencia de sucursales** entre el plan y la app: `GDL` → `Cedis`, `CZD` → `Guadalajara`,
  `MEX` → `Ciudad de Mexico`, `MTY` → `Monterrey`, `CAN` → `Cancun`, `PVR` → `Vallarta`,
  `CBS` → `Cabos`, `TIS` → `Tisa`. **`Tisa` no existe hoy en el catálogo de sucursales de la
  app**; el importador la anota en el acta. Sus 4 vencimientos los ve el administrador (ve todas)
  y un técnico solo si el admin de la app da de alta la sucursal y se la asigna.
- **Semana actual** con la fórmula del Excel: la semana 1 de 2026 empieza el 29-dic-2025 y cada
  semana vence el sábado. El 29-sep-2026 es la semana 40.
- **Vencida** se deriva solo de `programada` con fecha límite pasada. Una actividad que el técnico
  dejó `pendiente` o `en proceso` conserva ese estatus (igual que la agenda de referencia).
- Cuando un técnico **toma** una actividad sin asignar (la inicia o la completa), queda asignada a
  él para esa semana y aparece en «mías»; se anota en el historial como «tomada».
- El **importador es un script de CloudShell** (`seed/importar_plan_mtto.py`), no una ruta de la
  API: leer los colores del Excel exige `openpyxl`, que no está en la Lambda. Las rutas
  `admin/generar` y `admin/publicar` (año siguiente) sí viven en la API.
- Las rutas nuevas **sí se declaran en `template.yaml`** (eventos del HTTP API). La sección 9 del
  traspaso decía «nada en template.yaml», pero sin el evento API Gateway responde 404: es
  aditivo y obligatorio.
