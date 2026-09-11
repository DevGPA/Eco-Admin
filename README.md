# GPA · Alta de Clientes

Portal para armar el expediente de un cliente nuevo sin que el cliente tenga que
registrarse en nada.

**El flujo, en una línea:** GPA captura una pre-solicitud → el sistema genera una
**liga** y una **clave** → el cliente entra, captura y adjunta → GPA revisa, devuelve
si hace falta, y firma la autorización.

> **El alta en SAP sigue como hoy.** Este sistema no toca SAP: junta la información y
> el expediente, y deja los formatos listos.

---

## Lo que no se negocia

1. **El cliente nunca tiene cuenta.** Ni usuario, ni contraseña, ni registro, ni app.
   Entra con una liga y una clave, las veces que necesite.
2. **Nadie se da de alta solo.** Sin una pre-solicitud capturada por GPA no existe liga.
3. **Alta y crédito son solicitudes separadas**, con sus propios documentos y su propia
   autorización.
4. **Las reglas viven en el servidor.** La pantalla avisa; nunca decide.

---

## Los dos formatos que reproduce

| | Alta de cliente | Solicitud de crédito |
|---|---|---|
| Formato | `PNO-VE01-F3` | `CYC-FT-001 Rev.03` |
| Módulos | Fiscal y facturación · Entrega y horarios · Contactos | Fiscal y facturación · Crédito · Buró |
| Documentos | 5 | 13 |
| Autoriza | 1 firma del Comité de Crédito | Nivel 1 (1 firma) + Nivel 2 (2 firmas distintas) |

El catálogo unificado tiene **15 documentos únicos**: 5 del alta más 13 del crédito,
menos 3 que ambos formatos pedían por separado.

El tipo de persona sale del **régimen fiscal del SAT** (`c_RegimenFiscal`, 22 claves).
En los regímenes que aplican a ambas (610 y 626 RESICO) decide la longitud del RFC:
12 caracteres es persona moral, 13 es persona física. Si el régimen capturado y el RFC
no concuerdan, el sistema lo advierte antes de generar la liga.

---

## Roles internos

| Rol | Crea pre-solicitud | Revisa documentos | Firma | Panel de usuarios |
|---|---|---|---|---|
| Administrador | sí | sí | sí | sí |
| Comité de Crédito | sí | sí | sí | no |
| Ventas | sí | sí | no | no |
| Consulta | no | no | no | no |

Los niveles de firma (1 y 2) se prenden por persona en el panel de usuarios, y solo
se pueden dar a Comité de Crédito o Administrador.

---

## Seguridad de la liga

- La **liga** lleva un token de ~60 bits y va por correo.
- La **clave** va por otro canal (teléfono o WhatsApp). Si alguien reenvía el correo,
  la liga sola no abre nada.
- La clave **se muestra una sola vez** al generarla: en la base solo queda su huella
  (PBKDF2-SHA256, 210 000 vueltas, con sal por expediente). Si se pierde, se genera otra
  desde el expediente.
- **Cinco intentos fallidos** bloquean la liga hasta que GPA emita una clave nueva.
- Los documentos viven en un bucket privado y cifrado; se suben y se ven con URLs
  temporales (15 min para subir, 5 min para ver). Nunca pasan por la Lambda.

---

## Desplegar (AWS CloudShell)

Todo se hace desde CloudShell, en el navegador. No hace falta instalar nada.

**1. Abrir CloudShell**
Entre a la consola de AWS y abra CloudShell (el icono `>_` de la barra superior).
Espere a que aparezca la línea de comandos.

**2. Traer el proyecto**

```bash
git clone --single-branch --branch alta-clientes https://github.com/DevGPA/Eco-Admin.git alta-clientes
cd alta-clientes
```

**3. Construir y desplegar**

```bash
make deploy-guided ENV=dev
```

Le va a preguntar varias cosas. Acepte lo que propone (Enter) salvo:
- *Stack Name*: deje `gpa-alta-clientes-dev`
- *AWS Region*: `us-east-1`
- *Confirm changes before deploy*: `N`
- *Allow SAM CLI IAM role creation*: `Y`
- *Disable rollback*: `N`
- *Save arguments to configuration file*: `Y`

**Qué debe ver:** varias líneas `CREATE_COMPLETE` y al final
`Successfully created/updated stack - gpa-alta-clientes-dev`.
Tarda entre 3 y 6 minutos.

