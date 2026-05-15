# 🌊 GPA Eco-Admin · Motor de Fletes v2.4

<p align="center">
  <strong>General de Productos para el Agua</strong><br>
  Ecosistema Administrativo y Financiero Inteligente
</p>

---

## Descripción

Sistema de evaluación automatizada de solicitudes de apoyo de flete para **GPA** (General de Productos para el Agua). El motor aplica 6 capas de reglas de negocio con 30 códigos de resultado (`R-xxx`), almacena cada evaluación en DynamoDB y expone 12 endpoints REST vía API Gateway.

## Arquitectura

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Monitor    │────▶│  API Gateway     │────▶│   Lambda     │
│  HTML/JS    │     │  HTTP API v2     │     │   Python 3.12│
│  gpa-api.js │     │  + JWT Cognito   │     │   Motor v2.4 │
└─────────────┘     └──────────────────┘     └──────┬───────┘
                                                     │
                    ┌────────────┬───────────────────┼────────────┐
                    ▼            ▼                   ▼            ▼
              ┌──────────┐ ┌──────────┐      ┌──────────┐ ┌──────────┐
              │ DynamoDB │ │    S3    │      │   SQS    │ │   SNS    │
              │ gpa_     │ │ docs    │      │ cola     │ │ alertas  │
              │ fletes   │ │ PDF/XML │      │ async    │ │ email    │
              └──────────┘ └──────────┘      └──────────┘ └──────────┘
```

## Motor v2.4 — 6 Capas de Evaluación

| Capa | Señal | Tipo Operación | Motor |
|------|-------|----------------|-------|
| 0 | Pre-validación | R-091/R-092 | DynamoDB unicidad |
| 1a | GS0231 | DISPERSIÓN_INTERNA | Solo GDL → tarifas 2026 |
| 1b | GS0248 | CARGO_POR_ENVÍO | FV vs CP ±1% |
| 2 | GS0229 | BACK_ORDER | Solo C3, cualquier sucursal |
| 3 | Sin señal | VENTA_CLIENTE | C1–C5 completo |
| 4 | — | DISPERSIONES | Tarifas × fletera × destino |

## 30 Códigos R-xxx

| Grupo | Códigos | Concepto |
|-------|---------|----------|
| Aprobados | R-000, R-050, R-060, R-800 | Apoyo completo, Back Order, Cargo envío, Dispersión |
| Pre-validación | R-091, R-092 | FV duplicada, CP duplicada |
| C1 Monto | R-101 … R-105 | Monto insuficiente / Costal / Accesorios |
| C2 Producto | R-201, R-202 | Excluido sin elegible / Sin elegible |
| C3 Destino | R-301, R-302 | No cubierto / Ciudad borderline |
| C4 Entrega | R-401, R-401-S, R-401-D, R-402 | No domicilio / Sucursal / Fletera |
| C5 Proporción | R-501, R-502, R-601, R-602 | Flete alto / Crítico / Remoto |

## API — 12 Endpoints

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `POST` | `/evaluar` | JWT | Motor v2.4 — evaluar solicitud |
| `POST` | `/aprobar` | aprobador1 | Aprobar solicitud EN_REVISION |
| `POST` | `/rechazar` | aprobador1 | Rechazar solicitud |
| `POST` | `/escalar` | aprobador1 | Escalar a aprobador 2 |
| `GET` | `/monitor` | JWT | Kanban + filtro estado/fechas |
| `GET` | `/kpis` | JWT | KPIs del mes |
| `GET` | `/solicitud/{id}` | JWT | Detalle + historial |
| `GET` | `/solicitudes` | JWT | Listado paginado |
| `GET` | `/auditor/fletera` | auditor | Por RFC de fletera |
| `GET` | `/auditor/sucursal` | auditor | Por sucursal origen |
| `GET` | `/auditor/destino` | auditor | Por estado destino |
| `GET` | `/health` | Público | Health check |

## Estructura del Proyecto

```
Eco-Admin/
├── template.yaml                    ← SAM template (toda la infra)
├── samconfig.toml                   ← Config por ambiente
├── handler.py                       ← Lambda handler + router
├── motor/
│   ├── catalogos.py                 ← Parámetros + catálogos + R-xxx
│   ├── evaluador.py                 ← Motor 6 capas
│   └── tarifas.py                   ← Tarifas dispersiones 2026
├── db/
│   ├── validaciones.py              ← R-091 / R-092 (DynamoDB)
│   ├── escritura.py                 ← TransactWriteItems
│   └── queries.py                   ← Monitor + KPIs + auditoría
├── s3/
│   └── extractor.py                 ← Clasificar y agrupar docs PDF
├── frontend/
│   └── gpa-api.js                   ← SDK JS — Cognito + API Gateway
├── infrastructure/
│   ├── stack-gpa-fletes.yaml        ← CloudFormation alternativo
│   └── api-gateway-gpa.yaml         ← API Gateway standalone
├── layer/
│   └── requirements.txt             ← Dependencias del Lambda Layer
├── Makefile                         ← Build, deploy, logs, test
└── .gitignore
```

## Deploy

### Requisitos
- AWS CLI configurado con credenciales GPA
- AWS SAM CLI (`brew install aws-sam-cli`)
- Python 3.12

### Comandos

```bash
# Build
sam build

