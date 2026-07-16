from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
import os
from app.core import sales_log
from app.routers import products, engagements, payments, payment_info, discounts

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # El cliente Mongo del registro de ventas es lazy (se conecta al primer
    # uso). Acá solo lo cerramos al apagar. La persistencia operativa vive en
    # archivos JSON, sin conexión que abrir al arrancar.
    yield
    sales_log.close()


app = FastAPI(
    title="Agraound / AETHERYON — NDA & Engagement API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────
# Frontend and API share the same origin on Render.
# Keep * for local dev; restrict to your domain in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes (registered first — take priority over static) ─────
app.include_router(products.router,     prefix="/api/products",     tags=["Products"])
app.include_router(engagements.router,  prefix="/api/engagements",  tags=["Engagements"])
app.include_router(payments.router,     prefix="/api/payments",     tags=["Payments"])
app.include_router(payment_info.router, prefix="/api/payment-info", tags=["Payment Info"])
app.include_router(discounts.router,    prefix="/api/discounts",    tags=["Discounts"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


# ── Static frontend ───────────────────────────────────────────────
# static/index.html  →  served at /
# All /api/* routes above take priority because they are registered first.
if STATIC_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "API running. Add a static/ directory to serve the frontend.", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
