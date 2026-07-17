from fastapi import APIRouter, HTTPException, Query

from app.services import rates_service

router = APIRouter()


@router.get("")
async def get_conversion(
    amount: float = Query(
        ..., ge=0, description="Monto en USD (moneda base) a convertir"
    ),
):
    """
    Convierte un monto en USD a EUR, ARS y cripto (BTC/ETH/USDT/USDC).

    Las tasas se obtienen de proveedores externos con caché de 5 min y se
    reutiliza el último valor válido si un proveedor no responde. La conversión
    es solo para visualización; el precio operativo siempre queda en USD.
    """
    try:
        return await rates_service.convert(amount)
    except Exception as e:  # noqa: BLE001 — nunca romper el flujo de pago por FX
        raise HTTPException(
            503, f"No se pudieron obtener las cotizaciones: {e}"
        )
