# GPA ViaticOS — Sistema Integral de Viáticos

Módulo independiente para gestionar el ciclo completo de viáticos de GPA según la
política **POL-TE01**: solicitud → aprobación → transporte → anticipo →
comprobación → validación → revisión → cierre → reembolso.

Arquitectura idéntica a los demás proyectos GPA (Operaciones-GPA / Eco-Admin):
**PWA estática + backend serverless AWS SAM**, sin paso de build de npm.

```
ViaticOS-GPA/
├── template.yaml          Infra SAM (Lambda · HTTP API · DynamoDB · S3 · Cognito · SNS)
├── samconfig.toml         Config de despliegue por ambiente (dev/staging/prod)
├── Makefile               Atajos: build, deploy, seed, outputs, amplify-vars…
├── amplify.yml            Build spec de Amplify (genera config.js desde variables)
├── handler.py             Router de la Lambda (rutas + máquina de estados POL-TE01)
├── auth_cognito.py        Alta/edición de cuentas (panel admin)
├── db/                    Capa DynamoDB (modelos, escritura, queries)
├── s3/                    URLs prefirmadas para CFDIs/tickets/firmas
├── layer/                 Dependencias Python (boto3)
├── seed/                  Carga inicial: catálogos POL-TE01 + cuentas por rol
└── frontend/              PWA: index.html, gpa-api.js, viaticos-app.jsx (diseño), assets
```

## Roles del flujo (grupos de Cognito)

| Rol         | Hace |
|-------------|------|
| `empleado`  | Crea solicitudes y captura comprobantes |
| `supervisor`| Aprueba/rechaza solicitudes de su área y da visto bueno |
| `compras`   | Cotiza y registra el transporte |
| `tesoreria` | Libera el anticipo |
| `finanzas`  | Valida comprobación, cierra el viaje y marca el reembolso |
| `direccion` | Consulta global (dashboard) |
| `admin`     | Todo + panel de cuentas |

Estados: `Solicitada → Aprobada/Rechazada → TransporteCotizado → AnticipoLiberado
→ EnComprobacion → Validada → Revisada → Cerrada → Reembolsada`.

## Requisitos

- AWS SAM CLI · AWS CLI configurado (`aws configure`) · Python 3.12
- Windows (PowerShell): `setx PYTHONUTF8 1` (o `$env:PYTHONUTF8=1` por sesión)

## Despliegue del backend

```bash
# 1) Primera vez (crea el stack en dev)
make deploy-guided ENV=dev          # o: sam build && sam deploy --guided --config-env dev

# 2) Ver URLs e IDs del stack
make outputs ENV=dev

# 3) Cargar catálogos POL-TE01 + cuentas iniciales (una por rol)
make seed ENV=dev                   # contraseña por defecto: Gpa2026!
#   make seed ENV=dev PASSWORD="OtraClave1"   para cambiarla

# Despliegues posteriores
make deploy ENV=dev
```

Cuentas que crea el seed (contraseña `Gpa2026!`): `empleado@gpa.com.mx`,
`supervisor@gpa.com.mx`, `compras@gpa.com.mx`, `tesoreria@gpa.com.mx`,
`finanzas@gpa.com.mx`, `direccion@gpa.com.mx`, `administracion@gpa.com.mx` (admin).
Edita `seed/cuentas.json` antes de seedear en prod.

## Despliegue del frontend (AWS Amplify)

1. Sube este repo a GitHub y conéctalo en **AWS Amplify Hosting**.
2. Si vive como subcarpeta de un monorepo, marca *monorepo* y pon app root `ViaticOS-GPA`.
3. En **App settings → Environment variables** captura (de `make amplify-vars ENV=dev`):
   - `API_URL`, `POOL_ID`, `CLIENT_ID`, `APP_ENV` (`AWS_REGION` lo pone Amplify).
4. Amplify usa `amplify.yml` para generar `frontend/config.js` y publica `frontend/`.

### Probar el frontend en local
```bash
cp frontend/config.example.js frontend/config.js   # rellena con los Outputs de SAM
cd frontend && python -m http.server 8080          # abre http://localhost:8080
```

## La PWA

- **Solicitudes** (bandeja): listar/filtrar por estado, abrir detalle y ejecutar la
  acción que corresponde a tu rol y al estado actual (todo contra la API real).
- **Nueva**: alta de solicitud de viaje (empleado/supervisor/admin).
- **Cuentas** (solo admin): alta/edición de logins y roles en Cognito.
- **Diseño (demo)**: el recorrido maestro de 10 pasos (`viaticos-app.jsx`), la maqueta
  visual completa del flujo POL-TE01 con cotizador de vuelos/autobús y validación.

## Notas de integración / pendientes

- El backend persiste la solicitud y todo su ciclo (estados + historial + datos de cada
  etapa: transporte, anticipo, comprobantes) en DynamoDB single-table.
- La pantalla **Diseño (demo)** usa datos de ejemplo (el cotizador de vuelos/autobús y la
  validación IA son simulación de presentación). Para volverla operativa habría que
  conectar sus pasos a `api.paso(...)` igual que ya lo hace el módulo de bandeja/detalle,
  y, si se requiere, integrar un proveedor real de tarifas.
- `frontend/config.js` está en `.gitignore`: nunca se commitea (lo genera Amplify).
