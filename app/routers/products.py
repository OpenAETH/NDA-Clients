from fastapi import APIRouter, HTTPException
from typing import List
from bson import ObjectId

from app.core.database import get_db
from app.models.schemas import ProductCreate, ProductOut

router = APIRouter()


def _serialize(doc) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("", response_model=List[ProductOut])
async def list_products():
    """Return active products ordered by sort_order. Used by the frontend form."""
    db = get_db()
    cursor = db.products.find({"is_active": True}).sort("sort_order", 1)
    return [_serialize(p) async for p in cursor]


@router.get("/{code}", response_model=ProductOut)
async def get_product(code: str):
    db = get_db()
    p = await db.products.find_one({"code": code.upper(), "is_active": True})
    if not p:
        raise HTTPException(404, f"Product '{code}' not found")
    return _serialize(p)


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(payload: ProductCreate):
    """Admin endpoint to add a new product or customization to the catalog."""
    db = get_db()
    existing = await db.products.find_one({"code": payload.code.upper()})
    if existing:
        raise HTTPException(409, f"Product code '{payload.code}' already exists")
    doc = payload.model_dump()
    doc["code"] = doc["code"].upper()
    result = await db.products.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    return doc


@router.put("/{code}", response_model=ProductOut)
async def update_product(code: str, payload: ProductCreate):
    """Update price, description, milestones, etc. for an existing product."""
    db = get_db()
    doc = payload.model_dump()
    result = await db.products.find_one_and_update(
        {"code": code.upper()},
        {"$set": doc},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, f"Product '{code}' not found")
    return _serialize(result)


@router.delete("/{code}", status_code=204)
async def deactivate_product(code: str):
    """Soft-delete: marks product as inactive (preserves historical engagement data)."""
    db = get_db()
    result = await db.products.update_one(
        {"code": code.upper()},
        {"$set": {"is_active": False}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, f"Product '{code}' not found")
