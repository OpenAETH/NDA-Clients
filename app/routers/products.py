from fastapi import APIRouter, HTTPException
from typing import List

from app.core import store
from app.models.schemas import ProductCreate, ProductOut

router = APIRouter()


@router.get("", response_model=List[ProductOut])
async def list_products():
    """Return active products ordered by sort_order. Used by the frontend form."""
    return store.products.find({"is_active": True}, sort=("sort_order", 1))


@router.get("/{code}", response_model=ProductOut)
async def get_product(code: str):
    p = store.products.find_one({"code": code.upper(), "is_active": True})
    if not p:
        raise HTTPException(404, f"Product '{code}' not found")
    return p


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(payload: ProductCreate):
    """Admin endpoint to add a new product or customization to the catalog."""
    if store.products.find_one({"code": payload.code.upper()}):
        raise HTTPException(409, f"Product code '{payload.code}' already exists")
    doc = payload.model_dump()
    doc["code"] = doc["code"].upper()
    return store.products.insert(doc)


@router.put("/{code}", response_model=ProductOut)
async def update_product(code: str, payload: ProductCreate):
    """Update price, description, milestones, etc. for an existing product."""
    doc = payload.model_dump()
    doc["code"] = doc["code"].upper()
    result = store.products.update_one({"code": code.upper()}, doc)
    if not result:
        raise HTTPException(404, f"Product '{code}' not found")
    return result


@router.delete("/{code}", status_code=204)
async def deactivate_product(code: str):
    """Soft-delete: marks product as inactive (preserves historical engagement data)."""
    result = store.products.update_one({"code": code.upper()}, {"is_active": False})
    if result is None:
        raise HTTPException(404, f"Product '{code}' not found")
