# Plan y Control de Mantenimiento — GPA

**Estado:** Fase 1 construida en la rama `mantenimiento` (sin desplegar) · **v1.4**
**Fecha:** 29 de septiembre de 2026
**Fuente del plan:** `CALENDARIO MANTENIMIENTO 2025 SCS.xlsx`, hoja `CALENDARIO 2026`
(OneDrive de `mantenimiento@gpa.com.mx`). El original **no se modificó**; todo se leyó de una copia.

---

## 1. Qué resuelve

Hoy el plan de mantenimiento vive en una matriz de Excel donde cada fila es un activo y
cada columna una de las 52 semanas. La programación está en el **color de la celda**: si
está pintada, esa actividad vence esa semana, y el tono dice de qué sucursal es.

Eso funciona para que el Jefe de Mantenimiento lea una columna y sepa qué vence. No
funciona para nada más: el técnico no puede consultarlo desde el piso, no hay forma de
registrar que se hizo, no existe la evidencia, y el cumplimiento se arma a mano.

El módulo convierte esa matriz en dos cosas:

> **Para el técnico:** qué me toca esta semana, qué traigo atrasado, qué necesito para
> hacerlo, y cómo dejo constancia de que lo hice.

> **Para la jefatura:** qué debía hacerse, qué se hizo, quién lo hizo, cuándo, con qué
> evidencia, y qué está pendiente — sin repartir tarea por tarea.

### El límite del módulo: actividad, no condición

Esta distinción define qué entra y qué no, y manda sobre el resto del documento:

| | Para qué sirve | Qué se hace |
|---|---|---|
| **Plan de mantenimiento** *(este módulo)* | dar seguimiento a las **actividades** de mantenimiento | se interviene el activo |
| **Formatos `GRL-SH-FO`** *(Seguridad e Higiene)* | confirmar el **estado o condición** del activo o la instalación | se observa y se reporta |

GPA ya tiene formatos de condición para varias familias de activos —`GRL-SH-FO-3`
ventilación, `GRL-SH-FO-5` extintores, `GRL-SH-FO-20` instalaciones eléctricas, entre
otros—. **Ninguno es un procedimiento de mantenimiento y ninguno entra a este plan.**

De ahí se sigue que una periodicidad distinta entre ambos no es una contradicción: la
revisión de condición puede ser mensual y el servicio de mantenimiento anual, porque son
instrumentos distintos. Confundirlos metería 96 inspecciones al año en un plan de 546
actividades y volvería ilegible el cumplimiento.

---

## 2. Lo que el Excel contiene, leído celda por celda

| Dato | Cifra |
|---|---:|
| Activos y servicios | 233 |
| Vencimientos en el año (celdas pintadas) | 546 |
| Activos con al menos una semana marcada | 230 |
| Activos sin ninguna semana | 3 |
| Sucursales | 8 |
| Áreas (después de normalizar las 26 secciones) | 16 |
| Tipos de activo | 23 |

**Unidad de programación: la semana, y es un plazo, no una cita.** El trabajo puede
hacerse cualquier día de esa semana o antes; vence al cerrarla. La semana 1 de 2026
empieza el **29 de diciembre de 2025**, siguiendo la misma fórmula del Excel
(`1 de enero − WEEKDAY(1 de enero, 12)`).

### Carga por sucursal

| Código | Sucursal | Vencimientos | Semana pico |
|---|---|---:|---|
| GDL | Guadalajara · Cedis | 140 | sem 8: 35 |
| CZD | Guadalajara · Calzada | 92 | sem 9: 19 |
| MTY | Monterrey | 65 | sem 43: 5 |
| CBS | Los Cabos | 65 | sem 7: 5 |
| CAN | Cancún | 62 | sem 20: 5 |
| MEX | Ciudad de México | 61 | sem 12: 6 |
| PVR | Puerto Vallarta | 57 | sem 20: 4 |
| TIS | TISA | 4 | sem 3: 1 |

**La carga está muy dispareja.** La semana 8 junta 44 vencimientos en toda la empresa y
la 46 otros 34. Son los 33 minisplits de Cedis, que vencen todos el mismo sábado dos
veces al año. En Calzada pasa igual: 19 en la semana 9 y 19 en la 47. Dos semanas cargan
la cuarta parte del año de Guadalajara. Esto no lo inventa el sistema: está así en el
plan, y es el argumento más fuerte para el repartidor de carga del §9.

### El color

Cada sucursal tiene su tono. Se validó contra la columna de sucursal de cada renglón:

