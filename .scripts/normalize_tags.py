#!/usr/bin/env python3
"""Normalise misspelled and inconsistent names inside the Fanfiction tags.

The tag scheme puts a character in the last segment of almost every facet, so
the same name is retyped once per facet and the typos multiply: "Izuku
Midoriya" is also spelled "Izuku MIdoriya" and "Izuki MIdoriya", and appears
as a leaf under eight different roots. This rewrites the name atoms, leaving
the structure of the vocabulary alone.

A tag is treated as dot-separated segments; a segment may be a "/"-joined
cast list, and each member of that may be an "X!Y" identity compound. Fixes
apply to every atom at every level, so both

    Powers.Generic.Power Borrowing.Izuki MIdoriya
    Romance.Supernatural.Dean Wnchester/OC

are reached without either rule knowing where in a tag it sits.

Only names already attested elsewhere in the library are used as targets, and
the name order follows the library's own majority (Western: "Izuku Midoriya"
107 uses vs "Midoriya Izuku" 3).

Every applied run writes a rollback file mapping each book back to the tag
list it had, so a bad rename is one command to undo.

Usage (from server/, where config.toml lives):
    python ../.scripts/normalize_tags.py                 # dry run
    python ../.scripts/normalize_tags.py --apply
    python ../.scripts/normalize_tags.py --rollback tag-rollback-<n>.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
from ratchet import configfiles  # noqa: E402

# Misspellings, name orders that disagree with the library's majority, and
# surnames with no full form to normalise against. Keys are whole atoms,
# never substrings, so "Sam" cannot eat "Sam Vimes" and "Taylor" cannot eat
# "Taylor Hebert". They describe one library, so they live in
# config/tag_scheme.toml rather than here.
NAME_FIXES = configfiles.require("name_fixes")


def fix_atom(atom: str) -> str:
    """One name, possibly an 'X!Y' identity compound.

    Rebuilt only when one of its names was actually fixed. A '!' is also just
    punctuation in a freeform tag — "good for him! good for him" — and
    splitting that and joining it back up would respace it for nothing.
    """
    if "!" in atom:
        names = [p.strip() for p in atom.split("!")]
        fixed = [NAME_FIXES.get(n, n) for n in names]
        return "!".join(fixed) if fixed != names else atom
    return NAME_FIXES.get(atom, atom)


def fix_segment(seg: str) -> str:
    """One dot-segment, possibly a '/'-joined cast list."""
    return "/".join(fix_atom(p) for p in seg.split("/"))


def fix_tag(tag: str) -> str:
    return ".".join(fix_segment(s) for s in tag.split("."))


def transform(tags: list[str], meta: dict) -> list[str]:
    return [fix_tag(t) for t in tags]


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    raise SystemExit(_tagtool.run(ap.parse_args(), transform, "tag-rollback"))
