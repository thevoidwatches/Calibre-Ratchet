#!/usr/bin/env python3
"""Repoint omnibuser-era books at their forum source and re-fetch them.

Books downloaded from the defunct omnibuser.com carry "Downloaded via
omnibuser.com" as their calibre comments, and the address they came from only
inside the epub, as a "Source:" link in the frontmatter. calibre and
FanFicFare cannot see that, so the books look sourceless and cannot be
updated. This lifts the link out, records it as calibre's `url` identifier,
and has Ratchet fetch a fresh FanFicFare copy from it.

Only forum books are touched — SpaceBattles, SufficientVelocity,
QuestionableQuesting — because those are the ones FanFicFare can actually
update from a script. fanfiction.net is left alone: its Cloudflare turns away
non-browser fetchers, and FFF 4.60.0 additionally crashes on its cover
handling (see TODO.md). Those stay a job for the calibre plugin.

On "force": this deliberately does NOT use `fanficfare --force`, which
run_fff refuses outright, because --force disables both chapter reuse and the
count guard that the whole safety design rests on. It is not needed here.
These epubs were not made by FanFicFare, so they have no chapter identities
to protect, and Ratchet's /convert already means exactly "throw this file
away and take a fresh one from the site" — every chapter, current metadata,
with the old file backed up first and the result verified against the site's
own chapter list before anything is written to calibre.

Convert replaces the epub but not calibre's own columns, so the comments are
rewritten separately, from FanFicFare's own metadata for the story.

Not from the epub, though that looks like the cheaper route: calibre
metadata-injects every file it hands out, rewriting <dc:description> from the
comments it already holds. Reading the description back from a downloaded
epub therefore returns the omnibuser line it was supposed to replace, and the
rewrite silently achieves nothing.

Runs one book at a time, and pauses between them.

Usage (from server/, where config.toml lives):
    python ../.scripts/omnibuser_sources.py                      # dry run, all
    python ../.scripts/omnibuser_sources.py --book 1212 --apply  # one book
    python ../.scripts/omnibuser_sources.py --apply              # the rest
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import httpx                                             # noqa: E402
from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.config import load_config                   # noqa: E402
from ratchet.sites import (SiteFetchError, fetch_remote,      # noqa: E402
                           normalize_story_url)

MARKER = "Downloaded via omnibuser.com"

# Sites FanFicFare can fetch unattended. fanfiction.net is excluded on
# purpose; see the note above.
FORUM_DOMAINS = {
    "forums.spacebattles.com",
    "forums.sufficientvelocity.com",
    "forum.questionablequesting.com",
    "forums.questionablequesting.com",
}

# The frontmatter reads: <li><strong>Source:</strong> <a href="...">...</a>
# Anchored to the label rather than taking the first URL in the file, because
# that would find the XHTML namespace declaration in the document header.
SOURCE_RE = re.compile(
    r'Source:\s*(?:</strong>)?\s*<a[^>]+href=["\'](https?://[^"\']+)', re.I)


def epub_bytes(calibre: CalibreClient, book_id: int, library: str) -> bytes:
    return calibre.download_format(book_id, "EPUB", library)


def source_url(data: bytes) -> str | None:
    """The Source: link from an omnibuser epub's frontmatter."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        docs = [n for n in z.namelist()
                if n.lower().endswith((".xhtml", ".html", ".htm"))]
        front = [n for n in docs if "frontmatter" in n.lower()] or docs[:1]
        text = "".join(z.read(n).decode("utf-8", "replace") for n in front)
    m = SOURCE_RE.search(text)
    return m.group(1) if m else None




