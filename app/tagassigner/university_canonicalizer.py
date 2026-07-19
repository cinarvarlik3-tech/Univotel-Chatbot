"""
Deterministic university canonicalization for TagAssigner (spec 027, Mode C).

The LLM is unreliable at picking the exact canonical Chatwoot list string —
it either invents a wrong-but-valid value (near-name confusion, e.g.
"istanbul kent" -> "Kültür Üniversitesi") or gives up on cases a deterministic
matcher resolves easily (faculty shorthand on a single-campus parent, e.g.
"Atlas tıp fakültesi" -> bilinmiyor-kampus). This module re-derives the
university from the lead's raw phrase using the same matching primitives
InfoGatherer already uses interactively (app.layers.matching), so TagAssigner
gets InfoGatherer-grade university resolution without any additional LLM
compute.

Used as the "suspenders" half of the option-3 override in router.py: the
LLM's list-value guess is the "belt" (kept as fallback), this module's result
wins whenever it produces a confident campus match.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.db.models import Message, University, UniversityAlias, UniversityParentMap
from app.layers.matching import MatchConfidence, match_campus, normalize, scan_entities_by_ngram
from app.tagassigner.attribute_helpers import UNIVERSITY_CAMPUS_AMBIGUOUS
from app.tagassigner.university_resolver import resolve_university_list_value

_UNI_SENTINELS: frozenset[str] = frozenset({"", "bilinmiyor", UNIVERSITY_CAMPUS_AMBIGUOUS, "boş"})

# Faculty/department/degree-level descriptors — never campus discriminators.
FACULTY_STOPLIST: frozenset[str] = frozenset({
    "tip", "fakultesi", "fakulte", "muhendislik", "hukuk", "tibbi", "dis",
    "hastane", "arastirma", "egitim", "meslek", "yuksekokul", "myo",
    "onlisans", "lisans", "bolum", "bolumu",
})

# Structural campus-naming words that add no discriminating signal.
STRUCTURAL_STOPLIST: frozenset[str] = frozenset({
    "kampus", "kampusu", "kampusleri", "yerleskesi", "yerleske",
})

# District / neighborhood / landmark names. A bare district mention is NOT a
# university statement (mirrors the prompt's district guard) — without this
# stoplist, token-containment would match campuses named after the district
# they sit in (e.g. "kadıköy" -> "Doğuş Üniversitesi - Kadıköy").
DISTRICT_STOPLIST: frozenset[str] = frozenset({
    "kadikoy", "cevizlibag", "besiktas", "avcilar", "mecidiyekoy", "taksim",
    "atakoy", "atasehir", "kartal", "beylikduzu", "bakirkoy", "sisli",
    "umraniye", "uskudar", "fatih", "eyup", "gaziosmanpasa", "esenyurt",
    "dudullu", "hamidiye", "ayazaga",
})


class CanonConfidence(str, Enum):
    CAMPUS = "campus"           # confident campus-level match — safe to override the LLM
    PARENT_ONLY = "parent_only"  # institution known, campus ambiguous -> bilinmiyor-kampus
    NONE = "none"                # no deterministic signal


@dataclass
class CanonResult:
    confidence: CanonConfidence
    university_id: Optional[uuid.UUID] = None


@dataclass(frozen=True)
class UniversityUniverse:
    """Cached, in-memory snapshot of the university matching universe."""
    universities: list[University]
    aliases: list[UniversityAlias]
    campuses_by_parent: dict[uuid.UUID, list[UniversityParentMap]] = field(default_factory=dict)


def _build_universe(
    universities: list[University],
    aliases: list[UniversityAlias],
    parent_map: list[UniversityParentMap],
) -> UniversityUniverse:
    campuses_by_parent: dict[uuid.UUID, list[UniversityParentMap]] = {}
    for row in parent_map:
        campuses_by_parent.setdefault(row.parent_university_id, []).append(row)
    return UniversityUniverse(
        universities=universities,
        aliases=aliases,
        campuses_by_parent=campuses_by_parent,
    )


_TOKEN_CONTAINMENT_MIN_WINDOW = 2  # never match on a single bare token (WS3b collision guard)


def token_containment(
    phrase: str,
    universities: list[University],
) -> Optional[University]:
    """
    Return the unique university whose name (+ short name) token set contains
    ALL significant tokens of some contiguous WINDOW of the lead's phrase
    (after dropping faculty, structural, and district tokens) — not
    necessarily the whole phrase. Scans windows longest-first (most specific,
    safest, wins), then left-to-right, and returns the first UNIQUE hit.
    Returns None if no window ever produces a unique hit.

    Windowed (WS3b, UNIVERSITY_ACCURACY_PLAN.md): a clean, unambiguous
    mention (e.g. "Mimar Sinan Fındıklı") embedded in a long, noisy message
    (widget boilerplate, unrelated follow-up questions) used to be invisible
    here, because the OLD implementation required ALL tokens of the ENTIRE
    phrase to be a subset of one university's name — any unrelated word
    anywhere in the message broke the match. Scanning windows finds the
    clean mention regardless of surrounding noise.

    _TOKEN_CONTAINMENT_MIN_WINDOW=2 guards against the single-token collision
    class WS1 fixed at the alias layer (a bare common/short word coincidentally
    matching some university) — this function never resolves on 1 token alone.
    """
    drop = FACULTY_STOPLIST | STRUCTURAL_STOPLIST | DISTRICT_STOPLIST
    tokens = [t for t in normalize(phrase).split() if t not in drop]
    n_tokens = len(tokens)
    if n_tokens < _TOKEN_CONTAINMENT_MIN_WINDOW:
        return None

    name_token_sets: list[tuple[University, set[str]]] = []
    for uni in universities:
        name_tokens = set(normalize(uni.name).split())
        if uni.university_short_name:
            name_tokens |= set(normalize(uni.university_short_name).split())
        name_token_sets.append((uni, name_tokens))

    for window_len in range(n_tokens, _TOKEN_CONTAINMENT_MIN_WINDOW - 1, -1):
        for start in range(0, n_tokens - window_len + 1):
            window = tokens[start : start + window_len]
            hits = [uni for uni, name_tokens in name_token_sets if all(t in name_tokens for t in window)]
            if len(hits) == 1:
                return hits[0]

    return None


def canonicalize(phrase: str, universe: UniversityUniverse) -> CanonResult:
    """
    Resolve a lead's raw university phrase to a university_id, deterministically.

    Precedence (most to least specific):
      1. scan_entities_by_ngram exact/alias campus match -> CAMPUS.
      2. token_containment unique campus match -> CAMPUS.
      3. scan_entities_by_ngram parent match -> try match_campus on the phrase;
         resolves to a campus -> CAMPUS; single-campus parent -> that campus
         (CAMPUS); otherwise -> PARENT_ONLY (bilinmiyor-kampus).
      4. no signal -> NONE.

    This precedence is why an intentionally broad parent alias (e.g. a bare
    "istanbul" alias resolving to İÜ) never hijacks a more specific phrase
    like "istanbul kent" (tier 2 wins there) while still correctly degrading
    bare "istanbul" to PARENT_ONLY at tier 3.
    """
    if not phrase or not phrase.strip():
        return CanonResult(CanonConfidence.NONE)

    scan = scan_entities_by_ngram(phrase, universe.universities, universe.aliases)

    if (
        scan.confidence in (MatchConfidence.EXACT, MatchConfidence.ALIAS, MatchConfidence.LEVENSHTEIN)
        and scan.university_id is not None
    ):
        return CanonResult(CanonConfidence.CAMPUS, scan.university_id)

    token_hit = token_containment(phrase, universe.universities)
    if token_hit is not None:
        return CanonResult(CanonConfidence.CAMPUS, token_hit.id)

    if scan.confidence == MatchConfidence.ALIAS and scan.parent_university_id is not None:
        parent_id = scan.parent_university_id
        campuses = universe.campuses_by_parent.get(parent_id, [])
        matched_campus = match_campus(phrase, parent_id, campuses, universe.aliases)
        if matched_campus is not None:
            return CanonResult(CanonConfidence.CAMPUS, matched_campus.university_id)
        if len(campuses) == 1:
            return CanonResult(CanonConfidence.CAMPUS, campuses[0].university_id)
        return CanonResult(CanonConfidence.PARENT_ONLY)

    return CanonResult(CanonConfidence.NONE)


def extract_university_phrase_from_messages(messages: list[Message]) -> Optional[str]:
    """
    Deterministically extract the lead's own university/campus phrase from
    the conversation (spec 028.1, Mode C mention fix).

    Scans **inbound** messages only — mirrors the pattern in
    app.tagassigner.fiyat_soruyor. Outbound (bot) messages are never
    scanned: Router-authored pitch text routinely names specific
    universities near a hotel (e.g. "Marmara Üniversitesi, Ticaret
    Üniversitesi vb. civar okullarına"), and feeding that into canonicalize()
    would produce false-positive campus matches. This is a hard requirement,
    not an optimization.

    Concatenates all inbound message content in chronological order (the
    order `messages` is already in) so a lead who splits their university
    mention across multiple messages — e.g. "Topkapı üniversitesi" in one
    message, "Altunizade kampüsü" in a later one — is still seen as a single
    phrase by canonicalize()'s n-gram/token-containment matchers.

    Returns None when there is no inbound text to scan; the caller falls
    back to the LLM's own university_mention / attributes.university guess.
    """
    parts = [
        (msg.content or "").strip()
        for msg in messages
        if msg.message_type == "inbound" and (msg.content or "").strip()
    ]
    if not parts:
        return None
    return " ".join(parts)


def resolve_university_override(
    proposed_uni: str,
    mention: Optional[str],
    label_map: list[tuple[uuid.UUID, str]],
    universe: UniversityUniverse,
    mention_is_authoritative: bool = False,
) -> str:
    """
    Pure option-3 decision (spec 027, Mode C; corrected by spec 028.1): the
    university string the Router should feed into merge_attributes. No I/O
    — fully unit-testable.

    proposed_uni: the LLM's own attributes.university guess (the "belt").
    mention: the university phrase to canonicalize against. As of spec
        028.1 this is normally the Router's own deterministic scan of the
        lead's inbound messages (see extract_university_phrase_from_messages),
        falling back to the LLM's optional university_mention echo only when
        the deterministic scan finds nothing.
    mention_is_authoritative: True when `mention` is that deterministic scan
        result (not an LLM echo, and not a fallback onto proposed_uni
        itself). Only the caller knows this — resolve_university_override
        cannot infer it from the string alone.

    Precedence:
    - A confident CAMPUS canonicalization always wins (translated to its
      Chatwoot list value via label_map). Unaffected by authoritativeness.
    - A PARENT_ONLY canonicalization:
        - When `mention_is_authoritative` is True: forces bilinmiyor-kampus
          UNCONDITIONALLY. The lead named a multi-campus institution without
          a resolvable campus — per product policy (2026-07-15) this must
          withhold even when the belt happens to be a well-formed,
          independently-resolvable campus value, because that belt value is
          not grounded in anything the lead actually said (it is exactly
          the class of hallucination this fix exists to catch — see
          docs/028_tagAssigner_bugFixes_2.md §1 and
          docs/028.1_tagAssigner_bugFixes_2_corrected.md §0).
        - Otherwise (LLM-echo fallback, spec 027 behavior unchanged): forces
          bilinmiyor-kampus ONLY when the belt itself has nothing specific
          either — a stale or ambiguous echo must never downgrade an
          already-confident, independently-resolvable belt guess.
    - Otherwise (NONE, or mention is a sentinel/absent), the belt is used
      as-is; when mention is a sentinel this falls back to canonicalizing
      off proposed_uni itself (the safety net for providers/prompts that
      don't populate `university_mention`).
    """
    used_authoritative = (
        mention_is_authoritative
        and mention is not None
        and mention.strip() not in _UNI_SENTINELS
    )

    canon_mention = mention if mention and mention.strip() not in _UNI_SENTINELS else proposed_uni
    if canon_mention.strip() in _UNI_SENTINELS:
        return proposed_uni

    canon_result = canonicalize(canon_mention, universe)

    if canon_result.confidence == CanonConfidence.CAMPUS:
        canon_list_value = next(
            (lv for uid, lv in label_map if uid == canon_result.university_id), None
        )
        return canon_list_value if canon_list_value is not None else proposed_uni

    if canon_result.confidence == CanonConfidence.PARENT_ONLY:
        if used_authoritative:
            return UNIVERSITY_CAMPUS_AMBIGUOUS
        belt_resolves = (
            proposed_uni.strip() not in _UNI_SENTINELS
            and resolve_university_list_value(proposed_uni, label_map).university_id is not None
        )
        return proposed_uni if belt_resolves else UNIVERSITY_CAMPUS_AMBIGUOUS

    return proposed_uni


# ---------------------------------------------------------------------------
# Module-level TTL cache — the universe is static-ish DB data (universities,
# aliases, campus map). At 10-20k conversations/sweep this must be loaded
# once, not per conversation.
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 600
_cached_universe: Optional[UniversityUniverse] = None
_cached_at: float = 0.0


async def get_university_universe(force_refresh: bool = False) -> UniversityUniverse:
    """Return the cached matching universe, refreshing if the TTL has elapsed."""
    global _cached_universe, _cached_at

    now = time.monotonic()
    if not force_refresh and _cached_universe is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
        return _cached_universe

    from app.db import queries

    universities = await queries.get_all_universities()
    aliases = await queries.get_all_university_aliases()
    parent_map = await queries.get_all_university_parent_map()

    _cached_universe = _build_universe(universities, aliases, parent_map)
    _cached_at = now
    return _cached_universe


def reset_universe_cache() -> None:
    """Clear the cached universe (for tests and config reload)."""
    global _cached_universe, _cached_at
    _cached_universe = None
    _cached_at = 0.0
