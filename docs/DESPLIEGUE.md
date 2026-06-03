# Despliegue · GPA Eco-Admin · Motor de Fletes v2.4

El sistema tiene **dos partes** que se despliegan distinto:

| Parte | Qué es | Cómo se despliega |
|------|--------|-------------------|
| **Backend (el motor)** | Lambda, DynamoDB, S3, SQS, Cognito, **Textract** | **AWS SAM** (`template.yaml`) |
| **Frontend (el monitor)** | El dashboard web (`monitor-v24-gpa.html` + `gpa-api.js`) | **AWS Amplify Hosting** (`amplify.yml`) |

> ⚠️ **AWS Amplify NO puede correr el backend.** Amplify solo hostea el monitor web.
> El motor (Lambda/DynamoDB/Textract) va sí o sí por SAM.

Requisito común: **acceso a la consola de AWS de GPA** (un usuario IAM que pueda entrar a `aws.amazon.com`). No se necesitan llaves de acceso locales ni instalar nada gracias a **AWS CloudShell**.

---

## 1) Backend — AWS SAM desde CloudShell (sin instalar nada)

**AWS CloudShell** es una terminal en el navegador, ya autenticada con tu cuenta y con `sam`/`git` preinstalados. Es la forma más simple si no tienes AWS CLI ni llaves locales.

1. Entra a la consola de AWS → arriba a la derecha, ícono de **CloudShell** (`>_`). Elige región **us-east-1**.
2. Clona el repo y entra:
   ```bash
   git clone https://github.com/DevGPA/Eco-Admin.git
   cd Eco-Admin
   ```
3. Compila y despliega (primera vez, interactivo):
   ```bash
   sam build
   sam deploy --guided --config-env prod
   ```
   - Acepta los defaults; cuando pregunte, confirma crear el changeset y los roles (`CAPABILITY_NAMED_IAM`).
   - `OcrBackend` queda en `textract` por defecto (recomendado, no requiere habilitar modelos).
4. Despliegues siguientes:
   ```bash
   sam build && sam deploy --config-env prod
   ```
5. Al terminar, anota los **Outputs** del stack (los necesita el frontend):
   ```bash
   aws cloudformation describe-stacks --stack-name gpa-fletes-prod \
     --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" --output table
   ```
   Te interesan: **ApiUrl**, **UserPoolId**, **UserPoolClientId**.
6. Crea un usuario para entrar al monitor:
   ```bash
   make crear-usuario ENV=prod EMAIL=usuario@gpa.com.mx
   ```

> Permisos: el rol del Lambda ya incluye `textract:AnalyzeDocument` (y `bedrock:InvokeModel` por si cambias el backend). No necesitas configurar nada extra de Textract.

---

## 2) Frontend — AWS Amplify Hosting (conectado a GitHub)

1. Consola de AWS → **Amplify** → **Crear nueva app** → **Hospedar app web**.
2. Conecta el proveedor **GitHub** → autoriza → elige el repo **DevGPA/Eco-Admin**, rama **main**.
3. Amplify detecta el archivo **`amplify.yml`** del repo (no cambies nada). Guarda y despliega.
4. Cada `git push` a `main` vuelve a desplegar el monitor automáticamente.
5. Amplify te da una URL (ej. `https://main.xxxx.amplifyapp.com`). Ahí abre el monitor.

El monitor arranca en **modo demo offline**. Para conectarlo al **motor real**, hay que ponerle los datos del backend (paso 3).

---

## 3) Conectar el monitor con el backend

En `docs/monitor/monitor-v24-gpa.html` busca el bloque **`GPA_CONFIG`** (cerca de la línea 1625) y llénalo con los Outputs del paso 1.5:

```js
const GPA_CONFIG = {
  env:      'prod',
  region:   'us-east-1',
  apiUrl:   'https://XXXX.execute-api.us-east-1.amazonaws.com/prod',  // = ApiUrl
  poolId:   'us-east-1_XXXXXXXXX',                                    // = UserPoolId
  clientId: 'XXXXXXXXXXXXXXXXXXXXXXXXXX',                             // = UserPoolClientId
};
```

Haz `git commit` + `push`; Amplify redepliega y el monitor queda **en vivo** contra el motor.

> CORS: el backend permite el origen configurado en `AllowedOrigin` (parámetro SAM).
> En prod, pásale la URL de Amplify: `sam deploy --config-env prod --parameter-overrides AllowedOrigin=https://main.xxxx.amplifyapp.com`

---

## Resumen del flujo de documentos (cómo opera ya desplegado)

1. Se sube un PDF (carta porte + factura) a `s3://gpa-documentos-prod/pendientes/{fecha}/`.
2. S3 dispara el Lambda → **Textract** hace OCR de cada página.
3. Se clasifica CP/FV por el RFC de GPA, se arma 1 caso por carta porte (emparejado a su factura por el folio del comentario).
4. El motor evalúa (6 capas, códigos R-xxx) y guarda el resultado en DynamoDB.
5. El monitor (Amplify) muestra el Kanban y permite aprobar/rechazar.