class Ratchet:
    """The running service, so every fetch goes through its safety checks,
    its politeness throttle and its event log rather than around them."""

    def __init__(self, cfg):
        self.base = f"http://{cfg.bind_host}:{cfg.service.port}"
        self.headers = {"X-Api-Token": cfg.service.auth_token}

    def _call(self, method: str, path: str, **kw):
        r = httpx.request(method, self.base + path, headers=self.headers,
                          timeout=1800, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def story_state(self, book_id: int, library: str) -> dict:
        return self._call("GET", f"/books/{book_id}/story-state",
                          params={"library": library})

    def convert(self, book_id: int, library: str) -> dict:
        return self._call("POST", f"/books/{book_id}/convert",
                          params={"library": library})

    def update(self, book_id: int, library: str) -> dict:
        return self._call("POST", f"/books/{book_id}/update",
                          params={"library": library})


def process(book_id: int, meta: dict, calibre: CalibreClient, ratchet: Ratchet,
            cfg, library: str, apply: bool) -> str:
    """Returns a one-line outcome for this book."""
    title = meta.get("title") or f"book {book_id}"
    # The Source link, or — once this book has been converted and the
    # omnibuser frontmatter is gone with it — the identifier written on the
    # first pass. Without that fallback a book whose fetch succeeded but whose
    # comments write failed could never be repaired.
    found = (source_url(epub_bytes(calibre, book_id, library))
             or (meta.get("identifiers") or {}).get("url"))
    if not found:
        return f"SKIP  {title}: no Source link in the epub and no url identifier"

    domain = urlparse(found).netloc.lower()
    if domain not in FORUM_DOMAINS:
        return f"skip  {title}: {domain} is not a forum FFF can fetch"

    url = normalize_story_url(found)
    if not url:
        return f"SKIP  {title}: FanFicFare does not recognise {found}"

    if not apply:
        return f"would  {title}\n         url -> {url}"

    # 1. Record the source where calibre shows it. Ratchet reads the epub's
    #    own <dc:source> first, which these books already carry (schemeless),
    #    so this is for calibre's sake and for the fallback chain rather than
    #    for the fetch below.
    identifiers = dict(meta.get("identifiers") or {})
    if identifiers.get("url") != url:
        identifiers["url"] = url
        calibre.set_fields(book_id, {"identifiers": identifiers}, library)

    # 2. The story's real metadata, which is the only honest source for the
    #    description — see the note at the top about calibre's injection.
    remote = fetch_remote(url, cfg)

    # 3. Fetch a fresh copy. Convert for the omnibuser epubs (not FFF-made);
    #    update for any that have already been through this once.
    state = ratchet.story_state(book_id, library)
    if state.get("fff_managed"):
        result = ratchet.update(book_id, library)
        chapters = (result.get("final_chapter_count")
                    if result.get("updated") else result.get("local_count"))
        outcome = ("updated" if result.get("updated")
                   else f"already current ({result.get('action')})")
    else:
        result = ratchet.convert(book_id, library)
        chapters = result.get("chapter_count")
        outcome = "converted"

    # 4. Convert replaces the file, not calibre's columns, so the omnibuser
    #    marker would otherwise survive in the comments. Done even when
    #    nothing was downloaded, so a rerun repairs a book left half-done.
    description = (remote.raw or {}).get("description")
    if description and description.strip():
        calibre.set_fields(book_id, {"comments": description.strip()}, library)
        note = "comments rewritten"
    else:
        note = "no description from the site; comments left alone"
    return f"OK    {title}: {outcome}, {chapters} chapters, {note}\n         {url}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--library", default="Fanfiction")
    ap.add_argument("--apply", action="store_true",
                    help="without this, only report what would happen")
    ap.add_argument("--book", type=int, help="just this one book id")
    ap.add_argument("--limit", type=int, help="stop after this many books")
    ap.add_argument("--pause", type=float, default=5.0,
                    help="seconds between books (default 5)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    ratchet = Ratchet(cfg)

    ids = calibre.search(query=f'comments:"{MARKER}"', num=10000,
                         library_id=args.library)["book_ids"]
    if args.book:
        if args.book not in ids:
            print(f"book {args.book} is not an omnibuser book in {args.library}")
            return 1
        ids = [args.book]
    if args.limit:
        ids = ids[:args.limit]

    metas = calibre.books(ids, library_id=args.library) if ids else {}
    print(f"{len(ids)} book(s) to consider in {args.library}"
          f"{'' if args.apply else '  (dry run — nothing will change)'}\n")

    done = 0
    for i, book_id in enumerate(ids):
        try:
            print(process(book_id, metas.get(str(book_id)) or {}, calibre,
                          ratchet, cfg, args.library, args.apply))
        except (CalibreError, SiteFetchError, RuntimeError,
                zipfile.BadZipFile) as e:
            print(f"FAIL  book {book_id}: {e}")
        done += 1
        # One at a time, with a breath between: each convert is a full story
        # download from a forum that would rather not be hammered.
        if args.apply and i + 1 < len(ids):
            time.sleep(args.pause)
    print(f"\n{done} book(s) processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