# Deploy (primera vez — interactivo)
sam deploy --guided --config-env dev

# Deploy (siguientes veces)
sam deploy --config-env dev        # desarrollo
sam deploy --config-env staging    # staging
sam deploy --config-env prod       # producción

# Solo actualizar código (sin recrear infra)
make update-code ENV=prod

# Logs en tiempo real
make logs ENV=prod

# Ver outputs (URLs, ARNs)
make outputs ENV=prod

# Crear usuario Cognito
make crear-usuario ENV=prod
```

## DynamoDB — Single Table Design

**Tabla:** `gpa_fletes_{env}`

| Entidad | PK | SK | Propósito |
|---------|----|----|-----------|
| Solicitud | `SOL#uuid` | `#META` | Registro completo |
| Índice FV | `FV#folioFV` | `SOL#uuid` | R-091 duplicidad |
| Índice CP | `CP#folioCP` | `SOL#uuid` | R-092 duplicidad |
| Historial | `SOL#uuid` | `HIST#timestamp` | Trazabilidad |

**4 GSIs:** estado-fecha, origen-fecha, fletera-fecha, destino-fecha

## Costo Estimado

| Recurso | Costo/mes |
|---------|-----------|
| Lambda (300 invocaciones) | ~$0.01 |
| API Gateway HTTP API | ~$0.01 |
| DynamoDB on-demand | ~$0.01 |
| S3 (10 MB docs) | ~$0.01 |
| Cognito (5 usuarios) | Gratis |
| **Total** | **< $1 USD/mes** |

## 10 Fleteras Autorizadas

| RFC | Razón Social |
|-----|-------------|
| ACT68080665A | Autotransportes de Carga Tresguerras |
| TEE070612ITA | Transportes y Envíos Estrella |
| TOS0407087T2 | Transportadora Osorio |
| FOR630225561 | Fletes de Oriente |
| TJO680807GU2 | Transportes Julian de Obregon |
| EME880309SK5 | Estafeta Mexicana |
| ACA170911HY7 | Autotransportes y Carga PTX |
| TCH170824TH2 | Transportes de Carga Hormik |
| FASG781207JM9 | Gerardo Franco Sánchez |
| CAAE970704V91 | Evelyn M. Camacho Aviña |

## 6 Sucursales

| Código | Ciudad | CP |
|--------|--------|-----|
| GDL | Guadalajara | 44930/44190 |
| CDMX | Ciudad de México | 09040/09230 |
| MTY | Monterrey | 64820 |
| CUN | Cancún | 77510 |
| PVR | Puerto Vallarta | 46291 |
| SJD | Los Cabos | 23473 |

---

**GPA** · General de Productos para el Agua S.A. de C.V.  
Motor de Fletes v2.4 · Mayo 2026
