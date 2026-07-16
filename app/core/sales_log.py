"""
sales_log.py — Registro de ventas en MongoDB (best-effort)

MongoDB se usa EXCLUSIVAMENTE como registro (ledger) consultable de ventas.
NO es la fuente de verdad operativa: esa es el JSON en el volumen persistente
(ver store.py). Por eso todas las operaciones acá son best-effort:

  • Si MONGODB_URI no está configurado, todo es no-op silencioso.
  • Si Mongo está caído o falla, se loguea y se sigue — nunca bloquea ni
    revierte la firma de una venta ni la verificación de un pago.

Colección: `sales` — un documento por engagement (venta), con el estado del
pago inicial y el total. Se identifica por `engagement_id`.
"""

from typing import Optional

import certifi
import motor.motor_asyncio
from pymongo.server_api import ServerApi

from app.core.config import settings

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None


def _get_db():
    """Cliente lazy singleton. Devuelve None si Mongo no está configurado."""
    global _client
    if not settings.mongo_enabled:
        return None
    if _client is None:
        _client = motor.motor_asyncio.AsyncIOMotorClient(
            settings.MONGODB_URI,
            server_api=ServerApi("1"),
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5000,
        )
    return _client[settings.MONGODB_DB]


async def record_sale(sale: dict) -> None:
    """
    Registra (o actualiza) una venta en el ledger. Idempotente por
    `engagement_id`. Best-effort: cualquier error se loguea y se ignora.
    """
    db = _get_db()
    if db is None:
        return
    try:
        await db.sales.update_one(
            {"engagement_id": sale["engagement_id"]},
            {"$set": sale},
            upsert=True,
        )
        print(f"[SALES] Venta registrada en Mongo: {sale['engagement_id']}")
    except Exception as e:
        print(f"[SALES] No se pudo registrar la venta en Mongo (no-fatal): {e}")


async def update_sale_status(engagement_id: str, changes: dict) -> None:
    """Actualiza campos del registro de venta. Best-effort."""
    db = _get_db()
    if db is None:
        return
    try:
        await db.sales.update_one(
            {"engagement_id": engagement_id},
            {"$set": changes},
        )
    except Exception as e:
        print(f"[SALES] No se pudo actualizar la venta en Mongo (no-fatal): {e}")


def close():
    """Cierra el cliente Mongo si estaba abierto."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
