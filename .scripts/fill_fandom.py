#!/usr/bin/env python3
"""Set #fandom on books that have none, where their own tags already say it.

Sixteen books in the Fanfiction library carry no fandom at all, which makes
them invisible to every fandom filter and leaves major_characters.py unable
to attribute the people in them. Most of those books answer the question
themselves: a tag reading "Romance.Ranma 1/2.Ranma Saotome/Akane Tendo" is
not ambiguous about which fandom it belongs to.

Only books with an EMPTY #fandom are touched, so this can never argue with a
fandom that was set deliberately. Books whose tags say nothing useful are
reported and left alone.

Two of the rules go one step past the tag: Tortall's tags name the setting
but not which series, and Keladry of Mindelan and Alanna the Lioness are each
the protagonist of exactly one of them. That inference is called out in the
dry run so it can be checked rather than trusted.

Usage (from server/, where config.toml lives):
    python ../.scripts/fill_fandom.py                 # dry run
    python ../.scripts/fill_fandom.py --apply
    python ../.scripts/fill_fandom.py --rollback fandom-rollback-<n>.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402

FIELD = "#fandom"

# Tag prefix -> the #fandom value it settles. Longest match wins, so the
# character-specific Tortall rules are consulted before the plain one.
FROM_TAG = {
    "Romance.Tortall.Keladry of Mindelan": "Tortall.Protector of the Small",
    "Romance.Tortall.Alanna the Lioness": "Tortall.Song of the Lioness",
    "Romance.Ranma 1/2.": "Ranma 1/2",
    "Powers.Specific.Worm.": "Worm",
}


def fandom_from_tags(tags: list[str]) -> str | None:
    """The fandom this book's own tags name, if any of them do."""
    for prefix in sorted(FROM_TAG, key=len, reverse=True):
        if any(t.startswith(prefix) for t in tags):
            return FROM_TAG[prefix]
    return None


def transform(existing: list[str], meta: dict) -> list[str]:
    # Never argue with a fandom already recorded — this fills gaps only.
    if existing:
        return existing
    found = fandom_from_tags(meta.get("tags") or [])
    return [found] if found else existing


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    raise SystemExit(_tagtool.run(ap.parse_args(), transform,
                                  "fandom-rollback", FIELD))
