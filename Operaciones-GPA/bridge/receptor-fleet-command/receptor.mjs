// receptor.mjs — Receptor del puente gpa.ops.v1 (vive en Fleet Command)
// ─────────────────────────────────────────────────────────────────
// Pieza PORTABLE: copiar al repo de Fleet Command y cablear los TODO
// con sus process*()/analyzeRow() existentes. Ver README.md contiguo.
//
// Responsabilidades (capa anticorrupción, lado consumidor):
//   1. Autenticar: HMAC-SHA256 + ventana de tiempo ±300 s
//   2. Validar contrato (version 1, tipos SOL/CL)
//   3. Archivar el crudo en s3://<BUCKET>/ops-capture/AAAA/MM/<registroId>.json
//   4. Resolver identidad contra el catálogo Unit (placas → economico → vehicleId)
//   5. Traducir vocabularios (FIELD_MAP) — valores no mapeados → DLQ
//   6. Copiar evidencias al bucket propio: opsgpa_<unidad>_<uuid8>_<campo>.<ext>
//   7. Reutilizar los process*() existentes con folio OPS-<registroId>,
//      marcando fuente:"ops-gpa" (idempotente: reenvío = upsert)
//
// Env vars:
//   BRIDGE_SECRET      secreto compartido (mismo FleetBridgeSecret del stack Ops)
//   BUCKET             bucket S3 de Fleet Command
//   OPS_BUCKET_OK      (opcional) bucket origen permitido; si se define,
//                      se rechazan eventos con otro bucketOrigen
//   VENTANA_SEG        (opcional) ventana anti-replay, default 300
// ─────────────────────────────────────────────────────────────────

import { createHmac, timingSafeEqual } from 'node:crypto';
import { S3Client, HeadObjectCommand, CopyObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';

const s3 = new S3Client({});
const BUCKET = process.env.BUCKET;
const VENTANA = Number(process.env.VENTANA_SEG || 300);

// ── 1. Autenticación ─────────────────────────────────────────────
export function verificarFirma(headers, rawBody, ahoraEpoch = Math.floor(Date.now() / 1000)) {
  const h = Object.fromEntries(Object.entries(headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  const ts = h['x-gpa-timestamp'];
  const firma = h['x-gpa-firma'];
  if (!ts || !firma) return { ok: false, error: 'faltan headers de firma' };
  if (Math.abs(ahoraEpoch - Number(ts)) > VENTANA) return { ok: false, error: 'timestamp fuera de ventana' };
  const esperada = createHmac('sha256', process.env.BRIDGE_SECRET || '')
    .update(`${ts}.${rawBody}`).digest('hex');
  const a = Buffer.from(esperada), b = Buffer.from(String(firma));
  if (a.length !== b.length || !timingSafeEqual(a, b)) return { ok: false, error: 'firma inválida' };
  return { ok: true };
}

// ── 2. Validación de contrato ────────────────────────────────────
export function validarContrato(ev) {
  if (ev?.version !== 1) return `version no soportada: ${ev?.version}`;
  if (!['SOL', 'CL'].includes(ev.tipo)) return `tipo fuera del puente: ${ev.tipo}`;
  if (!ev.registroId) return 'falta registroId';
  if (!ev.fechaISO) return 'falta fechaISO';
  if (!ev.unidad?.placas && !ev.unidad?.economico && !ev.unidad?.vehicleId) return 'unidad sin llaves';
  if (process.env.OPS_BUCKET_OK && ev.bucketOrigen !== process.env.OPS_BUCKET_OK)
    return `bucketOrigen no autorizado: ${ev.bucketOrigen}`;
  return null;
}

// ── 4. Identidad ─────────────────────────────────────────────────
// TODO(Fleet Command): sustituir por consulta real al modelo Unit.
// Orden de resolución: placas → economico → vehicleId. Si nada resuelve,
// se responde 422 y el evento cae a la DLQ del publisher — NUNCA persistir
// con identidad ambigua (evita fracturar el historial de la unidad).
export async function resolverUnidad(unidad /* {vehicleId, economico, placas} */) {
  throw new Error('resolverUnidad: cablear contra el catálogo Unit de Fleet Command');
}

// ── 5. Vocabularios ──────────────────────────────────────────────
// TODO(Fleet Command): completar con la matriz item-por-item
// (itemId Operaciones-GPA → columna FIELD_MAP → analyzeRow). Mantener
// exhaustiva con pruebas de contrato: valor no mapeado lanza y va a DLQ.
export const FIELD_MAP = {
  // CL semanal — ejemplo (ajustar a los valores reales de calcEstatusSemanal):
  // 'llantas':   { 'Bien': 'OK', 'Con Raspaduras/Golpes': 'RASPADO', ... },
};

export function traducir(campo, valor) {
  const mapa = FIELD_MAP[campo];
  if (!mapa) return valor;                       // campo sin vocabulario cerrado
  if (!(String(valor) in mapa)) {
    const e = new Error(`vocabulario no mapeado: ${campo}=${valor}`);
    e.statusCode = 422;
    throw e;
  }
  return mapa[String(valor)];
}

// ── 6. Evidencias ────────────────────────────────────────────────
// Copia idempotente: opsgpa_<placa|eco>_<uuid8>_<campo>.<ext>
export async function copiarEvidencia(ev, evidencia, unidadResuelta) {
  const m = /^(?:SOL|CL|MC|FRM)\/([0-9a-f]{8})[0-9a-f]{24}\.(jpg|png|webp)$/.exec(evidencia.key);
  if (!m) throw new Error(`clave de evidencia inesperada: ${evidencia.key}`);
  const campo = evidencia.campo.replace(/[^a-zA-Z0-9]+/g, '-').slice(0, 40);
  const unidad = unidadResuelta?.placas || unidadResuelta?.economicoId || 'sin-unidad';
  const destino = `opsgpa_${unidad}_${m[1]}_${campo}.${m[2]}`;
  try {
    await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: destino }));
    return destino;                              // ya copiada (reenvío)
  } catch { /* no existe aún: copiar */ }
  await s3.send(new CopyObjectCommand({
    Bucket: BUCKET,
    Key: destino,
    CopySource: `${ev.bucketOrigen}/${encodeURIComponent(evidencia.key)}`,
    MetadataDirective: 'COPY',
  }));
  return destino;
}

