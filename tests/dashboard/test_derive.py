"""
Unit tests for the dashboard's pure derivations (DASHBOARD_SPEC.md §13.1).

No DB, no event loop. Every explanation string here is copied verbatim from a
write_log() call site in app/ — if one of those strings is reworded, the matching
test fails and the signature table gets updated with it.
"""
from __future__ import annotations

import pytest

from dashboard.api import derive


# ---------------------------------------------------------------------------
# normalize_explanation
# ---------------------------------------------------------------------------

def test_normalize_strips_uuid():
    text = derive.normalize_explanation(
        "No campus rows for pending parent 0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f"
    )
    assert text == "No campus rows for pending parent <id>"


def test_normalize_strips_quoted_span():
    text = derive.normalize_explanation("Divergence classifier failed for 'merhaba abi'")
    assert text == "Divergence classifier failed for '…'"


def test_normalize_strips_standalone_integers():
    text = derive.normalize_explanation("InfoGatherer abstained: 43 prior Chatwoot message(s) backfilled")
    assert text == "InfoGatherer abstained: <n> prior Chatwoot message(s) backfilled"


def test_normalize_runs_uuid_before_integer():
    """A UUID contains digit runs; rewriting integers first would break the match."""
    text = derive.normalize_explanation("hotel_id=11111111-2222-3333-4444-555555555555")
    assert text == "hotel_id=<id>"
    assert "<n>" not in text


def test_normalize_collapses_whitespace():
    assert derive.normalize_explanation("a   b\n\tc  ") == "a b c"


# ---------------------------------------------------------------------------
# failure_signature — every known explanation from app/
# ---------------------------------------------------------------------------

KNOWN_CASES = [
    ("Post-completion message did not name a specific hotel — deferred to human",
     "post_completion_no_hotel"),
    ("No response schema messages could be sent for eligible hotels",
     "no_schema_messages_sent"),
    ("No matching row in response_schemas for hotel_id=0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f",
     "no_response_schema_for_hotel"),
    ("University clarification reply 'bogazici uni' failed twice — FallBack stub",
     "university_clarification_twice"),
    ("Divergence routing escalate (missing row or persistence cap)",
     "divergence_unhandled"),
    ("Divergence classifier failed for 'napiyon'", "off_script_no_answer"),
    ("Gender set but university missing after gender slot reply",
     "gender_set_university_missing"),
    ("awaiting_campus_clarification with no pending_parent_university_id — data inconsistency",
     "missing_pending_parent"),
    ("No campus rows for pending parent 0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f",
     "parent_no_campus_rows"),
    ("Parent university 0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f has no campus rows — cannot escalate",
     "parent_no_campus_rows"),
    ("Failed to build campus question for parent 0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f",
     "campus_question_build_failed"),
    ("InfoGatherer abstained: Chatwoot transcript fetch failed", "abstain_backfill_failed"),
    ("InfoGatherer abstained: 5 prior Chatwoot message(s) backfilled", "abstain_prior_history"),
]


@pytest.mark.parametrize("explanation,expected_slug", KNOWN_CASES)
def test_failure_signature_known_explanations(explanation, expected_slug):
    slug, label = derive.failure_signature(explanation=explanation)
    assert slug == expected_slug
    assert label and label != slug or slug == label


def test_two_parent_variants_share_one_signature():
    """Both parent-campus escalations describe the same defect and must not split the pie."""
    a, _ = derive.failure_signature(
        explanation="No campus rows for pending parent 0c8f1e2a-4b3d-4c5e-9f10-1a2b3c4d5e6f")
    b, _ = derive.failure_signature(
        explanation="Parent university 9999999a-4b3d-4c5e-9f10-1a2b3c4d5e6f "
                    "has no campus rows — cannot escalate")
    assert a == b == "parent_no_campus_rows"


def test_internal_class_wins_over_explanation():
    slug, _ = derive.failure_signature(
        internal_class="attr_write_failed",
        explanation="Gender set but university missing after gender slot reply",
    )
    assert slug == "attr_write_failed"


