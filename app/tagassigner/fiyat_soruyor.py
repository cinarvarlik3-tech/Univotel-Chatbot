"""
Router-computed fiyat-soruyor label (spec 027, Mode B).

fiyat-soruyor is never assigned by the LLM (label_resolver strips any proposal
of it via strip_llm_fiyat_soruyor). It is computed deterministically from the
message transcript: "asked and not yet informed." Bidirectional — the Router
both adds and removes it based on transcript evidence, unlike deal_awaiting
which is add-only.

State machine:
  fiyat-soruyor IS SET  iff  there exists an inbound message matching a
  PRICE_ASK pattern, AND there is no outbound message matching PRICE_DELIVERED
  at or after that (the most recent) matching inbound ask.

This removes the LLM's temporal/negative-reasoning burden (which is where the
model, regardless of provider, keeps failing — see docs/026) and replaces it
with a pure function over ordered messages.
"""
from __future__ import annotations
import re

from app.db.models import Message
from app.layers.matching import normalize

FIYAT_SORUYOR_LABEL = "fiyat-soruyor"

# Explicit price-intent tokens only. Generic "bilgi"/"detay" openers must NOT
# match — that's the exact false-positive (Mode B1) this replaces.
_PRICE_ASK_TOKENS: tuple[str, ...] = (
    "fiyat", "ücret", "ucret", "ne kadar", "kaça", "kaca", "aylık kaç",
    "aylik kac", "kaç tl", "kac tl", "kaç para", "kac para",
    "fiyat ne", "fiyat nedir", "fiyat bilgisi", "ücretler", "ucretler",
    "price", "how much",
)

# Amount + currency word/abbreviation, checked against normalized text.
_PRICE_DELIVERED_AMOUNT_RE = re.compile(r"\d+\s*(tl|lira)\b")
# The ₺ symbol is stripped by normalize() (not a \w char) — check raw content.
_PRICE_DELIVERED_TRY_SYMBOL_RE = re.compile(r"₺\s*\d+|\d+\s*₺")
_PRICE_DELIVERED_CANNED = "detaylar ve fiyat bilgisi"
_DRIVE_LINK_RE = re.compile(r"drive\.google\.com")


def _is_price_ask(content: str) -> bool:
    normalized = normalize(content)
    return any(token in normalized for token in _PRICE_ASK_TOKENS)


def _is_price_delivered(content: str) -> bool:
    normalized = normalize(content)
    if _PRICE_DELIVERED_AMOUNT_RE.search(normalized):
        return True
    if _PRICE_DELIVERED_TRY_SYMBOL_RE.search(content):
        return True
    if _PRICE_DELIVERED_CANNED in normalized and _DRIVE_LINK_RE.search(content):
        return True
    return False


def compute_fiyat_soruyor(
    messages: list[Message],
    labels: list[str],
) -> list[str]:
    """
    Add or remove fiyat-soruyor in the desired label set based on transcript
    evidence. messages must be in chronological order (as returned by
    queries.get_messages_for_conversation with no 'since' cutoff — the state
    machine needs the FULL history, not an incremental window).
    """
    last_ask_at = None
    delivered_since_ask = False

    for msg in messages:
        content = (msg.content or "").strip()
        if not content:
            continue
        if msg.message_type == "inbound":
            if _is_price_ask(content):
                last_ask_at = msg.created_at
                delivered_since_ask = False
        else:
            if last_ask_at is not None and _is_price_delivered(content):
                delivered_since_ask = True

    should_have_label = last_ask_at is not None and not delivered_since_ask

    result = set(labels)
    if should_have_label:
        result.add(FIYAT_SORUYOR_LABEL)
    else:
        result.discard(FIYAT_SORUYOR_LABEL)
    return sorted(result)
