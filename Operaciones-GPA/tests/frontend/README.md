# Pruebas de pantalla (frontend)

Montan los componentes **reales** de `frontend/index.html` —el mismo código que
corre en el celular, compilado con el mismo Babel— y simulan lo que hace el
usuario: capturar, salir, volver y enviar. No tocan AWS ni la red.

Existen porque un formulario puede *compilar* y aun así perder lo capturado: eso
solo se ve ejecutándolo.

## Cómo correrlas

Una sola vez, para bajar React (no se guardan en el repo):

    cd tests/frontend
    npm install react@18 react-test-renderer@18 @babel/standalone

Después:

    node test_borrador_checklist.js
    node test_borrador_mc_formularios.js

Cada línea sale con `✓` o con `✗ FALLA`; si algo falla, el proceso termina en
error (sirve para CI).

## Qué cubren

`test_borrador_checklist.js` — checklist de reparto (CLForm):
- «← Atrás» dentro del asistente conserva km y respuestas.
- Salir del módulo y volver recupera km, respuestas y el paso donde se quedó.
- Aparece el aviso «Retomaste un checklist sin enviar» y su botón Descartar.
- Descartar deja el formulario en blanco.
- El borrador del semanal y el del mensual no se mezclan.

`test_borrador_mc_formularios.js` — montacargas (MCForm) y formularios
dinámicos (FormDinamico):
- Salir y volver recupera horas y respuestas del chequeo.
- Recupera lo capturado en un formulario dinámico.
- Al ENVIAR, el borrador se borra y no reaparece (cubre la carrera del guardado
  con retraso, que sí llegó a resucitarlo).
- La vista previa de Admin no deja borradores.

`test_foto_km_solicitud.js` — foto del kilometraje en Combustible:
- La solicitud NO deja avanzar sin la foto del odómetro, y lo explica en pantalla.
- Las fotos de apoyo (tanque) siguen siendo opcionales.
- Lo que se envía lleva la foto del km como principal y al frente de la
  evidencia, sin duplicarla.
- Un borrador anterior a este cambio se migra solo y no traba al operador.
- El reporte de carga sigue exigiendo la foto de ANTES y la de FINALIZAR.

`test_escala_na.js` — opción N/A en la bitácora de extintores:
- «Ruedas en buen estado (si aplica)» tiene Sí / No / N/A, con N/A en verde.
- Al marcar N/A no se pide foto ni descripción del daño y el extintor queda
  «Óptimo / operativo»; al marcar «No» sí pide evidencia y queda en rojo.
- Los registros anteriores no cambian de significado ([0] sigue siendo «Sí» y
  [1] «No»), porque la opción nueva se agregó AL FINAL.

`test_checklist_bloquea_solicitud.js` — candado del checklist en Combustible:
- Con el checklist de reparto vencido, la solicitud no deja avanzar y el aviso
  dice cuál falta, cuándo vencía y dónde capturarlo.
- Al día o todavía en plazo, no bloquea.
- Una unidad sin checklist de reparto (montacargas) nunca se bloquea.
- Tampoco pasa al enviar desde un borrador viejo que ya estaba en el último paso.

`test_boton_anclar.js` — botón para anclar la app en el teléfono:
- No aparece si ya está anclada, ni en un navegador que no puede instalarla.
- En Android aparece cuando el navegador ofrece la instalación y la dispara de
  verdad; si el usuario la cierra, el botón se queda mostrando los pasos
  (Chrome no vuelve a ofrecerla hasta recargar).
- En iPhone aparece siempre y abre las instrucciones de Safari (Compartir →
  Agregar a inicio), sin mezclarlas con las de Android.
- Un iPad con iPadOS se detecta bien; una Mac de verdad no.
- Está también en la pantalla de inicio de sesión, y se quita solo si la app se
  instala desde el menú del navegador.

`test_recorridos.js` — formulario «Recorridos en instalaciones»:
- 36 puntos en el orden del Excel, con su criterio de revisión visible.
- No deja avanzar con puntos sin responder.
- Se llena de principio a fin y SE ENVÍA (incluida la firma, sin la cual el
  botón está deshabilitado — es lo que hacía parecer que «no guardaba»).
- «No cumple» pide evidencia y deja la instalación fuera de servicio; «N/A» no.

`test_insignias_nav.js` — contador de pendientes en el menú:
- Los responsables de cumplimiento ven el número sobre cada pestaña; quien no lo
  es (o un admin que no está dado de alta como responsable) no ve nada.