def test_divergence_intents_collapse_to_one_slug():
    a, _ = derive.failure_signature(internal_class="divergence:price")
    b, _ = derive.failure_signature(internal_class="divergence:no_intent")
    assert a == b == "divergence"


def test_status_code_fallback():
    slug, label = derive.failure_signature(status_code="502")
    assert slug == "http_502"
    assert label == "HTTP 502"


def test_unclassified_when_nothing_present():
    slug, label = derive.failure_signature()
    assert slug == "unclassified"
    assert label == "Unclassified"


def test_unknown_explanation_is_truncated_not_dropped():
    long_text = "Some brand new failure mode " + ("x" * 200)
    slug, label = derive.failure_signature(explanation=long_text)
    assert len(slug) == 120
    assert slug == label
    assert slug.startswith("Some brand new failure mode")


def test_blank_explanation_is_not_a_signature():
    slug, _ = derive.failure_signature(explanation="   ", status_code="404")
    assert slug == "http_404"


# ---------------------------------------------------------------------------
# origin_flow_state
# ---------------------------------------------------------------------------

def test_origin_prefers_from_state_when_populated():
    """Spec §12.1 populates from_state; when it exists the lookup table is bypassed."""
    assert derive.origin_flow_state(
        status=derive.STATUS_HUMAN_NEEDED,
        flow_state="human_needed",
        from_state="awaiting_gender",
        signature="post_completion_no_hotel",
    ) == "awaiting_gender"


def test_origin_reconstructed_from_signature():
    assert derive.origin_flow_state(
        status=derive.STATUS_HUMAN_NEEDED,
        flow_state="human_needed",
        signature="university_clarification_twice",
    ) == "awaiting_university_clarification"


def test_origin_unknown_for_multi_state_escalations():
    """divergence_unhandled fires from four states — guessing one would be a lie."""
    assert derive.origin_flow_state(
        status=derive.STATUS_HUMAN_NEEDED,
        flow_state="human_needed",
        signature="divergence_unhandled",
    ) == derive.UNKNOWN_ORIGIN


def test_origin_unknown_when_no_signature():
    assert derive.origin_flow_state(
        status=derive.STATUS_HUMAN_NEEDED, flow_state="human_needed",
    ) == derive.UNKNOWN_ORIGIN


def test_origin_uses_live_flow_state_for_stalled_failures():
    """A stalled conversation never had its flow_state overwritten."""
    assert derive.origin_flow_state(
        status=derive.STATUS_FAILED, flow_state="awaiting_gender",
    ) == "awaiting_gender"


# ---------------------------------------------------------------------------
# normalize_message_text — Turkish
# ---------------------------------------------------------------------------

def test_turkish_i_variants_all_group_together():
    """
    İstanbul / istanbul / ISTANBUL / ıstanbul must be one group, not four.
    Leads type all four interchangeably — the live data is full of diacritic-free
    spellings like 'Istınye unıversıtesı'.
    """
    forms = ["İstanbul", "istanbul", "ISTANBUL", "ıstanbul", "İSTANBUL"]
    normalized = {derive.normalize_message_text(f) for f in forms}
    assert len(normalized) == 1


def test_turkish_dotless_i_groups_with_dotted():
    assert derive.normalize_message_text("Işık") == derive.normalize_message_text("ışık")


def test_real_lead_message_casing_variants_group():
    """Verbatim from the live messages table."""
    a = derive.normalize_message_text("Istınye unıversıtesı ıcın ornegıın")
    b = derive.normalize_message_text("istinye universitesi icin ornegiin")
    assert a == b


def test_normalize_message_collapses_whitespace_and_trims():
    # ı folds to i by the I-variant rule, so the expected form is ASCII here.
    assert derive.normalize_message_text("  Kız   ogrencı \n") == "kiz ogrenci"


def test_normalize_message_handles_none_and_empty():
    assert derive.normalize_message_text(None) == ""
    assert derive.normalize_message_text("") == ""


