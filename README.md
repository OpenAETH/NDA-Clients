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
| Cotizaciones | Coinbase + CoinGecko (cripto) · open.er-api (fiat) — keyless, con caché |
| Idiomas | Bilingüe **inglés (por defecto) / español** — datos, API, PDF, email y frontend |
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
│   ├── rates.py         # Conversión de moneda del total (USD → fiat/cripto)
│   ├── engagements.py   # Firma NDA, generación PDF, emails
│   └── payments.py      # Upload comprobantes, verificación hitos
├── services/
│   ├── pdf_service.py   # Generación NDA en PDF con ReportLab (detalles del acuerdo + medio de pago)
│   ├── email_service.py # Envío de emails via Resend
│   ├── storage_service.py # Upload/presigned URLs en R2
│   └── rates_service.py # Cotizaciones fiat/cripto con caché (5 min) + fallback
└── main.py              # App FastAPI, CORS, lifespan, static
data/
├── products.json        # Catálogo (versionado, editable)
├── payment_info.json    # Datos de pago (versionado, editable)
└── discount_codes.json  # Códigos de descuento (versionado, editable)
static/
├── index.html           # Frontend embebido (formulario de 5 pasos)
└── assets/              # Imágenes QR de las wallets cripto (por red)
```

> Los datos transaccionales (`clients/engagements/payments.json`) se crean en `TX_DATA_DIR` en runtime — no están en el repo.

---

## Flujo principal

El formulario (`static/index.html`) tiene un **toggle de idioma EN/ES** en el header (inglés por defecto, ver [Idiomas (i18n)](#idiomas-i18n)) y **5 pasos**:

1. **Datos del cliente**
2. **Selección de producto / servicio**
3. **Activación del proyecto** — modalidad de pago (hitos/anticipado), método de pago (ARS/USD/EUR/cripto) con datos copiables, resumen de pago (valor del proyecto vs. pago de hoy) y **carga del comprobante**.
4. **Firma del NDA** — el documento incluye **todos los detalles del acuerdo** (producto, montos por hito con su "cuándo", método y medio de pago, token/red de cripto) + la firma digital, integrados en un mismo paso.
5. **Aceptar y enviar**

> **El comprobante es obligatorio y habilita la firma:** el botón "Continuar a la firma del NDA" queda deshabilitado hasta cargar un archivo válido (validación de tipo/tamaño en el cliente, espejo del backend). La subida real al backend ocurre en el envío, con el `engagement_id` devuelto.

```
Cliente llena formulario (pasos 1–3, incluye comprobante)
        ↓
Firma el NDA (paso 4, con todos los detalles del acuerdo)
        ↓
POST /api/engagements
        ↓
  ┌───────────────────────────────────────┐
  │ 1. Resuelve producto del catálogo (JSON)│
  │ 2. Calcula precio: base/monto manual +  │
  │    código de descuento (re-validado)   │
  │ 3. Upsert cliente (JSON, file-lock)    │
  │ 4. Crea engagement + pagos (JSON)      │
  │    (guarda payment_details elegido)    │
  │ 5. Registra la venta en Mongo (opcional)│
  │ 6. Genera PDF del NDA (con detalles     │
  │    del acuerdo + medio de pago)        │
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
| GET | `/api/products?lang=en\|es` | Listar productos activos (localizados) |
| GET | `/api/products/{code}?lang=en\|es` | Detalle de un producto (localizado) |
| POST | `/api/products` | Crear producto (admin) |
| PUT | `/api/products/{code}` | Actualizar producto (admin) |
| DELETE | `/api/products/{code}` | Desactivar producto (soft-delete) |
| GET | `/api/payment-info?lang=en\|es` | Datos de pago habilitados (localizados) |
| GET | `/api/discounts/validate?…&lang=en\|es` | Validar código y previsualizar precio (localizado) |
| GET | `/api/rates?amount=` | Convertir un monto USD a EUR/ARS/cripto (solo visualización) |

