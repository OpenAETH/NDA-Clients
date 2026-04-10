# NDA-Clients — Agraound / AETHERYON

API backend para gestión de contratos NDA, engagements de clientes y pagos por hitos. Construida con **FastAPI + MongoDB Atlas + Cloudflare R2**.

🔗 **Producción:** [clientsnda.onrender.com](https://clientsnda.onrender.com)  
📄 **Docs interactivos:** [clientsnda.onrender.com/docs](https://clientsnda.onrender.com/docs)

---

## Stack

| Capa | Tecnología |
|---|---|
| Runtime | Python 3.11 |
| Framework | FastAPI 0.115 |
| Base de datos | MongoDB Atlas (motor async) |
| Almacenamiento | Cloudflare R2 (PDFs y comprobantes) |
| Email | Resend |
| PDF | ReportLab |
| Deploy | Render (Web Service) |

---

## Estructura del proyecto

```
app/
├── core/
│   ├── config.py        # Settings via pydantic-settings (.env)
│   └── database.py      # Conexión async a MongoDB Atlas
├── models/
│   └── schemas.py       # Modelos Pydantic (request/response)
├── routers/
│   ├── products.py      # CRUD catálogo de productos/servicios
│   ├── engagements.py   # Firma NDA, generación PDF, emails
│   └── payments.py      # Upload comprobantes, verificación hitos
├── services/
│   ├── pdf_service.py   # Generación NDA en PDF con ReportLab
│   ├── email_service.py # Envío de emails via Resend
│   └── storage_service.py # Upload/presigned URLs en R2
└── main.py              # App FastAPI, CORS, lifespan, static
static/
└── index.html           # Frontend embebido
```

---

## Flujo principal

```
Cliente llena formulario
        ↓
POST /api/engagements
        ↓
  ┌─────────────────────────────────┐
  │ 1. Resuelve producto del catálogo│
  │ 2. Calcula precio + descuento   │
  │ 3. Upsert cliente en MongoDB    │
  │ 4. Crea engagement + pagos      │
  │ 5. Genera PDF del NDA           │
  │ 6. Envía PDF al cliente (email) │
  │ 7. Notifica al proveedor        │
  │ 8. Sube PDF a Cloudflare R2     │
  └─────────────────────────────────┘
        ↓
Cliente sube comprobante de pago
POST /api/payments/{id}/receipt
        ↓
Admin verifica el pago
PATCH /api/payments/{id}/{n}/verify
        ↓
Engagement → status: "active"
```

---

## Variables de entorno

Crear un `.env` basado en `.env.example`:

```env
# MongoDB Atlas
MONGODB_URI=mongodb+srv://<user>:<password>@cluster0.xxxx.mongodb.net/?appName=Cluster0
MONGODB_DB=agraound-nda

# Resend
RESEND_API_KEY=re_xxxxxxxxxxxx
EMAIL_FROM=contacto@tudominio.com
EMAIL_FROM_NAME=Tu Empresa
EMAIL_PROVIDER_TO=contacto@tudominio.com

# App
SECRET_KEY=un-secreto-seguro-aqui
MAX_UPLOAD_MB=10
UPLOAD_DIR=/tmp/uploads

# Cloudflare R2 (opcional — sin esto usa almacenamiento local)
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=agraound-docs
R2_PRESIGNED_EXPIRY=3600
```

---

## Instalación local

```bash
git clone https://github.com/tu-org/NDA-Clients.git
cd NDA-Clients
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
uvicorn app.main:app --reload
```

Luego abrir: http://localhost:8000

---

## Deploy en Render

1. Crear un **Web Service** apuntando a este repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Agregar las variables de entorno del panel de Render.
5. **Importante:** copiar las **Outbound IPs** del servicio en Render y agregarlas a la whitelist de **Network Access** en MongoDB Atlas.

---

## Endpoints principales

### Productos
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/products` | Listar productos activos |
| GET | `/api/products/{code}` | Detalle de un producto |
| POST | `/api/products` | Crear producto (admin) |
| PUT | `/api/products/{code}` | Actualizar producto (admin) |
| DELETE | `/api/products/{code}` | Desactivar producto (soft-delete) |

### Engagements
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/engagements` | Firmar NDA + crear engagement |
| GET | `/api/engagements` | Listar engagements (admin) |
| PATCH | `/api/engagements/{id}/status` | Actualizar estado (admin) |
| GET | `/api/engagements/{id}/nda/download` | URL presignada del PDF (admin) |

### Pagos
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/payments/{id}/receipt` | Subir comprobante de pago |
| GET | `/api/payments/{id}` | Ver pagos de un engagement |
| PATCH | `/api/payments/{id}/{n}/verify` | Verificar/rechazar pago (admin) |
| GET | `/api/payments/{id}/receipt/{n}/download` | URL presignada del comprobante (admin) |

---

## Semilla de datos

Para cargar productos de ejemplo en la base de datos:

```bash
python seed_mongo.py
```

---

## Colecciones MongoDB

| Colección | Descripción |
|---|---|
| `products` | Catálogo de servicios con precios y hitos |
| `clients` | Datos de clientes (upsert por email) |
| `engagements` | Contratos firmados + metadata NDA |
| `payments` | Hitos de pago por engagement |

---

## Ideas de mejora

### 🔐 Seguridad
- **Autenticación admin:** Las rutas de admin (listar engagements, verificar pagos, descargar NDAs) están actualmente abiertas. Agregar JWT o API key con header `Authorization`.
- **Rate limiting:** Proteger `POST /api/engagements` contra spam con `slowapi` o un middleware de rate limit.
- **Validación de firma digital:** Guardar hash del PDF generado en MongoDB para poder verificar integridad posterior.

### 📬 Notificaciones
- **Webhooks:** Emitir eventos a un endpoint configurable cuando cambia el estado de un engagement o se verifica un pago. Útil para integraciones con CRMs.
- **Recordatorios de pago:** Cron job (Render Cron Job o APScheduler) que detecte pagos pendientes vencidos y envíe recordatorio por email.
- **Email de confirmación de verificación:** Actualmente solo se notifica al proveedor. Notificar también al cliente cuando su pago queda verificado.

### 🧾 Facturación
- **Generación de recibo en PDF:** Al verificar un pago, generar automáticamente un recibo/factura en PDF y enviarlo al cliente por email.
- **Integración con facturación electrónica:** Conectar con AFIP (Argentina) o SAT (México) para emitir comprobantes fiscales automáticamente.

### 🛠️ Admin panel
- **Dashboard web:** Actualmente la administración es 100% por API. Construir un panel simple con tabla de engagements, estado de pagos y botón de verificación.
- **Búsqueda y filtros:** Endpoint de engagements con filtros por fecha, producto, cliente y estado.

### 🔧 Código
- **Manejo de errores centralizado:** Crear un exception handler global en FastAPI en lugar de `try/except` dispersos por los routers.
- **Tests:** Agregar tests de integración con `pytest` + `httpx AsyncClient` y MongoDB en memoria (`mongomock-motor`).
- **Logging estructurado:** Reemplazar los `print()` por un logger con `structlog` o el `logging` estándar configurado en JSON para Render.
- **Paginación:** El endpoint `GET /api/engagements` tiene un `limit` hardcodeado. Agregar `skip` para paginación real.

### ☁️ Infraestructura
- **MongoDB Atlas IP estática:** Usar el addon de Static Outbound IPs de Render para fijar las IPs de salida y no tener que actualizar la whitelist de Atlas en cada redeploy.
- **Health check de DB:** El endpoint `/health` devuelve `ok` incluso si la DB está caída. Agregar un ping real a MongoDB en ese endpoint.
- **Backups automáticos:** Habilitar backups continuos en MongoDB Atlas para no depender solo de R2.
