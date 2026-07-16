# Agraound Backend — Guía de Deploy y Configuración

## Stack
- **API**: FastAPI + Uvicorn
- **Persistencia operativa**: archivos JSON (catálogo estático + datos transaccionales en volumen persistente)
- **Registro de ventas**: MongoDB (opcional, best-effort)
- **Email**: Resend
- **PDF**: ReportLab (server-side)
- **Archivos** (PDFs/comprobantes): Cloudflare R2
- **Deploy**: Render.com

---

## Arquitectura de persistencia

Hay **tres orígenes de datos** separados a propósito:

| Origen | Qué guarda | Dónde vive | Fuente de verdad |
|---|---|---|---|
| **Catálogo estático** | `products.json`, `payment_info.json` | `data/` (versionado en el repo) | ✅ del catálogo |
| **Transaccional** | `clients.json`, `engagements.json`, `payments.json` | `TX_DATA_DIR` (volumen persistente, fuera del repo) | ✅ operativa |
| **Registro de ventas** | colección `sales` | MongoDB (opcional) | ❌ ledger consultable |

- El **catálogo** se edita a mano en el repo y viaja con cada deploy.
- Los **datos transaccionales** son la fuente de verdad operativa. Se escriben con **file-lock a nivel de SO (`fcntl.flock`)** para serializar las escrituras, más escritura atómica (`.tmp` + `fsync` + `os.replace`) para no corromper el JSON.
- **MongoDB** actúa solo como registro (ledger) de ventas: se actualiza al firmar y al verificar el pago inicial. Es **best-effort**: si `MONGODB_URI` está vacío o Mongo falla, la venta se procesa igual y solo se loguea el aviso.

---

## 1. Configurar MongoDB (opcional — solo registro de ventas)

MongoDB es **opcional**. Si lo dejás sin configurar, el sistema funciona igual (solo no lleva el registro consultable de ventas). Para habilitarlo:

1. Ir a https://cloud.mongodb.com → crear cuenta
2. Crear un **Cluster M0** (free tier)
3. En **Database Access** → crear usuario con contraseña
4. En **Network Access** → agregar IP `0.0.0.0/0` (Render usa IPs dinámicas)
5. En **Connect** → copiar la connection string:
   ```
   mongodb+srv://user:password@cluster.mongodb.net
   ```
6. Pegarla en `MONGODB_URI` del `.env`. La colección `sales` se crea sola.

---

## 2. Configurar Resend

1. Ir a https://resend.com → crear cuenta gratuita
2. **Domains** → agregar y verificar tu dominio (agrega registros DNS TXT/MX)
3. **API Keys** → crear key → copiarla en `RESEND_API_KEY`
4. Confirmar que `EMAIL_FROM` use el dominio verificado

> **Sin dominio propio**: podés usar `onboarding@resend.dev` para pruebas (solo envía a tu propio email).

---

## 3. Deploy en Render.com

### Opción A — Deploy con `render.yaml` (recomendado)

1. Subir el proyecto a GitHub
2. Ir a https://dashboard.render.com → **New** → **Blueprint**
3. Conectar el repo → Render detecta `render.yaml` automáticamente. Esto crea:
   - el Web Service,
   - un **disco persistente** montado en `/var/data` (variable `TX_DATA_DIR`).
4. Completar las variables marcadas como `sync: false` en el dashboard:
   - `MONGODB_URI` (opcional — dejar vacío desactiva el registro de ventas)
   - `RESEND_API_KEY`
   - `EMAIL_PROVIDER_TO`
   - las de R2 (`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`)
5. **Deploy** → esperar ~2 min

### Opción B — Manual

1. **New** → **Web Service** → conectar repo
2. Runtime: **Python 3**
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
5. En **Disks** → agregar un disco (ej. 1 GB) montado en `/var/data`
6. Agregar las variables de entorno del `.env.example` (incluida `TX_DATA_DIR=/var/data`)

---

## 4. Editar el catálogo (sin base de datos)

