# Contrato de eventos `gpa.ops.v1`

Puente Operaciones-GPA → Fleet Command (patrón Strangler Fig con capa
anticorrupción). Operaciones-GPA **publica**; Fleet Command **recibe,
traduce y persiste**. Cada sistema conserva su propia base de datos.

```
gpa_operaciones_{env} (DynamoDB Streams)
        │  NEW_AND_OLD_IMAGES
        ▼
bridge/publisher.py  (Lambda gpa-ops-bridge-{env})
        │  POST JSON firmado (HMAC-SHA256)
        ▼
Receptor en Fleet Command  (bridge/receptor-fleet-command/)
        ├─ verifica firma y ventana de tiempo
        ├─ traduce vocabularios (FIELD_MAP)
        ├─ resuelve identidad contra catálogo Unit
        ├─ reutiliza process*() / analyzeRow() existentes
        ├─ copia evidencias S3 → opsgpa_<unidad>_<uuid8>_<campo>.<ext>
        └─ archiva el crudo en ops-capture/
```

## Sobre HTTP

| Header | Valor |
|---|---|
| `Content-Type` | `application/json` |
| `X-GPA-Contrato` | `gpa.ops.v1` |
| `X-GPA-Timestamp` | epoch segundos (UTC) del envío |
| `X-GPA-Firma` | `hex( HMAC-SHA256( secreto, "<timestamp>.<body>" ) )` |

El receptor DEBE rechazar (401) firmas inválidas y timestamps fuera de una
ventana de ±300 s. El secreto se comparte fuera de banda (parámetro
`FleetBridgeSecret` del stack / variable de entorno del receptor).

**Idempotencia**: el receptor DEBE tratar reenvíos del mismo
`(registroId, evento)` como upsert — reprocesar nunca duplica.
El publisher reintenta ante cualquier respuesta ≠ 2xx.

## Cuerpo del evento

```jsonc
{
  "version": 1,                       // SIEMPRE presente; evolución solo aditiva
  "contrato": "gpa.ops.v1",
  "tipo": "SOL",                      // SOL=combustible · CL=checklist reparto
                                      // (MC/montacargas NO cruza el puente aún)
  "subtipo": "semanal",               // CL: "semanal"|"mensual" · SOL: null
  "evento": "creacion",               // "creacion" | "cambio_estado"
  "registroId": "a1b2c3d4e5f6",       // uuid12 de Operaciones-GPA
  "folio": "OPS-a1b2c3d4e5f6",        // eventoId en Fleet Command: OPS-<registroId>
  "fechaISO": "2026-07-09T18:30:00+00:00",  // sellada por el servidor, UTC
  "sucursal": "Culiacán",
  "unidad": {                         // las TRES llaves para resolución robusta
    "vehicleId": "V-0042",            // id inmutable en Operaciones-GPA
    "economico": "42",                // mutable — NO usar como llave única
    "placas": "ABC123D"               // llave de inspecciones en Fleet Command
  },
  "responsable": {
    "nombre": "Juan Pérez",
    "userId": "U-17",
    "accountId": "juan@gpa.com.mx"    // cuenta Cognito que capturó
  },
  "status": "Pendiente",              // SOL: Pendiente|Aprobada|Rechazada|Por corregir|Anulado · CL: Aprobado|Anulado
  "answers": { /* campos de negocio tal como se capturaron (verbatim) */ },
  "evidencias": [                     // claves S3 en el bucket de Operaciones-GPA
    { "campo": "photo",  "key": "SOL/3f2a…c9.jpg" },
    { "campo": "answers.llantas.foto", "key": "CL/77b1…04.jpg" }
  ],
  "firma": "SOL/9e8d…11.png",         // clave S3 de la firma, o null
  "bucketOrigen": "gpa-ops-evidencias-prod-123456789012",
  "emitidoEn": "2026-07-09T18:30:02+00:00"
}
```

### Reglas

1. **`version` primero**: el receptor rechaza versiones que no conoce
   (`400 version no soportada`), nunca adivina.
2. **Evolución aditiva**: `gpa.ops.v1` solo agrega campos opcionales; cambios
   incompatibles crean `gpa.ops.v2` y un periodo de doble publicación.
3. **`answers` es verbatim**: el publisher NO traduce vocabularios; la
   traducción (`FIELD_MAP`) vive en el receptor (anticorrupción del lado
   consumidor). Valores no mapeados → DLQ del receptor con contexto.
4. **Identidad**: el receptor resuelve la unidad probando `placas` →
   `economico` → `vehicleId` contra su catálogo `Unit`. Si no resuelve,
   NO persiste: manda a su DLQ para inspección (evita fracturar historial).
5. **Fuente**: todo lo que el receptor persista lleva `fuente: "ops-gpa"` y
   folio `OPS-<registroId>` — trazable y sin colisión con folios MoreApp
   (`meta.serialNumber`).
6. **Evidencias**: el receptor copia de `bucketOrigen` a su propio bucket con
   nombre determinista `opsgpa_<placa|eco>_<uuid8>_<campo>.<ext>`,
   idempotente por `HeadObject` previo. Los primeros 8 hex del uuid de la
   clave origen son el `<uuid8>`.