| Sucursal | Tono dominante | Celdas |
|---|---|---:|
| GDL | `#92D050` verde claro | 67 |
| CZD | tema 9 al 80% → `#DCEDD5` | 73 |
| MEX | `#FFC000` ámbar | 51 |
| MTY | `#FFFF00` amarillo | 61 |
| CAN | `#0070C0` azul | 57 |
| PVR | `#7030A0` morado | 53 |
| CBS | tema 5 al 60% → `#F6C7AD` | 55 |
| TIS | `#FF0000` rojo | 4 |

Con dos advertencias que definen el comportamiento del importador:

1. Hay **19 rellenos distintos para 8 sucursales**. Guadalajara Cedis usa tres.
2. **Dos sucursales usan colores de tema**, no un RGB fijo. Si alguien cambia el tema del
   libro de Excel, esos tonos se recorren solos.

**Por eso el importador no saca la sucursal del color.** La saca de la columna, que es
autoritativa, y usa el color únicamente como verificación cruzada. Esa verificación es lo
que produce el acta del §10.

---

## 3. Códigos de control

Los códigos del Excel no sirven como llave: 66 filas comparten código con otra, 15 no
tienen ninguno, 7 traen la palabra `TRIMESTRAL` en la columna de código y 3 cisternas
dicen `1 TINACO` o `CISTERNA (2)TINACOS`.

Se recodificaron los 233 con el formato **`TIPO-SUCURSAL-##`**: tres letras, tres letras
y consecutivo. Se dicta por teléfono, se escribe sin dudar y es llave única.

Guadalajara se separa en `GDL` (Cedis) y `CZD` (Calzada). Ahí estaba la mitad de los
códigos repetidos: `TRASP-GDL-01` existía en los dos sitios.

**Los 23 tipos:** `MON` montacargas · `TRA` traspaletas · `CAR` carritos · `DIA` diablos ·
`AIR` minisplits · `TAB` eléctrico a tableros · `ELE` eléctrico interno · `FON` fontanería ·
`ILU` iluminación · `PIN` pintura · `IMP` impermeabilización · `CNL` limpieza de canaletas ·
`BAJ` bajantes · `CIS` cisternas y tinacos · `MOB` mobiliario · `VEN` extractores ·
`FUM` fumigación · `BAS` básculas · `OSM` ósmosis y dispensadores · `EXT` extintores ·
`ALA` alarma · `PLZ` plantas de luz · `JAR` jardinería.

Motivo del cambio de cada código: 139 normalización de formato, 66 código repetido, 15 sin
código, 10 el texto no era un código, 3 carácter inválido (`/`).

El catálogo completo, con código nuevo, anterior y motivo, está en
`CATALOGO-CODIGOS-mantenimiento-GPA.xlsx`.

---

## 4. Modelo de datos

Ocho entidades. Ninguna lista está escrita en el código: áreas, sucursales, tipos,
periodicidades, procedimientos, materiales y herramienta se editan desde el panel.

| Entidad | Contenido | Origen |
|---|---|---|
| `sucursal` | 8 sitios | normaliza las 24 variantes de escritura |
| `area` | 16 áreas | secciones del Excel |
| `tipo_activo` | 23 tipos, con procedimiento, puntos de revisión, material y herramienta | prefijo del código |
| `activo` | 233 equipos y servicios | columnas B–H; **llave = código nuevo** |
| `plan_actividad` | activo + periodicidad + `INTERNO`/`EXTERNO` | plantilla anual |
| `programacion` | **activo + año + semana + estatus** | el color de la celda |
| `ejecucion` | lo que capturó el técnico, con evidencia e historial | celular |
| `correctivo` | falla fuera del plan | celular |

### Periodicidad

El texto libre del Excel (12 variantes) se traduce a semanas con un catálogo editable:

| Texto | Semanas | | Texto | Semanas |
|---|---:|---|---|---:|
| `POR MES` | 4 | | `6 MESES` | 26 |
| `2 meses` / `2 MESES` | 8 | | `12 MESES` / `12MESES` / `ANUAL` | 52 |
| `3 MESES` / `3MESES` | 13 | | `Variable` / `VARIABLES` | no se calcula |
| `4 MESES` | 17 | | | |

`Variable` son 13 activos —montacargas y extintores— que dependen de horas de uso o del
proveedor. **El sistema nunca les calcula semana**; los lista aparte para que la jefatura
se la ponga a mano.

---

## 5. Quién hace qué

El Excel no dice quién ejecuta. La asignación es **por sucursal y por persona**, y una
sucursal puede tener varios técnicos o auxiliares.

Se resuelve en dos niveles, para no asignar 546 ejecuciones a mano:

**Titular del activo** — se pone una vez y vale para sus 52 semanas. Se asigna un área
completa de un golpe («todo Minisplits a Marco»), y después se afina activo por activo.

**Excepción de una semana** — vacaciones, carga, ausencia. Cambia solo esa semana y no
toca al titular.

Manda la excepción; si no hay, el titular. **Si no hay ninguno de los dos, la actividad la
ve todo el técnico de esa sucursal**, marcada como *sin asignar*, para que nada se quede
sin hacer por no estar repartido. El contador de sin asignar está siempre a la vista.

El técnico ve por omisión solo lo suyo, y puede cambiar a toda la sucursal.

Dar de baja a una persona no deja actividades huérfanas en silencio: le retira titulares y
excepciones, y esas actividades vuelven a *sin asignar*.

### El módulo no administra usuarios

**El técnico es un usuario de Operaciones-GPA**, con su cuenta, su rol y su acceso a este
módulo. Aquí **no se da de alta a nadie: se selecciona**. La lista de quién puede ejecutar
en una sucursal son las cuentas que cumplen las tres condiciones:

1. Tienen acceso al módulo — `custom:modulos` contiene la clave, o está vacío (todos).
2. Tienen esa sucursal — `custom:sucursales` la contiene, o está vacío (todas).
3. Su rol les permite capturar.

Las altas, bajas y permisos se hacen en el Panel de cuentas que ya existe. Lo único que
este módulo guarda es **la relación activo → usuario**, y la excepción por semana.

Si al abrir la asignación no aparece nadie, el problema no se resuelve aquí: hay que darle
el módulo y la sucursal a esas cuentas en el panel.

**Hueco detectado en la app actual.** La única ruta que lista cuentas es
`GET /admin/cuentas`, y está restringida a rol `admin` (`handler.py:210-214`). La jefatura
que asigna suele ser `supervisor`, no `admin`. El módulo necesita su propia ruta de solo
lectura —`GET /mantenimiento/asignables`— que devuelva únicamente identificador, nombre y
sucursales de las cuentas con acceso al módulo, legible por supervisor en adelante. Es
aditiva: no toca el candado de administración.

### Quién administra el módulo sin ser admin de la app

El Jefe de Mantenimiento administra **este módulo** —asigna, edita catálogos, importa el
plan, arma el año siguiente, ve todas las sucursales— pero **no** es admin de
Operaciones-GPA: no toca cuentas, vehículos ni combustible.

Hoy la app tiene un solo rol global por cuenta (`custom:rol`) y sus candados de
administración comparan `rol == "admin"` en seis lugares. Crear un rol nuevo obligaría a
tocar cada uno. En su lugar:

**La lista de administradores vive en la configuración del propio módulo.** El registro
`CAT#MODULO / MOD#mantenimiento` —el mismo tipo que ya usan los módulos dinámicos— lleva
un campo `administradores` con los correos de quienes lo administran. El admin de la app lo
fija una vez desde **Panel → Módulos**, que ya existe; es un campo más en ese formulario.

Dentro del módulo, el nivel de cada persona **se deriva, no se captura**:

| Nivel | Cómo se obtiene | Qué puede hacer |
|---|---|---|
| **Administra** | su correo está en `administradores` | todo lo del módulo, en todas las sucursales |
| **Ejecuta** | tiene el módulo en `custom:modulos` y rol `operador` o `supervisor` | ve y captura lo suyo o lo de su sucursal, según su rol de siempre |
| **Consulta** | tiene el módulo y rol `analista` | ve todo, no captura — como ya hace en los demás módulos |

El servidor calcula el nivel en cada llamada y lo devuelve en `GET /mantenimiento`; la
pantalla lo pinta, no lo decide.

**Un `supervisor` no se vuelve administrador del módulo.** Queda en *Ejecuta* con el alcance
de su sucursal. Pero ese alcance, tal como la app lo aplica hoy, le permitiría capturar
sobre cualquier actividad de mantenimiento de su sucursal aunque no esté asignada a él.
Para acotarlo se propone una regla propia del módulo, pendiente de decisión (§14):

| Quién | Ve | Ejecuta | Reprograma | Asigna, catálogos, plan |
|---|---|---|---|---|
| Técnico asignado (`operador`) | lo suyo | lo suyo | pide | — |
| `supervisor` con el módulo | su sucursal | solo lo asignado a él | pide | — |
| `analista` con el módulo | todo | — | — | — |
| Administrador del módulo | todo | todo | sí | sí |

