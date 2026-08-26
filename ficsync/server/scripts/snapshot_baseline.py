#!/usr/bin/env python3
"""One-time baseline: snapshot every FFF-managed book's chapter list into the
sidecar DB. Reads epubs from the content server; makes ZERO requests to fic
sites. Also your first data-quality report: any book listed as 'no-chapterurls'
predates FFF's chapterurl embedding (very old) or wasn't made by FFF, and
won't be updatable through ficsync until refreshed once via the plugin.

Usage:
    python scripts/snapshot_baseline.py --config config.toml [--query 'tags:web-serial'] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ficsync import epub as epub_mod           # noqa: E402
from ficsync.calibre import CalibreClient, CalibreError  # noqa: E402
from ficsync.chapterkeys import site_of        # noqa: E402
from ficsync.config import load_config         # noqa: E402
from ficsync.db import Sidecar                 # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--query", default="", help="calibre search to select books "
                    "(default: whole library)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cfg = load_config(args.config)
    sidecar = Sidecar(cfg.db_path)
    cal = CalibreClient(cfg.calibre.base_url, cfg.calibre.library_id,
                        cfg.calibre.username, cfg.calibre.password)

    ids: list[int] = []
    offset = 0
    while True:
        res = cal.search(query=args.query, num=200, offset=offset)
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
            data = cal.download_format(bid, "EPUB")
        except CalibreError:
            stats["no-epub"] += 1
            continue
        with tempfile.NamedTemporaryFile(suffix=".epub") as tf:
            tf.write(data)
            tf.flush()
            url = epub_mod.read_story_url(tf.name)
            if not url:
                stats["no-story-url"] += 1
                print(f"  [{bid}] no dc:source (not a FFF epub)")
                continue
            chapters = epub_mod.extract_chapters(tf.name)
            if not chapters:
                stats["no-chapterurls"] += 1
                print(f"  [{bid}] {url} — no embedded chapterurls; refresh via "
                      "FFF plugin once before using ficsync on it")
                continue
            sidecar.save_snapshot(bid, url, site_of(url),
                                  [c.as_dict() for c in chapters], baseline="exact")
            stats["ok"] += 1
            print(f"  [{bid}] {len(chapters):4d} ch  {url}")

    print("\nDone:", stats)


if __name__ == "__main__":
    main()