# ---------------------------------------------------------------------------
# build_slices
# ---------------------------------------------------------------------------

def test_slices_ranked_descending():
    result = derive.build_slices({"a": 1, "b": 5, "c": 3})
    assert [s["key"] for s in result["slices"]] == ["b", "c", "a"]
    assert result["total"] == 9


def test_slices_tie_broken_by_key_for_stability():
    result = derive.build_slices({"b": 2, "a": 2})
    assert [s["key"] for s in result["slices"]] == ["a", "b"]


def test_slices_fold_tail_into_other():
    # k0=10 … k8=2. Top 6 are k0..k5; the tail is k6=4, k7=3, k8=2.
    counts = {f"k{i}": 10 - i for i in range(9)}
    result = derive.build_slices(counts)
    keys = [s["key"] for s in result["slices"]]
    assert len(keys) == 7
    assert keys[-1] == derive.OTHER_KEY
    other = result["slices"][-1]
    assert other["count"] == 4 + 3 + 2
    assert len(other["members"]) == 3


def test_single_leftover_is_kept_not_folded():
    """An 'Other' of one category replaces a real label with nothing useful."""
    counts = {f"k{i}": 10 - i for i in range(7)}
    result = derive.build_slices(counts)
    keys = [s["key"] for s in result["slices"]]
    assert len(keys) == 7
    assert derive.OTHER_KEY not in keys


def test_percentages_sum_to_exactly_100():
    result = derive.build_slices({"a": 1, "b": 1, "c": 1})
    assert sum(s["pct"] for s in result["slices"]) == pytest.approx(100.0)


def test_rounding_residue_lands_on_largest_slice():
    result = derive.build_slices({"a": 5, "b": 1, "c": 1})
    largest = max(result["slices"], key=lambda s: s["count"])
    assert largest["key"] == "a"
    assert sum(s["pct"] for s in result["slices"]) == pytest.approx(100.0)


def test_empty_counts_returns_no_slices():
    assert derive.build_slices({}) == {"total": 0, "slices": []}


def test_labels_applied():
    result = derive.build_slices({"x": 1}, labels={"x": "Nice label"})
    assert result["slices"][0]["label"] == "Nice label"


# ---------------------------------------------------------------------------
# percentage
# ---------------------------------------------------------------------------

def test_percentage_none_on_zero_denominator():
    """An em-dash is honest about an empty period; 0.0% is not."""
    assert derive.percentage(0, 0) is None


def test_percentage_rounds_to_one_decimal():
    assert derive.percentage(1, 3) == 33.3


# ---------------------------------------------------------------------------
# log_status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_success,level,expected", [
    (True, "info", derive.STATUS_SUCCESS),
    (True, "fatal", derive.STATUS_SUCCESS),
    (False, "fatal", derive.STATUS_HUMAN_NEEDED),
    (False, "error", derive.STATUS_FAILED),
    (False, "warn", derive.STATUS_FAILED),
    (False, "info", derive.STATUS_IN_PROGRESS),
    (None, "info", derive.STATUS_IN_PROGRESS),
    (None, None, derive.STATUS_IN_PROGRESS),
])
def test_log_status(is_success, level, expected):
    assert derive.log_status(is_success=is_success, log_level=level) == expected


def test_abstain_prior_history_is_informational_not_a_failure():
    """log_level='info', is_success=false — the real shape of these rows in the DB."""
    assert derive.log_status(is_success=False, log_level="info") == derive.STATUS_IN_PROGRESS


# ---------------------------------------------------------------------------
# operation_label
# ---------------------------------------------------------------------------

def test_operation_label_joins_parts():
    assert derive.operation_label(
        operation_layer="infoGatherer", which_run="contextRun",
    ) == "infoGatherer · contextRun"


def test_operation_label_appends_internal_class():
    assert derive.operation_label(
        operation_layer="infoGatherer", which_run="contextRun",
        internal_class="abstain_prior_history",
    ) == "infoGatherer · contextRun · abstain_prior_history"