El catálogo es estático y editable a mano. **No hay seed que correr.**

- **Productos** → `data/products.json` (código, precio, descuento, hitos, badge).
- **Datos de pago** → `data/payment_info.json` (ARS, USD, EUR, cripto). Cada método aparece como una pestaña en el formulario; `enabled: false` lo oculta y los campos sin `value` no se muestran.

Editás el archivo, commiteás y redeployás. También podés usar los endpoints `POST/PUT/DELETE /api/products` (escriben sobre `data/products.json`), útil para cambios puntuales, pero recordá reflejar el cambio en el repo o se pierde en el próximo deploy.

---

## 5. Frontend

El formulario ya está integrado en `static/index.html` y servido por la propia app en `/`. Consume la API del mismo origen automáticamente:

- `GET /api/products` → catálogo (paso 2 del formulario).
- `GET /api/payment-info` → datos de transferencia (paso 3, pestañas dinámicas).
- `POST /api/engagements` → firma del NDA.
- `POST /api/payments/{id}/receipt` → comprobante.

No hay que editar URLs a mano: `API_BASE` se resuelve desde `window.location.origin`.

---

## 6. Estructura del proyecto

```
agraound-backend/
├── app/
│   ├── main.py                  # FastAPI app — sirve API + frontend estático
│   ├── core/
│   │   ├── config.py            # Settings desde .env
│   │   ├── store.py             # Persistencia JSON + file-lock (fcntl)
│   │   └── sales_log.py         # Registro de ventas en MongoDB (best-effort)
│   ├── models/
│   │   └── schemas.py           # Pydantic models
│   ├── routers/
│   │   ├── products.py          # GET/POST/PUT/DELETE /api/products
│   │   ├── payment_info.py      # GET /api/payment-info
│   │   ├── engagements.py       # POST /api/engagements (firma NDA)
│   │   └── payments.py          # POST /api/payments/:id/receipt
│   └── services/
│       ├── email_service.py     # Resend — emails
│       ├── pdf_service.py       # ReportLab — PDF firmado
│       └── storage_service.py   # Cloudflare R2 — archivos
├── data/
│   ├── products.json            # Catálogo (versionado, editable)
│   └── payment_info.json        # Datos de pago (versionado, editable)
├── static/
│   └── index.html               # Formulario NDA (frontend integrado)
├── requirements.txt
├── render.yaml
├── R2_SETUP.md
└── .env.example
```

> Los datos transaccionales (`clients.json`, `engagements.json`, `payments.json`) **no** viven en el repo: se crean en `TX_DATA_DIR` (volumen persistente) en tiempo de ejecución.

### Flujo completo en producción

```
Cliente abre https://tu-backend.onrender.com/
    ↓
static/index.html  (servido por FastAPI StaticFiles)
    ↓
GET /api/products      →  catálogo (data/products.json)
GET /api/payment-info  →  datos de pago (data/payment_info.json)
    ↓
Cliente completa form + firma + adjunta comprobante
    ↓
POST /api/engagements  →  upsert client + crea engagement + pagos (JSON, file-lock)
                       →  registra la venta en Mongo (best-effort)
                       →  genera PDF (ReportLab)
                       →  sube PDF a R2 (backup)
                       →  envía PDF por email al cliente (Resend)
                       →  notifica al proveedor (Resend)
    ↓
POST /api/payments/:id/receipt  →  sube comprobante a R2
                                →  notifica al proveedor (Resend)
    ↓
PATCH /api/payments/:id/1/verify → engagement "active" + actualiza venta en Mongo
    ↓
Cliente ve pantalla de éxito + puede descargar copia local (jsPDF)
```

---