7. **`evento`**:
   - `creacion` — INSERT del registro (captura de campo).
   - `cambio_estado` — cambió `status` (aprobación/rechazo de combustible).
     Parches internos (p. ej. análisis de foto) NO emiten evento.
   - Valores de `status` que puede traer un `cambio_estado` (evolución aditiva
     de v1, envelope y firma sin cambios):
     - **`Por corregir`** — el autorizador devolvió el registro para corregir un
       campo. Es un estado **NO final**: volverá a `Pendiente` y luego a
       `Aprobada`. El receptor debe tratarlo como **retenido** (no aprobado) y
       NO mandarlo a DLQ por status desconocido.
     - **`Anulado`** — el registro fue **reasignado** a otra unidad en
       Operaciones-GPA. El receptor debe **anular** (baja lógica, idempotente
       por folio) el evento `OPS-<registroId>`.
   - **Reasignación de unidad** = corrección que se propaga como **DOS eventos**:
     un `creacion` con **folio nuevo** en la unidad correcta (mismos datos y
     `fechaISO` original; `answers.reasignadoDe` referencia el folio viejo) y un
     `cambio_estado` → `Anulado` del **folio viejo** (`answers.reasignadoA`
     referencia el folio nuevo). Al reusar el folio como `eventoId`, la anulación
     y el alta se aplican de forma idempotente.
8. **Qué cruza el puente**: `SOL` y `CL` únicamente (variable `BRIDGE_TIPOS`).
   Montacargas y las 27 plantillas de mantenimiento quedan fuera hasta que
   exista módulo consumidor.

## Mapeo de campos por tipo

### `SOL` (combustible) — discriminador `answers.formato`

**La solicitud y el reporte de carga se guardan ambos con `tipo="SOL"`**;
lo único que los distingue es el campo `answers.formato`. El receptor DEBE
despachar así:

| `answers.formato` | Significado | Destino en Fleet Command |
|---|---|---|
| *(ausente)* | Solicitud de combustible | *Solicitud Gasolina* (`economicoId`, litros, monto) |
| `"reporte"` | Reporte de carga realizada | *Carga Gasolina* (tolerancia monto/km, km/l) |

**Solicitud** — `answers` contiene:
`km, tankBefore, tankAfter, necesidad, litros, monto, combustible, producto,
precio, tanque, subMarca, obs, photo (clave S3), status`.
`photo` = evidencia del odómetro; validación km para km/l.

**Reporte de carga** (`formato:"reporte"`) — `answers` contiene:
`km, lleno (bool: tanque quedó lleno — filtro duro para km/l), litros,
precioLitro, monto (= litros × precioLitro, calculado), combustible,
producto, precio, tanque, subMarca, areaResponsable, ubicacion {lat,lng},
mail, obs, status`, y las evidencias de 5 puntos:
`fotoAntes, fotoDespues (odómetro), fotoBomba, fotoTicket, fotoPersona`.

#### `answers._auditoria` — bloque de auditoría (solo reporte de carga)

Metadatos anti-fraude que **NO se muestran al operador que capturó** (la app
los oculta en el listado del rol operador y no los renderiza), pero **sí
viajan a Fleet Command** en `answers`. La ubicación es del dispositivo, se
re-lee en fresco al enviar (no proviene de ningún valor editable) y el envío
se bloquea si el operador no concede el GPS: es **obligatoria e inmodificable**.

| Campo | Origen | Descripción |
|---|---|---|
| `inicioLlenado` / `finLlenado` | cliente | ISO de apertura del formulario y de envío |
| `duracionSeg` | cliente | segundos de llenado (fin − inicio) |
| `geo` | dispositivo | `{lat, lng, accuracy (m), capturadoEn (ISO)}` — lectura del GPS al enviar |
| `tz`, `plataforma` | cliente | zona horaria y user-agent |
| `servidor` | **backend** | `{sourceIp, userAgent, recibidoEn}` sellado por el Lambda; el cliente NO lo puede alterar (se escribe al final). Contraste independiente contra `geo` para detectar GPS falseado |

Nota técnica: el navegador exige permiso de geolocalización por diseño; no
existe forma de leer GPS preciso sin él. El control se logra haciéndolo
**obligatorio** (sin ubicación no hay envío) y **no editable** (nunca es un
campo de texto ni se persiste en el borrador), más la IP de origen del
servidor como señal sin permiso. Debe estar cubierto en el aviso de
privacidad / política laboral del personal.

### `CL` (checklist de reparto) — `answers` contiene

`km, fotoKm (clave S3), answers{ itemId → valor }, obs`

- `subtipo=semanal` → *Inspección Semanal* (insumos exactos de
  `calcEstatusSemanal`; validar con payloads golden).
- `subtipo=mensual` → *Inspección Mensual ROF* (~45 datos; las fechas de
  documentos vienen estructuradas — Cumplimiento sin OCR).

La matriz item-por-item (`itemId → columna FIELD_MAP → analyzeRow`) se
mantiene en el receptor y se congela con pruebas de contrato: un item nuevo
o renombrado en la plantilla DEBE romper CI, no fallar en silencio.
