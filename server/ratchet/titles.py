"""Chapter title normalization, shared by the epub reader and the site fetch.

Titles are compared between the local epub and the site to report retitles.
The two sources escape and space them differently — FanFicFare's JSON metadata
keeps raw HTML entities ("Intro &amp; Roses") while the epub may hold either
form — so both sides are normalized through here before comparison. Without
it, every check reports phantom retitles.

Purely cosmetic: titles never affect an update decision (chapter *keys* do).
"""

from __future__ import annotations

import html
import re


def normalize_title(raw: str) -> str:
    """Unescape HTML entities and collapse whitespace."""
    if not raw:
        return ""
    text = html.unescape(raw)
    # Entities can be double-escaped ("&amp;amp;") when a title round-trips
    # through two writers; one more pass settles it.
    if "&" in text:
        text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# Typographic variants that sites and epubs swap freely. Comparing them as
# equal keeps "the author changed a straight quote to a curly one" out of the
# retitle report; displayed titles keep whatever the source actually had.
_PUNCT_FOLD = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"',
    0x2013: "-", 0x2014: "-", 0x2015: "-", 0x2212: "-",
    0x2026: "...", 0x00A0: " ",
}


def title_key(raw: str) -> str:
    """Comparison form of a title: punctuation-variant- and case-insensitive
    enough that only real retitles are reported."""
    return normalize_title(raw).translate(_PUNCT_FOLD)