La diferencia con el resto de la app está en dos celdas: **ejecutar** exige estar asignado,
y **reprogramar** —que mueve un plazo— es del administrador; el técnico lo solicita con
motivo y el administrador lo aplica. Es una comprobación dentro de las rutas nuevas del
módulo; no toca las reglas de combustible, reparto ni montacargas. Un administrador del módulo puede ver todas las
sucursales **solo dentro de mantenimiento**: en combustible o reparto sigue siendo lo que
su rol diga.

Lo que esto **no** toca: `_claims`, `_modulo_ok`, los candados de `/admin/*`, Cognito ni la
plantilla del User Pool. Es un campo en un registro que ya existe y una comprobación dentro
de las rutas nuevas del módulo.

**Arranque:** el admin de la app da al Jefe el módulo en su cuenta y lo pone en
`administradores`. A partir de ahí el Jefe opera solo. Agregar o quitar administradores del
módulo sigue siendo tarea del admin de la app, para que la frontera de confianza no se
mueva desde adentro.

---

## 6. Estatus

Siete, como pide el módulo:

| Estatus | Quién lo pone |
|---|---|
| Programada | el sistema, al importar |
| En proceso | el técnico, al iniciar |
| Completada | el técnico, al cerrar |
| Pendiente | el técnico, **con motivo obligatorio** |
| Reprogramada | el técnico o la jefatura, **con motivo obligatorio** |
| No realizada | el técnico o la jefatura, **con motivo obligatorio** |
| **Vencida** | **nadie: la calcula el sistema** |

`Vencida` es la semana programada ya cerrada sin ejecución. No se teclea y no se puede
esconder. Esa es la diferencia con el Excel, donde no aparecer es indistinguible de no
haberse hecho.

Cada cambio guarda quién, cuándo y desde dónde, y no se borra.

El vocabulario que hoy usan en las celdas se traduce al importar:
`OK` y `SERV` → Completada · `MP` → Completada (preventivo) · `NR` → No realizada ·
`SI` → Completada · `NO` → No realizada.

---

## 7. Lo que ve y captura el técnico

**Abrir → ver lo de esta semana → abrir una → confirmar que tiene con qué → ejecutar →
foto → comentario → cerrar.** Sin formularios largos y sin computadora.

Tres listas: **esta semana**, **atrasadas**, **próximas**.

Al abrir una actividad ve el equipo, su área, la semana en que vence, la frecuencia, quién
la tiene asignada y el procedimiento.

**Antes de empezar** ve el material y la herramienta que necesita, y marca lo que le
falte. Si falta algo, la actividad **no se pierde**: sigue programada y el faltante le
llega a la jefatura. Esto es lo que evita el viaje en balde, y es el gancho de la Fase 2.

**Al ejecutar** marca los puntos revisados, toma foto de antes y después, describe lo
hecho y señala incidencias. Para cerrar, la descripción es obligatoria.

**El trabajo externo no sale de la agenda.** Las filas `EXTERNO` llegan como *validar
proveedor*: el técnico confirma que se hizo, sube la evidencia y la nota del servicio. Sin
esa validación el activo cuenta como no atendido, aunque el proveedor haya cobrado.

---

## 8. Correctivos

Lo que se descompone fuera del plan. Dos entradas: el botón de reportar falla, siempre
visible, y la incidencia *«requiere correctivo»* al cerrar un preventivo, que levanta el
correctivo con el equipo ya puesto.

Se captura qué falló, qué se hizo, refacciones usadas, si lo hizo GPA o un proveedor, y
evidencia.

**La regla que decide el calendario:** el reloj se reinicia **solo si el correctivo
incluyó el preventivo**. Si nada más se cambió una pieza, el equipo sigue debiendo su
servicio y el calendario no se toca. Hay una casilla explícita para eso.

Cuando sí reinicia, las semanas que faltaban se recalculan desde la semana del correctivo
más su periodicidad. **Lo ya vencido no se toca**: es historia y no se puede des-incumplir.
Antes de guardar, el sistema muestra qué semanas se retiran y cuáles quedan.

> Ejemplo: minisplit de 6 meses con vencimientos en las semanas 8 y 46. Falla y se repara
> con preventivo en la semana 39 → se retira la 46, la 8 se conserva como historia, y la
> siguiente cae en 2027. El activo queda marcado con *«calendario reiniciado en la semana
> 39»* y su historial de fallas.

Efecto secundario deseable: el recálculo corrige de paso las filas mal programadas del
Excel. El montacargas `MON-GDL-01` es de 2 meses y el archivo solo le puso 4 vencimientos
en vez de 6; tras un correctivo en la semana 20 el recálculo le deja 28, 36, 44 y 52.

