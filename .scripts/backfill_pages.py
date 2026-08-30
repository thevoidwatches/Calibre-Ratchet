#!/usr/bin/env python3
"""Give calibre a reason to count the pages of books it never measured.

calibre works out a page count when a book's format is written, and exposes
it as a sortable field. Books added before that feature arrived report 0,
which is indistinguishable from "no pages" when sorting: ascending order puts
every unmeasured book first and is useless until they are filled in.

Nothing here computes a count. Writing the epub back unchanged is enough to
make calibre measure it, and its own number is better than anything derivable
from the text: across the books it had already measured, characters per page
ranged from 792 to 3200, so it is clearly accounting for images and layout
rather than dividing by a constant.

WHAT THIS TOUCHES
Only the file, and only by replacing it with itself. calibre imports metadata
from a file when a book is ADDED, never when a format is replaced, so tags
and custom columns cannot be affected -- verified on a book carrying six
tags, thirty-six #majchar entries and four other columns, where the page
count was the single field that moved.

Two things do change and cannot be undone: last_modified and the format's
mtime. The file also grows once, by a few hundred bytes, because calibre
injects its metadata into every epub it serves and that copy is what gets
written back; a second pass over the same book changes nothing further.

There is no rollback file. The content is identical, so there is nothing to
restore; a book that fails is simply left alone and picked up next time.

RESUMABLE
Books are chosen by having no page count, so a run that is interrupted, or a
later import, is handled by running it again. A negative count is calibre
saying it looked and could not -- DRM, a format it cannot paginate, no format
at all -- which is an answer rather than a gap, so those are reported and
left alone instead of being re-uploaded on every run.

Usage (from server/, where config.toml lives):
    python ../.scripts/backfill_pages.py --library Serials
    python ../.scripts/backfill_pages.py --library Serials --apply
    python ../.scripts/backfill_pages.py --library all --apply
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.config import load_config  # noqa: E402

# The order asked for: smallest first, so a problem shows up on 107 books
# rather than 1844.
DEFAULT_ORDER = ["Serials", "Fanfiction", "Books", "Erotica"]


# calibre reports a negative page count when it tried to measure a book and
# could not, and each value says why. These are answers, not gaps: rewriting
# such a book achieves nothing and would have it re-uploaded on every future
# run, so they are left alone and reported instead.
REFUSED = {
    -1: "no format calibre can measure",
    -2: "format it cannot paginate",
    -3: "DRM-protected",
}


def page_count(meta: dict) -> int:
    """calibre's count, or 0 when it has never looked. Tolerates the field
    arriving as a string, which some versions do."""
    raw = meta.get("pages")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def unmeasured(calibre: CalibreClient, library: str) -> tuple[list[int], dict, dict]:
    """Books worth rewriting, every book's metadata, and a tally of the ones
    calibre has already given up on."""
    ids = calibre.search(query="", num=100000, library_id=library)["book_ids"]
    metas: dict = {}
    for i in range(0, len(ids), 200):
        metas.update(calibre.books(ids[i:i + 200], library_id=library))
    todo = []
    refused: dict[str, list[int]] = {}
    for book_id, meta in metas.items():
        if not meta:
            continue
        pages = page_count(meta)
        if pages > 0:
            continue
        if pages < 0:
            reason = REFUSED.get(pages, f"calibre reported {pages}")
            refused.setdefault(reason, []).append(int(book_id))
            continue
        formats = [f.lower() for f in (meta.get("formats") or [])]
        if "epub" not in formats:
            continue          # nothing to rewrite; calibre counts epubs
        todo.append(int(book_id))
    return sorted(todo), metas, refused


def size_of(meta: dict) -> int:
    return ((meta.get("format_metadata") or {}).get("epub") or {}).get("size") or 0


def run_library(calibre: CalibreClient, library: str, args) -> tuple[int, int]:
    todo, metas, refused = unmeasured(calibre, library)
    total = len(metas)
    no_epub = sum(1 for m in metas.values()
                  if m and page_count(m) == 0
                  and "epub" not in [f.lower() for f in (m.get("formats") or [])])
    bytes_total = sum(size_of(metas[str(b)]) for b in todo)
    print(f"### {library}: {total} books, {len(todo)} unmeasured with an epub"
          f"{f', {no_epub} unmeasured without one' if no_epub else ''}")
    print(f"    {bytes_total / 1e9:.2f} GB to move"
          f"{'' if args.apply else '   (dry run — nothing will change)'}")
    for reason, books in sorted(refused.items()):
        print(f"    {len(books)} skipped, {reason}: "
              f"{', '.join(str(b) for b in sorted(books)[:8])}"
              f"{' …' if len(books) > 8 else ''}")
    if args.limit:
        todo = todo[:args.limit]
    if not args.apply or not todo:
        return len(todo), 0

    done = failed = 0
    started = time.time()
    for n, book_id in enumerate(todo, start=1):
        title = (metas[str(book_id)].get("title") or "")[:40]
        try:
            data = calibre.download_format(book_id, "EPUB", library)
            calibre.replace_epub(book_id, data, library)
            done += 1
        except (CalibreError, OSError) as e:
            failed += 1
            print(f"    FAIL {book_id} {title}: {str(e)[:90]}", flush=True)
            continue
        if n % 25 == 0 or n == len(todo):
            rate = (time.time() - started) / n
            left = (len(todo) - n) * rate
            print(f"    {n}/{len(todo)}  {done} ok  {failed} failed  "
                  f"~{left / 60:.0f} min left", flush=True)
    print(f"    {library} done: {done} rewritten, {failed} failed, "
          f"{(time.time() - started) / 60:.1f} min", flush=True)
    return done, failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--library", default="all",
                    help="one library, or 'all' for "
                         + ", ".join(DEFAULT_ORDER))
    ap.add_argument("--apply", action="store_true",
                    help="without this, only report what would be rewritten")
    ap.add_argument("--limit", type=int, help="stop after this many per library")
    args = ap.parse_args()

    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password, timeout=600.0)
    libraries = DEFAULT_ORDER if args.library == "all" else [args.library]

    grand_done = grand_failed = 0
    for library in libraries:
        try:
            done, failed = run_library(calibre, library, args)
        except CalibreError as e:
            print(f"### {library}: could not read — {str(e)[:120]}")
            continue
        grand_done += done
        grand_failed += failed
        print()
    print(f"{grand_done} book(s) {'rewritten' if args.apply else 'to rewrite'}, "
          f"{grand_failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
