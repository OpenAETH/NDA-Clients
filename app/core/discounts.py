"""
discounts.py — Códigos de descuento (fuente: data/discount_codes.json)

Lógica única de resolución y cálculo, usada tanto por el endpoint de
validación en vivo (/api/discounts/{code}) como por la creación de engagements.
El cálculo del precio SIEMPRE se re-hace en el servidor: el frontend solo
muestra una previsualización, nunca es la fuente de verdad.

Tipos de código:
  • percent : descuenta `value`% sobre el precio base.
  • fixed   : descuenta `value` USD (no baja de 0).

Restricciones opcionales por código:
  • products   : lista de códigos de producto habilitados ([] o ausente = todos).
  • enabled    : false lo desactiva.
  • expires_at : fecha ISO (YYYY-MM-DD o datetime). Vencido = inválido.
"""

from datetime import date, datetime
from typing import Optional

from app.core import store


class DiscountError(Exception):
    """El código no existe, está deshabilitado, venció o no aplica al producto."""


def _parse_expiry(raw) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def resolve_code(code: str, product_code: str, today: Optional[date] = None) -> dict:
    """
    Devuelve el código de descuento normalizado si es válido para `product_code`.
    Lanza DiscountError con un mensaje apto para el usuario si no aplica.
    """
    if not code or not code.strip():
        raise DiscountError("Código vacío.")

    wanted = code.strip().upper()
    catalog = store.load_document("discount_codes").get("codes", [])
    match = next((c for c in catalog if str(c.get("code", "")).upper() == wanted), None)

    if match is None:
        raise DiscountError("El código no existe.")
    if not match.get("enabled", True):
        raise DiscountError("El código no está disponible.")

    expiry = _parse_expiry(match.get("expires_at"))
    if expiry and (today or date.today()) > expiry:
        raise DiscountError("El código está vencido.")

    products = match.get("products") or []
    if products and product_code.upper() not in [p.upper() for p in products]:
        raise DiscountError("El código no aplica a este producto.")

    dtype = match.get("type")
    if dtype not in ("percent", "fixed"):
        raise DiscountError("El código tiene una configuración inválida.")

    return {
        "code":        match["code"].upper(),
        "type":        dtype,
        "value":       float(match.get("value", 0)),
        "description": match.get("description", ""),
    }


def apply_discount(base_price: float, disc: dict) -> float:
    """Aplica un descuento ya resuelto a un precio base. Nunca baja de 0."""
    if disc["type"] == "percent":
        final = base_price * (1 - disc["value"] / 100)
    else:  # fixed
        final = base_price - disc["value"]
    return round(max(final, 0.0), 2)


def quote(base_price: Optional[float], product_code: str,
          code: Optional[str] = None, today: Optional[date] = None) -> dict:
    """
    Cotiza un precio: resuelve el código (si hay) y calcula el final.
    Devuelve un dict con base_price, final_price, discount info y ahorro.
    Lanza DiscountError si el código es inválido para el producto.

    Si base_price es None (producto "a cotizar" sin monto), no se puede
    aplicar un descuento porcentual/fijo — se devuelve sin descuento.
    """
    if not code or not code.strip():
        return {
            "base_price":     base_price,
            "final_price":    base_price,
            "discount":       None,
            "amount_saved":   0.0,
        }

    disc = resolve_code(code, product_code, today)

    if base_price is None:
        raise DiscountError("Indicá primero el monto para aplicar el código.")

    final_price = apply_discount(base_price, disc)
    return {
        "base_price":   round(base_price, 2),
        "final_price":  final_price,
        "discount":     disc,
        "amount_saved": round(base_price - final_price, 2),
    }
