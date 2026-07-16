import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings, validate_config  # noqa: F401 — validates env vars at import time
from app.llm.factory import validate_llm_config
from app.db.client import create_pool, close_pool
from app.health.integrity_check import run_integrity_check, start_daily_integrity_sweep
from app.background.reprompt_sweep import start_reprompt_sweep
from app.tagassigner.trigger import (
    start_idle_scan_sweep,
    start_midnight_reset_sweep,
    start_nightly_batch_sweep,
)
from app.tagassigner.queue import start_queue_drain

logger = logging.getLogger(__name__)

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_pool()
    validate_config(
        settings.live_testing_mode,
        settings.testing_limitations_mode,
        settings.live_testing_limit,
    )
    validate_llm_config()
    await run_integrity_check(fatal_on_failure=not settings.integrity_check_bypass)
    _background_tasks.append(asyncio.create_task(start_reprompt_sweep()))
    _background_tasks.append(asyncio.create_task(start_daily_integrity_sweep()))
    _background_tasks.append(asyncio.create_task(start_queue_drain()))
    _background_tasks.append(asyncio.create_task(start_idle_scan_sweep()))
    _background_tasks.append(asyncio.create_task(start_midnight_reset_sweep()))
    _background_tasks.append(asyncio.create_task(start_nightly_batch_sweep()))
    logger.info("Univotel Chatbot started")
    yield
    for task in _background_tasks:
        task.cancel()
    await close_pool()
    logger.info("Univotel Chatbot stopped")


app = FastAPI(title="Univotel Chatbot", lifespan=lifespan)


@app.middleware("http")
async def request_diagnostics(request: Request, call_next):
    """
    Diagnostic access log: records every request, its final status, and timing.
    Catches any unhandled exception and logs the full traceback so a crash shows
    up in the terminal as a 500 with a stack trace instead of a bare 502.
    """
    start = time.monotonic()
    logger.info("→ %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error(
            "✗ %s %s UNHANDLED EXCEPTION after %.0fms\n%s",
            request.method, request.url.path, elapsed_ms, traceback.format_exc(),
        )
        return JSONResponse(status_code=500, content={"status": "internal_error"})
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "← %s %s %d %.0fms",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


from app.webhooks.chatwoot import router as chatwoot_router  # noqa: E402
from app.webhooks.internal import router as internal_router  # noqa: E402
from app.webhooks.batch_results import router as batch_results_router  # noqa: E402

app.include_router(chatwoot_router)
app.include_router(internal_router)
app.include_router(batch_results_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
