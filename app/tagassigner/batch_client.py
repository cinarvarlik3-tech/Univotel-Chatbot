"""
Nightly batch submission via the Gemini Batch API (§5.3 of tagassigner-v1-spec.md).

Key design constraints (see tagassigner-build-brief.md §1):
- Batch job creation is NOT idempotent — the run_id guard prevents double-submission.
- Dynamic webhooks are bound at submit time so batch.succeeded routes back to us.
- The webhook delivers a thin pointer (output_file_uri gs://...) — results are fetched
  from GCS in the batch results webhook handler (webhooks/batch_results.py).
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from typing import Optional

from app.config import settings
from app.db import queries
from app.db.models import Conversation, Message

logger = logging.getLogger(__name__)


async def submit_nightly_batch() -> None:
    """
    Sweep eligible conversations and submit them as a single Gemini Batch API job.
    Idempotency guard: each conversation gets its own run_id; if a run row already
    exists in 'processing' for the same conversation from a prior retry, it's skipped.
    """
    if not settings.gemini_api_key:
        logger.fatal("batch_client: GEMINI_API_KEY not configured — skipping nightly batch")
        return

    conversations = await queries.get_conversations_eligible_for_nightly_batch()
    if not conversations:
        logger.info("batch_client: nightly sweep — no eligible conversations")
        return

    logger.info("batch_client: %d conversation(s) eligible for nightly batch", len(conversations))

    # Build one request per conversation, pre-generating run_ids
    requests = []
    run_ids: dict[str, uuid.UUID] = {}  # custom_id → run_id

    for conv in conversations:
        run_id = uuid.uuid4()
        custom_id = str(conv.id)

        # Write the processing row BEFORE touching the Batch API (idempotency guard)
        await queries.insert_tagassigner_run(run_id, conv.id, "scheduled")

        messages = await queries.get_messages_for_conversation(conv.id)
        current_labels = await _fetch_current_labels_safe(conv)

        from app.tagassigner.payload_builder import build_batch_request
        req = build_batch_request(conv, messages, current_labels, custom_id)
        requests.append(req)
        run_ids[custom_id] = run_id

    if not requests:
        return

    batch_job_name = await _submit_batch(requests, run_ids)
    if not batch_job_name:
        # Submission failed — drive every inserted run to a terminal state so none are
        # left orphaned in 'processing' (which would block future triggers per conversation).
        logger.error("batch_client: batch submission failed — marking %d run(s) failed", len(run_ids))
        for run_id in run_ids.values():
            await queries.update_tagassigner_run_failed(run_id)
        return

    # Record the batch job name on each run for lookup when the webhook arrives
    for custom_id, run_id in run_ids.items():
        await queries.update_tagassigner_run_batch(run_id, batch_job_name)

    # Increment auto_run_count for each submitted conversation
    for conv in conversations:
        await queries.increment_auto_run_count(conv.id)

    # Move queue items to 'awaiting_results'
    run_id_list = list(run_ids.values())
    await queries.mark_queue_items_awaiting_results(run_id_list)

    logger.info(
        "batch_client: nightly batch submitted — job=%s conversations=%d",
        batch_job_name, len(conversations),
    )


async def _submit_batch(
    requests: list[dict],
    run_ids: dict[str, uuid.UUID],
) -> Optional[str]:
    """
    Submit requests to the Gemini Batch API with a dynamic webhook bound to this job.
    Returns the Google batch job resource name, or None on failure.
    """
    if not settings.gemini_api_key:
        return None

    try:
        import google.genai as genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)

        # Build the batch requests in Gemini's expected format
        batch_requests = []
        for req in requests:
            batch_requests.append(
                types.EmbedContentRequest(
                    content=types.Content(
                        parts=[types.Part(text=req["user_content"])]
                    )
                )
            )

        # TODO: Replace with the actual Gemini Batch API call once the client
        # exposes batch.create with webhook_config. The interface below is
        # illustrative — confirm against the google-genai SDK docs before running.
        #
        # The dynamic webhook must carry user_metadata so the handler knows
        # which nightly run this job belongs to.
        #
        # batch_job = await asyncio.to_thread(
        #     client.batches.create,
        #     model=settings.model_id,
        #     src=batch_requests,
        #     config=types.CreateBatchJobConfig(
        #         webhook_config=types.WebhookConfig(
        #             uri=f"{settings.public_base_url}/webhooks/batch-results",
        #             user_metadata=json.dumps({r["custom_id"]: str(run_ids[r["custom_id"]]) for r in requests}),
        #         ),
        #         system_instruction=requests[0]["system_prompt"] if requests else "",
        #     ),
        # )
        # return batch_job.name

        logger.warning(
            "batch_client: Batch API submission is stubbed — "
            "wire the google-genai client.batches.create call when the SDK interface is confirmed"
        )
        return None

    except Exception as exc:
        logger.error("batch_client: batch submission error: %s", exc)
        return None


async def process_batch_results(output_file_uri: str, run_id_map: dict[str, str]) -> None:
    """
    Fetch the JSONL output from the GCS URI and process each conversation's labels.
    Called from the batch_results webhook handler after the thin pointer is received.

    run_id_map: maps custom_id (conversation_id str) → run_id str
    """
    lines = await _fetch_gcs_jsonl(output_file_uri)
    if lines is None:
        logger.error("batch_client: could not fetch GCS output — results lost for this batch")
        return

    for line in lines:
        try:
            item = json.loads(line)
            custom_id = item.get("custom_id")
            raw_response = item.get("response", {}).get("text", "")
            run_id_str = run_id_map.get(custom_id)
            if not custom_id or not run_id_str:
                logger.error("batch_client: missing custom_id or run_id in result line")
                continue

            run_id = uuid.UUID(run_id_str)
            conversation_id = uuid.UUID(custom_id)

            from app.tagassigner.payload_builder import parse_gemini_tag_result
            gemini_result = parse_gemini_tag_result(raw_response)
            if gemini_result is None:
                logger.error(
                    "batch_client: malformed Gemini response for conversation %s", conversation_id
                )
                await queries.update_tagassigner_run_failed(run_id)
                continue

            from app.tagassigner.router import apply_tagassigner_result
            await apply_tagassigner_result(conversation_id, run_id, gemini_result)

        except Exception as exc:
            logger.error("batch_client: error processing batch result line: %s", exc)


async def _fetch_gcs_jsonl(gcs_uri: str) -> Optional[list[str]]:
    """
    Fetch a GCS object and return its lines.
    gcs_uri format: gs://<bucket>/<object>

    Uses google-cloud-storage with Application Default Credentials (ADC).
    On Railway, set GOOGLE_APPLICATION_CREDENTIALS to a service account key path.
    """
    try:
        from google.cloud import storage  # type: ignore

        if not gcs_uri.startswith("gs://"):
            logger.error("batch_client: unexpected GCS URI format: %s", gcs_uri)
            return None

        path = gcs_uri[5:]  # strip "gs://"
        bucket_name, _, blob_name = path.partition("/")

        gcs_client = storage.Client()
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        content = await asyncio.to_thread(blob.download_as_text)
        return [line for line in content.splitlines() if line.strip()]

    except Exception as exc:
        logger.error("batch_client: GCS fetch error for %s: %s", gcs_uri, exc)
        return None


async def _fetch_current_labels_safe(conv: Conversation) -> list[str]:
    """Fetch live labels from Chatwoot; fall back to the DB replica on failure."""
    from app.chatwoot_client import get_labels
    live = await get_labels(conv.chatwoot_conversation_id)
    if live is not None:
        return live
    return conv.labels or []
