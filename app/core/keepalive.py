"""
keepalive.py — Ping periódico para evitar el spin-down de Render (free tier).

IMPORTANTE — por qué esto NO es solo "una consulta a la DB cada tanto":
Render apaga (spin down) un Web Service free tras ~15 minutos SIN TRÁFICO
HTTP ENTRANTE PÚBLICO. Es una medición de tráfico hacia el load balancer,
no de actividad interna del proceso. Un job interno que solo hiciera una
consulta a Mongo (sin pegarle a la URL pública) no cuenta como tráfico
entrante, así que NO evita el spin-down: el proceso se sigue apagando igual,
y con él se muere también ese mismo job.

Lo que sí funciona es que el propio proceso, mientras está vivo, se pegue a
sí mismo por HTTP a su URL pública (RENDER_EXTERNAL_URL, la setea Render
automáticamente en cada Web Service) con más frecuencia que el timeout de
15 min. Esa request sí pasa por el load balancer de Render y resetea el
contador de inactividad. Acá aprovechamos ese ping para además tocar Mongo
(vía /health -> sales_log.ping_db()), así el resultado sirve como monitoreo
real de la DB y no es un ping "vacío".

Limitaciones a tener en cuenta:
  • Es un workaround best-effort, no un mecanismo oficialmente soportado
    por Render — Render puede cambiar esta política en cualquier momento.
  • Si el proceso ya se durmió (por un deploy, un restart, o porque este
    loop no llegó a correr todavía), este ping no lo puede "despertar" a
    sí mismo — hace falta una request externa real para eso.
  • Mantener el proceso siempre activo consume horas del free tier
    (750 hs/mes): para UN solo servicio corriendo 24/7 entra justo, pero
    si tenés más servicios free en la misma cuenta puede no alcanzar.
  • Alternativa más robusta (y más simple): un cron externo — cron-job.org,
    UptimeRobot, o un GitHub Actions con `schedule:` — pegándole a
    GET /health cada 10 min desde afuera. No depende de que el proceso ya
    esté vivo para autoprogramarse, y no consume horas del propio servicio
    en el request en sí. Se puede usar en combinación con este loop o en
    su reemplazo (en ese caso, dejar KEEP_ALIVE_ENABLED=false acá).
"""

import asyncio
import os

import httpx

from app.core.config import settings

_task: "asyncio.Task | None" = None


async def _loop() -> None:
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not base_url:
        # No estamos en Render (o la variable no está seteada) — no hay
        # URL pública propia a la cual pegarle, así que no arrancamos.
        print("[KEEPALIVE] RENDER_EXTERNAL_URL no seteada — loop desactivado.")
        return

    endpoint = f"{base_url}/health"
    interval = settings.KEEP_ALIVE_INTERVAL_SECONDS
    print(f"[KEEPALIVE] activo — ping a {endpoint} cada {interval}s")

    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            await asyncio.sleep(interval)
            try:
                resp = await client.get(endpoint)
                print(f"[KEEPALIVE] ping ok -> {resp.status_code} {resp.json()}")
            except Exception as e:
                # Best-effort: un ping fallido no debe tumbar el proceso.
                print(f"[KEEPALIVE] ping falló (no-fatal): {e}")


def start() -> None:
    """Arranca el loop en background. Llamar una sola vez, en el lifespan de la app."""
    global _task
    if not settings.KEEP_ALIVE_ENABLED:
        print("[KEEPALIVE] deshabilitado por config (KEEP_ALIVE_ENABLED=false).")
        return
    if _task is None:
        _task = asyncio.create_task(_loop())


def stop() -> None:
    """Cancela el loop. Llamar al apagar la app."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
