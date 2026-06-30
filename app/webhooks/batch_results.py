"""
POST /webhooks/batch-results — Gemini batch.succeeded webhook handler.

Implements the Standard Webhooks spec (build brief §1, tagassigner-v1-spec.md §4.2):
- Verification: Standard Webhooks (symmetric v1 HMAC), separate from Chatwoot HMAC.
- Thin payload: event carries output_file_uri (gs://), not inline results.
- Responds 2xx immediately; GCS fetch + processing runs in a background task.
- Deduplication: claims batch_webhook_id on tag_assigner_runs atomically (at-most-once).
- Replay protection: timestamp checked in verify_standard_webhook (5-min window).
"""
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.security import verify_standard_webhook

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/batch-results")
async def batch_results_webhook(request: Request, background_tasks: BackgroundTasks):
    # Verify signature first (Standard Webhooks — NOT Chatwoot HMAC)
    webhook_id = await verify_standard_webhook(request)

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        logger.fatal("BATCH_WEBHOOK: malformed JSON — dropping request")
        return JSONResponse(status_code=200, content={"status": "dropped_malformed"})

    event_type = payload.get("type", "")
    if event_type != "batch.succeeded":
        logger.info("BATCH_WEBHOOK: ignoring event type=%r", event_type)
        return JSONResponse(status_code=200, content={"status": "ignored"})

    # The thin pointer: output file + user_metadata for run routing
    data = payload.get("data", {})
    output_file_uri = data.get("output_file_uri") or data.get("outputFileUri")
    user_metadata_raw = data.get("user_metadata") or data.get("userMetadata") or "{}"

    if not output_file_uri:
        logger.fatal("BATCH_WEBHOOK: missing output_file_uri in payload — dropping")
        return JSONResponse(status_code=200, content={"status": "dropped_no_uri"})

    try:
        user_metadata = json.loads(user_metadata_raw) if isinstance(user_metadata_raw, str) else user_metadata_raw
    except json.JSONDecodeError:
        logger.error("BATCH_WEBHOOK: could not parse user_metadata")
        user_metadata = {}

    # user_metadata maps custom_id (conversation_id str) → run_id str
    run_id_map: dict[str, str] = {k: v for k, v in user_metadata.items() if isinstance(v, str)}

    if not run_id_map:
        logger.error("BATCH_WEBHOOK: no run_id_map in user_metadata — cannot route results")
        return JSONResponse(status_code=200, content={"status": "dropped_no_run_map"})

    # Deduplication: claim webhook_id atomically against the first run_id in the map.
    # All runs in the batch share the same batch job, so we key dedup on the first.
    first_run_id_str = next(iter(run_id_map.values()), None)
    if first_run_id_str:
        try:
            import uuid
            first_run_id = uuid.UUID(first_run_id_str)
            from app.db import queries
            claimed = await queries.claim_batch_webhook(first_run_id, webhook_id)
            if not claimed:
                logger.info(
                    "BATCH_WEBHOOK: webhook_id=%s already processed — skipping duplicate",
                    webhook_id,
                )
                return JSONResponse(status_code=200, content={"status": "duplicate"})
        except Exception as exc:
            logger.error("BATCH_WEBHOOK: dedup check failed: %s", exc)
            # Don't block processing on a failed dedup check

    background_tasks.add_task(
        _process_batch_results,
        output_file_uri=output_file_uri,
        run_id_map=run_id_map,
        webhook_id=webhook_id,
    )

    return JSONResponse(status_code=200, content={"status": "ok"})


async def _process_batch_results(
    output_file_uri: str,
    run_id_map: dict[str, str],
    webhook_id: str,
) -> None:
    try:
        from app.tagassigner.batch_client import process_batch_results
        await process_batch_results(output_file_uri, run_id_map)
    except Exception as exc:
        logger.error(
            "BATCH_WEBHOOK bg: unhandled error processing batch results (webhook_id=%s): %s",
            webhook_id, exc,
        )