- Admin y Seguimiento nunca traen número.
- Al capturar los checklists, el número baja y la insignia deja de estar roja.
Monta la App COMPLETA, sembrando lo que devuelve la api con `mundo`.

`test_epp.js` — módulo EPP (entradas por factura, entregas por vale):
- La entrada exige número y foto de factura y no pregunta talla.
- La entrega pide número de empleado ANTES del nombre, muestra la carta de
  conformidad, pregunta talla solo en los artículos que la llevan, y no se
  registra sin firma. El registro guarda número, nombre, talla, firma y carta.
- Existencias: lista solo artículos activos y avisa los saldos en negativo.
- Historial e identificación (factura / #empleado), filtro por tipo.
- El detalle sale como «Vale de entrega de EPP» y le pasa la sucursal al PDF.
- La factura admite foto de cámara, de galería o archivo PDF (campo sin
  `capture`, acepta `application/pdf`); es el ÚNICO campo así — se comprueba que
  los del reporte de carga sigan con cámara directa. Un PDF se previsualiza como
  archivo y en el detalle se abre con un enlace, nunca como <img> roto.

`test_historico_pantalla.js` — consulta histórica y descarga en los 5 historiales
(combustible, reparto, montacargas, formularios, EPP) y en la descarga de todo un
módulo. Para cada uno: avisa la ventana de 45 días; con «Desde» dentro de la
ventana no llama al servidor; con «Desde» viejo pide el archivo con ese rango y
lo muestra; con solo «Hasta» pide todo=1 hasta esa fecha y deja solo lo anterior;
el CSV se lee con un lector RFC 4180 (comillas, comas dentro de celdas, BOM por
bytes) y debe traer TODOS los registros del rango, todas las filas con las mismas
columnas que el encabezado, sin encabezados repetidos ni vacíos; el filtro de
sucursal recorta lista y CSV. Lo que este archivo NO ejecuta: la generación de
PDF/ZIP (necesita navegador); solo comprueba que los botones existan.
Hallazgos que destapó: encabezado CSV sin comillas (columnas desalineadas con
títulos que llevan coma), encabezados repetidos en reparto, y el historial de
EPP sin archivo histórico ni CSV.

`test_permisos_modulos.js` — permisos por módulo: Admin → Cuentas ofrece EPP; una
cuenta sin módulos marcados ve todos; una limitada a EPP ve solo EPP; una limitada a
Combustible y Mtto no ve EPP ni Seguridad; las cuentas viejas con «montacargas» o
«checklist» siguen abriendo Mtto; el admin ve Admin y Seguimiento. Monta la App real.

`test_epp_prerregistro.js` — entrega en dos manos: la casilla «Dejar en pre-registro»
quita la firma y manda status Prerregistro; la pestaña «Por concluir» solo la ve la
cuenta con marca de responsable (sin importar mayúsculas del correo); la lista muestra
al empleado y abre la pantalla de conclusión con los artículos ya capturados; no
concluye sin evidencia + firma; el detalle distingue «Por concluir (sin firma)» de una
concluida (evidencias, quién concluyó, observación). La llamada final a /concluir se
prueba en el servidor (tests/test_epp_prerregistro.py): en Node no hay FileReader para
meter la foto por el <input>.

`test_examen_publico.js` — la liga pública del examen médico (frontend/examen.html,
montada con fetch simulado): liga incompleta/inactiva → aviso sin formulario; validación
de campaña y token; paso a paso con obligatorios, edad calculada, «Negados» precargado,
Sí/No obligatorios, gineco-obstétrico solo para mujeres; consentimiento + firma para
enviar; payload exacto (campaña, token, consentimiento, firma PNG, sin datos de
navegación); folio de recibido; borrador local retomado; el 409 del servidor se muestra.

`test_examen_app.js` — el examen dentro de Responsivas: la tarjeta solo con la marca
«Expediente médico» (sin distinguir mayúsculas); pendientes/concluidos con conteo;
campañas y liga (con token) y alta de campaña; el médico no concluye sin diagnóstico,
clasificación y firma, el IMC se calcula, y el envío lleva signos, exploración,
antidoping, diagnóstico, clasificación, firma y nombre; el formato completo trae todas
las secciones y ambas firmas; la lista de seguimiento CSV NO lleva datos clínicos.

`montar.js` es el andamio: extrae el `<script type="text/babel">` de
`index.html`, lo compila y lo ejecuta con un `localStorage` simulado que tiene
cuota real, para poder probar también qué pasa cuando las fotos no caben.