> **`lang`** acepta `en` (por defecto) o `es`. Devuelve los textos del catálogo en ese idioma; los datos neutros (precios, alias, IBAN, direcciones cripto) no cambian. Ver [Idiomas (i18n)](#idiomas-i18n).

### Engagements
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/engagements` | Firmar NDA + crear engagement |
| GET | `/api/engagements` | Listar engagements (admin) |
| GET | `/api/engagements/{id}` | Detalle de un engagement (admin) |
| PATCH | `/api/engagements/{id}/status` | Actualizar estado (admin) |
| GET | `/api/engagements/{id}/nda/download` | URL presignada del PDF (admin) |

`POST /api/engagements` acepta un campo opcional **`payment_details`** con el método/medio de pago elegido por el cliente (que el backend no conoce de otro modo). Se guarda en el engagement y se incrusta en el PDF firmado bajo "Medio de pago acordado":

```json
{
  "payment_details": {
    "method_key": "crypto",
    "method_label": "Cripto",
    "currency": "CRYPTO",
    "token": "USDT",
    "network": "Tron (TRC20)",
    "address": "THH5PJ…",
    "fields": null
  }
}
```

Para métodos fiat, `token/network/address` van en `null` y los datos de la transferencia (Alias, CVU, IBAN…) llegan en `fields: [{label, value}]`.

`POST /api/engagements` también acepta **`lang`** (`"en"` por defecto, o `"es"`): determina el idioma del **PDF firmado** y del **email al cliente**. El frontend lo envía según el toggle activo. Ver [Idiomas (i18n)](#idiomas-i18n).

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
- **Datos de pago** → `data/payment_info.json` (ARS, USD, EUR, cripto). Cada método es una pestaña del formulario; `enabled: false` lo oculta. Los métodos fiat usan `fields` (los campos sin `value` no se muestran); el método cripto usa `tokens → networks` con QR, dirección y advertencia por red (ver [Wallets cripto](#wallets-cripto-token--red--qr--dirección)).
- **Códigos de descuento** → `data/discount_codes.json` (ver abajo).

> **Textos bilingües:** los campos traducibles del catálogo se guardan como objetos `{"en": "…", "es": "…"}` y la API los devuelve ya resueltos según `?lang=`. Los datos neutros (precios, alias, IBAN, direcciones, QR, nombres de red) se dejan como valor plano. Ver [Idiomas (i18n)](#idiomas-i18n).

### Códigos de descuento

Se agregan/editan en `data/discount_codes.json`. Cada código:

```json
{
  "code": "LANZAMIENTO15",
  "type": "percent",          // "percent" (% sobre el precio) o "fixed" (USD a restar)
  "value": 15,
  "description": {            // texto bilingüe (se devuelve según ?lang=)
    "en": "15% launch discount",
    "es": "15% de descuento de lanzamiento"
  },
  "products": [],             // [] o ausente = todos; ["DAE"] = solo ese producto
  "enabled": true,            // false lo desactiva
  "expires_at": null          // fecha ISO "YYYY-MM-DD" o null (sin vencimiento)
}
```

El cliente ingresa el código en el formulario; `GET /api/discounts/validate` lo verifica y muestra el precio actualizado en vivo. **El descuento se re-valida y re-calcula siempre en el servidor al contratar** — el precio que envía el frontend nunca se toma como fuente de verdad.

### Monto manual (CUSTOM y productos "a cotizar")

Los productos sin `base_price` (p. ej. `CUSTOM`) piden un **monto acordado** en el formulario. Ese importe (`agreed_price`) se usa como precio base y admite código de descuento encima. El backend rechaza (`422`) contratar este tipo de producto sin un monto válido (`> 0`).

---

## Conversión de moneda (solo visualización)

El total del formulario se calcula **siempre en USD** (moneda base). La conversión a otras monedas es únicamente informativa: se muestra el equivalente según el método de pago que el cliente elija, sin alterar el precio operativo ni lo que se guarda o se firma en el PDF (que quedan en USD).

**Cómo funciona:**

1. El frontend detecta el cambio de método de pago en `#pm-tabs` y pide `GET /api/rates?amount=<total_usd>`.
2. El backend (`rates_service.py`) obtiene las tasas de proveedores externos **sin API key**:
   - **Fiat (EUR, ARS)** → [open.er-api.com](https://open.er-api.com).
   - **Cripto (BTC, ETH)** → **Coinbase** como primario y **CoinGecko** como fallback (Coinbase es estable y evita el `429` del tier gratuito de CoinGecko).
   - **USDT/USDC** → stablecoins ancladas 1:1 al USD; no se consultan.
3. Las tasas se **cachean 5 min** en memoria. Ante fallo de un proveedor se reutiliza el último valor válido (y se marca `stale`), de modo que el pago nunca se bloquea por FX.
4. El frontend actualiza el **resumen de pago** (`div.pay-summary`) en vivo: valor del proyecto, pago de hoy convertido, referencia en USD, la cotización usada (`1 BTC = 63.100,13 USD`) y la antigüedad del dato (`Cotización actualizada hace 2 min`).

**Pago de hoy vs. total:** el resumen separa el **valor del proyecto** (total, siempre en USD) del **pago de hoy** (lo que se abona al firmar). En modo **hitos**, el pago de hoy es el **primer hito** (p. ej. 40% "Al firmar"), y el NDA detalla los hitos restantes con su momento (30% "Al avanzar", 30% "Al finalizar") sin ambigüedad. En modo **anticipado**, el pago de hoy es el total. La conversión a la moneda elegida se escala linealmente desde la conversión cacheada del total (la conversión es `monto × tasa`), sin re-consultar el API.

**Método cripto:** al elegirlo, el formulario pide **qué token** se usará. Los tokens se derivan dinámicamente de `payment_info.json` (no hardcodeados) y el resumen de pago muestra solo el activo seleccionado.

### Wallets cripto: token → red → QR + dirección

El método cripto en `payment_info.json` usa un modelo **`tokens → networks`**: cada token declara las redes por las que se acepta, y cada red trae su dirección, su imagen QR y una advertencia de red. El flujo en el formulario es:

1. El cliente elige el **token** (BTC, ETH, USDT, USDC).
2. Elige la **red**. Si el token tiene una sola red, se **auto-selecciona** (p. ej. BTC → BNB Chain).
3. Se muestra el **QR** de esa red, la **dirección copiable** (botón "Copiar", con fallback para contextos sin Clipboard API) y una **advertencia contextual** para evitar pérdida de fondos por red incorrecta.

Redes soportadas actualmente:

| Token | Redes | QR (`static/assets/`) |
|---|---|---|
| BTC | BNB Chain (BEP20) | `1000001292.jpg` |
| ETH | BNB Chain (BEP20), Optimism | `1000001292.jpg`, `1000001298.jpg` |
| USDT | BNB Chain (BEP20), Tron (TRC20) | `1000001292.jpg`, `1000001294.jpg` |
| USDC | BNB Chain (BEP20), Solana | `1000001292.jpg`, `1000001296.jpg` |

Estructura de cada token en `payment_info.json`:

```json
{
  "symbol": "ETH",
  "networks": [
    {
      "name": "Optimism (Ethereum L2)",
      "address": "0x2e3c…",
      "qr": "assets/1000001298.jpg",
      "warning": {
        "en": "Send ETH only via the Optimism (Ethereum L2) network. Using the wrong network may result in loss of funds.",
        "es": "Enviá únicamente ETH mediante la red Optimism (L2 de Ethereum). El uso de una red incorrecta puede provocar la pérdida de los fondos."
      }
    }
  ]
}
```

> `name`, `address` y `qr` son neutros al idioma; solo `warning` es bilingüe (`{en, es}`).

> **Agregar un token/red:** sumá el objeto a `tokens[].networks` en `payment_info.json` (con `address`, `qr` y `warning`) y dejá la imagen QR en `static/assets/`. El frontend arma el selector y el bloque de wallet solo. Para que además aparezca su conversión, el símbolo debe existir en el backend (`CRYPTO_IDS` o `STABLECOINS`).

**Ejemplo de respuesta de `/api/rates?amount=2500`:**

```json
{
  "base_currency": "USD",
  "base_amount": 2500.0,
  "conversions": {
    "USD": 2500.0,
    "EUR": 2143.52,
    "ARS": 3482100.0,
    "CRYPTO": { "BTC": 0.021534, "ETH": 0.842311, "USDT": 2500.0, "USDC": 2500.0 }
  },
  "rates_used": {
    "EUR":  { "from": "USD", "to": "EUR", "value": 0.857408 },
    "ARS":  { "from": "USD", "to": "ARS", "value": 1392.84 },
    "BTC":  { "from": "BTC", "to": "USD", "value": 118500.0 }
  },
  "age_seconds": 42,
  "stale": false
}
```

> **Extensible:** para agregar una moneda fiat, sumá su símbolo a `FIAT_SYMBOLS`; para una cripto, a `CRYPTO_IDS` (con su id de CoinGecko). El frontend la formatea automáticamente vía `CURRENCY_FMT`.

---

## Idiomas (i18n)

La aplicación es **bilingüe**: **inglés por defecto** y **español** opcional, seleccionable con un toggle **EN/ES** en el header del formulario. La preferencia se guarda en `localStorage` (`nda_lang`). El idioma atraviesa las cinco capas:

| Capa | Cómo se traduce |
|---|---|
| **Datos** (`data/*.json`) | Los campos traducibles se guardan como `{"en": "…", "es": "…"}`. Los neutros (precios, alias, CVU/IBAN, direcciones, QR, nombres de red, símbolos de token) quedan como valor plano. |
| **API** | `store.localize(value, lang)` colapsa recursivamente los objetos `{en,es}` al idioma pedido. Los endpoints `products`, `payment-info` y `discounts/validate` aceptan `?lang=en\|es`. |
| **PDF** | `pdf_service.py` tiene un diccionario `PDF_STRINGS[lang]` para el texto fijo (cláusulas, encabezados, "cuándo" de cada hito); el contenido dinámico llega ya localizado desde el router. |
| **Email** | El email **al cliente** (`CLIENT_EMAIL_STRINGS`) sale en su idioma. El aviso interno **al proveedor** queda en español (panel interno). |
| **Frontend** | Diccionario `I18N` con `en`/`es` (a paridad de claves), helper `t(key, vars)` con interpolación `{var}`, atributos `data-i18n` / `data-i18n-ph`. Al cambiar de idioma se re-consultan catálogo y datos de pago con el nuevo `?lang=`, preservando la selección del usuario. |

**Fallback:** `localize()` usa `en → es → cualquier idioma disponible`; `t()` cae a inglés y luego a la propia clave. `normalize_lang()` acepta variantes como `en-US` (toma el prefijo) y desconocidos caen al default.

**Coherencia legal:** el `lang` enviado en `POST /api/engagements` fija el idioma del **PDF firmado** y del **email al cliente**, de modo que el documento que el cliente firma y recibe está íntegramente en el idioma que eligió. Los montos y la moneda operativa (USD) no cambian con el idioma.

**Agregar/editar textos:**
- Catálogo → editá el objeto `{en, es}` correspondiente en `data/*.json`.
- Textos de UI del frontend → editá `I18N.en` **y** `I18N.es` en `static/index.html` (mantené las mismas claves en ambos).
- Textos del PDF/email → `PDF_STRINGS` en `pdf_service.py` y `CLIENT_EMAIL_STRINGS` en `email_service.py`.

**Agregar un idioma nuevo:** sumá el código a `SUPPORTED_LANGS` en `store.py`, añadí la clave en cada objeto `{en, es, …}` de los JSON, y un bloque nuevo en `I18N`, `PDF_STRINGS` y `CLIENT_EMAIL_STRINGS`.

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
