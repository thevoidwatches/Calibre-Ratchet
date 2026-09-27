#!/usr/bin/env python3
"""Ask the sites what your books are tagged, and file that through your rules.

The tag rules run when a book is added, so anything added since they existed
is already filed. This is for the backlog: books that arrived before the
rules did, or before a rule was written, whose site tags were cleared by hand
or never imported at all.

It fetches metadata only — no chapters, no epub is written, nothing about the
book's text is touched. For each book it asks FanFicFare what the site says
the story is tagged, runs those tags through ../config/tag_rules.txt exactly
as an add would, and merges the result on top of what the book already has.

What it will not do is take a decision away from you:

  * a tag you filed only goes when something deeper replaces it — a book
    filed under "Science Fiction" that the site says is a space opera ends
    up under "Science Fiction.Space Opera" alone, which says both
  * a value already in a column is never duplicated
  * where the site disagrees with a tag under one of scripts.exclusive_roots
    — a serial is ongoing or finished, not both — it changes nothing and
    lists the disagreement for you to settle

Site fetches are the slow part, so they are cached: a dry run and the --apply
that follows it ask each site once. Delete the cache to re-ask.

Usage (from server/, where config.toml lives):
    python ../.scripts/refresh_site_tags.py --library Serials
    python ../.scripts/refresh_site_tags.py --library Serials --apply
    python ../.scripts/refresh_site_tags.py --library Serials --site royalroad
    python ../.scripts/refresh_site_tags.py --library Serials --since 2026-09
    python ../.scripts/refresh_site_tags.py --rollback sitetags-rollback-<n>.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
from ratchet import sites, tagmap  # noqa: E402
from ratchet.config import load_config  # noqa: E402

CACHE = _tagtool.BACKUPS / "site-tags-cache.json"

CFG = None
RULES = tagmap.Rules()
COLUMNS: dict[str, str] = {}
EXCLUSIVE: list[str] = []
SITE_TAGS: dict[str, list[str]] = {}     # book id -> what the site says
DISAGREED: list[tuple[int, str, str, str]] = []


def configure(cfg) -> None:
    global CFG, RULES, COLUMNS, EXCLUSIVE
    CFG = cfg
    RULES = tagmap.load(tagmap.rules_path(cfg))
    COLUMNS = tagmap.columns_from(cfg)
    EXCLUSIVE = list(cfg.scripts.exclusive_roots)


def story_url(meta: dict) -> str:
    """Where this book came from, per the identifier the FFF plugin sets.

    The epub's own dc:source would be better, but reading it means
    downloading every book — and a book with no identifier is one this
    script has nothing to ask about anyway.
    """
    idents = meta.get("identifiers") or {}
    value = str(idents.get(CFG.calibre.identifier_key) or "")
    if value.startswith(("http//", "https//")):
        value = value.replace("//", "://", 1)
    return value if value.startswith(("http://", "https://")) else ""


def load_cache() -> dict:
    if CACHE.is_file():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            print(f"WARNING: {CACHE.name} is unreadable — refetching")
    return {}


def fetch_all(metas: dict, wanted: set[str], only_site: str,
              pause: float) -> None:
    """Ask each book's site what it is tagged, once, politely — only about
    the books this run may change, since every other answer would be a
    site hit for nothing."""
    cache = load_cache()
    ask = []
    for book_id, meta in sorted(metas.items(), key=lambda kv: int(kv[0])):
        if not meta or book_id not in wanted:
            continue
        url = story_url(meta)
        if not url or (only_site and only_site not in url):
            continue
        if url in cache:
            SITE_TAGS[book_id] = cache[url]
        else:
            ask.append((book_id, url))

    print(f"{len(SITE_TAGS)} book(s) answered from {CACHE.name}, "
          f"{len(ask)} to ask the site about")
    if ask:
        print("fetching metadata only — no chapters are downloaded\n")
    for n, (book_id, url) in enumerate(ask, 1):
        if n > 1:
            time.sleep(pause)
        try:
            proc = sites.run_fff(["-m", "-j", "--no-output", url], CFG)
            data = json.loads(proc.stdout) if proc.returncode == 0 else {}
        except Exception as e:                       # noqa: BLE001
            print(f"  {n:>4}/{len(ask)}  FAILED {url} — {e}")
            continue
        tags = data.get("subject_tags") or []
        if not tags:
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            print(f"  {n:>4}/{len(ask)}  no tags from {url} — {tail[0][:70]}")
            continue
        SITE_TAGS[book_id] = cache[url] = tags
        print(f"  {n:>4}/{len(ask)}  {str(data.get('title'))[:44]:44} "
              f"{len(tags)} tags", flush=True)
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    print()


def exclusive_root(tag: str) -> str:
    head = tagmap.HIERARCHY_DOT.split(tag)[0]
    return head if head in EXCLUSIVE else ""


def transform(meta: dict) -> dict:
    """This book's columns, with the site's tags filed on top of them."""
    book_id = int(meta["application_id"])
    site = SITE_TAGS.get(str(book_id))
    if not site:
        return {}

    # The rules judge the site's tags against the columns this book already
    # has, so a move that is already recorded simply does not repeat itself.
    changes = tagmap.apply({"tags": list(site),
                            "user_metadata": meta.get("user_metadata") or {}},
                           RULES, COLUMNS)
    if not changes:
        return {}

    have = list(meta.get("tags") or [])
    keep = list(have)
    for tag in changes.get("tags", []):
        if tag in keep:
            continue
        root = exclusive_root(tag)
        if root:
            # One value at a time under this root: a difference is the site
            # disagreeing with a decision, which is not this script's to make.
            mine = [t for t in have if exclusive_root(t) == root and t != tag]
            if mine:
                DISAGREED.append((book_id, meta.get("title") or "",
                                  mine[0], tag))
                continue
        keep.append(tag)

    # Only what this book should end up with; _tagtool drops the columns
    # that already say exactly that, so a book nothing moved is not written.
    out = {"tags": tagmap.drop_implied(keep)}
    for column, values in changes.items():
        if column != "tags":
            out[column] = tagmap.drop_implied(values)
    return out


def report_disagreements() -> None:
    if not DISAGREED:
        return
    print(f"\n{len(DISAGREED)} book(s) where the site disagrees with a tag you "
          f"filed, left alone:")
    for book_id, title, mine, theirs in sorted(DISAGREED):
        print(f"  {book_id:>5}  {title[:42]:42} yours {mine!r} / site {theirs!r}")
    print("\n  Nothing above was changed. Settle them in calibre, or in the "
          "UI.")


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    ap.add_argument("--site", default="",
                    help="only books whose URL contains this, e.g. royalroad")
    ap.add_argument("--pause", type=float, default=None,
                    help="seconds between site requests (default: politeness "
                         "setting from config.toml)")
    parsed = ap.parse_args()
    configure(load_config(parsed.config))
    if not RULES:
        raise SystemExit(
            f"no tag rules in {tagmap.rules_path(load_config(parsed.config))} — "
            "there is nothing to file the site's tags through. Write some "
            "rules first; ../.scripts/stray_tags.py --review lists what a "
            "library has arrived with.")
    pause = (parsed.pause if parsed.pause is not None
             else CFG.politeness.min_seconds_between_site_requests)

    code = _tagtool.run_multi(
        parsed, transform, "sitetags-rollback",
        prepare=lambda metas, wanted: fetch_all(metas, wanted, parsed.site, pause))
    report_disagreements()
    raise SystemExit(code)
