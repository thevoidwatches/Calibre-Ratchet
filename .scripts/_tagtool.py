"""Shared plumbing for the one-off metadata rewriting scripts.

Each script supplies a transform from a book's current metadata to the value
one or more of its columns should have. This module handles the library
sweep, the dry-run report, the write, and the rollback file. Keeping it here
means a fix to the apply/undo path is made once rather than in every script
that rewrites metadata.

run() is the single-column case, which most of the scripts use. run_multi()
is for the ones that move a value from one column into another, where both
ends have to change together or not at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Story titles routinely carry curly quotes and dashes that the Windows
# console's default cp1252 cannot encode, which would abort a report
# part-way through and leave no record of what was about to change.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ratchet.calibre import CalibreClient, CalibreError
from ratchet.config import load_config


# Undo files are data, not code: they live outside the tracked script folder
# so a library-sized rollback never lands in a commit.
BACKUPS = Path(__file__).resolve().parents[1] / ".backups"


def backup_path(name: str) -> Path:
    """Resolve a --rollback argument: the path as given if it exists, else
    that name inside .backups/, so the short filename printed when a run is
    applied is the one that works to undo it."""
    given = Path(name)
    return given if given.exists() else BACKUPS / given.name


def parser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--library", default="Fanfiction")
    ap.add_argument("--apply", action="store_true",
                    help="without this, only report what would change")
    ap.add_argument("--rollback", help="undo a previous run from its json")
    return ap


def current(meta: dict, field: str) -> list[str]:
    """A multi-value column's value, wherever calibre keeps it. Custom columns
    live under user_metadata; built-ins sit at the top level."""
    if field.startswith("#"):
        value = (meta.get("user_metadata") or {}).get(field, {}).get("#value#")
    else:
        value = meta.get(field)
    return list(value) if isinstance(value, (list, tuple)) else ([] if value is None else [value])


def dedupe(tags: list[str]) -> list[str]:
    """Rewriting can collapse two spellings onto one tag; keep first order."""
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def run(args, transform, rollback_stem: str, field: str = "tags",
        prepare=None) -> int:
    """Sweep the library, report, and (with --apply) write and record undo.

    `transform(value, meta) -> list[str]` is called once per book with that
    book's current value for `field`. `prepare(metas)`, when given, is called
    once with every book's metadata first, for rules that need to look at the
    library as a whole before deciding anything about one book.
    """
    def one_field(meta):
        return {field: transform(current(meta, field), meta)}

    return run_multi(args, one_field, rollback_stem, prepare=prepare)


def run_multi(args, transform, rollback_stem: str, prepare=None) -> int:
    """As run(), but `transform(meta) -> {field: value}` may name several
    columns. Only the columns it returns are compared and written, so a
    script that usually touches one and occasionally touches three does not
    have to declare that up front."""
    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)

    if args.rollback:
        undo = json.loads(backup_path(args.rollback).read_text(encoding="utf-8"))
        for book_id, fields in undo.items():
            # Older undo files hold a bare list, from when only tags moved.
            if isinstance(fields, list):
                fields = {"tags": fields}
            calibre.set_fields(int(book_id), fields, args.library)
            print(f"restored {book_id}: {fields}")
        print(f"\n{len(undo)} book(s) restored.")
        return 0

    ids = calibre.search(query="", num=100000, library_id=args.library)["book_ids"]
    metas: dict = {}
    for i in range(0, len(ids), 200):
        metas.update(calibre.books(ids[i:i + 200], library_id=args.library))

    if prepare is not None:
        prepare(metas)

    changes: dict[str, tuple[dict, dict]] = {}
    for book_id, meta in metas.items():
        if not meta:
            continue
        proposed = transform(meta) or {}
        old, new = {}, {}
        for name, value in proposed.items():
            was = current(meta, name)
            now = dedupe(value)
            if now != was:
                old[name], new[name] = was, now
        if new:
            changes[book_id] = (old, new)

    print(f"{len(changes)} book(s) to change"
          f"{'' if args.apply else '  (dry run — nothing will change)'}\n")
    for book_id, (old, new) in sorted(changes.items(), key=lambda x: int(x[0])):
        print(f"{book_id:>5}  {(metas[book_id].get('title') or '')[:44]}")
        for name in sorted(new):
            label = "" if name == "tags" else f"{name} "
            for t in old[name]:
                if t not in new[name]:
                    print(f"       - {label}{t}")
            for t in new[name]:
                if t not in old[name]:
                    print(f"       + {label}{t}")

    if args.apply and changes:
        undo = {bid: old for bid, (old, _) in changes.items()}
        BACKUPS.mkdir(exist_ok=True)
        out = BACKUPS / f"{rollback_stem}-{len(changes)}.json"
        out.write_text(json.dumps(undo, indent=1), encoding="utf-8")
        print(f"\nrollback written to {out}")
        failed = 0
        for book_id, (_, new) in changes.items():
            try:
                calibre.set_fields(int(book_id), new, args.library)
            except CalibreError as e:
                failed += 1
                print(f"FAIL  {book_id}: {e}")
        print(f"applied to {len(changes) - failed} book(s), {failed} failed")

    print(f"\n{len(changes)} book(s) affected.")
    return 0