def test_operation_label_handles_all_nulls():
    assert derive.operation_label(operation_layer=None, which_run=None) == "unknown"


# ---------------------------------------------------------------------------
# resolve_failure_reason
# ---------------------------------------------------------------------------

def test_reason_prefers_log():
    text, source, slug = derive.resolve_failure_reason(
        status=derive.STATUS_HUMAN_NEEDED, flow_state="human_needed", stale_hours=24,
        failure_log_explanation="Post-completion message did not name a specific hotel — deferred to human",
        rec_engine_status="failed",
    )
    assert source == derive.REASON_SOURCE_LOG
    assert slug == "post_completion_no_hotel"
    assert text.startswith("Post-completion")


def test_reason_falls_back_to_rec_engine():
    text, source, slug = derive.resolve_failure_reason(
        status=derive.STATUS_HUMAN_NEEDED, flow_state="human_needed", stale_hours=24,
        rec_engine_status="failed", rec_engine_status_code="502",
        rec_engine_network_status="timeout",
    )
    assert source == derive.REASON_SOURCE_REC_ENGINE
    assert slug == "recengine_failed"
    assert "502" in text and "timeout" in text


def test_reason_infers_ladder_exhaustion():
    """rec_engine_ladder.py:61 escalates without writing any log row."""
    text, source, slug = derive.resolve_failure_reason(
        status=derive.STATUS_HUMAN_NEEDED, flow_state="human_needed", stale_hours=24,
        rec_engine_status="processing",
    )
    assert source == derive.REASON_SOURCE_INFERRED
    assert slug == "recengine_ladder_exhausted"
    assert "3 attempts" in text


def test_reason_stale_mentions_window_and_state():
    text, source, slug = derive.resolve_failure_reason(
        status=derive.STATUS_FAILED, flow_state="awaiting_gender", stale_hours=48,
    )
    assert source == derive.REASON_SOURCE_STALE
    assert slug == "stalled"
    assert "48h" in text and "awaiting_gender" in text


def test_reason_unknown_returns_none_not_a_guess():
    text, source, slug = derive.resolve_failure_reason(
        status=derive.STATUS_SUCCESS, flow_state="completed", stale_hours=24,
    )
    assert text is None
    assert source == derive.REASON_SOURCE_UNKNOWN
    assert slug is None


# ---------------------------------------------------------------------------
# bubble_kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mtype,stype,private,expected", [
    ("inbound", "contact", False, derive.BUBBLE_INBOUND),
    ("outbound", "infoGatherer", False, derive.BUBBLE_BOT),
    ("outbound", "fallBack", False, derive.BUBBLE_BOT),
    ("outbound", "user", False, derive.BUBBLE_HUMAN),
    ("outbound", "automation", False, derive.BUBBLE_HUMAN),
    ("inbound", "user", True, derive.BUBBLE_PRIVATE),
    ("inbound", "contact", True, derive.BUBBLE_PRIVATE),
    ("outbound", "infoGatherer", True, derive.BUBBLE_PRIVATE),
])
def test_bubble_kind(mtype, stype, private, expected):
    assert derive.bubble_kind(
        message_type=mtype, sender_type=stype, is_private=private,
    ) == expected


# ---------------------------------------------------------------------------
# to_iso
# ---------------------------------------------------------------------------

def test_to_iso_appends_z_and_normalises_tz():
    from datetime import datetime, timedelta, timezone
    value = datetime(2026, 7, 22, 23, 30, tzinfo=timezone(timedelta(hours=3)))
    assert derive.to_iso(value) == "2026-07-22T20:30:00Z"


def test_to_iso_treats_naive_as_utc():
    from datetime import datetime
    assert derive.to_iso(datetime(2026, 7, 22, 21, 30)) == "2026-07-22T21:30:00Z"


def test_to_iso_none():
    assert derive.to_iso(None) is None
