#!/usr/bin/env python3
"""Set the #downloaded bool for books that came from a fic site.

A book counts as downloaded when any of:
  1. its epub has a <dc:source> story URL (made by FanFicFare);
  2. calibre has a `url` identifier for it (FFF plugin, fallback);
  3. an archiveofourown.org link appears in the first few spine documents —
     AO3's own generated epubs carry a "Posted originally on the Archive of
     Our Own at ..." preface, so this catches direct AO3 downloads that never
     went through FFF.

Only ever sets #downloaded to TRUE on detected books; everything else is left
untouched (an unset bool column reads as blank in calibre and as not-managed
in Ratchet). Reruns are safe: already-true books are skipped.

Lives in .scripts alongside the other one-off curation tools, kept for reruns.
The detection heuristic (dc:source OR AO3 preface) is an approximation of the
column's real meaning — "FanFicFare can update this" — so review the dry run
before applying; e.g. two pre-FFF epubs with a dc:source were false positives.

Usage (from server, where config.toml lives):
    python ../../.scripts/mark_downloaded.py --config config.toml --library Fanfiction
    python ../../.scripts/mark_downloaded.py --config config.toml --library Fanfiction --apply
"""

from __future__ import annotations

import argparse
import posixpath
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

from ratchet import epub as epub_mod            # noqa: E402
from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.config import load_config          # noqa: E402

# The AO3 preface sits in the first document or two; a couple extra for luck.
SPINE_DOCS_TO_SCAN = 4
AO3_MARK = b"archiveofourown.org/"


def ao3_generated(epub_path: str) -> bool:
    """True when an early spine document links to AO3 — the fingerprint of
    AO3's own epub generator ("Posted originally on the Archive...")."""
    import zipfile
    try:
        with zipfile.ZipFile(epub_path) as zf:
            opf_path, opf = epub_mod._opf(zf)
            base = posixpath.dirname(opf_path)
            manifest = {i.get("id"): i.get("href")
                        for i in opf.findall(".//opf:manifest/opf:item", epub_mod._NS)}
            scanned = 0
            for itemref in opf.findall(".//opf:spine/opf:itemref", epub_mod._NS):
                href = manifest.get(itemref.get("idref"))
                if not href:
                    continue
                path = posixpath.normpath(posixpath.join(base, href)) if base else href
                try:
                    data = zf.read(path)
                except KeyError:
                    continue
                if AO3_MARK in data:
                    return True
                scanned += 1
                if scanned >= SPINE_DOCS_TO_SCAN:
                    break
    except Exception:
        return False
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--library", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write #downloaded=true; without it, only report")
    args = ap.parse_args()

    cfg = load_config(args.config)
    cal = CalibreClient(cfg.calibre.base_url, args.library,
                        cfg.calibre.username, cfg.calibre.password)

    ids: list[int] = []
    offset = 0
    while True:
        batch = cal.search(query="", num=200, offset=offset).get("book_ids", [])
        if not batch:
            break
        ids.extend(batch)
        offset += len(batch)
    field = cfg.scripts.downloaded_field
    if not field:
        # Guessing at a column name here would write true into whatever
        # column happened to answer to it.
        raise SystemExit(f"scripts.downloaded_field is not set in {args.config}")
    print(f"{len(ids)} book(s) in {args.library}, marking {field}")

    detected: list[tuple[int, str, str]] = []   # (id, reason, title)
    undetected: list[tuple[int, str]] = []
    already, no_epub, no_column = 0, 0, 0

    for bid in ids:
        meta = cal.book(bid)
        title = (meta.get("title") or "")[:60]
        um = meta.get("user_metadata", {})
        if field not in um:
            no_column += 1
            continue
        if um[field].get("#value#") is True:
            already += 1
            continue

        if cal.story_url_from_identifiers(meta, cfg.calibre.identifier_key):
            detected.append((bid, "url identifier", title))
            continue

        try:
            data = cal.download_format(bid, "EPUB")
        except CalibreError:
            no_epub += 1
            undetected.append((bid, title + "  [no epub]"))
            continue
        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td) / "b.epub")
            Path(p).write_bytes(data)
            # A single malformed epub must classify, not kill the whole run.
            try:
                has_source = bool(epub_mod.read_story_url(p))
            except Exception:
                undetected.append((bid, title + "  [unreadable epub]"))
                continue
            if has_source:
                detected.append((bid, "dc:source", title))
            elif ao3_generated(p):
                detected.append((bid, "AO3 preface", title))
            else:
                undetected.append((bid, title))

    print(f"\nalready true: {already}   no {field} column: {no_column}   "
          f"no epub: {no_epub}")
    reasons: dict[str, int] = {}
    for _, reason, _t in detected:
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f"detected as downloaded: {len(detected)}  {reasons}")
    print(f"left untouched (not detected): {len(undetected)}")
    for bid, title in undetected[:40]:
        print(f"    [{bid}] {title}")
    if len(undetected) > 40:
        print(f"    ... and {len(undetected) - 40} more")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to set them.")
        return

    for bid, _reason, _title in detected:
        cal.set_fields(bid, {field: True})
    print(f"\nwrote {field}=true on {len(detected)} book(s)")


if __name__ == "__main__":
    main()
