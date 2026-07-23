"""
Pure derivations for the dashboard — no DB, no I/O, no framework.

Everything here is a function of values already read from the database. Keeping it
free of side effects is what makes DASHBOARD_SPEC.md §13.1 testable without a
connection, and it is the single place a rule like "what counts as a failure
signature" is written down.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Status vocabulary (spec §4.1)
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_IN_PROGRESS = "in_progress"
STATUS_HUMAN_NEEDED = "human_needed"
STATUS_HUMAN_INTERRUPTION = "human_interruption"
STATUS_NOT_RUN = "not_run"

ALL_STATUSES: list[str] = [
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_HUMAN_NEEDED,
    STATUS_HUMAN_INTERRUPTION,
    STATUS_NOT_RUN,
]

# Mirrors the live conversations_flow_state_check constraint.
ALL_FLOW_STATES: list[str] = [
    "new",
    "awaiting_university",
    "awaiting_university_clarification",
    "awaiting_campus_clarification",
    "awaiting_gender",
    "recengine_running",
    "completed",
    "human_needed",
    "stopped",
]

# States InfoGatherer can still act from — the ones the stale rule applies to.
MID_FLOW_STATES: list[str] = [
    "new",
    "awaiting_university",
    "awaiting_university_clarification",
    "awaiting_campus_clarification",
    "awaiting_gender",
    "recengine_running",
]

ALL_LOG_LEVELS: list[str] = ["info", "warn", "error", "fatal"]
ALL_OPERATION_LAYERS: list[str] = ["infoGatherer", "recEngine", "tagAssigner", "fallBack"]
ALL_WHICH_RUNS: list[str] = ["contextRun", "outputRun"]

# ---------------------------------------------------------------------------
# Failure signatures (spec §4.6)
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_QUOTED_RE = re.compile(r"'[^']*'")
_INT_RE = re.compile(r"(?<![\w<])\d+(?![\w>])")
_WS_RE = re.compile(r"\s+")

_SIGNATURE_MAX_CHARS = 120

# Normalised explanation -> (slug, display label). Seeded from every write_log()
# call site in the codebase; adding a row is the whole cost of covering a new one.
_KNOWN_SIGNATURES: dict[str, tuple[str, str]] = {
    "Post-completion message did not name a specific hotel — deferred to human": (
        "post_completion_no_hotel",
        "Post-completion, no hotel named",
    ),
    "No response schema messages could be sent for eligible hotels": (
        "no_schema_messages_sent",
        "No hotel schema messages sent",
    ),
    "No matching row in response_schemas for hotel_id=<id>": (
        "no_response_schema_for_hotel",
        "Missing response schema",
    ),
    "University clarification reply '…' failed twice — FallBack stub": (
        "university_clarification_twice",
        "University clarification failed twice",
    ),
    "Divergence routing escalate (missing row or persistence cap)": (
        "divergence_unhandled",
        "Divergence unhandled",
    ),
    "Divergence classifier failed for '…'": (
        "off_script_no_answer",
        "Divergence classifier failed",
    ),
    "Gender set but university missing after gender slot reply": (
        "gender_set_university_missing",
        "Gender set, university missing",
    ),
    "awaiting_campus_clarification with no pending_parent_university_id — data inconsistency": (
        "missing_pending_parent",
        "Missing pending parent",
    ),
    "No campus rows for pending parent <id>": (
        "parent_no_campus_rows",
        "Parent has no campuses",
    ),
    "Parent university <id> has no campus rows — cannot escalate": (
        "parent_no_campus_rows",
        "Parent has no campuses",
    ),
    "Failed to build campus question for parent <id>": (
        "campus_question_build_failed",
        "Campus question build failed",
    ),
    "InfoGatherer abstained: Chatwoot transcript fetch failed": (
        "abstain_backfill_failed",
        "Backfill failed",
    ),
    "InfoGatherer abstained: <n> prior Chatwoot message(s) backfilled": (
        "abstain_prior_history",
        "Abstained — prior history",
    ),
}

# Signatures with no log row behind them — synthesised by the resolution chains.
_DERIVED_SIGNATURE_LABELS: dict[str, str] = {
    "recengine_ladder_exhausted": "RecEngine ladder exhausted",
    "recengine_502": "RecEngine 502",
    "recengine_invalid_found": "RecEngine invalid payload",
    "recengine_failed": "RecEngine failed",
    "stalled": "Stalled — no reply",
    "unclassified": "Unclassified",
}

# internal_class values that are informational, not failures.
_INTERNAL_CLASS_LABELS: dict[str, str] = {
    "abstain_prior_history": "Abstained — prior history",
    "abstain_backfill_failed": "Backfill failed",
    "divergence": "Divergence turn",
    "divergence_unhandled": "Divergence unhandled",
    "off_script_no_answer": "Divergence classifier failed",
    "attr_write_failed": "Attribute write failed",
    "missing_pending_parent": "Missing pending parent",
    "unhandled_exception": "Unhandled exception",
}


def normalize_explanation(explanation: str) -> str:
    """
    Collapse the variable parts of a log explanation so equivalent failures group.

    Order matters: UUIDs are replaced before integers, otherwise the digit runs
    inside a UUID would be rewritten first and the UUID pattern would no longer
    match.
    """
    text = _UUID_RE.sub("<id>", explanation)
    text = _QUOTED_RE.sub("'…'", text)
    text = _INT_RE.sub("<n>", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def failure_signature(
    *,
    internal_class: Optional[str] = None,
    explanation: Optional[str] = None,
    status_code: Optional[str] = None,
) -> tuple[str, str]:
    """
    Resolve (slug, display_label) for a log row. Spec §4.6, rules applied in order.
    """
    if internal_class:
        slug = "divergence" if internal_class.startswith("divergence:") else internal_class
        return slug, _INTERNAL_CLASS_LABELS.get(slug, slug)

    if explanation and explanation.strip():
        normalized = normalize_explanation(explanation)
        known = _KNOWN_SIGNATURES.get(normalized)
        if known:
            return known
        truncated = normalized[:_SIGNATURE_MAX_CHARS]
        return truncated, truncated

    if status_code:
        return f"http_{status_code}", f"HTTP {status_code}"

    return "unclassified", _DERIVED_SIGNATURE_LABELS["unclassified"]


def signature_label(slug: str) -> str:
    """Display label for a slug, including the synthesised ones with no log row."""
    if slug in _DERIVED_SIGNATURE_LABELS:
        return _DERIVED_SIGNATURE_LABELS[slug]
    if slug in _INTERNAL_CLASS_LABELS:
        return _INTERNAL_CLASS_LABELS[slug]
    for known_slug, label in _KNOWN_SIGNATURES.values():
        if known_slug == slug:
            return label
    return slug


# ---------------------------------------------------------------------------
# Origin flow state (spec §4.5)
# ---------------------------------------------------------------------------

UNKNOWN_ORIGIN = "unknown"

# Which state each escalation site fired from. Only needed while chatbot_logs
# .from_state is unpopulated (spec §12.1 makes this table redundant).
_SIGNATURE_ORIGIN: dict[str, str] = {
    "post_completion_no_hotel": "completed",
    "university_clarification_twice": "awaiting_university_clarification",
    "gender_set_university_missing": "awaiting_gender",
    "missing_pending_parent": "awaiting_campus_clarification",
    "parent_no_campus_rows": "awaiting_campus_clarification",
    "campus_question_build_failed": "awaiting_campus_clarification",
    "no_response_schema_for_hotel": "completed",
    "no_schema_messages_sent": "completed",
    "abstain_backfill_failed": "new",
    "abstain_prior_history": "new",
    "recengine_ladder_exhausted": "recengine_running",
    "recengine_502": "recengine_running",
    "recengine_invalid_found": "recengine_running",
    "recengine_failed": "recengine_running",
    # Reachable from four different states — deliberately not guessed.
    "divergence_unhandled": UNKNOWN_ORIGIN,
    "off_script_no_answer": UNKNOWN_ORIGIN,
}


def origin_flow_state(
    *,
    status: str,
    flow_state: str,
    from_state: Optional[str] = None,
    signature: Optional[str] = None,
) -> str:
    """
    The state a conversation escalated *from*. Spec §4.5, first match wins.

    For statuses that never overwrite flow_state (failed-by-stall, in_progress),
    the live flow_state is already the answer.
    """
    if from_state:
        return from_state

    if status in (STATUS_HUMAN_NEEDED, STATUS_HUMAN_INTERRUPTION):
        if signature:
            return _SIGNATURE_ORIGIN.get(signature, UNKNOWN_ORIGIN)
        return UNKNOWN_ORIGIN

    if flow_state in ALL_FLOW_STATES:
        return flow_state

    return UNKNOWN_ORIGIN


# ---------------------------------------------------------------------------
# Turkish-aware normalisation (spec §5.10)
# ---------------------------------------------------------------------------

# All four Turkish I-variants fold to one character. Strict Turkish casefolding
# maps I→ı and İ→i, which is orthographically right but splits groups this job
# wants merged: leads type WhatsApp messages without diacritics constantly (the
# live data has "Istınye unıversıtesı", "Kız ogrencı"), mixing all four freely.
# The cost is that a genuine minimal pair like ılık/ilik would merge — acceptable
# when the alternative is scattering one message across four buckets.
_TURKISH_I_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def normalize_message_text(content: Optional[str]) -> str:
    """
    Group key for trigger messages — see _TURKISH_I_FOLD for the I-variant rule.

    The fold must run before casefold(): Python lowercases 'İ' to 'i' plus a
    combining dot, which would then no longer compare equal to a plain 'i'.
    """
    if not content:
        return ""
    text = content.translate(_TURKISH_I_FOLD).casefold()
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Pie slices (spec §5.9)
# ---------------------------------------------------------------------------

MAX_SLICES = 6
OTHER_KEY = "__other__"


def build_slices(
    counts: dict[str, int],
    *,
    labels: Optional[dict[str, str]] = None,
    max_slices: int = MAX_SLICES,
) -> dict[str, Any]:
    """
    Rank categories, fold the tail into "Other", and compute percentages that sum
    to exactly 100.0.

    A single leftover category is kept as itself — an "Other" of one is noise, not
    a summary. Rounding residue lands on the largest slice so the pie never
    displays 99.9%.
    """
    labels = labels or {}
    total = sum(counts.values())
    if total == 0:
        return {"total": 0, "slices": []}

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    head = ranked[:max_slices]
    tail = ranked[max_slices:]

    # Folding a lone leftover would replace a real label with "Other (1 category)".
    if len(tail) == 1:
        head = head + tail
        tail = []

    slices: list[dict[str, Any]] = [
        {
            "key": key,
            "label": labels.get(key, key),
            "count": count,
            "pct": round(count * 100.0 / total, 1),
        }
        for key, count in head
    ]

    if tail:
        tail_count = sum(count for _, count in tail)
        slices.append(
            {
                "key": OTHER_KEY,
                "label": f"Other ({len(tail)} categories)",
                "count": tail_count,
                "pct": round(tail_count * 100.0 / total, 1),
                "members": [
                    {"key": key, "label": labels.get(key, key), "count": count}
                    for key, count in tail
                ],
            }
        )

    residue = round(100.0 - sum(s["pct"] for s in slices), 1)
    if residue and slices:
        largest = max(slices, key=lambda s: s["count"])
        largest["pct"] = round(largest["pct"] + residue, 1)

    return {"total": total, "slices": slices}


# ---------------------------------------------------------------------------
# Percentages (spec §5.8)
# ---------------------------------------------------------------------------

def percentage(count: int, denominator: int) -> Optional[float]:
    """None (rendered as an em-dash) rather than 0.0 when there is nothing to divide."""
    if denominator <= 0:
        return None
    return round(count * 100.0 / denominator, 1)


# ---------------------------------------------------------------------------
# Log presentation (spec §4.9, §5.4)
# ---------------------------------------------------------------------------

def log_status(*, is_success: Optional[bool], log_level: Optional[str]) -> str:
    """
    Colour class for a log row. Spec §4.9.

    'fatal' maps to human_needed because every fatal in this codebase is written by
    _escalate_human_needed immediately before the state change.
    """
    if is_success is True:
        return STATUS_SUCCESS
    if log_level == "fatal":
        return STATUS_HUMAN_NEEDED
    if log_level == "error":
        return STATUS_FAILED
    if log_level == "warn" and is_success is False:
        return STATUS_FAILED
    return STATUS_IN_PROGRESS


def operation_label(
    *,
    operation_layer: Optional[str],
    which_run: Optional[str],
    internal_class: Optional[str] = None,
) -> str:
    """The human-readable 'operation name' shown on every log row."""
    parts = [p for p in (operation_layer, which_run) if p]
    label = " · ".join(parts) if parts else "unknown"
    if internal_class:
        label = f"{label} · {internal_class}"
    return label


# ---------------------------------------------------------------------------
# Failure reason resolution (spec §4.4)
# ---------------------------------------------------------------------------

REASON_SOURCE_LOG = "log"
REASON_SOURCE_REC_ENGINE = "rec_engine"
REASON_SOURCE_INFERRED = "inferred"
REASON_SOURCE_STALE = "stale"
REASON_SOURCE_UNKNOWN = "unknown"


def resolve_failure_reason(
    *,
    status: str,
    flow_state: str,
    stale_hours: int,
    failure_log_explanation: Optional[str] = None,
    failure_log_internal_class: Optional[str] = None,
    failure_log_status_code: Optional[str] = None,
    rec_engine_status: Optional[str] = None,
    rec_engine_status_code: Optional[str] = None,
    rec_engine_network_status: Optional[str] = None,
) -> tuple[Optional[str], str, Optional[str]]:
    """
    Resolve (reason_text, reason_source, signature_slug). Spec §4.4, first hit wins.

    Returning the source alongside the text is the point: an inferred reason must
    never be rendered as though it were logged.
    """
    if failure_log_explanation or failure_log_internal_class:
        slug, _ = failure_signature(
            internal_class=failure_log_internal_class,
            explanation=failure_log_explanation,
            status_code=failure_log_status_code,
        )
        return failure_log_explanation, REASON_SOURCE_LOG, slug

    if rec_engine_status == "failed":
        detail = ", ".join(
            part
            for part in (
                f"status_code={rec_engine_status_code}" if rec_engine_status_code else None,
                f"network={rec_engine_network_status}" if rec_engine_network_status else None,
            )
            if part
        )
        text = f"RecEngine failed ({detail})" if detail else "RecEngine failed"
        return text, REASON_SOURCE_REC_ENGINE, "recengine_failed"

    if status == STATUS_HUMAN_NEEDED and rec_engine_status == "processing":
        return (
            "RecEngine ladder exhausted — 3 attempts, no resolution",
            REASON_SOURCE_INFERRED,
            "recengine_ladder_exhausted",
        )

    if status == STATUS_FAILED and flow_state in MID_FLOW_STATES:
        return (
            f"Stalled — no activity for {stale_hours}h in state {flow_state}",
            REASON_SOURCE_STALE,
            "stalled",
        )

    return None, REASON_SOURCE_UNKNOWN, None


# ---------------------------------------------------------------------------
# Message bubbles (spec §5.6)
# ---------------------------------------------------------------------------

BUBBLE_INBOUND = "inbound"
BUBBLE_BOT = "bot"
BUBBLE_HUMAN = "human"
BUBBLE_PRIVATE = "private"

_BOT_SENDER_TYPES = frozenset({"infoGatherer", "fallBack"})


def bubble_kind(
    *,
    message_type: Optional[str],
    sender_type: Optional[str],
    is_private: Optional[bool],
) -> str:
    """
    Which bubble style a message wears. Spec §5.6.

    Private wins over everything — a private note is never rendered as a lead or
    bot message regardless of who sent it.
    """
    if is_private:
        return BUBBLE_PRIVATE
    if message_type == "outbound":
        return BUBBLE_BOT if sender_type in _BOT_SENDER_TYPES else BUBBLE_HUMAN
    return BUBBLE_INBOUND


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def to_iso(value: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 with a trailing Z, which is what the client parses."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def first_not_none(values: Iterable[Any]) -> Optional[Any]:
    for value in values:
        if value is not None:
            return value
    return None
