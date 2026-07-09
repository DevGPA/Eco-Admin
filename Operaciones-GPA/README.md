# Operaciones-GPA

App operativa de GPA para **celular**, con datos centrales en AWS. Tres módulos:

| Módulo | Qué hace |
|---|---|
| **Combustible** | Solicitud de combustible (vehículo, km, nivel de tanque, foto, firma). Flujo de aprobación. |
| **Reparto** | Checklist de unidades de reparto (semanal y mensual). |
| **Montacargas** | Checklist de montacargas (gas/eléctrico) con autorización del supervisor. |

Proyecto independiente del Motor de Fletes (Eco-Admin), pero con el mismo patrón
de infraestructura (AWS SAM).

## Arquitectura

```
Celular (PWA)  ──HTTPS──>  AWS Amplify Hosting  (build desde la branch de GitHub)
     │
     │ login (Cognito JWT) + API REST
     ▼
API Gateway (HTTP API) ──> Lambda (Python) ──> DynamoDB (datos)
                                          └──> S3 (fotos y firmas, URL prefirmada)
                                          └──> SNS (avisos por correo)
```

- **Frontend** (`frontend/`): app React servida como estáticos + PWA (instalable en el celular). Se hospeda en **AWS Amplify**, conectado a la branch de GitHub (CI/CD: cada push se publica). No usa `localStorage` para datos: todo va a la API.
- **Backend** (`handler.py`, `db/`, `s3/`): Lambda con router por ruta — se despliega con SAM.
- **Infra** (`template.yaml`): DynamoDB, Cognito, S3 de evidencias, SNS. (El hosting web NO está aquí: lo maneja Amplify, ver `amplify.yml`.)
- **Roles** (Cognito): `operador` (captura lo suyo), `supervisor` (su sucursal + autoriza), `analista` (lee todo + cambia estado), `admin` (todo + panel).
- **Panel Admin** (rol `admin`): alta/edición de vehículos, responsables, sucursales, correos de notificación y **cuentas de acceso** (crear logins, asignar rol/sucursal, resetear contraseña, activar/desactivar — opera contra Cognito).

## Requisitos para desplegar

- **AWS CLI** y **AWS SAM CLI** instalados y `aws configure` hecho.
- **Python 3.12**.
- En Windows/PowerShell, antes de usar SAM: `$env:PYTHONUTF8=1`.

## Despliegue paso a paso (ambiente `dev`)

```bash
# 1) Construir y desplegar la infraestructura (primera vez, interactivo)
make deploy-guided ENV=dev
#    (siguientes veces: make deploy ENV=dev)

# 2) Ver los datos del stack (URLs, IDs de Cognito, buckets)
make outputs ENV=dev

# 3) Cargar catálogos (vehículos/responsables/sucursales) y cuentas especiales
make seed ENV=dev
#    Para crear además un login por cada chofer:
#    make seed-operadores ENV=dev

# 4) Ver las variables para Amplify (API_URL, POOL_ID, CLIENT_ID)
make amplify-vars ENV=dev
```

### Publicar el frontend en AWS Amplify (una vez)

1. Consola de **AWS Amplify** → **Create new app** → **Host web app** → **GitHub**, autoriza y elige el repo `DevGPA/Eco-Admin`, branch **`Operaciones-GPA`**.
2. Marca que **es un monorepo** y pon como app root: **`Operaciones-GPA`** (Amplify usará `Operaciones-GPA/amplify.yml`). Equivale a definir la variable `AMPLIFY_MONOREPO_APP_ROOT=Operaciones-GPA`.
3. En **App settings → Environment variables** captura lo que imprime `make amplify-vars`:
   `API_URL`, `POOL_ID`, `CLIENT_ID`, `APP_ENV`.
4. **Save and deploy.** Amplify genera `config.js` en el build y publica. Te da una URL `https://operaciones-gpa.xxxx.amplifyapp.com`.
5. (Opcional) Agrega una regla de *redirects/rewrites* `/<*>` → `/index.html` (200) para que el refresco siempre cargue la app.

Desde entonces, **cada push a la branch `Operaciones-GPA` se publica solo**.

> **Importante (SNS):** al desplegar, AWS envía un correo de confirmación a
> `logisticaalmacenes@gpa.com.mx` y `admonriesgos@gpa.com.mx`. Hay que aceptar la
> suscripción una vez para que empiecen a llegar los avisos.

### Acceso inicial

Las cuentas se crean en Cognito con el seed:

```bash
# Resuelve tabla y pool del stack; pide la contraseña de forma segura.
# Por defecto la contraseña es TEMPORAL (cada quien define la suya al entrar).
python seed/seed.py --stack gpa-operaciones-dev --operadores
```

- El login es por **correo**. Cuenta admin por defecto: `administracion@gpa.com.mx`.
- La contraseña inicial NO se escribe en el comando: usa `GPA_SEED_PASSWORD` o se pregunta.
- Cambio obligatorio en el primer ingreso (recomendado). Usa `--permanente` para una clave definitiva, o `--password "…"` para fijarla.

### Instalar como app en el celular

Abre la URL de Amplify en Chrome/Safari → menú → **“Agregar a pantalla de inicio”**.
Queda como una app (PWA) a pantalla completa.

## Estructura

```
Operaciones-GPA/
├── template.yaml          # Infraestructura SAM (backend)
├── amplify.yml            # Build spec de AWS Amplify (frontend)
├── samconfig.toml         # Config de deploy por ambiente
├── Makefile               # build / deploy / seed / amplify-vars
├── handler.py             # Lambda (router)
├── db/                    # modelos, escritura y queries DynamoDB
├── s3/                    # URLs prefirmadas de evidencias
├── layer/                 # dependencias Python
├── seed/                  # catalogos.json, cuentas.json, seed.py
├── bridge/                # puente → Fleet Command (contrato gpa.ops.v1)
│   ├── publisher.py       #   Lambda: DynamoDB Streams → POST firmado
│   ├── CONTRATO-gpa.ops.v1.md
│   └── receptor-fleet-command/  # pieza portable para el stack de Fleet Command
├── tests/                 # pruebas del puente + payloads golden (tests/golden/)
└── frontend/              # PWA: index.html, gpa-api.js, sw.js, manifest, icon
```

## Puente → Fleet Command

Cada captura `SOL` (combustible) o `CL` (checklist) se publica a Fleet
Command vía DynamoDB Streams → `bridge/publisher.py` → POST firmado
(HMAC-SHA256) con el contrato `gpa.ops.v1`. Sin `FleetBridgeUrl`
configurada el publisher queda en modo espera (no envía). Detalles y
plan de integración: [bridge/CONTRATO-gpa.ops.v1.md](bridge/CONTRATO-gpa.ops.v1.md)
y [bridge/receptor-fleet-command/README.md](bridge/receptor-fleet-command/README.md).

```bash
python -m unittest tests.test_puente -v   # pruebas + regenerar golden
```

## Probar el frontend en local (sin desplegar la app)

Necesitas un backend ya desplegado. Copia `frontend/config.example.js` a
`frontend/config.js`, rellena los valores de `make outputs`, y sirve la carpeta:

```bash
cd frontend && python -m http.server 8080
# abre http://localhost:8080
```

## Pendiente / mejoras futuras

- Iconos PNG dedicados para la PWA (hoy usa `icon.svg`).
- Reporte/exportación a PDF de checklists.
- Notificaciones más ricas vía SES (plantillas) en lugar de SNS texto plano.
