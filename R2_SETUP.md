# Cloudflare R2 — Setup completo

## 1. Crear el bucket

1. Cloudflare Dashboard → **R2 Object Storage** → **Create bucket**
2. Name: `agraound-docs`
3. Location: **Automatic**
4. Click **Create bucket**

El bucket queda **privado** por defecto. No activar Public Access.

---

## 2. Crear el API Token (con permiso correcto)

1. R2 → **Manage R2 API Tokens** → **Create API Token**

Completá el form así:

| Campo | Valor |
|-------|-------|
| **Token name** | `agraound-backend` |
| **Permissions → Account** | `Workers R2 Storage` → `Edit` ← este es el crítico |
| **Account Resources** | Include → All accounts |
| **Client IP Address Filtering** | dejar vacío (o poner la IP de Render si la tenés fija) |
| **TTL** | sin Start Date ni End Date (token permanente) |

> ⚠️ En el dropdown de **Permissions**, el campo tiene dos niveles:
> - Primer select: elegir **Account**
> - Segundo select: buscar **Workers R2 Storage** → seleccionar **Edit**
>
> Sin este permiso el token puede autenticarse pero no puede escribir objetos.

3. Click **Create API Token**
4. Copiar **inmediatamente** (solo se muestran una vez):
   - `Access Key ID`  → `R2_ACCESS_KEY_ID`
   - `Secret Access Key` → `R2_SECRET_ACCESS_KEY`

---

## 3. Obtener el Endpoint URL

En la página del bucket o del token vas a ver:

```
S3 Endpoint: https://abc123def456.r2.cloudflarestorage.com
```

El `abc123def456` es tu **Account ID**.  
También lo encontrás en: Cloudflare Dashboard → barra lateral derecha → **Account ID**.

`R2_ENDPOINT_URL` = `https://<account_id>.r2.cloudflarestorage.com`

---

## 4. Variables en .env

```env
R2_ENDPOINT_URL=https://abc123def456.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=tu_access_key_aqui
R2_SECRET_ACCESS_KEY=tu_secret_key_aqui
R2_BUCKET_NAME=agraound-docs
R2_PRESIGNED_EXPIRY=3600
```

---

## 5. Variables en Render.com

Dashboard → tu servicio → **Environment** → agregar:

| Key | Value |
|-----|-------|
| `R2_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | el valor copiado |
| `R2_SECRET_ACCESS_KEY` | el valor copiado |
| `R2_BUCKET_NAME` | `agraound-docs` |
| `R2_PRESIGNED_EXPIRY` | `3600` |

No cargar los secrets via `render.yaml` — siempre manual desde el dashboard.

---

## 6. Verificar que funciona

```bash
python -c "
import boto3
from botocore.client import Config

client = boto3.client(
    's3',
    endpoint_url='https://TU_ACCOUNT_ID.r2.cloudflarestorage.com',
    aws_access_key_id='TU_KEY_ID',
    aws_secret_access_key='TU_SECRET',
    config=Config(signature_version='s3v4'),
    region_name='auto',
)
# Listar objetos (bucket vacío devuelve lista vacía, no error)
resp = client.list_objects_v2(Bucket='agraound-docs')
print('OK — objetos:', resp.get('KeyCount', 0))
"
```

Si devuelve `OK — objetos: 0`, las credenciales son correctas y el bucket es accesible.

Errores comunes:
- `AccessDenied` → el token no tiene permiso `Workers R2 Storage → Edit`
- `NoSuchBucket` → el nombre del bucket no coincide con `R2_BUCKET_NAME`
- `InvalidAccessKeyId` → copiaste mal el Access Key ID

---

## Estructura de objetos en el bucket

```
agraound-docs/
├── receipts/
│   └── {engagement_id}/
│       └── {milestone_n}_{uuid8}.{pdf|jpg|png}
└── ndas/
    └── {engagement_id}/
        └── NDA_{engagement_id_upper}.pdf
```

## Endpoints de descarga (URLs firmadas)

```
GET /api/payments/{id}/receipt/{n}/download        → URL firmada del comprobante
GET /api/engagements/{id}/nda/download             → URL firmada del NDA PDF
GET /api/engagements/{id}/nda/download?expires=1800  → expira en 30 min
```

Respuesta:
```json
{
  "url": "https://...r2.cloudflarestorage.com/ndas/...?X-Amz-Signature=...",
  "expires_in": 3600,
  "note": "URL válida por 60 minutos."
}
```
