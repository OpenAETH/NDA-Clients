# Agraound Backend — Guía de Deploy y Configuración

## Stack
- **API**: FastAPI + Uvicorn
- **DB**: MongoDB (Atlas recomendado)
- **Email**: Resend
- **PDF**: ReportLab (server-side)
- **Deploy**: Render.com

---

## 1. Configurar MongoDB Atlas (gratis)

1. Ir a https://cloud.mongodb.com → crear cuenta
2. Crear un **Cluster M0** (free tier)
3. En **Database Access** → crear usuario con contraseña
4. En **Network Access** → agregar IP `0.0.0.0/0` (Render usa IPs dinámicas)
5. En **Connect** → copiar la connection string:
   ```
   mongodb+srv://user:password@cluster.mongodb.net
   ```
6. Pegarla en `MONGODB_URI` del `.env`

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
3. Conectar el repo → Render detecta `render.yaml` automáticamente
4. Completar las variables marcadas como `sync: false` en el dashboard:
   - `MONGODB_URI`
   - `RESEND_API_KEY`
   - `EMAIL_FROM`
   - `EMAIL_PROVIDER_TO`
5. **Deploy** → esperar ~2 min

### Opción B — Manual

1. **New** → **Web Service** → conectar repo
2. Runtime: **Python 3**
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Agregar todas las variables de entorno del `.env.example`

---

## 4. Correr el seed de MongoDB

**Primera vez** (local o en Render shell):

```bash
# Local
cp .env.example .env
# editar .env con tus valores reales
python seed_mongo.py

# En Render: ir a tu servicio → Shell → ejecutar:
python seed_mongo.py
```

Esto crea los índices y carga DAE, CAE y CUSTOM en la colección `products`.

---

## 5. Conectar el formulario HTML al backend

Abrir `nda_form_agraound.html` y hacer **dos cambios**:

### 5a. Cargar productos desde la API (reemplazar el array estático)

Buscar el bloque que empieza con `const PRODUCTS = [` y reemplazarlo:

```javascript
// Reemplazar el array estático PRODUCTS con:
let PRODUCTS = [];

async function loadProducts() {
  const res = await fetch("https://tu-backend.onrender.com/api/products");
  PRODUCTS = await res.json();
  renderProducts();
  // Opcional: preseleccionar el primero
}
```

Y en `DOMContentLoaded` cambiar `renderProducts()` por `loadProducts()`.

### 5b. Enviar el formulario al backend en lugar de generar PDF local

En la función `submitForm()`, después de la validación, reemplazar la generación local de PDF por:

```javascript
async function submitForm() {
  const errors = validateForm();
  if (errors.length > 0) { /* mostrar errores */ return; }

  const sigUrl = getSignatureDataURL();

  const payload = {
    client: {
      full_name:    document.getElementById("client-name").value,
      company:      document.getElementById("client-company").value,
      email:        document.getElementById("client-email").value,
      phone:        document.getElementById("client-phone").value,
      country:      document.getElementById("client-country").value,
    },
    product_code:        selectedProduct.id,
    payment_mode:        paymentMode,
    custom_description:  document.getElementById("custom-desc").value || null,
    signature_type:      sigMode,
    signature_data:      sigUrl,
    user_agent:          navigator.userAgent,
  };

  const res = await fetch("https://tu-backend.onrender.com/api/engagements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json();
    showError(err.detail || "Error al enviar. Intentá de nuevo.");
    return;
  }

  const data = await res.json();
  engagementId = data.engagement_id;

  // Subir comprobante si fue adjuntado
  if (uploadedFile) {
    const fd = new FormData();
    fd.append("file", uploadedFile);
    fd.append("milestone_n", "1");
    fd.append("method", activePayTab);
    await fetch(`https://tu-backend.onrender.com/api/payments/${engagementId}/receipt`, {
      method: "POST",
      body: fd,
    });
  }

  // Mostrar pantalla de éxito
  document.getElementById("main-form").style.display = "none";
  document.getElementById("success-screen").style.display = "block";
}
```

---

## 6. Estructura del proyecto

```
agraound-backend/
├── app/
│   ├── main.py                  # FastAPI app — sirve API + frontend estático
│   ├── core/
│   │   ├── config.py            # Settings desde .env
│   │   └── database.py          # Conexión Motor/MongoDB
│   ├── models/
│   │   └── schemas.py           # Pydantic models
│   ├── routers/
│   │   ├── products.py          # GET /api/products
│   │   ├── engagements.py       # POST /api/engagements (firma NDA)
│   │   └── payments.py          # POST /api/payments/:id/receipt
│   └── services/
│       ├── email_service.py     # Resend — emails
│       ├── pdf_service.py       # ReportLab — PDF firmado
│       └── storage_service.py   # Cloudflare R2 — archivos
├── static/
│   └── index.html               # Formulario NDA (frontend integrado)
├── seed_mongo.py                # Carga inicial de productos
├── requirements.txt
├── render.yaml
├── R2_SETUP.md
└── .env.example
```

### Flujo completo en producción

```
Cliente abre https://tu-backend.onrender.com/
    ↓
static/index.html  (servido por FastAPI StaticFiles)
    ↓
fetch GET /api/products  →  carga catálogo desde MongoDB
    ↓
Cliente completa form + firma + adjunta comprobante
    ↓
POST /api/engagements  →  crea client + engagement en MongoDB
                       →  genera PDF (ReportLab)
                       →  sube PDF a R2 (backup)
                       →  envía PDF por email al cliente (Resend)
                       →  notifica al proveedor (Resend)
    ↓
POST /api/payments/:id/receipt  →  sube comprobante a R2
                                →  notifica al proveedor (Resend)
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
| POST | `/api/engagements` | **Firma NDA** — genera PDF + envía emails |
| GET | `/api/engagements` | Listar engagements (admin) |
| GET | `/api/engagements/{id}` | Detalle de un engagement |
| PATCH | `/api/engagements/{id}/status` | Cambiar estado |
| POST | `/api/payments/{id}/receipt` | **Subir comprobante de pago** |
| GET | `/api/payments/{id}` | Ver pagos de un engagement |
| PATCH | `/api/payments/{id}/{n}/verify` | Verificar/rechazar pago (admin) |
| GET | `/health` | Health check |

Documentación interactiva: `https://tu-backend.onrender.com/docs`

---

## 8. Agregar / modificar productos

### Opción A — Via API (POST)
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

### Opción B — Editar `seed_mongo.py` y volver a correrlo
El script usa `upsert`, así que actualiza si ya existe.

---

## 9. Notas de producción

- **Archivos subidos**: Render tiene filesystem efímero. Para persistencia real, integrar Cloudflare R2 o AWS S3 — reemplazar el `open()` en `payments.py` con un `boto3.upload_fileobj()`.
- **CORS**: En `main.py`, cambiar `allow_origins=["*"]` por el dominio exacto del formulario.
- **Autenticación admin**: Los endpoints de admin (listar engagements, verificar pagos) no tienen auth todavía. Agregar un middleware de API key o JWT antes de exponer en producción.
- **Logs**: Render muestra los logs en tiempo real desde el dashboard → tu servicio → **Logs**.
