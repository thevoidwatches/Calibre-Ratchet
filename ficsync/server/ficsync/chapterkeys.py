"""Canonical chapter identity keys.

The safety layer compares chapters by *identity*, not by URL string or title.
Titles get edited; Royal Road chapter URLs embed title slugs that change on
retitle. Both sites embed a stable numeric chapter ID in the URL, so we reduce
every chapter URL to a site-prefixed key built from that ID.

This mirrors what FanFicFare itself does internally: its adapters normalize
chapter URLs before matching old epub chapters against the site's current list
(base_adapter.py normalize_chapterurl, verified in FFF 4.60.0). We just do it
one layer up so the pre-flight diff is slug- and scheme-insensitive.

Unknown sites fall back to a normalized URL string, which is correct as long
as that site's chapter URLs are stable. If you add a site whose URLs mutate,
add a pattern here.
"""

from __future__ import annotations

import re

# Royal Road long form: /fiction/<fid>/<slug>/chapter/<cid>/<slug>
# short form:           /fiction/chapter/<cid>
# (Pattern adapted from FFF 4.60.0 adapter_royalroadcom.py, which accepts both.)
_RR_RE = re.compile(
    r"https?://(?:www\.)?royalroadl?\.com/fiction(?:/\d+/[^/]+)?/chapter/(\d+)(?:/[^/]+)?/?$",
    re.IGNORECASE,
)

# AO3 chapter URL: /works/<wid>/chapters/<cid>, optionally with ?view_adult=true.
# AO3 one-shots also get a /chapters/<cid> URL via the /navigate page
# (verified in FFF 4.60.0 base_otw_adapter.py), so this covers them too.
_AO3_RE = re.compile(
    r"https?://(?:www\.)?archiveofourown\.org(?:/collections/[^/]+)?/works/\d+/chapters/(\d+)",
    re.IGNORECASE,
)

# AO3 work URL without a chapter component (defensive; not expected from FFF).
_AO3_WORK_RE = re.compile(
    r"https?://(?:www\.)?archiveofourown\.org(?:/collections/[^/]+)?/works/(\d+)/?(?:\?.*)?$",
    re.IGNORECASE,
)


def canonical_key(url: str) -> str:
    """Reduce a chapter URL to a stable identity key."""
    url = url.strip()
    m = _RR_RE.match(url)
    if m:
        return f"rr:{m.group(1)}"
    m = _AO3_RE.match(url)
    if m:
        return f"ao3:{m.group(1)}"
    m = _AO3_WORK_RE.match(url)
    if m:
        return f"ao3work:{m.group(1)}"
    # Fallback: scheme/host-normalized URL, query and fragment stripped.
    u = re.sub(r"^https?://(www\.)?", "", url)
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return f"url:{u.lower()}"


def site_of(url: str) -> str:
    """Coarse site tag for politeness throttling and reporting."""
    u = url.lower()
    if "royalroad" in u:
        return "royalroad.com"
    if "archiveofourown" in u:
        return "archiveofourown.org"
    m = re.match(r"https?://(?:www\.)?([^/]+)/", u + "/")
    return m.group(1) if m else "unknown"