// ── 3. Archivo del crudo ─────────────────────────────────────────
export async function archivarCrudo(ev, rawBody) {
  const [anio, mes] = ev.fechaISO.split('-');
  await s3.send(new PutObjectCommand({
    Bucket: BUCKET,
    Key: `ops-capture/${anio}/${mes}/${ev.registroId}-${ev.evento}.json`,
    Body: rawBody,
    ContentType: 'application/json',
  }));
}

// ── 7. Persistencia (reutiliza el dominio de Fleet Command) ──────
// TODO(Fleet Command): cablear cada rama al process*() existente.
// Regla de folio: eventoId = ev.folio ("OPS-<registroId>") y fuente:"ops-gpa".
async function persistir(ev, unidad, evidenciasCopiadas) {
  if (ev.tipo === 'SOL') {
    // OJO: solicitud y reporte de carga llegan AMBOS como tipo SOL;
    // el discriminador es answers.formato (ver CONTRATO-gpa.ops.v1.md).
    if (ev.answers?.formato === 'reporte') {
      // Reporte de carga: litros/precioLitro/monto/lleno + 5 evidencias
      // creacion → processCargaGasolina({...}) — `lleno` es el filtro duro km/l
      throw new Error('persistir SOL reporte (carga): cablear a process* de Fleet Command');
    }
    // creacion      → processSolicitudGasolina({...})
    // cambio_estado → actualizar estado de la solicitud (Aprobada/Rechazada)
    throw new Error('persistir SOL solicitud: cablear a process* de Fleet Command');
  }
  if (ev.tipo === 'CL' && ev.subtipo === 'semanal') {
    // → processInspeccionSemanal: validar insumos EXACTOS de calcEstatusSemanal
    throw new Error('persistir CL semanal: cablear a process* de Fleet Command');
  }
  if (ev.tipo === 'CL' && ev.subtipo === 'mensual') {
    // → processInspeccionMensual (~45 datos; fechas de documentos estructuradas)
    throw new Error('persistir CL mensual: cablear a process* de Fleet Command');
  }
  throw Object.assign(new Error(`sin ruta de persistencia: ${ev.tipo}/${ev.subtipo}`), { statusCode: 422 });
}

// ── Handler (API Gateway HTTP API v2 / Function URL) ─────────────
export async function handler(event) {
  const rawBody = event.isBase64Encoded
    ? Buffer.from(event.body || '', 'base64').toString('utf8')
    : (event.body || '');

  const auth = verificarFirma(event.headers, rawBody);
  if (!auth.ok) return respuesta(401, { error: auth.error });

  let ev;
  try { ev = JSON.parse(rawBody); } catch { return respuesta(400, { error: 'JSON inválido' }); }

  const errContrato = validarContrato(ev);
  if (errContrato) return respuesta(400, { error: errContrato });

  // Crudo SIEMPRE se archiva, incluso si la persistencia falla después:
  // todo evento es re-procesable desde ops-capture/.
  await archivarCrudo(ev, rawBody);

  try {
    const unidad = await resolverUnidad(ev.unidad);
    if (!unidad) return respuesta(422, { error: 'unidad no resuelta', unidad: ev.unidad });

    const copiadas = [];
    for (const e of ev.evidencias || []) copiadas.push(await copiarEvidencia(ev, e, unidad));
    if (ev.firma) copiadas.push(await copiarEvidencia(ev, { campo: 'firma', key: ev.firma }, unidad));

    await persistir(ev, unidad, copiadas);
    return respuesta(200, { ok: true, folio: ev.folio, evidencias: copiadas.length });
  } catch (err) {
    // 4xx = evento malo (no reintentar tiene sentido, pero el publisher
    // reintenta todo ≠2xx: el récord terminará en la DLQ con contexto aquí
    // en los logs). 5xx = falla transitoria, el reintento la resuelve.
    const code = err.statusCode || 500;
    console.error('receptor gpa.ops.v1:', ev?.folio, err);
    return respuesta(code, { error: String(err.message || err), folio: ev?.folio });
  }
}

const respuesta = (statusCode, body) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