**Decisión abierta:** hoy el correctivo del técnico queda firme de inmediato. Si la
jefatura debe autorizarlo antes de que mueva el calendario, se agrega un estatus
intermedio. Ver §14.

---

## 9. Cómo se arma el año siguiente

No se recapturan 233 filas. Corre cuando la jefatura lo pide.

1. **Periodicidad a semanas**, con el catálogo editable del §4.
2. **Punto de partida de cada activo:** su última semana con estatus *Completada*. Si
   nunca se ejecutó, se conserva la del año en curso; si tampoco tenía, queda *sin
   programar*. No se inventa.
3. **Se siembra el año:** se suma la periodicidad tantas veces como quepa en las 52
   semanas; cada resultado es una fecha límite. Lo que se pasa de la 52 arrastra al año
   siguiente.
4. **`Variable` no se calcula.** Los 13 activos se listan aparte.
5. **Se reparte la carga.** Con el plan actual la semana 8 lleva 44 y la 46 lleva 34. El
   motor lo marca y propone corrimientos de ±1 o ±2 semanas. La jefatura acepta o mueve.
6. **Nace como Propuesta.** Ningún técnico ve el año entrante hasta que la jefatura lo
   publica. Antes se puede comparar contra el año actual y exportar a Excel.

---

## 10. Importador

Se ejecuta sobre una copia. **Nunca escribe en el archivo original.**

Lee las filas de sección como área, el color de las columnas I–BI como semanas límite, y
cruza el tono contra la columna de sucursal. Es re-ejecutable: actualiza por
`código + año + semana` sin duplicar y **sin borrar las ejecuciones ya capturadas**.

Los activos dados de alta dentro del módulo **no se eliminan** al reimportar: se marcan
como *«no está en el Excel vigente»* para que la jefatura decida.

Entrega un **acta de importación** con lo que no pudo resolver solo. Sobre el archivo
actual son **57 hallazgos**:

| Hallazgo | Casos |
|---|---:|
| Filas con menos marcas de las que pide su periodicidad | 38 |
| Celdas pintadas con el tono de otra sucursal | 16 |
| Actividades sin ninguna semana | 3 |
| **Total** | **57** |

Las 16 celdas con tono ajeno no son azar: **todas están en el bloque de montacargas**, y
hay un corrimiento de renglón — la fila de México lleva el verde de Cedis, la de Vallarta
el ámbar de México, la de Monterrey el morado de Vallarta y la de Cancún el amarillo de
Monterrey, cuatro celdas cada una. El acta lo señala; **el importador no lo corrige solo**.

Además reporta dos señales que no son hallazgos de datos sino avisos de captura:

- **30 celdas con texto pero sin color** — se registró algo en una semana que no estaba
  programada. Puede ser un trabajo extra legítimo o un tecleo en la celda equivocada.
- **La semana 52 aparece dos veces en el encabezado**, que tiene 53 columnas para 52
  semanas. El importador toma la primera y avisa.

Un cruce más amplio del tono —comparando contra el tono dominante global en vez del de la
sucursal— marca 27 celdas en lugar de 16. Las 11 de diferencia son ambiguas porque
Guadalajara Cedis usa tres tonos distintos; el acta se queda con las 16 inequívocas para
no generar ruido.

---

## 11. Supervisión

**Tablero:** cumplimiento sobre lo exigible a la fecha, vencimientos del año,
completadas, vencidas, pendientes, no realizadas y correctivos. Cumplimiento por
sucursal, **por área y por técnico**.

**Calendario:** las 52 semanas con su carga, coloreada por estatus, con la semana en curso
marcada.

**Evidencias:** todo lo capturado con su foto, quién, cuándo, qué se hizo, incidencias y
faltantes. Los correctivos se distinguen y muestran la falla, las refacciones y las
semanas que retiraron del calendario.

La jefatura administra excepciones y resultados. No reparte tarea por tarea.

---

## 12. El hueco de los procedimientos

El plan dice **qué** activo y **cuándo**, pero no qué hacerle. Los procedimientos salen de
`PLAN DE MANTENIMIENTO - SAULO.xlsx`, que cubre **10 de los 23 tipos**: minisplits,
eléctrico a tableros, eléctrico interno, fontanería, iluminación, pintura, mobiliario,
impermeabilización, canaletas y bajantes.

**Eso deja 274 de las 546 ejecuciones del año sin procedimiento escrito** — la mitad
exacta. Sin describir: montacargas, fumigación, ósmosis, traspaletas, carritos, diablos,
jardinería, cisternas, alarmas, extractores, básculas, plantas de luz y extintores.

