"""
seed_mongo.py — Agraound / AETHERYON Systems
Crea índices y carga el catálogo inicial de productos.

Uso:
    python seed_mongo.py

Requiere MONGODB_URI y MONGODB_DB en .env o en el entorno.
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGODB_DB",  "agraound")

# ═══════════════════════════════════════════════════════════════
# CATÁLOGO DE PRODUCTOS — editá aquí para agregar o modificar
# ═══════════════════════════════════════════════════════════════
PRODUCTS = [
    {
        "code":         "DAE",
        "name":         "DAE",
        "full_name":    "Data Audit & Evaluation",
        "description":  "Auditoría y evaluación de datos, sistemas y código existente.",
        "base_price":   3500.00,
        "discount_pct": 0,
        "badge_label":  "Estándar",
        "badge_type":   "std",
        "is_active":    True,
        "sort_order":   1,
        "milestones": [
            {"milestone_n": 1, "label": "Inicio + firma NDA",         "pct": 40},
            {"milestone_n": 2, "label": "Entrega de informe parcial", "pct": 30},
            {"milestone_n": 3, "label": "Entrega final + cierre",     "pct": 30},
        ],
    },
    {
        "code":         "CAE",
        "name":         "CAE",
        "full_name":    "Code & Architecture Engineering",
        "description":  "Desarrollo de API + Frontend HTML con deploy en producción.",
        "base_price":   8000.00,
        "discount_pct": 10,
        "badge_label":  "Premium",
        "badge_type":   "prem",
        "is_active":    True,
        "sort_order":   2,
        "milestones": [
            {"milestone_n": 1, "label": "Inicio + firma NDA",      "pct": 40},
            {"milestone_n": 2, "label": "API operativa (hito 2)",  "pct": 30},
            {"milestone_n": 3, "label": "Frontend + deploy final", "pct": 30},
        ],
    },
    {
        "code":         "CUSTOM",
        "name":         "Custom",
        "full_name":    "Proyecto personalizado",
        "description":  "Definimos juntos el alcance, tecnologías y precio.",
        "base_price":   None,
        "discount_pct": 0,
        "badge_label":  "A medida",
        "badge_type":   "custom",
        "is_active":    True,
        "sort_order":   3,
        "milestones": [
            {"milestone_n": 1, "label": "Inicio + firma NDA", "pct": 40},
            {"milestone_n": 2, "label": "Hito intermedio",    "pct": 30},
            {"milestone_n": 3, "label": "Entrega final",      "pct": 30},
        ],
    },
]


async def seed():
    print(f"[SEED] Connecting to Atlas...")
    client = AsyncIOMotorClient(
        MONGO_URI,
        server_api=ServerApi("1"),
        tls=True,
        tlsAllowInvalidCertificates=False,
    )

    # Verify connection
    try:
        await client.admin.command("ping")
        print(f"[SEED] Connected — db: {MONGO_DB}")
    except Exception as e:
        print(f"[SEED] Connection failed: {e}")
        client.close()
        return

    db = client[MONGO_DB]

    # ── Índices ──────────────────────────────────────────────────
    await db.products.create_index("code",       unique=True)
    await db.products.create_index("is_active")
    await db.clients.create_index("email",       unique=True)
    await db.engagements.create_index("client_id")
    await db.engagements.create_index("status")
    await db.engagements.create_index("product_code")
    await db.engagements.create_index("created_at")
    await db.engagements.create_index("client_email")
    await db.payments.create_index(
        [("engagement_id", 1), ("milestone_n", 1)], unique=True
    )
    await db.payments.create_index("status")
    print("[SEED] Indexes created")

    # ── Productos ────────────────────────────────────────────────
    for p in PRODUCTS:
        result = await db.products.update_one(
            {"code": p["code"]},
            {"$set": p},
            upsert=True,
        )
        action = "inserted" if result.upserted_id else "updated"
        price  = f"${p['base_price']:,.0f}" if p["base_price"] else "a cotizar"
        print(f"[SEED] {p['code']:8s} {action:8s}  {price}")

    count = await db.products.count_documents({})
    print(f"\n[SEED] Done — {count} products in catalog")
    print(f"[SEED] Collections: {await db.list_collection_names()}")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
