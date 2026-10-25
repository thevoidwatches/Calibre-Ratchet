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

Deciding which is a judgement call, so it is made in the rules file rather
than here — see ratchet/tagmap.py for the format, which this shares with the
service. The service applies those rules as each book is added, so this is
the sweep for the backlog and for tags nobody has ruled on yet. Regenerate
the file with --review after an import; rules already in it are kept.

Usage (from server/, where config.toml lives):
    python ../.scripts/stray_tags.py --review    # rewrite the rules file
    python ../.scripts/stray_tags.py             # dry run
    python ../.scripts/stray_tags.py --apply
    python ../.scripts/stray_tags.py --rollback stray-rollback-<time>-<n>.json
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
from ratchet import tagmap  # noqa: E402
from ratchet.calibre import CalibreClient  # noqa: E402
from ratchet.config import load_config  # noqa: E402

# Filled from config.toml on the way in: which tag roots this library's own
# scheme owns, where its rules live, and which column a "kind: value" rule
# writes to. All three describe a particular library rather than anything
# universal, which is why they are configuration and not code.
SCHEME_ROOTS: set[str] = set()
COLUMNS: dict[str, str] = {}
RULES: Path | None = None


def configure(cfg) -> None:
    """Adopt the rules file, columns and tag roots this library uses."""
    global SCHEME_ROOTS, COLUMNS, RULES
    SCHEME_ROOTS = set(cfg.scripts.scheme_roots)
    COLUMNS = tagmap.columns_from(cfg)
    RULES = tagmap.rules_path(cfg)


def is_stray(tag: str) -> bool:
    return tag.split(".")[0] not in SCHEME_ROOTS


def stray_tags(metas: dict) -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for meta in metas.values():
        if meta:
            for tag in (meta.get("tags") or []):
                if is_stray(tag):
                    found[tag].append(int(meta["application_id"]))
    return found


_rules = tagmap.Rules()


def prepare(metas: dict, wanted: set[str]) -> None:
    global _rules
    _rules = tagmap.load(RULES)
    for number, text in _rules.bad_lines[:10]:
        print(f"WARNING: {RULES.name} line {number} has no '=' — ignored: {text}")


def transform(meta: dict) -> dict:
    """The columns this book should end up with, given the rules.

    The same call the service makes when a book is added, so a rule does the
    same thing whether it was applied on the way in or swept up afterwards.
    """
    return tagmap.apply(meta, _rules, COLUMNS)


def write_review(args) -> int:
    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    metas, _ = _tagtool.read_library(calibre, args)

    rules = tagmap.load(RULES)
    decided = rules.exact
    found = stray_tags(metas)
    bybook: dict[int, list[str]] = defaultdict(list)
    for tag, books in found.items():
        for book in books:
            bybook[book].append(tag)

    # A decision outlives the tag it was about. The same site tags come back
    # with the next import, so an answer already given is kept in the file and
    # applied again rather than being asked for a second time.
    # Patterns are general rules rather than answers about one tag, so they
    # are always carried over; an exact name is only carried when the tag it
    # was about is not on anything at the moment.
    standing = {t: v for t, v in decided.items() if t not in found and v}
    standing.update({p: v for p, v in rules.globs})

    lines = [
        "# Tags that arrived from the source sites rather than from your scheme.",
        "#",
        "# Set the right-hand side to one of:",
        "#",
        "#   -                             delete the tag",
        "#   Some.Scheme.Tag               rename it, staying in tags",
        *[f"#   {kind}: Value{' ' * (20 - len(kind))}add to {column}, drop the tag"
          for kind, column in sorted(COLUMNS.items())],
        "#   (blank)                       leave the tag alone for now",
        "#",
        "# The service applies these when a book is added, so most tags never",
        "# reach this file twice. A name on the left may use * and ? to cover",
        "# a family of tags whose values keep changing, e.g.",
        "#   Last Update*                  = -",
        "# An exact name always wins over a pattern.",
        "#",
        "# A tag that names a group stands for several things; separate them",
        "# with commas rather than losing them all to a '-', e.g.",
        "#   The Watch                     = majchar: Disc.Vimes, Disc.Nobby",
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
        shown = " ".join(f"{kind}={tagmap.field_values(meta, COLUMNS[kind])}"
                         for kind in ("fandom", "genre") if kind in COLUMNS)
        lines.append(f"#     {shown}")
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
    RULES.write_text("\n".join(lines) + "\n", encoding="utf-8")

    undecided = sum(1 for t in found if not decided.get(t))
    print(f"{len(found)} stray tags on {len(bybook)} books")
    print(f"   {len(found) - undecided:>4} already decided")
    print(f"   {undecided:>4} need a decision")
    print(f"   {len(standing):>4} standing decisions kept for future imports")
    print(f"\nwritten to {RULES}")
    return 0


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    ap.add_argument("--review", action="store_true",
                    help="write the rules file and stop")
    parsed = ap.parse_args()
    configure(load_config(parsed.config))
    if not SCHEME_ROOTS:
        raise SystemExit(
            "scripts.scheme_roots is empty in " + parsed.config + ", so there "
            "is no way to tell a tag you filed from one a site supplied — "
            "every tag in the library would count as stray. List the top-level "
            "names your own scheme uses and run this again.")
    if parsed.review:
        _tagtool.whole_library_only(
            parsed, "--review",
            f"it rewrites {RULES.name} from the tags it finds, so an undecided "
            "tag on a book outside the range would lose its line")
        raise SystemExit(write_review(parsed))
    raise SystemExit(_tagtool.run_multi(parsed, transform, "stray-rollback",
                                        prepare=prepare))
