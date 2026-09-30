# Inteligencia comercial del prospecto — Especificación

> **Estado:** propuesta. Decidido el proveedor (dos etapas, §7) y quién redacta el
> resumen (§7-BIS). Lista para construir la etapa 1.
> **Versión:** 0.5 · 30-sep-2026
> **Proyecto:** GPA Alta de Clientes, rama `alta-clientes` de `DevGPA/Eco-Admin`.

## 1. Qué se pidió

Que el expediente de alta deje de ser solo papeles y traiga además una **lectura del
negocio del prospecto**, para poder decidir si es cliente para GPA:

1. Un campo donde el cliente capture su dirección de Google Maps.
2. Con eso, verificar si el comercio tiene fotos, validar que sean posteriores a la fecha
   en que dijo que inició el negocio, y descargarlas al apartado de fotos del negocio.
   El cliente **no** las puede quitar, porque viven en el tablero interno y no en su
   solicitud. Si él sube más, complementan.
3. Revisar las redes sociales y el sitio web que el cliente haya declarado.
4. Una imagen del mapa con los negocios **150 a 500 m** alrededor, marcando los del giro:
   piscinas, albercas, mantenimiento o tratamiento de agua residencial y comercial,
   bombeo de agua o similar.
5. Al final, junto con el consolidado de datos, un **resumen de viabilidad**: afinidad del
   cliente con nuestro giro, si el local exhibe producto, si tiene letrero alusivo afuera
   (deseable), un resumen de sus redes, y cuántos puntos de competencia hay alrededor.

## 2. Hallazgos que cambian el diseño

Se verificaron contra la documentación de Google antes de diseñar nada. Dos puntos, como
están escritos, no se pueden ejecutar.

### 2.1 Las fotos de Google NO se pueden descargar ni guardar — BLOQUEANTE

La política de Places API dice, textual:

> *"You must not pre-fetch, cache, or store Places API content beyond the allowed
> exceptions."*

Y la única excepción es el identificador del lugar:

> *"the place ID … is exempt from the caching restrictions. You can therefore store place
> ID values indefinitely."*

Bajarlas a nuestro bucket de S3 nos pondría fuera de los términos de servicio, con la
cuenta de Google Cloud de GPA de por medio. **No se hace.**

**Lo que sí logra el mismo objetivo.** El objetivo real era que el cliente no pudiera
quitarlas. Eso se consigue igual sin guardarlas: las fotos se **muestran en el tablero
interno, traídas de Google en el momento de verlas**, con su atribución. El cliente nunca
las ve y nunca las puede tocar, porque no forman parte de su solicitud. Lo único que se
guarda en DynamoDB es el `place_id`, que sí está permitido.

Costo de la diferencia: si Google retira una foto, deja de verse. A cambio, GPA se queda
dentro de los términos.

### 2.2 Las fotos de Google no traen fecha — BLOQUEANTE

El objeto `Photo` de Places API (New) tiene exactamente estos campos:

`name` · `widthPx` · `heightPx` · `authorAttributions[]` · `flagContentUri` · `googleMapsUri`

**No hay fecha de captura ni de subida.** La validación «que las fotos sean posteriores a
la fecha en que inició el negocio» no es difícil: es imposible con esa fuente.

**Lo que sí existe con fecha.** Street View **sí** publica la fecha de captura de cada
panorámica, y consultarla es **gratis** (no consume cuota):

> *"date — when the photo was taken … Street View Static API metadata requests are
> available at no charge."*

Lo cual además cae justo donde importa: Street View muestra la **fachada**, que es donde
se ve el letrero del punto 5. Así que la fachada sí se puede fechar, y se puede decir
«imagen de marzo de 2025, posterior a que el cliente dice haber abierto en 2021».

La fecha es la del paso del auto de Google, no la de la foto del negocio. Hay que leerla
como lo que es: *a esa fecha, el local se veía así*.

### 2.3 Las redes sociales no se pueden leer automáticamente — PARCIAL

Facebook e Instagram bloquean la lectura automatizada y sus términos la prohíben. Una
petición desde un servidor recibe un muro de inicio de sesión, no el contenido.

**Lo que sí se puede:**

- Del **sitio web** declarado: traer sus datos públicos (título, descripción, imagen) y
  buscar en su texto las palabras del giro. Eso sí es información real y automatizable.
- De **Facebook e Instagram**: comprobar que la liga exista y responda, y dejarle al
  analista un botón para abrirla. El resumen lo escribe quien revisa, no el sistema.

