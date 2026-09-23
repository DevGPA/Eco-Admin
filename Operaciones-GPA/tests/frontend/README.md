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

`montar.js` es el andamio: extrae el `<script type="text/babel">` de
`index.html`, lo compila y lo ejecuta con un `localStorage` simulado que tiene
cuota real, para poder probar también qué pasa cuando las fotos no caben.