**4. Anotar los datos del sistema**

```bash
make outputs ENV=dev
```

**Qué debe ver:** una tabla con `ApiUrl`, `UserPoolId`, `UserPoolClientId` y otros.
Cópiela a un lado; la necesita en el paso 6.

**5. Crear su cuenta de Administrador**

```bash
make admin ENV=dev CORREO=administracion@gpa.com.mx NOMBRE="Oscar Cabrera"
```

**Qué debe ver:** `Cuenta creada.` con su correo y una contraseña temporal.
La primera vez que entre, el sistema le pedirá elegir su propia contraseña.

**6. Publicar la pantalla en Amplify**

1. En la consola de AWS abra **Amplify** → **Create new app** → **Deploy without Git**
   (o conecte el repositorio y elija la rama `alta-clientes`).
2. En **App settings → Environment variables** agregue, con los valores del paso 4:

   | Variable | Valor |
   |---|---|
   | `API_URL` | el `ApiUrl` |
   | `POOL_ID` | el `UserPoolId` |
   | `CLIENT_ID` | el `UserPoolClientId` |
   | `APP_ENV` | `dev` |

3. Vuelva a desplegar la app en Amplify.

**Qué debe ver:** una dirección tipo `https://dev.xxxxx.amplifyapp.com`. Ábrala:
debe aparecer la pantalla de acceso de GPA.

**7. Cerrar el paso abierto (importante)**

Mientras `AllowedOrigin` sea `*`, cualquier sitio puede llamar a la API. Con la
dirección de Amplify a la mano, ciérrelo:

```bash
sam deploy --config-env dev --no-confirm-changeset \
  --parameter-overrides Env=dev AllowedOrigin=https://dev.xxxxx.amplifyapp.com
```

**Cómo verificar que quedó bien**

| Qué | Cómo se comprueba | Qué debe pasar |
|---|---|---|
| La API vive | abra `<ApiUrl>/health` en el navegador | `{"ok": true, ...}` |
| Entra su cuenta | abra la dirección de Amplify | le pide elegir contraseña la primera vez |
| Se crea una liga | Nueva pre-solicitud → Generar liga y clave | aparecen liga y clave, y el caso en la bandeja |
| El cliente entra | abra la liga en una ventana privada | pide clave, no pide cuenta |
| La clave protege | escriba una clave equivocada | dice cuántos intentos quedan |

---

## Probar las reglas sin AWS

```bash
make pruebas
```

Ejecuta `db/escritura.py` tal cual, con una tabla en memoria: 70 comprobaciones sobre
folios, claves, permisos de captura, devoluciones, firmas y bitácora.

```bash
python tests/rutas.py
```

Comprueba que `template.yaml`, `handler.py` y el frontend declaren exactamente las
mismas rutas, y que solo las siete del portal sean públicas.

---

## Qué archivo hace qué

| Archivo | Qué hace |
|---|---|
| `catalogos.py` | Fuente **única** de régimen SAT, tipos, módulos, campos y documentos |
| `db/modelos.py` | Claves de la tabla, folios, hora de México, hash de la clave |
| `db/queries.py` | Lecturas. Quita la huella de la clave antes de devolver nada |
| `db/escritura.py` | **Todas las reglas de negocio** |
| `s3/documentos.py` | URLs prefirmadas de subida y lectura |
| `auth_cognito.py` | Usuarios internos, roles y niveles de firma |
| `handler.py` | Router: público para el portal, Cognito para lo interno |
| `frontend/gpa-api.js` | Dos clientes: `GpaApi` (interno) y `PortalApi` (cliente) |
| `frontend/app.js` | Las pantallas |
| `template.yaml` | La infraestructura |

---

## Pendientes

- **Correo automático.** Hoy la liga se copia y se pega; el correo de bienvenida de
  Cognito está apagado a propósito porque SES no está configurado (requiere IT).
- **Vencimiento de la liga.** El parámetro `VigenciaLigaDias` existe en el template
  pero todavía no se aplica al validar: una liga no caduca sola.
- **Generar el formato lleno** (`PNO-VE01-F3` y `CYC-FT-001` en PDF) a partir de lo
  capturado.
- **Descargar el expediente en ZIP.**
- **Umbral de monto** para decidir si un crédito necesita los dos niveles o solo uno.
- Definir los **usuarios reales** y sus niveles de firma.
