# NDA-Clients — Agraound / AETHERYON

API backend para gestión de contratos NDA, engagements de clientes y pagos por hitos. Construida con **FastAPI**, con persistencia en **archivos JSON** (catálogo estático + datos transaccionales en volumen persistente con file-lock) y **MongoDB** como registro de ventas.

🔗 **Producción:** [clientsnda.onrender.com](https://clientsnda.onrender.com)  
📄 **Docs interactivos:** [clientsnda.onrender.com/docs](https://clientsnda.onrender.com/docs)

---

## Stack

| Capa | Tecnología |
|---|---|
| Runtime | Python 3.11 |
| Framework | FastAPI 0.115 |
| Persistencia operativa | Archivos JSON + file-lock (`fcntl.flock`) |
| Registro de ventas | MongoDB (opcional, best-effort) |
| Almacenamiento | Cloudflare R2 (PDFs y comprobantes) |
| Email | Resend |
| PDF | ReportLab |
| Deploy | Render (Web Service + disco persistente) |

---

## Persistencia

Tres orígenes de datos, separados a propósito:

| Origen | Qué guarda | Dónde vive | Rol |
|---|---|---|---|
| **Catálogo estático** | `products.json`, `payment_info.json` | `data/` (versionado en el repo) | Fuente de verdad del catálogo, editable a mano |
| **Transaccional** | `clients.json`, `engagements.json`, `payments.json` | `TX_DATA_DIR` (volumen persistente) | **Fuente de verdad operativa** |
| **Registro de ventas** | colección `sales` | MongoDB (opcional) | Ledger consultable, best-effort |

- El **catálogo** viaja con el repo y se edita a mano.
- Los **datos transaccionales** se escriben con **file-lock a nivel de SO** para serializar las escrituras entre procesos, más escritura atómica (`.tmp` + `fsync` + `os.replace`).
- **MongoDB** solo registra ventas (al firmar y al verificar el pago inicial). Si no está configurado o falla, la venta se procesa igual — no bloquea nada.

> **Escalado:** el file-lock coordina escrituras dentro de **una sola instancia / un solo worker**. No escala horizontalmente. Ver la nota de escalado en [`DEPLOY.md`](DEPLOY.md#9-notas-de-producción).

---

## Estructura del proyecto

```
app/
├── core/
│   ├── config.py        # Settings via pydantic-settings (.env)
│   ├── store.py         # Persistencia JSON + file-lock (fcntl)
│   ├── discounts.py     # Resolución/cálculo de códigos de descuento
│   └── sales_log.py     # Registro de ventas en MongoDB (best-effort)
├── models/
│   └── schemas.py       # Modelos Pydantic (request/response)
├── routers/
│   ├── products.py      # CRUD catálogo de productos/servicios
│   ├── payment_info.py  # Datos de pago (transferencias/cripto)
│   ├── discounts.py     # Validación de códigos de descuento
│   ├── engagements.py   # Firma NDA, generación PDF, emails
│   └── payments.py      # Upload comprobantes, verificación hitos
├── services/
│   ├── pdf_service.py   # Generación NDA en PDF con ReportLab
│   ├── email_service.py # Envío de emails via Resend
│   └── storage_service.py # Upload/presigned URLs en R2
└── main.py              # App FastAPI, CORS, lifespan, static
data/
├── products.json        # Catálogo (versionado, editable)
├── payment_info.json    # Datos de pago (versionado, editable)
└── discount_codes.json  # Códigos de descuento (versionado, editable)
static/
└── index.html           # Frontend embebido
```

> Los datos transaccionales (`clients/engagements/payments.json`) se crean en `TX_DATA_DIR` en runtime — no están en el repo.

---

## Flujo principal

```
Cliente llena formulario
        ↓
POST /api/engagements
        ↓
  ┌───────────────────────────────────────┐
  │ 1. Resuelve producto del catálogo (JSON)│
  │ 2. Calcula precio: base/monto manual +  │
  │    código de descuento (re-validado)   │
  │ 3. Upsert cliente (JSON, file-lock)    │
  │ 4. Crea engagement + pagos (JSON)      │
  │ 5. Registra la venta en Mongo (opcional)│
  │ 6. Genera PDF del NDA                  │
  │ 7. Envía PDF al cliente (email)        │
  │ 8. Notifica al proveedor               │
  │ 9. Sube PDF a Cloudflare R2            │
  └───────────────────────────────────────┘
        ↓
Cliente sube comprobante de pago
POST /api/payments/{id}/receipt
        ↓
Admin verifica el pago
PATCH /api/payments/{id}/{n}/verify
        ↓
Engagement → status: "active"  (+ actualiza registro en Mongo)
```

---

## Variables de entorno

Crear un `.env` basado en `.env.example`:

```env
# Persistencia transaccional (volumen persistente)
TX_DATA_DIR=data/tx          # en prod: /var/data (disco montado)

# MongoDB — opcional, solo registro de ventas
MONGODB_URI=                 # vacío = registro desactivado (best-effort)
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

> No hay seed que correr: el catálogo ya está en `data/products.json`, `data/payment_info.json` y `data/discount_codes.json`. Los archivos transaccionales se crean solos en `TX_DATA_DIR` al primer uso.

---

## Deploy en Render

1. Crear un **Web Service** apuntando a este repo (o usar el `render.yaml` como Blueprint).
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
4. Agregar un **disco persistente** montado en `/var/data` y setear `TX_DATA_DIR=/var/data`.
5. Agregar las variables de entorno del panel de Render.
6. Mantener **1 worker / 1 instancia** (requisito del file-lock — ver `DEPLOY.md`).
7. Si usás MongoDB: copiar las **Outbound IPs** de Render y agregarlas a **Network Access** en Atlas.

Detalle completo en [`DEPLOY.md`](DEPLOY.md).

---

## Endpoints principales

### Productos y datos de pago
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/products` | Listar productos activos |
| GET | `/api/products/{code}` | Detalle de un producto |
| POST | `/api/products` | Crear producto (admin) |
| PUT | `/api/products/{code}` | Actualizar producto (admin) |
| DELETE | `/api/products/{code}` | Desactivar producto (soft-delete) |
| GET | `/api/payment-info` | Datos de pago habilitados |
| GET | `/api/discounts/validate` | Validar código y previsualizar precio |

### Engagements
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/engagements` | Firmar NDA + crear engagement |
| GET | `/api/engagements` | Listar engagements (admin) |
| GET | `/api/engagements/{id}` | Detalle de un engagement (admin) |
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

## Editar catálogo, datos de pago y descuentos

Todo el catálogo es estático y editable a mano (sin base de datos). Editás el archivo, commiteás y redeployás:

- **Productos** → `data/products.json` (código, precio, descuento por anticipado, hitos, badge).
- **Datos de pago** → `data/payment_info.json` (ARS, USD, EUR, cripto). Cada método es una pestaña del formulario; `enabled: false` lo oculta, y los campos sin `value` no se muestran (útil para wallets aún sin dirección).
- **Códigos de descuento** → `data/discount_codes.json` (ver abajo).

### Códigos de descuento

Se agregan/editan en `data/discount_codes.json`. Cada código:

```json
{
  "code": "LANZAMIENTO15",
  "type": "percent",          // "percent" (% sobre el precio) o "fixed" (USD a restar)
  "value": 15,
  "description": "15% de descuento de lanzamiento",
  "products": [],             // [] o ausente = todos; ["DAE"] = solo ese producto
  "enabled": true,            // false lo desactiva
  "expires_at": null          // fecha ISO "YYYY-MM-DD" o null (sin vencimiento)
}
```

El cliente ingresa el código en el formulario; `GET /api/discounts/validate` lo verifica y muestra el precio actualizado en vivo. **El descuento se re-valida y re-calcula siempre en el servidor al contratar** — el precio que envía el frontend nunca se toma como fuente de verdad.

### Monto manual (CUSTOM y productos "a cotizar")

Los productos sin `base_price` (p. ej. `CUSTOM`) piden un **monto acordado** en el formulario. Ese importe (`agreed_price`) se usa como precio base y admite código de descuento encima. El backend rechaza (`422`) contratar este tipo de producto sin un monto válido (`> 0`).

---

## Colecciones / archivos de datos

| Nombre | Dónde | Descripción |
|---|---|---|
| `products.json` | `data/` (repo) | Catálogo de servicios con precios y hitos |
| `payment_info.json` | `data/` (repo) | Datos de transferencia y cripto |
| `discount_codes.json` | `data/` (repo) | Códigos de descuento (% o fijo) |
| `clients.json` | `TX_DATA_DIR` | Datos de clientes (upsert por email) |
| `engagements.json` | `TX_DATA_DIR` | Contratos firmados + metadata NDA |
| `payments.json` | `TX_DATA_DIR` | Hitos de pago por engagement |
| `sales` (Mongo) | MongoDB | Registro consultable de ventas (opcional) |

---

## Ideas de mejora

### 🔐 Seguridad
- **Autenticación admin:** Las rutas de admin (listar engagements, verificar pagos, descargar NDAs) están actualmente abiertas. Agregar JWT o API key con header `Authorization`.
- **Rate limiting:** Proteger `POST /api/engagements` contra spam con `slowapi` o un middleware de rate limit.
- **Validación de firma digital:** Guardar hash del PDF generado para poder verificar integridad posterior.

### 📬 Notificaciones
- **Webhooks:** Emitir eventos a un endpoint configurable cuando cambia el estado de un engagement o se verifica un pago.
- **Recordatorios de pago:** Cron job que detecte pagos pendientes vencidos y envíe recordatorio por email.
- **Email de confirmación de verificación:** Notificar también al cliente cuando su pago queda verificado.

### 🧾 Facturación
- **Generación de recibo en PDF:** Al verificar un pago, generar automáticamente un recibo/factura en PDF y enviarlo al cliente.
- **Integración con facturación electrónica:** Conectar con AFIP (Argentina) o SAT (México).

### 🛠️ Admin panel
- **Dashboard web:** Construir un panel simple con tabla de engagements, estado de pagos y botón de verificación.
- **Búsqueda y filtros:** Endpoint de engagements con filtros por fecha, producto, cliente y estado.

### 🔧 Código
- **Manejo de errores centralizado:** Exception handler global en FastAPI en lugar de `try/except` dispersos.
- **Tests:** Tests de integración con `pytest` + `httpx AsyncClient` sobre un `TX_DATA_DIR` temporal.
- **Logging estructurado:** Reemplazar los `print()` por un logger (`structlog` o `logging` en JSON para Render).
- **Paginación:** `GET /api/engagements` tiene `limit`; agregar `skip` para paginación real.

### ☁️ Infraestructura
- **Escalado horizontal:** Si se necesita más de una instancia, migrar la fuente de verdad de los JSON+file-lock a una base de datos real (p. ej. promover Mongo a store principal). El diseño actual asume 1 worker / 1 instancia.
- **Backups del volumen:** Snapshot periódico del disco persistente (`TX_DATA_DIR`), además del backup de PDFs/comprobantes en R2.
- **Health check real:** `/health` devuelve `ok` siempre; podría verificar acceso de escritura a `TX_DATA_DIR`.
