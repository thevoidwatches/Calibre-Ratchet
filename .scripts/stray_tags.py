#!/usr/bin/env python3
"""Deal with tags that arrived from the source sites rather than the scheme.

FanFicFare copies a story's own tags into calibre, so importing a batch of
fics brings in whatever the author or the forum used: "FanFiction", "Worm",
"In-Progress", "will add tags as needed", AO3 freeform tags like "Unreliable
Narrator", and character names in the site's own spelling. They sit beside
the hierarchical vocabulary and clutter every tag browser and filter picker.

Some of them are worth keeping, which is why this is not simply a delete.
A stray tag can be:

  the only record of a crossover   "Mass Effect" on a book filed only as Worm
  a genre in disguise              "Worm AU" -> AU
  a character                      "Midoriya Izuku" -> #majchar
  something the scheme has a home for   "Child Abuse" -> Key Events.Child Abuse
  noise                                 "will add tags as needed"

Deciding which is a judgement call per book, so it is made in
stray_tags.txt rather than here. Regenerate that file with --review after an
import; decisions already in it are kept.

    -                       delete the tag
    Some.Scheme.Tag         rename it, staying in tags
    genre: Value            add to #genre, drop the tag
    fandom: Value           add to #fandom, drop the tag
    majchar: Fandom.Name    add to #majchar, drop the tag
    (blank)                 leave it alone for now

The moves are additive at the far end: a value is added to #genre or
#majchar, never replacing what is there, so a book that already records the
same thing is left as it is and the tag still goes away.

Usage (from server/, where config.toml lives):
    python ../.scripts/stray_tags.py --review    # write stray_tags.txt
    python ../.scripts/stray_tags.py             # dry run
    python ../.scripts/stray_tags.py --apply
    python ../.scripts/stray_tags.py --rollback stray-rollback-<n>.json
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
import major_characters as mc  # noqa: E402

REVIEW = Path(__file__).with_name("stray_tags.txt")
DELETE = "-"

# Roots the hierarchical scheme owns. Anything else came from a site.
SCHEME_ROOTS = set(mc.ROOTS) | {"Content", "Format", "Themes", "Relative Time",
                                "Time Period", "Group Traits"}
# Where a "kind: value" decision sends the value.
COLUMNS = {"genre": "#genre", "fandom": "#fandom", "majchar": "#majchar"}


def is_stray(tag: str) -> bool:
    return tag.split(".")[0] not in SCHEME_ROOTS


def read_decisions() -> dict[str, str]:
    decided: dict[str, str] = {}
    unreadable = []
    if not REVIEW.exists():
        return decided
    for number, line in enumerate(
            REVIEW.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            unreadable.append((number, line.strip()))
            continue
        left, _, right = line.partition("=")
        decided[left.strip()] = right.strip()
    if unreadable:
        print(f"WARNING: {len(unreadable)} line(s) in {REVIEW.name} have no "
              f"'=' and were ignored:")
        for number, text in unreadable[:10]:
            print(f"   line {number}: {text}")
    return decided


def stray_tags(metas: dict) -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for meta in metas.values():
        if meta:
            for tag in (meta.get("tags") or []):
                if is_stray(tag):
                    found[tag].append(int(meta["application_id"]))
    return found


_decided: dict[str, str] = {}


def prepare(metas: dict) -> None:
    _decided.clear()
    _decided.update(read_decisions())


def transform(meta: dict) -> dict:
    """The columns this book should end up with, given the decisions."""
    tags = meta.get("tags") or []
    if not any(is_stray(t) for t in tags):
        return {}
    keep: list[str] = []
    additions: dict[str, list[str]] = {}
    for tag in tags:
        if not is_stray(tag):
            keep.append(tag)
            continue
        decision = _decided.get(tag, "")
        if not decision:
            keep.append(tag)                 # undecided: leave it where it is
            continue
        if decision == DELETE:
            continue
        kind, sep, value = decision.partition(":")
        kind, value = kind.strip(), value.strip()
        if sep and kind in COLUMNS:
            column = COLUMNS[kind]
            if value:
                additions.setdefault(
                    column, list(_tagtool.current(meta, column))).append(value)
        else:
            keep.append(decision)            # a rename, still a tag
    out = {"tags": keep}
    out.update(additions)
    return out


def write_review(args) -> int:
    from ratchet.calibre import CalibreClient
    from ratchet.config import load_config
    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    ids = calibre.search(query="", num=100000,
                         library_id=args.library)["book_ids"]
    metas: dict = {}
    for i in range(0, len(ids), 200):
        metas.update(calibre.books(ids[i:i + 200], library_id=args.library))

    decided = read_decisions()
    found = stray_tags(metas)
    bybook: dict[int, list[str]] = defaultdict(list)
    for tag, books in found.items():
        for book in books:
            bybook[book].append(tag)

    # A decision outlives the tag it was about. The same site tags come back
    # with the next import, so an answer already given is kept in the file and
    # applied again rather than being asked for a second time.
    standing = {t: v for t, v in decided.items() if t not in found and v}

    lines = [
        "# Tags that arrived from the source sites rather than from your scheme.",
        "#",
        "# Set the right-hand side to one of:",
        "#",
        "#   -                             delete the tag",
        "#   Some.Scheme.Tag               rename it, staying in tags",
        "#   genre: Value                  add to #genre, drop the tag",
        "#   fandom: Value                 add to #fandom, drop the tag",
        "#   majchar: Fandom.Name          add to #majchar, drop the tag",
        "#   (blank)                       leave the tag alone for now",
        "#",
        "# Grouped by book, because the same word can mean different things on",
        "# different ones. A tag on several books is listed under each, and a",
        "# decision applies to every book carrying that tag.",
        "",
    ]
    width = max([len(t) for t in found] + [10]) + 1
    for book in sorted(bybook):
        meta = metas[str(book)]
        lines.append(f"#   {book}  {(meta.get('title') or '')[:46]}")
        lines.append(f"#     fandom={_tagtool.current(meta, '#fandom')}  "
                     f"genre={_tagtool.current(meta, '#genre')}")
        for tag in sorted(bybook[book]):
            lines.append(f"{tag.ljust(width)}= {decided.get(tag, '')}")
        lines.append("")
    if standing:
        lines.append("#   ---- decided earlier, not currently on any book ----")
        lines.append("#   Kept so the next import does not ask again. Delete a")
        lines.append("#   line to be asked about that tag afresh.")
        lines.append("")
        swidth = max(len(t) for t in standing) + 1
        for tag in sorted(standing):
            lines.append(f"{tag.ljust(swidth)}= {standing[tag]}")
        lines.append("")
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")

    undecided = sum(1 for t in found if not decided.get(t))
    print(f"{len(found)} stray tags on {len(bybook)} books")
    print(f"   {len(found) - undecided:>4} already decided")
    print(f"   {undecided:>4} need a decision")
    print(f"   {len(standing):>4} standing decisions kept for future imports")
    print(f"\nwritten to {REVIEW}")
    return 0


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    ap.add_argument("--review", action="store_true",
                    help="write stray_tags.txt and stop")
    parsed = ap.parse_args()
    if parsed.review:
        raise SystemExit(write_review(parsed))
    raise SystemExit(_tagtool.run_multi(parsed, transform, "stray-rollback",
                                        prepare=prepare))