El módulo **lo dice en pantalla en lugar de inventarlo**, y ofrece que la jefatura lo
escriba **una vez por tipo de activo** — son 13 textos, no 274. Al escribirlo, todos los
equipos de ese tipo lo heredan.

Material y herramienta no vienen de ningún archivo: la propuesta inicial que trae el
módulo es un punto de partida para que la jefatura la corrija.

---

## 13. Fases

### Fase 0 — App independiente *(donde estamos)*

`agenda-mantenimiento-GPA.html`, un solo archivo que se abre con doble clic. Sin internet,
sin cuenta, sin servidor. Trae las 233 actividades y los 546 vencimientos reales.

Todos los datos pasan por un único objeto `almacen`, con cuatro funciones. **Esa es la
regla dura:** para conectarlo a Operaciones-GPA se cambia solo el cuerpo de esas funciones
por llamadas a la API, y no se toca una línea más del archivo.

Sirve para cerrar las decisiones y para que el equipo lo use de verdad antes de escribir
nada del backend. Lo que se captura se guarda en el navegador y se exporta como respaldo
`.json`, que se puede pasar a otra máquina o entregar para revisión.

**Limitación honesta:** las capturas viven en cada equipo. Para consolidar hay que juntar
los respaldos a mano. Es aceptable para probar; no lo es para operar.

#### Cómo se corre la ronda de revisión

El comentario se captura **dentro de la app**, no en Teams ni por chat. Nace pegado a la
pantalla o a la actividad de la que habla, viaja en el mismo respaldo `.json` que ya se
descarga, y obliga a ponerle estado. Cinco reglas para que la lista se cierre:

1. El comentario va pegado a lo que critica. «La báscula no debería pedir foto» vale;
   «está confuso» no se puede atender.
2. Cada uno nace **abierto** y solo sale como **atendido** o **descartado con razón**.
   Descartar también es cerrar; lo que no se vale es dejarlo sin estado.
3. El contador de abiertos está siempre a la vista. Si sube y no baja, se nota.
4. La ronda tiene fecha de cierre. Lo que llegue después va a la siguiente.
5. Un solo dueño de la lista decide qué se atiende.

Cada quien entrega su respaldo al cerrar la ronda y se consolidan en uno solo.

### Fase 1 — Módulo en Operaciones-GPA

Lo que ya está desplegado y se reusa sin tocarlo:

| Pieza | Dónde |
|---|---|
| Login con rol y **varias sucursales** por persona | `handler.py`, `custom:sucursales` |
| Permiso por módulo, con la clave `mtto` ya creada | `_modulo_ok()` |
| Subida de fotos a S3 con URL prefirmada | `POST /evidencias/url-subida` |
| Tabla única con índices por tipo, **por sucursal** y por cuenta | `template.yaml` |
| Alta de cuentas con selección múltiple de sucursales | Panel Admin |

Lo que hay que construir: el catálogo de activos (`CAT#ACTIVO`), el tipo de registro de
programación —que encaja en el índice por sucursal ya desplegado, sin índice nuevo—, el
motor del §9, el importador del §10 y la ruta de solo lectura `GET /mantenimiento/asignables`
del §5.

Todo aditivo: rutas nuevas y prefijo de llave nuevo. No toca combustible, reparto ni
montacargas. Los únicos dos puntos compartidos son una clave en el mapa de módulos y una
pestaña en la navegación.

**El motor de formularios dinámicos no sirve para esto**: captura formularios, y
mantenimiento es una agenda que debe conocer los 546 vencimientos antes de que alguien
abra nada.

### Fase 2 — Materiales y refacciones

La relación activo → material y herramienta ya está en el modelo desde la Fase 0. Falta el
requerimiento proyectado por periodo:

| Actividad | Material | Cantidad | Semana requerida | Existencia | Faltante |
|---|---|---:|---|---|---:|

La existencia se valida **a mano** al inicio. Los faltantes que el técnico marca en la
pantalla de ejecución ya alimentan esta tabla.

### Fase 3 — Inventario y compras

Integración con inventario por API. No condiciona nada de las fases anteriores.

---

## 14. Decisiones que faltan