## 7. Endpoints disponibles

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/products` | Catálogo activo (usado por el frontend) |
| POST | `/api/products` | Agregar nuevo producto |
| PUT | `/api/products/{code}` | Actualizar producto/precio |
| DELETE | `/api/products/{code}` | Desactivar producto (soft delete) |
| GET | `/api/payment-info` | Datos de pago habilitados (usado por el frontend) |
| POST | `/api/engagements` | **Firma NDA** — genera PDF + envía emails |
| GET | `/api/engagements` | Listar engagements (admin) |
| GET | `/api/engagements/{id}` | Detalle de un engagement |
| GET | `/api/engagements/{id}/nda/download` | URL presignada del PDF (admin) |
| PATCH | `/api/engagements/{id}/status` | Cambiar estado |
| POST | `/api/payments/{id}/receipt` | **Subir comprobante de pago** |
| GET | `/api/payments/{id}` | Ver pagos de un engagement |
| PATCH | `/api/payments/{id}/{n}/verify` | Verificar/rechazar pago (admin) |
| GET | `/api/payments/{id}/receipt/{n}/download` | URL presignada del comprobante (admin) |
| GET | `/health` | Health check |

Documentación interactiva: `https://tu-backend.onrender.com/docs`

---

## 8. Agregar / modificar productos

### Opción A — Editar `data/products.json` (recomendado)
Editar el archivo, commitear y redeployar. Es la fuente de verdad del catálogo.

### Opción B — Via API (POST)
```bash
curl -X POST https://tu-backend.onrender.com/api/products \
  -H "Content-Type: application/json" \
  -d '{
    "code": "AUDIT_PLUS",
    "name": "Audit Plus",
    "full_name": "Auditoría Extendida",
    "description": "Auditoría completa con informe ejecutivo y roadmap.",
    "base_price": 5500,
    "discount_pct": 8,
    "badge_label": "Nuevo",
    "badge_type": "prem",
    "is_active": true,
    "sort_order": 4,
    "milestones": [
      {"milestone_n": 1, "label": "Inicio + NDA", "pct": 40},
      {"milestone_n": 2, "label": "Informe parcial", "pct": 30},
      {"milestone_n": 3, "label": "Entrega final + roadmap", "pct": 30}
    ]
  }'
```
> El POST escribe sobre `data/products.json`. Reflejá el cambio en el repo o se perderá en el próximo deploy (el filesystem del repo se reconstruye).

---

## 9. Notas de producción

- **Persistencia transaccional**: `clients/engagements/payments.json` viven en `TX_DATA_DIR`. En Render **debe** ser un disco persistente montado (ej. `/var/data`), o los datos se pierden en cada redeploy. El catálogo, en cambio, viaja en el repo.
- **Comprobantes y PDFs**: se guardan en Cloudflare R2 (ver `R2_SETUP.md`). Sin R2 configurado, caen a `UPLOAD_DIR` local (efímero en Render — solo dev).
- **CORS**: En `main.py`, cambiar `allow_origins=["*"]` por el dominio exacto del formulario.
- **Autenticación admin**: Los endpoints de admin (listar engagements, verificar pagos) no tienen auth todavía. Agregar un middleware de API key o JWT antes de exponer en producción.
- **Logs**: Render muestra los logs en tiempo real desde el dashboard → tu servicio → **Logs**.

### ⚠️ Escalado: correr con un solo worker / una sola instancia

El diseño usa **un file-lock local (`fcntl.flock`) sobre un disco montado en un único host**. Esto garantiza consistencia y escrituras secuenciales **dentro de una instancia**, pero **no escala horizontalmente**:

- Mantené **`--workers 1`** y **una sola instancia** del servicio (ya viene fijado en `render.yaml`).
- El `flock` no coordina entre hosts distintos, y el disco persistente de Render se monta en una única instancia. Con 2+ instancias, cada una vería un disco distinto y el lock no las coordinaría → escrituras perdidas o divergentes.
- Para el volumen de una app de contratación, **1 worker sobra** (las escrituras son pocas y cortas).
- Si algún día se necesita escalar a múltiples instancias, la fuente de verdad debería migrar a una base de datos real (p. ej. promover MongoDB de "registro de ventas" a store principal, con transacciones), no al file-lock.