Prometer un resumen automático de redes sería prometer algo que se va a quedar en blanco
la mayoría de las veces.

## 3. Lo que sí se construye

| # | Pedido | Veredicto | Cómo |
|---|---|---|---|
| 1 | Campo de dirección de Google Maps | **Completo** | Campo en el formulario del cliente; el servidor lo resuelve a un lugar y guarda su `place_id` |
| 2 | Fotos del comercio | **Adaptado** | Se muestran en el tablero desde Google, no se descargan (§2.1). Sin fecha (§2.2) |
| 2b | Fachada fechada | **Añadido** | Street View con su fecha de captura, gratis |
| 3 | Redes y web | **Parcial** | Web sí se lee; FB/IG se validan y se abren a mano (§2.3) |
| 4 | Mapa de competencia 150–500 m | **Completo** | Búsqueda por giro en el radio + mapa con marcadores |
| 5 | Resumen de viabilidad | **Completo** | Ficha con los cinco criterios, para que decida una persona |

## 4. Cómo queda el flujo

```
CLIENTE (portal, sin cuenta)
  └─ captura su negocio en Google Maps  ─────┐
     y la fecha en que inició operaciones    │
                                             ▼
GPA recibe el expediente          ──►  Se arma la ficha comercial
                                        │
                                        ├─ Lugar: nombre, dirección, giro, calificación
                                        ├─ Fotos del local (desde Google, con atribución)
                                        ├─ Fachada de Street View + su fecha
                                        ├─ Mapa 150–500 m con la competencia marcada
                                        ├─ Sitio web: qué dice, si habla de nuestro giro
                                        └─ Ligas de redes, para abrirlas
                                        ▼
                             RESUMEN DE VIABILIDAD  ──►  Comité de Crédito
```

La ficha se arma **cuando el cliente envía**, junto con la revisión de obligados
solidarios que ya existe. El cliente no ve nada de esto, igual que no ve los comentarios
internos ni los anexos.

## 5. El resumen de viabilidad

Cinco criterios, cada uno con el dato que lo sustenta y de dónde salió. **No es un
semáforo automático que decida por el comité**: es la evidencia ordenada, con una
sugerencia, para que decida una persona.

| Criterio | Cómo se mide | Fuente |
|---|---|---|
| **Vende lo que vendemos** | GPA vende de negocio a negocio: el formato es «Alta Cliente **Distribuidor**». No basta con que el prospecto tenga que ver con albercas; importa si REVENDE o si solo consume. Un hotel con alberca nombra todas nuestras palabras y no es distribuidor: se marca como **usuario final** | Places |
| **Exhibe producto** | Hay fotos de interior del local | Places |
| **Letrero afuera** *(deseable)* | Fachada visible en Street View, con su fecha | Street View |
| **Presencia digital** | El sitio web responde y habla del giro; las redes existen | Sitio web declarado |
| **Mercado y competencia alrededor** | Cuántos **distribuidores** del giro hay a 150 m y a 500 m. En B2B esto NO se lee como «entre menos, mejor»: que haya distribuidores en la zona significa que ahí hay demanda, y una zona vacía puede ser territorio virgen o puede no tener mercado. Se reportan las dos lecturas y decide quien conoce la plaza | Places |

Cada criterio dice también **qué no se pudo comprobar**: «el negocio no aparece en Google
Maps», «no hay Street View en esa calle», «el sitio web no respondió». Un dato faltante
se ve como faltante, nunca como un cero.

### El diccionario del giro

Vive en `catalogos.py`, junto a todo lo demás, para poder afinarlo sin tocar código:

```
piscina · alberca · pool · spa · jacuzzi · hidroneumático · bomba de agua · bombeo
purificadora · purificación · tratamiento de agua · agua residual · filtro · filtración
cloro · químicos para alberca · cisterna · riego · hidráulica · plomería · ferretería
```

Ferretería y plomería son afinidad **indirecta**: cuentan, pero menos. Conviene revisar
este diccionario después de los primeros 20 prospectos reales.

## 6. Lo que cuesta

Precios de lista de Google Maps Platform, por 1,000 peticiones:

| Servicio | Precio | Peticiones por prospecto |
|---|---|---|
| Text Search (encontrar el lugar) | $32 USD | 1 |
| Place Details con fotos | $7 USD | 1 |
| Street View metadata (la fecha) | **gratis** | 1 |
| Street View imagen | $7 USD | 1 |
| Mapa estático con marcadores | $2 USD | 1 |
| Text Search de competencia | $32 USD | 3 a 4 |

