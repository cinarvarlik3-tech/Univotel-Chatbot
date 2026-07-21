"""
Router-computed hizmet-veremiyoruz label (TAGASSIGNER_ACCURACY_FIXES_PLAN.md A2).

hizmet-veremiyoruz means "the lead's university is outside Univotel's İstanbul service
area" — geography, and nothing else. Ground truth is a table lookup
(out_of_city_universities), so the LLM gets no say: strip_llm_hizmet_veremiyoruz always
removes Gemini's own proposal, and compute_hizmet_veremiyoruz recomputes the label
deterministically afterward from the resolved label set — mirroring
app.tagassigner.info_check's strip_gemini_info_check / apply_info_check pattern (NOT
fiyat_soruyor/deal_awaiting, which live in a different accuracy-harness registry bucket;
hizmet-veremiyoruz stays in label_resolver.LIST_1_USABLE, so
accuracy_optimization/tagassigner/tagassigner_accuracy.py's frozen LLM_OWNED/ROUTER_OWNED
buckets and their registry-sync test need no change).

Router-authoritative: once this module runs, a human-added hizmet-veremiyoruz label on a
conversation whose university resolves in-city WILL be removed on the next run. This is
intended — geography is objective, not a judgment call — but is a real behavior change,
flagged here so it is never rediscovered as a surprise.

İstanbul-only invariant this module depends on: `universities` / `parent_universities`
hold ONLY İstanbul institutions (verified: all 93 universities rows map into
university_chatwoot_label_map). Out-of-city institutions live exclusively in the separate
`out_of_city_universities` table (148 rows). So "canonicalize() resolved anything other
than NONE" is equivalent to "in-city" — which is why PARENT_ONLY (an İstanbul PARENT
matched, campus still ambiguous) counts as in-city below, not just CAMPUS.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.db.models import OutOfCityUniversity
from app.layers.matching import (
    _ENTITY_SCAN_STOPWORDS,
    levenshtein_distance,
    match_out_of_city,
    normalize,
    scan_ngrams,
)
from app.tagassigner.university_canonicalizer import (
    CanonConfidence,
    UniversityUniverse,
    canonicalize,
)

HIZMET_VEREMIYORUZ_LABEL = "hizmet-veremiyoruz"

# 1-token out-of-city candidates shorter than this are never considered (matches the
# same length floor used by the university-side entity scan guard).
_MIN_1GRAM_LEN = 4

# Locality-fragment fuzzy tolerance — absorbs Turkish inflection ("hisarında" vs "hisarı").
_LOCALITY_FUZZY_MAX_DIST = 3


def strip_llm_hizmet_veremiyoruz(proposed_labels: list[str]) -> list[str]:
    """Remove hizmet-veremiyoruz if the LLM proposed it — the Router recomputes it
    deterministically afterward (mirrors strip_gemini_info_check)."""
    return [l for l in proposed_labels if l != HIZMET_VEREMIYORUZ_LABEL]


@dataclass(frozen=True)
class OutOfCityIndex:
    """
    Derived, data-driven state the out-of-city scan needs — built fresh from the
    university universe + out-of-city table each call (a few dozen universities / a few
    hundred out-of-city rows: cheap enough that a TTL cache alongside UniversityUniverse
    is not warranted unless profiling says otherwise).
    """
    localities: tuple[str, ...]
    istanbul_tokens: frozenset[str]
    ooc_full_names: frozenset[str]


def _derive_istanbul_localities(universe: UniversityUniverse) -> tuple[str, ...]:
    """
    2-3 token fragments (normalized) shared by universities under 2+ DISTINCT parents —
    a shared place name (campus locality / district), not a discriminating university
    identifier. E.g. "anadolu hisari" is a fragment of both a Boğaziçi and a Marmara
    campus name, so it must never, alone, be read as the out-of-city Anadolu
    Üniversitesi.

    Owner-of-university = its parent_university_id (inverted from campuses_by_parent),
    falling back to the university's own id when unmapped (defensive; every university in
    this schema has a parent_map row today).
    """
    owner_by_uni: dict[uuid.UUID, uuid.UUID] = {}
    for parent_id, campuses in universe.campuses_by_parent.items():
        for campus in campuses:
            owner_by_uni[campus.university_id] = parent_id

    fragment_owners: dict[str, set[uuid.UUID]] = {}
    for uni in universe.universities:
        owner = owner_by_uni.get(uni.id, uni.id)
        tokens = normalize(uni.name).split()
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                fragment_owners.setdefault(" ".join(tokens[i : i + n]), set()).add(owner)

    return tuple(sorted(f for f, owners in fragment_owners.items() if len(owners) >= 2))


def _derive_istanbul_tokens(universe: UniversityUniverse) -> frozenset[str]:
    """Single normalized tokens appearing in any İstanbul university name/short-name —
    the data-derived exclusion set for the 1-gram out-of-city scan (condition d)."""
    tokens: set[str] = set()
    for uni in universe.universities:
        tokens |= set(normalize(uni.name).split())
        if uni.university_short_name:
            tokens |= set(normalize(uni.university_short_name).split())
    return frozenset(tokens)


def build_out_of_city_index(
    universe: UniversityUniverse,
    out_of_city: list[OutOfCityUniversity],
) -> OutOfCityIndex:
    return OutOfCityIndex(
        localities=_derive_istanbul_localities(universe),
        istanbul_tokens=_derive_istanbul_tokens(universe),
        ooc_full_names=frozenset(normalize(u.name) for u in out_of_city if u.name),
    )


def _locality_masked_positions(tokens: list[str], localities: tuple[str, ...]) -> set[int]:
    """Token positions covered by a matched locality fragment — masked from the 1-gram
    scan. Token-scoped (not text-scoped): a locality fragment like "tip fakultesi" only
    masks THOSE tokens, so "Hacettepe Tıp Fakültesi" still finds Hacettepe via its own,
    unmasked token."""
    masked: set[int] = set()
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i : i + n])
            for loc in localities:
                if gram == loc or levenshtein_distance(gram, loc) <= _LOCALITY_FUZZY_MAX_DIST:
                    masked.update(range(i, i + n))
                    break
    return masked


def _match_out_of_city_exact(
    token: str, out_of_city: list[OutOfCityUniversity]
) -> Optional[OutOfCityUniversity]:
    normalized = normalize(token)
    if not normalized:
        return None
    for uni in out_of_city:
        if normalize(uni.name) == normalized:
            return uni
        if uni.short_name and normalize(uni.short_name) == normalized:
            return uni
    return None


def scan_out_of_city(
    text: str,
    out_of_city: list[OutOfCityUniversity],
    index: OutOfCityIndex,
) -> Optional[OutOfCityUniversity]:
    """
    Two-tier out-of-city scan (TAGASSIGNER_ACCURACY_FIXES_PLAN.md amendments 1/6/10):

    1. 2+ NORMALIZED-token candidates may use match_out_of_city's existing exact +
       Levenshtein behavior. A raw 2-5 word window is only trusted here if it still has
       >=2 tokens AFTER normalize() (which strips a trailing suffix word like
       "üniversitesi") — e.g. "biruni universitesi" collapses to the single token
       "biruni" and is EXCLUDED from this tier, because fuzzy matching on that single
       token false-positived onto İzmir Tınaztepe's short_name "İTÜNİ" at distance 2, and
       Biruni is an İstanbul university.
    2. Bare 1-token candidates require ALL of:
       (a) EXACT match only, no Levenshtein — `_get_levenshtein_cutoff` returns 0 for
           length <= 3 so a short exact match like "bu" == normalize("BÜ") (Bingöl) would
           otherwise survive; length/stoplist below is what actually kills it.
       (b) normalized length >= 4;
       (c) not an _ENTITY_SCAN_STOPWORDS common Turkish word;
       (d) not a token of any İstanbul university/short-name, UNLESS the token is itself
           the complete normalized name of an out-of-city university — this lets bare
           "anadolu" resolve to Anadolu Üniversitesi (a real out-of-city lead) while still
           blocking generic tokens like "boun"/"marmara".
       Locality-masked token positions (see _locality_masked_positions) are skipped
       entirely regardless of (a)-(d) — this is what keeps a bare "Anadolu Hisarı" (a
       Boğaziçi/Marmara campus locality) from ever being read as the out-of-city Anadolu
       Üniversitesi, while "Boğaziçi Anadolu Hisarı" / "Marmara Anadolu Hisarı" still
       resolve to their real İstanbul campuses via the canonicalizer upstream (in-city
       short-circuit in compute_hizmet_veremiyoruz never even reaches this scan).
    """
    for cand in scan_ngrams(text, min_n=2, max_n=5):
        if len(normalize(cand).split()) < 2:
            continue
        hit = match_out_of_city(cand, out_of_city)
        if hit is not None:
            return hit

    tokens = normalize(text).split()
    masked = _locality_masked_positions(tokens, index.localities)
    for i, tok in enumerate(tokens):
        if i in masked:
            continue
        if len(tok) < _MIN_1GRAM_LEN:
            continue
        if tok in _ENTITY_SCAN_STOPWORDS:
            continue
        if tok in index.istanbul_tokens and tok not in index.ooc_full_names:
            continue
        hit = _match_out_of_city_exact(tok, out_of_city)
        if hit is not None:
            return hit
    return None


def _is_in_city(
    inbound_phrase: Optional[str],
    universe: UniversityUniverse,
    conv_university_id: Optional[uuid.UUID],
) -> bool:
    """
    In-city iff canonicalize(inbound) resolves CAMPUS or PARENT_ONLY (an İstanbul PARENT
    matched — see the İstanbul-only invariant in this module's docstring) OR the
    conversation already has a written university_id.

    Deliberately NOT keyed off resolved_uni_id / merge_result.university_id from the
    Router's Mode C override — those diverge from reality exactly when the merge was
    BLOCKED (human_set, campus_ambiguous), which is precisely the case this must survive.
    When in doubt, suppress: falsely applying hizmet-veremiyoruz on a sellable İstanbul
    lead is the expensive error; falsely missing it is cheap wasted follow-up.
    """
    if conv_university_id is not None:
        return True
    if not inbound_phrase or not inbound_phrase.strip():
        return False
    canon = canonicalize(inbound_phrase, universe)
    return canon.confidence in (CanonConfidence.CAMPUS, CanonConfidence.PARENT_ONLY)


def compute_hizmet_veremiyoruz(
    inbound_phrase: Optional[str],
    universe: UniversityUniverse,
    out_of_city: list[OutOfCityUniversity],
    conv_university_id: Optional[uuid.UUID],
    labels: list[str],
) -> list[str]:
    """
    Add/remove hizmet-veremiyoruz in the desired label set, deterministically. `labels`
    must already have the LLM's own proposal stripped (strip_llm_hizmet_veremiyoruz) —
    this function is the sole authority on whether the label survives.

    inbound_phrase: the Router's own deterministic inbound scan (same value used for the
    Mode C university override — app.tagassigner.university_canonicalizer.
    extract_university_phrase_from_messages) — never an LLM echo.
    """
    result = set(labels)
    result.discard(HIZMET_VEREMIYORUZ_LABEL)

    if _is_in_city(inbound_phrase, universe, conv_university_id):
        return sorted(result)

    if inbound_phrase and inbound_phrase.strip():
        index = build_out_of_city_index(universe, out_of_city)
        if scan_out_of_city(inbound_phrase, out_of_city, index) is not None:
            result.add(HIZMET_VEREMIYORUZ_LABEL)

    return sorted(result)
