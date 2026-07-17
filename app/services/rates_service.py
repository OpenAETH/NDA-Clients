"""
rates_service.py — Cotizaciones en tiempo real (fiat + cripto)

Convierte un monto en USD (moneda base de la app) a EUR, ARS, BTC y ETH.
Las conversiones son SOLO para visualización: el cálculo interno de precios
siempre permanece en USD (ver payment calculator del frontend).

Proveedores externos (sin API key, para no exponer credenciales):
  • Fiat  (EUR, ARS): https://open.er-api.com/v6/latest/USD
  • Cripto (BTC, ETH): https://api.coingecko.com/api/v3/simple/price

Diseño:
  - Caché en memoria con TTL (default 5 min) para evitar consultar a los
    proveedores en cada request y mejorar el rendimiento.
  - Manejo de errores: si un proveedor no responde, se reutiliza el último
    valor cacheado (aunque esté vencido). Si nunca hubo datos, ese tramo
    queda como None y el frontend lo muestra como no disponible.
  - Extensible: agregá símbolos a FIAT_SYMBOLS / CRYPTO_IDS y aparecen solos.

USDT/USDC se tratan como stablecoins ancladas 1:1 al USD (coherente con la
nota de pago "1 USD = 1 USDt"). No se consultan al proveedor.
"""

import time
import httpx

# ── Proveedores ───────────────────────────────────────────────────
FIAT_URL   = "https://open.er-api.com/v6/latest/USD"
CRYPTO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Símbolos fiat a extraer de la respuesta de open.er-api (tasas por 1 USD).
FIAT_SYMBOLS = ["EUR", "ARS"]

# Cripto: símbolo visible → id de CoinGecko.
CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}

# Stablecoins ancladas al USD — no requieren cotización externa.
STABLECOINS = ["USDT", "USDC"]

CACHE_TTL_SECONDS = 300  # 5 minutos

# ── Caché en memoria ──────────────────────────────────────────────
# _cache["rates"] = { "EUR": float, "ARS": float, "BTC": float, "ETH": float }
# donde cada valor es "unidades de esa moneda por 1 USD".
_cache = {"rates": {}, "fetched_at": 0.0}


async def _fetch_fiat(client: httpx.AsyncClient) -> dict:
    """Tasas USD→fiat desde open.er-api. Devuelve {} si falla."""
    try:
        resp = await client.get(FIAT_URL)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "success":
            return {}
        rates = data.get("rates", {})
        return {s: float(rates[s]) for s in FIAT_SYMBOLS if s in rates}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        print(f"[RATES] Fiat provider error: {e}")
        return {}


async def _fetch_crypto(client: httpx.AsyncClient) -> dict:
    """
    Tasas USD→cripto desde CoinGecko. El proveedor da el precio de 1 unidad
    de cripto en USD; lo invertimos a "cripto por 1 USD". Devuelve {} si falla.
    """
    try:
        ids = ",".join(CRYPTO_IDS.values())
        resp = await client.get(
            CRYPTO_URL, params={"ids": ids, "vs_currencies": "usd"}
        )
        resp.raise_for_status()
        data = resp.json()
        out = {}
        for symbol, gecko_id in CRYPTO_IDS.items():
            price_usd = data.get(gecko_id, {}).get("usd")
            if price_usd:  # precio de 1 cripto en USD, > 0
                out[symbol] = 1.0 / float(price_usd)
        return out
    except (httpx.HTTPError, ValueError, KeyError, ZeroDivisionError) as e:
        print(f"[RATES] Crypto provider error: {e}")
        return {}


async def get_rates() -> dict:
    """
    Devuelve las tasas "por 1 USD" para todos los símbolos soportados,
    usando caché con TTL. Ante fallo de un proveedor, conserva los últimos
    valores cacheados para ese tramo.
    """
    now = time.monotonic()
    if _cache["rates"] and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return _cache["rates"]

    async with httpx.AsyncClient(timeout=15) as client:
        fiat   = await _fetch_fiat(client)
        crypto = await _fetch_crypto(client)

    # Merge sobre lo previo: si un proveedor falló, retenemos su último valor.
    rates = dict(_cache["rates"])
    rates.update(fiat)
    rates.update(crypto)

    # Solo consideramos "refrescado" si obtuvimos algo nuevo; así, tras un
    # fallo total, seguimos sirviendo lo viejo sin resetear el reloj a vacío.
    if fiat or crypto:
        _cache["rates"] = rates
        _cache["fetched_at"] = now

    return rates


async def convert(amount_usd: float) -> dict:
    """
    Convierte un monto USD a todas las monedas/activos soportados.

    Estructura de salida (extensible):
        {
          "base_currency": "USD",
          "base_amount": 2500.0,
          "conversions": {
            "USD": 2500.0,
            "EUR": 2143.52,
            "ARS": 3482100.0,
            "CRYPTO": { "BTC": 0.021534, "ETH": 0.842311,
                         "USDT": 2500.0, "USDC": 2500.0 }
          },
          "stale": false          # true si se sirvieron datos cacheados vencidos
        }

    Un símbolo sin tasa disponible se devuelve como None.
    """
    rates = await get_rates()

    conversions = {"USD": round(amount_usd, 2)}
    for symbol in FIAT_SYMBOLS:
        rate = rates.get(symbol)
        conversions[symbol] = round(amount_usd * rate, 2) if rate else None

    crypto = {}
    for symbol in CRYPTO_IDS:
        rate = rates.get(symbol)
        crypto[symbol] = round(amount_usd * rate, 8) if rate else None
    for symbol in STABLECOINS:  # ancladas 1:1 al USD
        crypto[symbol] = round(amount_usd, 2)
    conversions["CRYPTO"] = crypto

    stale = (time.monotonic() - _cache["fetched_at"]) >= CACHE_TTL_SECONDS

    return {
        "base_currency": "USD",
        "base_amount": round(amount_usd, 2),
        "conversions": conversions,
        "stale": stale,
    }
