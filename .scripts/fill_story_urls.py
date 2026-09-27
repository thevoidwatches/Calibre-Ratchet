#!/usr/bin/env python3
"""Give a book with no link identifier the one its own epub names.

AO3's own download, added straight into calibre, arrives with no url
identifier: calibre fills identifiers from the epub's metadata, and AO3 does
not put its link there. The link is in the book's preface instead ("Posted
originally on the Archive of Our Own at ..."), which is where the FanFicFare
plugin looks, and Ratchet too, when asked to check or convert such a book.
But they look afresh every time, and nothing that reads identifiers —
calibre's own link to the story, refresh_site_tags.py — finds it at all.

This writes that link into the identifier, as the FanFicFare plugin would
have: the epub's <dc:source> when it has one, else the first link in the
book that a FanFicFare site adapter recognises, normalised the way the
adapter writes it. Only books with no identifier under that name are
touched, so one already set is never argued with.

Every epub without one is downloaded and read, so give it a range:

Usage (from server/, where config.toml lives):
    python ../.scripts/fill_story_urls.py --since 2026-09          # dry run
    python ../.scripts/fill_story_urls.py --since 2026-09 --apply
    python ../.scripts/fill_story_urls.py --rollback storyurl-rollback-<n>.json
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
from ratchet import epub, sites  # noqa: E402
from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.config import load_config  # noqa: E402

KEY = "url"
FOUND: dict[str, str] = {}          # book id -> the link its epub names


def story_url(data: bytes) -> str | None:
    """Where an epub says it came from, as a site adapter writes it."""
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "book.epub")
        Path(path).write_bytes(data)
        try:
            source = epub.read_story_url(path)
        except Exception:                            # noqa: BLE001
            # A malformed epub is one book with no answer, not a failed run.
            return None
        return (sites.normalize_story_url(source or "")
                or epub.find_story_url_in_html(path))


def prepare(metas: dict, wanted: set[str]) -> None:
    cfg = load_config(prepare.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    missing = sorted((k for k in wanted
                      if metas.get(k) and not (metas[k].get("identifiers") or {}).get(KEY)),
                     key=int)
    print(f"{len(missing)} book(s) with no {KEY!r} identifier — reading their epubs\n")
    for book_id in missing:
        try:
            url = story_url(calibre.download_format(int(book_id), "EPUB",
                                                    prepare.library))
        except CalibreError:
            url = None
        if url:
            FOUND[book_id] = url
        else:
            print(f"  {book_id:>5}  {(metas[book_id].get('title') or '')[:44]:44} "
                  "names no story link — left alone")
    if len(FOUND) < len(missing):
        print()


def transform(meta: dict) -> dict:
    url = FOUND.get(str(meta["application_id"]))
    if not url:
        return {}
    return {"identifiers": {**(meta.get("identifiers") or {}), KEY: url}}


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    parsed = ap.parse_args()
    KEY = load_config(parsed.config).calibre.identifier_key
    prepare.config, prepare.library = parsed.config, parsed.library
    raise SystemExit(_tagtool.run_multi(parsed, transform, "storyurl-rollback",
                                        prepare=prepare))