| # | Decisión | Quién |
|---|---|---|
| 1 | ¿El correctivo del técnico queda firme, o la jefatura lo autoriza antes de que mueva el calendario? | Jefatura |
| 2 | Los 13 procedimientos que faltan (§12) | Jefatura de Mantenimiento |
| 3 | Titular de cada activo, o al menos por área y sucursal | Jefatura de Mantenimiento |
| 4 | Los 57 hallazgos del acta (§10): cuáles se corrigen en el Excel y cuáles se aceptan | Jefatura de Mantenimiento |
| 5 | ¿Se corrige la carga dispareja de las semanas 8 y 46, o se deja como está? | Jefatura |
| 6 | Las 3 filas de extintores sin semana y las 13 de periodicidad `Variable` | Jefatura de Mantenimiento |
| 7 | ¿Ejecutar exige estar asignado, y reprogramar es solo del administrador del módulo? Hoy un `supervisor` con el módulo podría cerrar o mover cualquier actividad de su sucursal (§5) | Gerencia |

---

## 15. Lo que este módulo no hace

- **No genera el plan.** Lo importa. Las actividades, frecuencias, áreas y fechas son las
  que GPA ya decidió.
- **No corrige el Excel.** Reporta lo que encuentra y la jefatura decide.
- **No incluye el parque vehicular.** Las 84 unidades se programan por kilometraje, no por
  semana, y viven en otro archivo. Se decidió dejarlas fuera del alcance.
- **No calcula costos** ni se conecta a SAP.
- **No sustituye el criterio del técnico.** Le dice qué equipo y cuándo, y le da el
  procedimiento cuando existe.
- **No sustituye los formatos de condición.** Las revisiones `GRL-SH-FO` de Seguridad e
  Higiene siguen su propio camino y su propia periodicidad. Este módulo lleva las
  actividades de mantenimiento, no las inspecciones de estado.

---

## 16. Estado de verificación

| Afirmación | Cómo se comprobó |
|---|---|
| 233 activos, 546 vencimientos, semanas por activo | lectura del `.xlsx` con openpyxl, celda por celda |
| Semana 1 = 29-dic-2025 | fórmula del Excel reproducida y contrastada |
| Tono por sucursal | cruce del relleno contra la columna de sucursal de cada renglón |
| 272 con procedimiento / 274 sin | cruce de los 23 tipos contra el archivo de SAULO |
| 57 hallazgos del acta | salida del importador sobre el archivo real |
| Reinicio del reloj por correctivo | ejecución de las funciones reales con 3 casos y regresión |
| Asignación titular/excepción, respaldo y baja | ejecución de las funciones reales, 13 puntos |
| Piezas reusables de Operaciones-GPA | lectura de `handler.py`, `auth_cognito.py`, `template.yaml`, `frontend/index.html` |

**Sin verificar:** la interfaz en celular real, la cámara y el redimensionado de fotos.
Requieren que alguien la abra en su teléfono.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `agenda-mantenimiento-GPA.html` | la app independiente de la Fase 0 |
| `CATALOGO-CODIGOS-mantenimiento-GPA.xlsx` | los 233 códigos nuevos, el anterior y el motivo |
| `PLAN-2026-semanas-limite.xlsx` | semanas por actividad, las 546 ejecuciones, tonos y acta |
| `ESPECIFICACION.md` | este documento |
| `PROCEDIMIENTOS-PROPUESTOS.md` | los 13 procedimientos que faltan, para que Mantenimiento los corrija |
| `herramientas/` | el lector del plan (colores incluidos) y los 3 generadores; ver su `README.md` |
| `..\INSTRUCCIONES-modulo-mantenimiento-operaciones.md` | el traspaso a la sesión que construye el módulo en Operaciones-GPA |

---

## Cambios

**v1.4 — 29 de septiembre de 2026 — Fase 1 construida (rama `mantenimiento` de DevGPA/Eco-Admin, sin desplegar)**
- **Decisiones del usuario** a las preguntas de §14 (registradas en `Operaciones-GPA/docs/mantenimiento/DECISIONES.md`):
  #1 el correctivo queda firme al guardar; #7 solo hay un supervisor nacional (el Jefe de
  Mantenimiento, administrador del módulo), el técnico ejecuta lo asignado y lo sin asignar y
  **pide** reprogramar; `EXT` es la **revisión** del extintor por GPA (no la recarga; el plan no
  se mezcla con los checklists de Seguridad); traspaletas, carritos y diablos: **una pieza = un
  activo**, con la cantidad por sucursal tomada del **Tablero de Seguimiento** de la app; los
  textos de las celdas **no** se traducen a estatus; los 13 procedimientos se cargan como
  propuesta editable. La pestaña se llama **«Plan Mtto»** (clave `mantenimiento`) porque `mtto`
  ya es la pestaña de checklists en la app — corrige lo que decía §13 («la clave `mtto` ya
  creada»: existe, pero significa otra cosa).
