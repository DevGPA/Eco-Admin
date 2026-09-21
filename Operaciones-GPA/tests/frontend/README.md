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

`montar.js` es el andamio: extrae el `<script type="text/babel">` de
`index.html`, lo compila y lo ejecuta con un `localStorage` simulado que tiene
cuota real, para poder probar también qué pasa cuando las fotos no caben.
