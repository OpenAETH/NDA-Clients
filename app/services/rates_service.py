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

# Cripto: proveedores en cadena de fallback. Coinbase es el primario porque es
# keyless y estable (CoinGecko en su tier gratuito responde 429 con facilidad).
COINBASE_URL  = "https://api.coinbase.com/v2/prices/{pair}/spot"   # pair = BTC-USD
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Símbolos fiat a extraer de la respuesta de open.er-api (tasas por 1 USD).
FIAT_SYMBOLS = ["EUR", "ARS"]

# Cripto: símbolo visible → id de CoinGecko (usado solo por el fallback).
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


async def _fetch_coinbase(client: httpx.AsyncClient) -> dict:
    """
    Tasas USD→cripto desde Coinbase (una request por par). Keyless y estable.
    La API da el precio de 1 unidad de cripto en USD; lo invertimos a "cripto
    por 1 USD". Devuelve solo los símbolos que respondieron OK.
    """
    out = {}
    for symbol in CRYPTO_IDS:
        try:
            resp = await client.get(COINBASE_URL.format(pair=f"{symbol}-USD"))
            resp.raise_for_status()
            price_usd = float(resp.json()["data"]["amount"])
            if price_usd > 0:
                out[symbol] = 1.0 / price_usd
        except (httpx.HTTPError, ValueError, KeyError, ZeroDivisionError) as e:
            print(f"[RATES] Coinbase error for {symbol}: {e}")
    return out


async def _fetch_coingecko(client: httpx.AsyncClient, symbols: list) -> dict:
    """
    Fallback: tasas USD→cripto desde CoinGecko para los `symbols` pedidos.
    Mismo formato de salida que Coinbase ("cripto por 1 USD"). {} si falla.
    """
    if not symbols:
        return {}
    try:
        ids = ",".join(CRYPTO_IDS[s] for s in symbols)
        resp = await client.get(
            COINGECKO_URL, params={"ids": ids, "vs_currencies": "usd"}
        )
        resp.raise_for_status()
        data = resp.json()
        out = {}
        for symbol in symbols:
            price_usd = data.get(CRYPTO_IDS[symbol], {}).get("usd")
            if price_usd:  # precio de 1 cripto en USD, > 0
                out[symbol] = 1.0 / float(price_usd)
        return out
    except (httpx.HTTPError, ValueError, KeyError, ZeroDivisionError) as e:
        print(f"[RATES] CoinGecko error: {e}")
        return {}


async def _fetch_crypto(client: httpx.AsyncClient) -> dict:
    """
    Tasas USD→cripto con fallback: Coinbase primero; para los símbolos que
    falten, se intenta CoinGecko. Devuelve {} si ninguno responde.
    """
    try:
        rates = await _fetch_coinbase(client)
        missing = [s for s in CRYPTO_IDS if s not in rates]
        if missing:
            rates.update(await _fetch_coingecko(client, missing))
        return rates
    except Exception as e:  # noqa: BLE001 — nunca propagar; el merge conserva caché
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
          "rates_used": {
            # Tasa empleada, autodescriptiva: "1 {from} = {value} {to}".
            #   EUR → 1 USD = 0.86 EUR      (fiat: from=USD)
            #   ARS → 1 USD = 1395 ARS
            #   BTC → 1 BTC = 118500 USD    (cripto: from=activo)
            #   USDT→ 1 USDT = 1 USD        (stablecoin anclada)
            "EUR":  { "from": "USD", "to": "EUR", "value": 0.857408 },
            "ARS":  { "from": "USD", "to": "ARS", "value": 1392.84 },
            "BTC":  { "from": "BTC", "to": "USD", "value": 118500.0 },
            "ETH":  { "from": "ETH", "to": "USD", "value": 2968.0 },
            "USDT": { "from": "USDT", "to": "USD", "value": 1.0 },
            "USDC": { "from": "USDC", "to": "USD", "value": 1.0 }
          },
          "stale": false          # true si se sirvieron datos cacheados vencidos
        }

    Un símbolo sin tasa disponible se devuelve como None (y sin entrada en
    `rates_used`).
    """
    rates = await get_rates()

    conversions = {"USD": round(amount_usd, 2)}
    rates_used = {}
    for symbol in FIAT_SYMBOLS:
        rate = rates.get(symbol)
        conversions[symbol] = round(amount_usd * rate, 2) if rate else None
        if rate:
            # 1 USD = <rate> <symbol>
            rates_used[symbol] = {"from": "USD", "to": symbol, "value": round(rate, 6)}

    crypto = {}
    for symbol in CRYPTO_IDS:
        rate = rates.get(symbol)  # cripto por 1 USD
        crypto[symbol] = round(amount_usd * rate, 8) if rate else None
        if rate:
            # 1 <symbol> = <precio USD> USD  →  precio = 1/rate
            rates_used[symbol] = {"from": symbol, "to": "USD", "value": round(1.0 / rate, 2)}
    for symbol in STABLECOINS:  # ancladas 1:1 al USD
        crypto[symbol] = round(amount_usd, 2)
        rates_used[symbol] = {"from": symbol, "to": "USD", "value": 1.0}
    conversions["CRYPTO"] = crypto

    age = time.monotonic() - _cache["fetched_at"] if _cache["fetched_at"] else None
    stale = age is not None and age >= CACHE_TTL_SECONDS

    return {
        "base_currency": "USD",
        "base_amount": round(amount_usd, 2),
        "conversions": conversions,
        "rates_used": rates_used,
        "age_seconds": round(age) if age is not None else None,
        "stale": stale,
    }