**Aproximadamente $0.15 a $0.25 USD por prospecto** (unos 3 a 5 pesos), más lo que se
recalcule al volver a abrir la ficha.

Google da tope gratis mensual por servicio (entre 1,000 y 10,000 peticiones según el
servicio). **Al volumen de altas de GPA, esto cae dentro del tope gratis**, es decir,
costo cero en la práctica. Aun así hay que poner límite de gasto en la cuenta para que
un error en el código no se convierta en una factura.

## 6-BIS. Lo que cuesta el resumen redactado

Es lo ÚNICO de la ficha que consume tokens. El mapa, la competencia, el sitio
web y los cinco criterios son llamadas normales a una API: cero tokens.

Se midió armando la carga real que se le mandaría al modelo, no a ojo:

| | Medido |
|---|---|
| Tokens de entrada (la ficha completa + la instrucción) | ~790 |
| Tokens de salida (un párrafo de 4 a 6 líneas) | ~250 |

| Modelo | Por caso | 40 casos/mes | 500 casos/mes |
|---|---|---|---|
| **Haiku 4.5** | $0.0020 USD | $0.08 | $1.02 |
| Sonnet 4.5 *(el que ya usa Eco-Admin para OCR)* | $0.0061 USD | $0.24 | $3.06 |

Precios de lista de Anthropic. Bedrock puede variar, y su endpoint regional
cobra 10 % más que el global.

**Decidido: Sonnet 4.5** (30-sep-2026). Es el modelo que Eco-Admin ya tiene
habilitado en la cuenta, así que no hay que pedir acceso a otro en Bedrock.
Cuesta el triple que Haiku, y aun así son $0.24 USD al mes a 40 casos.

El modelo se configura con el parámetro `BedrockModelId` del `template.yaml`:
cambiarlo a Haiku más adelante no requiere tocar código, solo redesplegar.

**Cuándo se gasta.** Una vez por expediente enviado. Si el expediente se
devuelve al cliente y lo vuelve a mandar, la ficha se rearma y se paga otra
vez: en la vida de un caso, cuente 2 o 3 llamadas, no una.

Si aun así se quiere gasto cero por omisión, el resumen puede generarse
**cuando alguien abra la ficha** en vez de al enviarse. Solo se pagaría por los
expedientes que de verdad se analizan, a cambio de 3 a 5 segundos de espera la
primera vez.

## 7. Alternativas a Google, y por qué se construye en dos etapas

Google exige **cuenta de facturación activa** para dar una llave de API: *"you must set
up a billing account to set up a Cloud project"*. Da $300 USD de crédito por 90 días y
topes gratis mensuales, así que el problema **no es el dinero** — es que alguien tiene que
abrir una cuenta de Google Cloud de GPA y ponerle una tarjeta. GPA es casa Microsoft
(M365), así que sería un proveedor nuevo.

Se compararon los cuatro caminos posibles:

| | **Google Maps** | **Amazon Location** | **OpenStreetMap** | **Mapillary** |
|---|---|---|---|---|
| Cuenta nueva | **Sí**, con tarjeta | **No**, ya la tienen | No | Solo registro |
| Encontrar el negocio | Excelente | Bueno | Regular en México | — |
| **Fotos del local** | **Único que las da** | No | No | No |
| Fachada con fecha | Street View | No | No | Sí, cobertura irregular |
| Competencia alrededor | Excelente | Bueno | Pobre en México | — |
| Mapa con marcadores | Sí | Sí | Sí | — |
| Costo por prospecto | ~$0.20 USD | ~$0.003 USD | $0 | $0 |

**Amazon Location Service está dentro de la cuenta de AWS que ya usa este proyecto.**
Verificado en el propio `boto3` instalado: el cliente `geo-places` expone `search_text`,
`search_nearby`, `geocode` y `autocomplete`; el cliente `geo-maps` expone
`get_static_map`. Misma cuenta, mismo rol de IAM que ya tiene la Lambda, sin proveedor
nuevo y sin tarjeta nueva. Geocodificación a $0.50 USD y mapas a $0.70 USD **por cada mil**
peticiones: literalmente centavos al volumen de GPA.

Lo que Amazon Location **no** tiene es lo que hace único a Google: **las fotos del
negocio** y la imagen de la fachada. Y esas son justamente el punto 2 y dos de los cinco
criterios de viabilidad («exhibe producto» y «letrero afuera»).

