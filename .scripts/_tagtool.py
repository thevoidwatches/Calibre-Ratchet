"""Shared plumbing for the one-off metadata rewriting scripts.

Each script supplies a transform from a book's current metadata to the value
one or more of its columns should have. This module handles the library
sweep, the dry-run report, the write, and the rollback file. Keeping it here
means a fix to the apply/undo path is made once rather than in every script
that rewrites metadata.

run() is the single-column case, which most of the scripts use. run_multi()
is for the ones that move a value from one column into another, where both
ends have to change together or not at all.

--since and --until limit a run to the books added in that range. They limit
what a run reports on and writes, never what it reads: some scripts decide
one book by looking at the rest of the library — which fandom a name belongs
to, how the library spells it — and must decide it the same way whichever
books a run is limited to.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Story titles routinely carry curly quotes and dashes that the Windows
# console's default cp1252 cannot encode, which would abort a report
# part-way through and leave no record of what was about to change.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ratchet.calibre import CalibreClient, CalibreError, field_values
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


_DATE = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")


def _date(text: str) -> str:
    """A date as calibre's search takes one. Checked here, because calibre
    reads a malformed one as a search for something else rather than
    refusing it."""
    if not _DATE.fullmatch(text):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a date — write 2026-09-01, 2026-09 or 2026")
    return text


def parser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--library", default="Fanfiction")
    ap.add_argument("--apply", action="store_true",
                    help="without this, only report what would change")
    ap.add_argument("--rollback", help="undo a previous run from its json")
    ap.add_argument("--since", type=_date,
                    help="only books added on or after this date; 2026-09 "
                         "means from the start of that month")
    ap.add_argument("--until", type=_date,
                    help="only books added on or before this date; 2026-09 "
                         "means to the end of that month")
    return ap


def date_query(args) -> str:
    """The calibre search for the books a run is limited to; '' for all.

    calibre's own date search, so a range means what calibre's Date column
    shows, in the library's own time zone rather than UTC — a book added late
    in the evening belongs to that evening's date.
    """
    parts = []
    if getattr(args, "since", None):
        parts.append(f"date:>={args.since}")
    if getattr(args, "until", None):
        parts.append(f"date:<={args.until}")
    return " and ".join(parts)


def whole_library_only(args, mode: str, why: str) -> None:
    """Refuse a date range for a mode that has to cover every book."""
    if date_query(args):
        raise SystemExit(f"{mode} covers the whole library: {why}. "
                         "Run it without --since/--until.")


def read_library(calibre, args) -> tuple[dict, set[str]]:
    """(every book's metadata, the ids of the books this run is limited to).

    Ids are strings, as calibre keys the metadata by them.
    """
    ids = calibre.search(query="", num=100000, library_id=args.library)["book_ids"]
    metas: dict = {}
    for i in range(0, len(ids), 200):
        metas.update(calibre.books(ids[i:i + 200], library_id=args.library))
    query = date_query(args)
    if not query:
        return metas, set(metas)
    wanted = {str(i) for i in calibre.search(
        query=query, num=100000, library_id=args.library)["book_ids"]}
    print(f"limited to {len(wanted)} of {len(metas)} book(s): {query}\n")
    return metas, wanted


def current(meta: dict, field: str) -> list[str]:
    """A multi-value column's value, wherever calibre keeps it.

    The service reads columns through the same function, so the scripts and
    the tag rules cannot disagree with it about where calibre keeps things.
    """
    return field_values(meta, field)


def dedupe(tags: list[str]) -> list[str]:
    """Rewriting can collapse two spellings onto one tag; keep first order."""
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _shown(value: list[str] | dict) -> list[str]:
    """A column's value as the lines a report lists it by."""
    if isinstance(value, dict):
        return [f"{k}:{v}" for k, v in value.items()]
    return value


def run(args, transform, rollback_stem: str, field: str = "tags",
        prepare=None) -> int:
    """Sweep the library, report, and (with --apply) write and record undo.

    `transform(value, meta) -> list[str]` is called once per book with that
    book's current value for `field`. `prepare(metas, wanted)`, when given,
    is called once first with every book's metadata and the ids of the books
    that will be transformed, for rules that need to look at the library as
    a whole before deciding anything about one book.
    """
    def one_field(meta):
        return {field: transform(current(meta, field), meta)}

    return run_multi(args, one_field, rollback_stem, prepare=prepare)


def run_multi(args, transform, rollback_stem: str, prepare=None) -> int:
    """As run(), but `transform(meta) -> {field: value}` may name several
    columns. Only the columns it returns are compared and written, so a
    script that usually touches one and occasionally touches three does not
    have to declare that up front. A value is a list, or for identifiers a
    mapping."""
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

    metas, wanted = read_library(calibre, args)

    if prepare is not None:
        prepare(metas, wanted)

    changes: dict[str, tuple[dict, dict]] = {}
    for book_id, meta in metas.items():
        if not meta or book_id not in wanted:
            continue
        proposed = transform(meta) or {}
        old, new = {}, {}
        for name, value in proposed.items():
            if isinstance(value, dict):
                # A mapping (identifiers) is compared and written whole:
                # calibre replaces the lot, so the undo has to hold the lot.
                was, now = dict(meta.get(name) or {}), dict(value)
            else:
                was, now = current(meta, name), dedupe(value)
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
            was, now = _shown(old[name]), _shown(new[name])
            for t in was:
                if t not in now:
                    print(f"       - {label}{t}")
            for t in now:
                if t not in was:
                    print(f"       + {label}{t}")

    if args.apply and changes:
        undo = {bid: old for bid, (old, _) in changes.items()}
        BACKUPS.mkdir(exist_ok=True)
        # Named for when as well as how many: two runs of one script that
        # changed the same number of books once shared a name, and the second
        # replaced the first's undo. "x" refuses to overwrite even so, and
        # nothing is written to calibre unless the undo was.
        when = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = BACKUPS / f"{rollback_stem}-{when}-{len(changes)}.json"
        with out.open("x", encoding="utf-8") as f:
            f.write(json.dumps(undo, indent=1))
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
