#!/usr/bin/env python3
"""One-time baseline: snapshot every FFF-managed book's chapter list into the
sidecar DB. Reads epubs from the content server; makes ZERO requests to fic
sites. Also your first data-quality report: any book listed as 'no-chapterurls'
predates FFF's chapterurl embedding (very old) or wasn't made by FFF, and
won't be updatable through Ratchet until refreshed once via the plugin.

Usage:
    python scripts/snapshot_baseline.py --config config.toml [--library Serials]
        [--query 'tags:web-serial'] [--limit N]

--library may be given more than once, or omitted for the configured default;
--all-libraries walks every library the content server exposes.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet import epub as epub_mod           # noqa: E402
from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.chapterkeys import site_of        # noqa: E402
from ratchet.config import load_config         # noqa: E402
from ratchet.db import Sidecar                 # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--query", default="", help="calibre search to select books "
                    "(default: whole library)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--library", action="append", default=[],
                    help="library id (repeatable); default: the configured one")
    ap.add_argument("--all-libraries", action="store_true",
                    help="walk every library on the content server")
    args = ap.parse_args()

    cfg = load_config(args.config)
    sidecar = Sidecar(cfg.db_path)
    cal = CalibreClient(cfg.calibre.base_url, cfg.calibre.library_id,
                        cfg.calibre.username, cfg.calibre.password)

    if args.all_libraries:
        libraries = [lib["id"] for lib in cal.libraries()]
    elif args.library:
        libraries = args.library
    else:
        libraries = [cfg.calibre.library_id]

    totals = {"ok": 0, "no-epub": 0, "no-story-url": 0, "no-chapterurls": 0}
    for lib in libraries:
        print(f"\n=== library {lib or '(default)'} ===")
        stats = walk_library(cal, sidecar, lib, args)
        for k, v in stats.items():
            totals[k] += v
        print(" ", stats)

    print("\nDone:", totals)


def walk_library(cal: CalibreClient, sidecar: Sidecar, lib: str, args) -> dict:
    ids: list[int] = []
    offset = 0
    while True:
        res = cal.search(query=args.query, num=200, offset=offset, library_id=lib)
        batch = res.get("book_ids", [])
        if not batch:
            break
        ids.extend(batch)
        offset += len(batch)
        if args.limit and len(ids) >= args.limit:
            ids = ids[: args.limit]
            break

    print(f"{len(ids)} book(s) selected")
    stats = {"ok": 0, "no-epub": 0, "no-story-url": 0, "no-chapterurls": 0}

    for bid in ids:
        try:
            data = cal.download_format(bid, "EPUB", library_id=lib)
        except CalibreError:
            stats["no-epub"] += 1
            continue
        # A TemporaryDirectory, not NamedTemporaryFile: on Windows an open NamedTemporaryFile can't be reopened by name (zipfile would get a PermissionError).
        with tempfile.TemporaryDirectory(prefix=f"ratchet-{bid}-") as td:
            path = str(Path(td) / f"{bid}.epub")
            Path(path).write_bytes(data)
            url = epub_mod.read_story_url(path)
            if not url:
                stats["no-story-url"] += 1
                print(f"  [{bid}] no dc:source (not a FFF epub)")
                continue
            chapters = epub_mod.extract_chapters(path)
            if not chapters:
                stats["no-chapterurls"] += 1
                print(f"  [{bid}] {url} — no embedded chapterurls; refresh via "
                      "FFF plugin once before using Ratchet on it")
                continue
            sidecar.save_snapshot(lib, bid, url, site_of(url),
                                  [c.as_dict() for c in chapters], baseline="exact")
            stats["ok"] += 1
            print(f"  [{bid}] {len(chapters):4d} ch  {url}")

    return stats


if __name__ == "__main__":
    main()