### La decisión: dos etapas, con el proveedor intercambiable

El código se escribe contra **una sola interfaz** con dos implementaciones detrás. No hay
retrabajo: encender Google después es cambiar una variable de entorno.

**Etapa 1 — Amazon Location. Arranca de inmediato, sin pedirle nada a nadie.**
Cubre el punto 1 (campo de Maps), el punto 4 (mapa de competencia a 150–500 m) y el
criterio de competencia del punto 5. Los dos criterios que dependen de fotos aparecen
como **«pendiente: requiere Google»**, no como un cero ni como un hueco callado.

**Etapa 2 — Se añade Google cuando exista la cuenta.**
Se encienden las fotos del local, la fachada fechada de Street View y los dos criterios
que faltaban. Sin redesplegar nada más que la configuración.

Si la cuenta de Google nunca llega, la etapa 1 **sigue siendo útil por sí sola**: el mapa
de competencia y la afinidad del giro ya responden buena parte de «¿es cliente para
nosotros?».

## 7-BIS. Decisiones ya tomadas

**El resumen lo redacta un modelo** (29-sep-2026). Bedrock —el mismo que Eco-Admin ya usa
para OCR— redacta el párrafo de viabilidad a partir de los criterios medidos. Con tres
condiciones que no se negocian:

1. El modelo **solo redacta lo que se midió**. No opina sobre datos que no existen: si un
   criterio quedó pendiente, el párrafo lo dice, no lo rellena.
2. Va **marcado como borrador** en pantalla, con los cinco criterios y sus fuentes
   visibles al lado. Quien firma lee la evidencia, no solo el párrafo.
3. **No decide ni recomienda autorizar o rechazar.** Describe qué tan afín es el negocio;
   la decisión de crédito es del comité y queda en su firma, como hoy.

## 8. Lo que hay que vigilar al construir

- **La llave de API nunca en el navegador del cliente.** El portal es público, sin cuenta.
  Todo se resuelve desde el servidor, y la llave vive en el backend. Una llave expuesta
  en una página pública es una factura ajena esperando.
- **La ficha no bloquea el envío.** Si Google no responde, el cliente envía igual y la
  ficha queda pendiente. Nunca dejar al cliente atorado por un servicio de terceros.
- **Atribución obligatoria.** Las fotos de Places exigen mostrar el autor. Es requisito de
  los términos, no un detalle.
- **`_vista_cliente` es lista blanca.** Ningún campo de la ficha debe aparecer ahí. La
  prueba de `tests/rutas.py` ya vigila eso; hay que agregar los campos nuevos a su lista
  de prohibidos.
- **Tope de gasto en Google Cloud**, para que un bucle accidental no cueste dinero.
- **Aviso de privacidad.** Se va a guardar información del negocio obtenida de fuentes
  públicas. Vale la pena que el aviso del portal lo mencione.

## Changelog

| Versión | Fecha | Qué cambió |
|---|---|---|
| 0.1 | 29-sep-2026 | Primera versión. Verificados contra la documentación de Google los tres puntos dudosos: fotos no almacenables, fotos sin fecha, redes no leíbles. Pendientes las dos decisiones de §7. |
| 0.5 | 30-sep-2026 | Construido el resumen con Bedrock, configurado con Sonnet 4.5 por decisión del usuario. Con tres candados: solo redacta lo medido, va marcado como borrador, y si aun así recomienda autorizar o rechazar, se detecta y se avisa. Permisos de IAM de Amazon Location y Bedrock en el template. |
| 0.4 | 30-sep-2026 | Medido el consumo de tokens del resumen: ~790 de entrada y ~250 de salida por caso, o sea $0.002 USD con Haiku 4.5. Es lo único de la ficha que gasta tokens. |
| 0.3 | 29-sep-2026 | Corregido el enfoque: GPA vende B2B, a distribuidores. La afinidad ahora distingue distribuidor / usuario final / indirecto, y un hotel con alberca deja de contar como afín. El criterio de competencia deja de declarar «malo» tener un rival cerca: en B2B eso también puede significar demanda. |
| 0.2 | 29-sep-2026 | Comparados los cuatro proveedores. Amazon Location está en la cuenta de AWS que ya se usa (verificado en boto3: `geo-places.search_nearby`, `geo-maps.get_static_map`) y cuesta centavos, pero no tiene fotos. Se decide construir en dos etapas con el proveedor intercambiable, arrancando sin Google. El resumen lo redacta Bedrock, marcado como borrador y sin recomendar autorizar. |
