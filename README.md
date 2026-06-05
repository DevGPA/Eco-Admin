# GPA · Repositorio multi-proyecto

Este repositorio contiene **dos proyectos, separados por rama**.
`main` es solo este índice; **el código vive en las ramas**.

---

## 🚚 Motor de Fletes (Eco-Admin) → rama [`motor-fletes`](../../tree/motor-fletes)

Backend serverless en **AWS SAM** que evalúa solicitudes de apoyo de flete
(6 capas de reglas, 30 códigos R-xxx), con OCR de documentos escaneados
(Amazon Textract) y un monitor web (Kanban).

```bash
git checkout motor-fletes
```
Despliegue: ver `docs/DESPLIEGUE.md` en esa rama (backend con `sam deploy`).

---

## 📱 GPA Operaciones → rama [`Operaciones-GPA`](../../tree/Operaciones-GPA)

PWA de operaciones (combustible, checklist de reparto, montacargas) sobre
AWS SAM, con frontend hospedado en AWS Amplify.

```bash
git checkout Operaciones-GPA
```

---

> Nota: los dos proyectos no comparten código de aplicación. Si en el futuro
> conviene, **GPA Operaciones puede moverse a su propio repositorio**.