- **Construido:** `mantenimiento/logica.py` (semanas con la fórmula del Excel, estatus derivado,
  asignación titular/excepción, nivel derivado, reinicio del reloj, año siguiente), `datos.py`
  (prefijos `CAT#ACTIVO`, `CAT#TIPOACTIVO`, `CAT#PERIODICIDAD`, `CAT#AREA`, `MP`, `MPC`,
  `MTTO#ACTA`), `rutas.py` (las 11 rutas de §5 del traspaso salvo `admin/importar`), los 11
  eventos en `template.yaml`, la pestaña Plan Mtto completa en `frontend/index.html` (agenda,
  detalle con kit y faltantes, correctivo con vista previa, tablero con calendario y barras por
  sucursal/área/técnico, evidencias, acta, asignación, catálogos, año siguiente), el editor de
  administradores en Admin → Módulos, el manual v3.1, `seed/mtto_tipos.py` (23 tipos) y
  `seed/importar_plan_mtto.py` (dry-run por omisión; reproduce 233 / 546 / 3 / 57 y expande a
  291 activos / 720 vencimientos con las metas de respaldo).
- **No construido:** la ruta `POST /mantenimiento/admin/importar` (leer los colores del Excel
  exige `openpyxl`, que no está en la Lambda; el importador es el script de CloudShell); el
  repartidor automático de carga (§9.5) solo **señala** las semanas pico y sus alternativas, no
  mueve nada; la sucursal `Tisa` no existe en la app (el acta lo avisa).
- **Hallazgo de auditoría previa:** el código pendiente de desplegar rechazaba las evidencias de
  EPP y del examen médico (error #35 del protocolo); se corrigió en la rama `operaciones-gpa`
  (`5f43a3b`) antes de construir sobre ella.
- **Verificación:** 237 pruebas de servidor (33 de lógica + 30 de rutas de punta a punta con
  DynamoDB simulada, incluidas las de §11) y la prueba de pantalla `tests/frontend/test_plan_mtto.js`
  sobre los componentes reales. **Sin verificar:** contra el servicio real (no hay despliegue),
  en celular, y las metas reales del Tablero (el dry-run local usó el respaldo).

**v1.3 — 25 de septiembre de 2026**
- Se rescatan los scripts del importador a `herramientas/` (antes vivían en una carpeta
  temporal de la sesión) y se dejan autocontenidos; corridos de nuevo reproducen 233/546/57.
- Se escribe `INSTRUCCIONES-modulo-mantenimiento-operaciones.md` para la sesión que integra
  el módulo en la app; construye en rama `mantenimiento`, **sin desplegar**.
- Se aclara que `supervisor` no se vuelve administrador del módulo, y se propone acotar su
  alcance: ejecutar solo lo asignado y reprogramar solo por administradores (decisión #7).
- **Quién administra el módulo** (§5): el Jefe de Mantenimiento administra el módulo sin ser
  admin de la app, mediante el campo `administradores` en `CAT#MODULO / MOD#mantenimiento`,
  fijado desde Panel → Módulos. El nivel se deriva en el servidor; no hay rol nuevo ni cambio
  en Cognito ni en los candados existentes.

**v1.2 — 25 de septiembre de 2026**
- **El módulo no administra usuarios** (§5). El técnico es una cuenta de Operaciones-GPA
  con acceso al módulo y a la sucursal; aquí solo se selecciona. Corrige otro supuesto mío:
  yo había construido un padrón propio de técnicos dentro del módulo, con altas y bajas.
- Se detecta que `GET /admin/cuentas` es solo para rol `admin`, y la jefatura que asigna
  suele ser `supervisor`: hace falta la ruta `GET /mantenimiento/asignables`.

**v1.1 — 25 de septiembre de 2026**
- Se incorpora el límite del módulo (§1): el plan lleva **actividades** de mantenimiento;
  los formatos `GRL-SH-FO` confirman **condición** y no pertenecen aquí. Corrige un supuesto
  mío que era falso: yo había tratado los puntos de la FO-3 y la FO-5 como si fueran el
  procedimiento de mantenimiento de extractores y extintores, y había levantado como
  «contradicción» que su periodicidad no coincidiera con la del plan. No lo es: son dos
  instrumentos distintos.
- Se agrega el límite correspondiente al §15.
- Se corrige la tabla del acta (§10): son 57 filas —38 + 16 + 3—; las 30 celdas con texto
  sin color y la semana 52 duplicada son avisos de captura, no hallazgos de datos.
- Se documenta la ronda de revisión de la Fase 0 y sus cinco reglas de cierre.

**v1.0 — 24 de septiembre de 2026**
- Primera versión completa, con las 32 cifras auditadas contra el plan y el catálogo.
