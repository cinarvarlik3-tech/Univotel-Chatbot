"""
Keepalive sweep — self-pings /health every 5 minutes to stop Render's free
tier from idling the service out after 15 minutes of no inbound traffic.

Only runs when RENDER_EXTERNAL_URL is set (i.e. actually deployed on Render).
No-ops locally and on any other host.
"""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

PING_INTERVAL_SECONDS = 5 * 60  # 5 minutes


async def start_keepalive_sweep() -> None:
    base_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not base_url:
        logger.info("Keepalive sweep skipped — RENDER_EXTERNAL_URL not set")
        return

    url = f"{base_url.rstrip('/')}/health"
    logger.info("Keepalive sweep started (interval=%ds, url=%s)", PING_INTERVAL_SECONDS, url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                resp = await client.get(url)
                logger.debug("Keepalive ping -> %s", resp.status_code)
            except asyncio.CancelledError:
                logger.info("Keepalive sweep cancelled — shutting down")
                return
            except Exception as exc:
                logger.warning("Keepalive ping failed: %s", exc)
