#!/usr/bin/env python3
"""
alias_collision_check.py
========================
Automated collision / shadow detector for university_aliases, run against the
REAL normalize() function and the REAL database rows. This exists because the
diacritic-normalization fix (normalize both sides of the alias comparison)
activated ~200 previously-dead aliases at once; this script proves none of them
collide, shadow each other, or get shadowed by a university name.

WHAT IT CHECKS
--------------
C1  Cross-target normalized collisions:
      two aliases that normalize to the SAME string but point to DIFFERENT
      targets. This is a hard bug — the matcher returns whichever it hits first,
      so one target becomes unreachable. MUST be empty.

C2  Redundant normalized duplicates (WARN, not fail):
      two aliases that normalize to the same string AND point to the same target.
      Harmless (e.g. "itü" and "İTÜ" both -> parent İTÜ), but reported so the list
      can be trimmed if desired.

C3  Name-shadow (alias made unreachable by Tier 1):
      an alias whose normalized form equals normalize(university.name). Tier 1
      (full-name exact) runs before the alias tier, so such an alias never fires.
      If the alias points somewhere OTHER than that name's university, it is a
      silent dead alias. MUST be empty (or every hit must be self-consistent).

C4  Short-name awareness (INFO only):
      an alias whose normalized form equals normalize(university.short_name).
      After the fix, aliases win over short_name (Tier 2 before Tier 3), so this
      is no longer a bug — reported for awareness only.

C5  Empty normalization:
      an alias that normalizes to an empty string (would match nothing / match
      everything depending on caller). MUST be empty.

C6  Raw duplicate aliases:
      exact duplicate alias strings. The UNIQUE constraint should already prevent
      these; this is a belt-and-suspenders check in case the constraint was
      dropped during a migration.

C7  Common-word / corpus collisions (WARN, not fail) — added for
    UNIVERSITY_ACCURACY_PLAN.md WS1:
      a bare single-token alias whose normalized form is an ordinary Turkish
      word (TURKISH_COMMON_WORD_STOPLIST). These can hijack the n-gram scan
      on unrelated messages (e.g. "bilgi" = "information", present in nearly
      every greeting, used to hijack matches meant for other universities —
      see migrations/026_alias_hygiene.sql). WARN, not HARD: some overlaps
      are intentional (e.g. "istanbul" -> İstanbul Üniversitesi). Human
      judgment decides the remedy; this only surfaces candidates.

C8  university_short_name common-word collisions (INFO only):
      same hijack risk as C7 but via Tier 1 exact match against
      universities.university_short_name, independent of the alias table
      (e.g. "SU" -> Sabancı, "YÜ" -> Yeditepe — genuine real-world
      abbreviations, not alias-table junk; deleting an alias row would be a
      no-op here). INFO only — flagged for a human decision, never
      auto-remediated, since Tier 1 is the lookup path for every
      short_name in the system.

USAGE
-----
    export DATABASE_URL='postgresql://...'          # the ChatBot DB
    python3 alias_collision_check.py

    # Optional: dump every normalized group for manual eyeballing
    python3 alias_collision_check.py --verbose

EXIT CODE
---------
    0  all hard checks (C1, C3, C5, C6) passed
    1  at least one hard check failed  (suitable for CI)

ADJUST BEFORE RUNNING
---------------------
  * NORMALIZE_IMPORT: point this at wherever normalize() actually lives in the
    project so the test runs against the REAL function, not a copy. If the import
    fails, the script falls back to a VENDORED copy of normalize() that MUST be
    kept identical to the production one (see _vendored_normalize).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import asyncpg
except ImportError:
    sys.exit("asyncpg is required:  pip install asyncpg --break-system-packages")


# ---------------------------------------------------------------------------
# Import the REAL normalize(). Adjust this import to your project layout.
# Testing best practice: exercise the production function, never a re-implementation.
# ---------------------------------------------------------------------------
NORMALIZE_IMPORT_CANDIDATES = [
    "app.layers.matching",   # confirmed: normalize() and match_university() both live here
]

normalize = None
for _mod in NORMALIZE_IMPORT_CANDIDATES:
    try:
        _m = __import__(_mod, fromlist=["normalize"])
        normalize = getattr(_m, "normalize")
        print(f"[info] using real normalize() from {_mod}")
        break
    except Exception:
        continue

if normalize is None:
    # ---- VENDORED FALLBACK ----------------------------------------------
    # Keep this byte-for-byte identical to production normalize(). If they ever
    # diverge, this test gives false confidence. Prefer fixing the import above.
    _DIACRITIC_MAP = str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    })
    _SUFFIXES = [" universitesi", " uni", " kampusu", " yerleskesi"]

    def _vendored_normalize(text: str) -> str:
        text = text.replace("İ", "i").replace("I", "ı")
        text = text.lower().translate(_DIACRITIC_MAP).strip()
        for suffix in _SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
        return text

    normalize = _vendored_normalize
    print("[warn] real normalize() import failed — using VENDORED copy. "
          "Verify it matches production before trusting results.")


# ---------------------------------------------------------------------------
# C7/C8 stoplist — ordinary Turkish words / particles that must never be a
# BARE single-token university signal (they hijack unrelated messages).
# Seeded from the greeting/boilerplate vocabulary + general high-frequency
# words. Extend this list rather than hardcoding new one-off exceptions.
# ---------------------------------------------------------------------------
TURKISH_COMMON_WORD_STOPLIST: frozenset[str] = frozenset({
    "bilgi", "bir", "su", "ve", "veya", "icin", "var", "yok", "okul",
    "yurt", "oda", "kiz", "erkek", "merkez", "guney", "kuzey", "dogu",
    "bati", "teknik", "yeni", "eski", "iyi", "kotu", "evet", "hayir",
    "tamam", "lutfen", "tesekkur", "merhaba", "selam", "nasil", "ne",
    "kim", "ben", "sen", "biz", "siz", "bu", "o", "da", "de",
    "ki", "mi", "mu", "ama", "fakat", "ile", "gibi", "cok", "az",
})


def find_stoplist_alias_collisions(aliases, normalize_fn) -> list:
    """Pure C7 detection logic, extracted for unit testing without a DB.

    Returns the subset of `aliases` (dict-likes with an 'alias' key) whose
    normalized form is a single token AND is in TURKISH_COMMON_WORD_STOPLIST.
    """
    hits = []
    for a in aliases:
        n = normalize_fn(a["alias"])
        if not n or " " in n:
            continue  # only single-token aliases can hijack a bare word
        if n in TURKISH_COMMON_WORD_STOPLIST:
            hits.append(a)
    return hits


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
async def fetch(conn):
    aliases = await conn.fetch(
        "SELECT alias, university_id, parent_university_id FROM university_aliases"
    )
    unis = await conn.fetch(
        "SELECT id, name, university_short_name FROM universities"
    )
    return aliases, unis


def target_of(row) -> str:
    """A stable string describing what an alias points at, for equality checks."""
    if row["university_id"] is not None:
        return f"campus:{row['university_id']}"
    if row["parent_university_id"] is not None:
        return f"parent:{row['parent_university_id']}"
    return "NULL"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def run_checks(aliases, unis, verbose=False):
    failures = 0
    warnings = 0

    # Pre-compute normalized groupings
    by_norm = defaultdict(list)          # normalized -> [alias_row, ...]
    raw_seen = defaultdict(list)         # raw alias -> [alias_row, ...]
    for a in aliases:
        n = normalize(a["alias"])
        by_norm[n].append(a)
        raw_seen[a["alias"]].append(a)

    name_norm = {}   # normalized name -> uni_id
    short_norm = {}  # normalized short_name -> uni_id
    for u in unis:
        name_norm[normalize(u["name"])] = u["id"]
        if u["university_short_name"]:
            short_norm.setdefault(normalize(u["university_short_name"]), u["id"])

    print("\n" + "=" * 72)
    print("ALIAS COLLISION & SHADOW REPORT")
    print("=" * 72)
    print(f"aliases: {len(aliases)}   universities: {len(unis)}   "
          f"distinct normalized forms: {len(by_norm)}")

    # ---- C1: cross-target collisions (HARD) ------------------------------
    print("\n[C1] Cross-target normalized collisions (MUST be empty)")
    c1 = 0
    for n, rows in sorted(by_norm.items()):
        targets = {target_of(r) for r in rows}
        if len(targets) > 1:
            c1 += 1
            failures += 1
            print(f"  ✗ '{n}' <- " +
                  ", ".join(f"{r['alias']}→{target_of(r)}" for r in rows))
    if c1 == 0:
        print("  ✓ none")

    # ---- C2: redundant duplicates (WARN) ---------------------------------
    print("\n[C2] Redundant normalized duplicates (WARN — harmless, trim if noisy)")
    c2 = 0
    for n, rows in sorted(by_norm.items()):
        if len(rows) > 1 and len({target_of(r) for r in rows}) == 1:
            c2 += 1
            warnings += 1
            if verbose:
                print(f"  ~ '{n}' ← {', '.join(r['alias'] for r in rows)} "
                      f"(all → {target_of(rows[0])})")
    print(f"  ~ {c2} redundant group(s)" + (" (use --verbose to list)" if c2 and not verbose else ""))

    # ---- C3: name-shadow (HARD) ------------------------------------------
    print("\n[C3] Aliases shadowed by a full university NAME (Tier 1) (MUST be empty)")
    c3 = 0
    for a in aliases:
        n = normalize(a["alias"])
        if n in name_norm:
            shadow_uni = name_norm[n]
            # Only a problem if the alias points somewhere ELSE than that name's uni
            if target_of(a) != f"campus:{shadow_uni}":
                c3 += 1
                failures += 1
                print(f"  ✗ '{a['alias']}' (→{target_of(a)}) is shadowed by "
                      f"university name whose id={shadow_uni}; alias will NEVER fire")
    if c3 == 0:
        print("  ✓ none")

    # ---- C4: short-name overlap (INFO) -----------------------------------
    print("\n[C4] Aliases overlapping a short_name (INFO — alias wins post-fix)")
    c4 = 0
    for a in aliases:
        n = normalize(a["alias"])
        if n in short_norm:
            c4 += 1
            if verbose:
                print(f"  i '{a['alias']}' overlaps short_name of uni={short_norm[n]} "
                      f"→ alias (Tier 2) correctly wins")
    print(f"  i {c4} overlap(s)" + (" (use --verbose to list)" if c4 and not verbose else ""))

    # ---- C5: empty normalization (HARD) ----------------------------------
    print("\n[C5] Aliases that normalize to empty (MUST be empty)")
    c5 = 0
    for a in aliases:
        if normalize(a["alias"]) == "":
            c5 += 1
            failures += 1
            print(f"  ✗ '{a['alias']}' normalizes to empty string")
    if c5 == 0:
        print("  ✓ none")

    # ---- C7: common-word / corpus collisions (WARN — human review) -------
    # UNIVERSITY_ACCURACY_PLAN.md WS1. A bare single-token alias that is
    # itself an ordinary Turkish word (or a fragment of one) can hijack the
    # n-gram scan on unrelated messages — e.g. "bilgi" ("information") sits
    # in almost every greeting and used to hijack matches meant for other
    # universities before it was re-scoped to "bilgi üniversitesi" (see
    # migrations/026_alias_hygiene.sql). This is WARN, not HARD: some short
    # aliases are deliberately kept even though they overlap common words
    # (e.g. "istanbul" -> İstanbul Üniversitesi is an intentional broad
    # parent alias — see canonicalize()'s docstring in
    # app/tagassigner/university_canonicalizer.py). Human judgment decides
    # the remedy (delete / lengthen / keep); this check only surfaces
    # candidates so a collision isn't discovered the hard way again.
    print("\n[C7] Single-token aliases overlapping common Turkish words (WARN — review)")
    c7_hits = find_stoplist_alias_collisions(aliases, normalize)
    for a in c7_hits:
        warnings += 1
        print(f"  ~ '{a['alias']}' (normalized {normalize(a['alias'])!r}) -> {target_of(a)} "
              f"is a common Turkish word — verify it can't hijack unrelated messages")
    if not c7_hits:
        print("  ✓ none")

    # ---- C8: university_short_name common-word collisions (INFO) ---------
    # Same hijack risk as C7, but via Tier 1 (exact match against
    # universities.university_short_name) rather than the alias table.
    # Discovered while implementing WS1: "su" (Sabancı, short_name "SU") and
    # "yu"/"yü" (Yeditepe, short_name "YÜ") are NOT alias-table rows at all —
    # deleting an alias would be a no-op. These are genuine real-world
    # abbreviations, not junk data, and Tier 1 is the lookup path for every
    # short_name in the system (KHAS, BOUN, GSU, ...), so silently
    # special-casing it here is out of scope. INFO only — flagged for a
    # human decision, never auto-remediated.
    print("\n[C8] university_short_name values overlapping common Turkish words (INFO)")
    c8 = 0
    for u in unis:
        sn = u["university_short_name"]
        if not sn:
            continue
        n = normalize(sn)
        if " " in n or not n:
            continue
        if n in TURKISH_COMMON_WORD_STOPLIST:
            c8 += 1
            print(f"  i university_short_name={sn!r} (normalized {n!r}) on uni={u['id']} "
                  f"({u['name']}) collides with a common word via Tier 1 exact match")
    if c8 == 0:
        print("  i none")

    # ---- C6: raw duplicates (HARD) ---------------------------------------
    print("\n[C6] Exact-duplicate raw aliases (UNIQUE should prevent) (MUST be empty)")
    c6 = 0
    for raw, rows in raw_seen.items():
        if len(rows) > 1:
            c6 += 1
            failures += 1
            print(f"  ✗ '{raw}' appears {len(rows)} times")
    if c6 == 0:
        print("  ✓ none")

    if verbose:
        print("\n[--verbose] every normalized group:")
        for n, rows in sorted(by_norm.items()):
            print(f"  {n!r:30} ← {', '.join(r['alias'] for r in rows)}")

    print("\n" + "=" * 72)
    print(f"RESULT: {failures} hard failure(s), {warnings} warning(s)")
    print("=" * 72)
    return failures


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Set DATABASE_URL to the ChatBot Postgres DSN.")

    conn = await asyncpg.connect(dsn)
    try:
        aliases, unis = await fetch(conn)
    finally:
        await conn.close()

    failures = run_checks(aliases, unis, verbose=args.verbose)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
