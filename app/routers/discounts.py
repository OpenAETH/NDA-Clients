from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.core import store, discounts

router = APIRouter()


@router.get("/validate")
async def validate_discount(
    code: str = Query(..., description="Código de descuento a validar"),
    product_code: str = Query(..., description="Código del producto seleccionado"),
    amount: Optional[float] = Query(
        None, description="Monto base (requerido para CUSTOM o productos a cotizar)"
    ),
    lang: str = Query(store.DEFAULT_LANG, description="UI language: en | es"),
):
    """
    Valida un código de descuento contra un producto y devuelve el precio
    actualizado. Usado por el frontend para previsualizar en vivo.

    El precio base sale del catálogo; para CUSTOM (o productos sin precio)
    se toma de `amount`. El cálculo definitivo se re-hace al contratar.
    """
    product = store.products.find_one({"code": product_code.upper(), "is_active": True})
    if not product:
        raise HTTPException(404, f"Producto '{product_code}' no encontrado.")

    base_price = product.get("base_price")
    if base_price is None and amount is not None:
        base_price = amount

    try:
        result = discounts.quote(base_price, product_code, code, lang=lang)
    except discounts.DiscountError as e:
        raise HTTPException(422, str(e))

    return {
        "valid":        True,
        "code":         result["discount"]["code"],
        "type":         result["discount"]["type"],
        "value":        result["discount"]["value"],
        "description":  result["discount"]["description"],
        "base_price":   result["base_price"],
        "final_price":  result["final_price"],
        "amount_saved": result["amount_saved"],
    }
