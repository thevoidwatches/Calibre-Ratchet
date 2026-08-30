#!/usr/bin/env python3
"""Structural tidy-up of the Fanfiction tag vocabulary.

Four unrelated jobs, run together because each one is a handful of books and
they all rewrite the same column:

1. Flat pseudo-roots become branches. Eleven top-level roots held a single
   flat value each, which made the picker's first level twice as long as the
   number of real facets. They move under Content (what the story contains),
   Format (how it is presented) and Tropes (premises the story is built on,
   which is what Bed-Sharing and Friends to Lovers already are).

2. Character Traits.Relative entries that skipped the relationship level.
   Three books named a person with no relationship, and one doubled the name.

3. Names still abbreviated to a surname. normalize_tags.py expanded the ones
   with a full form already in the library; these four had none, which left
   "Rescued By.Marge Dursley" sitting next to "Rescued By.Snape".

4. Time Travel books whose #genre records a subtype the tags never got. The
   tag root only ever grew a Peggy Sue branch, so Backward, Forward and Time
   Loop had nowhere to go. The subtype is copied across only when the book
   has no tag on that branch already; the character and body-swap detail
   underneath it still has to be filled in by hand, per book.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402

# 1. Roots that were a single flat value, and where they belong.
ROOT_MOVES = {
    "Erotica": "Content.Erotica",
    "Polyamory": "Content.Polyamory",
    "OC Main Character": "Content.OC Main Character",
    "Novelization": "Format.Novelization",
    "Illustrated": "Format.Illustrated",
    "Recursive Fic": "Format.Recursive Fic",
    "Rewrite": "Format.Rewrite",
    "Reader Insert": "Format.Reader Insert",
    "Soul Bond": "Tropes.Soul Bond",
    "Penpals": "Tropes.Penpals",
}

# 2 and 3. Whole tags that need a specific hand-written replacement.
EXACT = {
    # Tagged with the wrong character: the miko in Constellations is Taylor,
    # not Harry, and the book is an Okami x Worm crossover with no Harry
    # Potter fandom on it at all.
    "Jobs.Generic.Miko.Harry Potter": "Jobs.Generic.Miko.Taylor Hebert",
    "Character Traits.Relative.Yandere.Taylor Hebert.Taylor Hebert":
        "Character Traits.Relative.Yandere.Taylor Hebert",
    "Character Traits.Relative.Miss Militia":
        "Character Traits.Relative.Transphobic.Miss Militia",
    "Character Traits.Relative.Armsmaster":
        "Character Traits.Relative.Uncle.Armsmaster",
    "Character Traits.Relative.Jack Slash":
        "Character Traits.Relative.Uncle.Jack Slash",
}

# Surnames with no full form anywhere in the library to normalise against.
SURNAMES = {
    "Snape": "Severus Snape",
    "McGonagall": "Minerva McGonagall",
    "Moody": "Alastor Moody",
    "Hagrid": "Rubeus Hagrid",
}

# 4. Genre subtypes worth carrying over to the tags.
TIME_TRAVEL_SUBTYPES = ["Time Travel.Peggy Sue", "Time Travel.Backward",
                        "Time Travel.Forward", "Time Travel.Time Loop"]


def rewrite(tag: str) -> str:
    if tag in EXACT:
        return EXACT[tag]
    segs = [SURNAMES.get(s, s) for s in tag.split(".")]
    tag = ".".join(segs)
    for old, new in ROOT_MOVES.items():
        if tag == old:
            return new
        if tag.startswith(old + "."):
            return new + tag[len(old):]
    return tag


def transform(tags: list[str], meta: dict) -> list[str]:
    out = [rewrite(t) for t in tags]
    genres = ((meta.get("user_metadata") or {}).get("#genre") or {}).get("#value#") or []
    for sub in TIME_TRAVEL_SUBTYPES:
        # The genre names this kind of time travel and no tag sits on that
        # branch yet. A bare branch tag is the honest placeholder: which
        # character travels, and into whose body, cannot be inferred here.
        if sub in genres and not any(t == sub or t.startswith(sub + ".") for t in out):
            out.append(sub)
    return out


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    raise SystemExit(_tagtool.run(ap.parse_args(), transform, "regroup-rollback"))
