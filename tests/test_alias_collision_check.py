"""
Regression tests for docs/alias_collision_check.py's C7 detector
(UNIVERSITY_ACCURACY_PLAN.md WS1).

These test the PURE detection logic against synthetic alias data — no DB
required — so they run in the normal pytest suite. The live-DB sweep
(actually checking today's university_aliases table) is
docs/alias_collision_check.py itself; run it manually before any alias
migration as documented there. There is no CI pipeline in this repo yet to
wire it into automatically (no .github/workflows present).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from app.layers.matching import normalize

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "docs" / "alias_collision_check.py"
_spec = importlib.util.spec_from_file_location("alias_collision_check", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["alias_collision_check"] = _module
_spec.loader.exec_module(_module)

find_stoplist_alias_collisions = _module.find_stoplist_alias_collisions
TURKISH_COMMON_WORD_STOPLIST = _module.TURKISH_COMMON_WORD_STOPLIST


def _alias(text, university_id=None, parent_university_id=None):
    return {"alias": text, "university_id": university_id, "parent_university_id": parent_university_id}


def test_stoplist_contains_the_known_fixed_collisions():
    """Locks in intent: the words fixed by migrations/026_alias_hygiene.sql
    must stay in the stoplist so a future migration can't silently
    reintroduce them as a bare single-token alias."""
    for word in ("bilgi", "bir", "su", "teknik"):
        assert word in TURKISH_COMMON_WORD_STOPLIST


def test_detects_bare_common_word_alias():
    aliases = [_alias("bilgi", parent_university_id="p1")]
    hits = find_stoplist_alias_collisions(aliases, normalize)
    assert len(hits) == 1
    assert hits[0]["alias"] == "bilgi"


def test_naive_university_suffix_replacement_does_NOT_fix_the_collision():
    """Regression lock for a bug caught while implementing WS1: normalize()
    strips a trailing "üniversitesi"/"uni"/"üni" WORD, so "bilgi
    üniversitesi" collapses right back down to bare "bilgi" — identical to
    the collision string. A migration must never use this form as the fix."""
    aliases = [_alias("bilgi üniversitesi", parent_university_id="p1")]
    hits = find_stoplist_alias_collisions(aliases, normalize)
    assert len(hits) == 1, (
        "if this now passes, either normalize() or the stoplist changed — "
        "re-verify migrations/026_alias_hygiene.sql still uses a "
        "non-collapsing replacement form (e.g. 'istanbul bilgi')"
    )


def test_actual_ws1_replacement_forms_do_not_collapse():
    """The real replacement aliases used in migrations/026_alias_hygiene.sql
    ('istanbul bilgi', 'istanbul rumeli') must NOT normalize down to a bare
    stoplist word — that's what makes them an actual fix."""
    aliases = [
        _alias("istanbul bilgi", parent_university_id="p1"),
        _alias("istanbul rumeli", parent_university_id="p2"),
    ]
    hits = find_stoplist_alias_collisions(aliases, normalize)
    assert hits == []


def test_does_not_flag_unambiguous_acronym():
    aliases = [_alias("boun", parent_university_id="p1"), _alias("itu", parent_university_id="p2")]
    hits = find_stoplist_alias_collisions(aliases, normalize)
    assert hits == []


def test_does_not_flag_multitoken_alias_even_if_first_word_is_common():
    aliases = [_alias("güney kampüs", university_id="u1")]
    hits = find_stoplist_alias_collisions(aliases, normalize)
    assert hits == []


@pytest.mark.parametrize("word", ["bilgi", "bir", "su", "teknik"])
def test_bare_form_of_each_fixed_word_is_still_detected(word):
    """If a future migration ever reintroduces one of these as a BARE
    single-token alias, this must catch it."""
    hits = find_stoplist_alias_collisions([_alias(word, parent_university_id="p1")], normalize)
    assert len(hits) == 1
