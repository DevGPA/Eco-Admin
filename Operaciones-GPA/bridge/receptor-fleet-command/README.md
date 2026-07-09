# Receptor del puente `gpa.ops.v1` — pieza portable para Fleet Command

Esta carpeta vive en el repo de **Operaciones-GPA** solo como *entrega
portátil*: el receptor debe integrarse **dentro del stack de Fleet Command**
(la anticorrupción vive del lado consumidor, junto a `FIELD_MAP`,
el catálogo `Unit` y los `process*()`/`analyzeRow()` que reutiliza).

## Por qué el receptor vive en Fleet Command

- La traducción de vocabularios y la resolución de identidad son
  conocimiento del dominio de Fleet Command.
- Reutiliza los `process*()` existentes: mismo semáforo, mismo km/l,
  mismas referencias de foto que produce el webhook de MoreApp.
- Fleet Command ya es idempotente por llaves naturales compuestas:
  un reenvío del publisher converge en upsert, nunca duplica.

## Integración (en el repo de Fleet Command, CloudShell)

1. Copiar `receptor.mjs` al proyecto y agregar una ruta nueva al Lambda
   (p. ej. `POST /bridge/ops`) — **separada** de las rutas de MoreApp.
2. Cablear los tres `TODO(Fleet Command)`:
   - `resolverUnidad()` → consulta al modelo `Unit`
     (orden: `placas` → `economico` → `vehicleId`; sin resolución = 422).
   - `FIELD_MAP` → matriz item-por-item (itemId de Operaciones-GPA →
     columna → `analyzeRow`). Congelar con pruebas de contrato.
   - `persistir()` → llamar a los `process*()` reales con
     `eventoId = "OPS-<registroId>"` y `fuente: "ops-gpa"`.
3. Variables de entorno: `BRIDGE_SECRET` (el mismo `FleetBridgeSecret`
   del stack de Operaciones-GPA), `BUCKET`, y opcional `OPS_BUCKET_OK`
   con el nombre del bucket de evidencias de Operaciones-GPA.
4. IAM del rol del receptor (misma cuenta AWS, no requiere bucket policy):
   - `s3:GetObject` sobre `arn:aws:s3:::gpa-ops-evidencias-<env>-<cuenta>/*`
   - `s3:PutObject` sobre su propio bucket (`ops-capture/*` y `opsgpa_*`)
   - Lectura/escritura DynamoDB que ya tienen los `process*()`.
5. Del lado Operaciones-GPA, redesplegar con los parámetros:
   ```
   sam deploy --config-env prod --parameter-overrides \
     FleetBridgeUrl=https://<api-fleet-command>/bridge/ops \
     FleetBridgeSecret=<secreto-compartido>
   ```
   Mientras `FleetBridgeUrl` esté vacía, el publisher queda en **modo
   espera** (no envía, no acumula DLQ) — se puede desplegar el lado
   Operaciones-GPA desde hoy.

## Pruebas de contrato (golden payloads)

En Operaciones-GPA: `tests/test_puente.py` genera los eventos canónicos.
En Fleet Command: alimentar esos mismos JSON al receptor y verificar que
producen upserts equivalentes a los de capturas reales de
`moreapp-capture/` (mismo semáforo, mismo km/l, mismas referencias de
foto). Un item nuevo o renombrado en plantillas debe ROMPER estas
pruebas, no fallar en silencio.

## Comportamiento ante fallas

| Situación | Respuesta | Efecto en el publisher |
|---|---|---|
| Firma inválida / fuera de ventana | 401 | reintento → DLQ |
| Contrato inválido (version, tipo) | 400 | reintento → DLQ |
| Unidad no resuelta | 422 | reintento → DLQ (inspección manual) |
| Vocabulario no mapeado | 422 | reintento → DLQ |
| Falla transitoria (S3/DynamoDB) | 500 | reintento la resuelve |
| Éxito (o reenvío ya procesado) | 200 | confirma el record |

El crudo SIEMPRE queda en `ops-capture/AAAA/MM/` antes de intentar
persistir: todo evento es re-procesable aun si la persistencia falló.
