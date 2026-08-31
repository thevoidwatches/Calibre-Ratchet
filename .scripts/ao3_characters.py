#!/usr/bin/env python3
"""Fill #majchar from the character tags AO3 authors put on their own works.

AO3 asks authors to tag the characters in a work, and that list survives into
the epub — in FanFicFare's title page as "Characters:", and in AO3's own
download as a <dt>Character:</dt> block. Either way it is the author's own
statement about who is in the story, which is better evidence than anything
inferable from a tag scheme.

Unlike the story status, this does not go stale: an author does not un-tag a
character, so a download from 2021 is as good as one from today.

NAMES DO NOT MATCH ON THEIR OWN
AO3 writes names its own way and this library writes them another. Four
differences are mechanical and handled here:

  accents          Alya Cesaire        <- Alya Cesaire
  romanisation     Katsuki Bakugo      <- Bakugou Katsuki
  name order       Izuku Midoriya      <- Midoriya Izuku
  disambiguators   Eliot Spencer       <- Eliot Spencer (Leverage)

Matching is done against the names already in #majchar, which is what makes
the order flip safe: a reversal is only accepted when it lands on a name the
library already uses. Two differences are NOT mechanical and live in the
review file instead — hero names ("Chat Noir" is Adrien Agreste) and tags
that give only a first name ("Alya").

THE REVIEW FILE
ao3_names.txt lists every distinct character tag found, with what this script
would do with it. Edit the right-hand side to correct, add, or drop entries:

    Chat Noir (Miraculous Ladybug) = Adrien Agreste     <- an alias
    Class 1-A (My Hero Academia)   = -                  <- not a character
    Tikki                          = Tikki              <- new, keep as-is
    Some Ambiguous Thing           =                    <- blank: skipped

Regenerate it with --review after adding books; entries you have already
decided are preserved.

Usage (from server/, where config.toml lives):
    python ../.scripts/ao3_characters.py --review    # write ao3_names.txt
    python ../.scripts/ao3_characters.py             # dry run
    python ../.scripts/ao3_characters.py --apply
    python ../.scripts/ao3_characters.py --rollback ao3-rollback-<n>.json
"""

from __future__ import annotations

import html
import io
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402
from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402
from ratchet.config import load_config  # noqa: E402

# Set from config.toml at startup: the columns this library keeps its
# characters and its fandoms in.
FIELD = ""
FANDOM_FIELD = ""
REVIEW = Path(__file__).with_name("ao3_names.txt")
NOT_A_CHARACTER = "-"

TAGS = re.compile(r"<[^>]+>")
PAREN = re.compile(r"\s*\([^)]*\)\s*$")
# FanFicFare's title page: <b>Label:</b> value, one per line.
FFF_ROW = re.compile(r"<b>\s*([^<:]{1,30})\s*:\s*</b>\s*(.{0,4000}?)\s*(?:<br|</div|</p)",
                     re.I | re.S)
# AO3's own download: a <dt>/<dd> metadata block.
AO3_ROW = re.compile(r"<dt[^>]*>(.{0,40}?)</dt>\s*<dd[^>]*>(.{0,4000}?)</dd>",
                     re.I | re.S)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", s))).strip()


def fold(s: str) -> str:
    """A comparison key that ignores the differences AO3 and this library have
    no real disagreement about: accents, case, punctuation, and the -ou-/-o-
    romanisation of Japanese names."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("ou", "o")).strip()


def parse_epub(data: bytes) -> dict:
    """The metadata block from either kind of AO3 epub."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if "OEBPS/title_page.xhtml" in names:
            text = z.read("OEBPS/title_page.xhtml").decode("utf-8", "replace")
            return {clean(k): clean(v) for k, v in FFF_ROW.findall(text)}
        pre = [n for n in names if n.endswith("preface.xhtml")]
        if pre:
            text = z.read(pre[0]).decode("utf-8", "replace")
            return {clean(k).rstrip(":"): clean(v) for k, v in AO3_ROW.findall(text)}
    return {}


def tagged_characters(fields: dict) -> list[str]:
    """Every character tag on the work, as AO3 spells them.

    A tag may pack aliases together with pipes — "Taylor Hebert | Skitter |
    Weaver" is one person under three names — so the whole tag is kept and
    the alternatives are tried in turn when matching.
    """
    raw = fields.get("Characters") or fields.get("Character") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def resolve(tag: str, folded: dict[str, str]) -> tuple[str | None, str]:
    """(library name, how it was reached) for one AO3 character tag."""
    for alias in [a.strip() for a in tag.split("|") if a.strip()]:
        for candidate in (alias, PAREN.sub("", alias)):
            key = fold(candidate)
            if key in folded:
                return folded[key], "matched"
    return None, "unmatched"


# Tags naming a group, the readership, or a placeholder rather than a person.
# Compared as whole folded words rather than by regex: an earlier attempt at
# this used \b word boundaries and the escaping turned every one of them into
# a literal backspace byte in this file.
NOT_PEOPLE_WORDS = {
    "everyone", "reader", "readers", "others", "various", "cast", "class",
    "classmates", "students", "original characters", "original character",
    "original male character", "original female character",
}
NOT_PEOPLE_TAIL = ("family", "crew", "team", "characters", "students")


def looks_like_a_group(tag: str) -> bool:
    """Whether a tag names something other than one person."""
    folded = fold(bare_name(tag))
    if not folded:
        return False
    return (folded in NOT_PEOPLE_WORDS
            or folded.startswith("original ")
            or folded.split()[-1] in NOT_PEOPLE_TAIL)


def bare_name(tag: str) -> str:
    """The tag as a plain name: first alias, without AO3's (Fandom) suffix."""
    first = tag.split("|")[0].strip()
    return PAREN.sub("", first).strip() or tag.strip()


def suggest(tag: str, folded: dict[str, str], fandoms: set[str],
            by_fandom: dict[str, set[str]]) -> str | None:
    """A library name this tag is probably a short form of.

    Only within the fandoms the tag actually appears in, and only when
    exactly one name there matches — "Alya" finds "Alya Cesaire", but a tag
    that could be two different people is left for a human."""
    key = fold(bare_name(tag))
    if not key:
        return None
    pool: set[str] = set()
    for fandom in fandoms:
        pool |= by_fandom.get(fandom, set())
    hits = {n for n in pool
            if fold(n).startswith(key + " ") or fold(n).endswith(" " + key)}
    return next(iter(hits)) if len(hits) == 1 else None


def names_by_fandom(metas: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for meta in metas.values():
        if not meta:
            continue
        for value in _tagtool.current(meta, FIELD):
            fandom, name = split_value(value)
            if name:
                out[fandom].add(name)
    return out


def library_names(metas: dict) -> dict[str, str]:
    """Folded key -> the spelling this library uses, including the reversed
    word order so an Eastern-order tag finds its Western-order entry."""
    out: dict[str, str] = {}
    for meta in metas.values():
        if not meta:
            continue
        for value in _tagtool.current(meta, FIELD):
            _fandom, name = split_value(value)
            if not name:
                continue
            out.setdefault(fold(name), name)
            parts = name.split()
            if len(parts) == 2:
                out.setdefault(fold(f"{parts[1]} {parts[0]}"), name)
    return out


def split_label(value: str) -> tuple[str, str | None]:
    """A review file value into (name, fandom).

    "Adrien Agreste"                 -> the book decides the fandom
    "Adrien Agreste @ Miraculous"    -> filed under Miraculous whatever the
                                        book says, which is how a crossover
                                        gets its characters placed at all.
    """
    name, sep, fandom = value.partition("@")
    return name.strip(), (fandom.strip() or None) if sep else None


def read_review() -> dict[str, str]:
    """The decisions already recorded in ao3_names.txt."""
    decided: dict[str, str] = {}
    if not REVIEW.exists():
        return decided
    unreadable = []
    for number, line in enumerate(
            REVIEW.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            # Every rule needs an "=". Without one the line is not a decision
            # at all, and staying quiet about it would look the same as never
            # having edited the tag.
            unreadable.append((number, line.strip()))
            continue
        left, _, right = line.partition("=")
        decided[left.strip()] = right.strip()
    if unreadable:
        print(f"WARNING: {len(unreadable)} line(s) in {REVIEW.name} have no "
              f"'=' and were ignored:")
        for number, text in unreadable[:10]:
            print(f"   line {number}: {text}")
        print("   a dropped tag is written 'Tag = -', not 'Tag - '")
    return decided


def ao3_books(metas: dict) -> list[int]:
    out = []
    for meta in metas.values():
        if not meta:
            continue
        idn = meta.get("identifiers") or {}
        url = idn.get("url") or idn.get("uri") or ""
        if url.startswith(("http//", "https//")):
            url = url.replace("//", "://", 1)
        if "archiveofourown.org" in urlparse(url).netloc.lower():
            out.append(int(meta["application_id"]))
    return out


def collect(args) -> tuple[dict, dict, dict]:
    """(book id -> character tags, folded library names, book id -> metadata)."""
    cfg = load_config(args.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    ids = calibre.search(query="", num=100000,
                         library_id=args.library)["book_ids"]
    metas: dict = {}
    for i in range(0, len(ids), 200):
        metas.update(calibre.books(ids[i:i + 200], library_id=args.library))
    tags: dict[int, list[str]] = {}
    for book_id in ao3_books(metas):
        try:
            fields = parse_epub(calibre.download_format(book_id, "EPUB", args.library))
        except (CalibreError, zipfile.BadZipFile):
            continue
        found = tagged_characters(fields)
        if found:
            tags[book_id] = found
    return tags, library_names(metas), metas


# calibre writes a hierarchy as "DC Comics.Batman", with no space after the
# separator, so a dot followed by one is punctuation inside a single name --
# "Jonathan Strange and Mr. Norrell" is one fandom, not two levels.
FANDOM_SPLIT = re.compile(r"\.(?!\s)")


def fandom_root(value: str) -> str:
    return FANDOM_SPLIT.split(value)[0]


def split_value(value: str) -> tuple[str, str]:
    """A stored "Fandom.Character" into its two halves, using the same rule
    that joined them: the separator is a dot with no space after it."""
    parts = FANDOM_SPLIT.split(value, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (value, "")


def fandom_roots(meta: dict) -> list[str]:
    """Every fandom this book is filed under, at root level, in order."""
    roots: list[str] = []
    for value in _tagtool.current(meta, FANDOM_FIELD):
        root = fandom_root(value)
        if root not in roots:
            roots.append(root)
    return roots


def fandom_of(meta: dict) -> str | None:
    """The branch a character on this book belongs under. Same rule the tag
    importer uses: the book's own fandom when it has exactly one, and nothing
    when it is a crossover, because guessing there is not recoverable."""
    roots = fandom_roots(meta)
    return roots[0] if len(roots) == 1 else None


def write_review(args) -> int:
    tags, folded, metas = collect(args)
    decided = read_review()
    by_fandom = names_by_fandom(metas)

    seen: Counter = Counter()
    where: dict[str, set] = defaultdict(set)
    for book_id, found in tags.items():
        fandom = fandom_of(metas[str(book_id)]) or "(crossover)"
        for tag in found:
            seen[tag] += 1
            where[tag].add(fandom)

    # Four outcomes, each pre-filled with its best guess so that reviewing
    # means correcting exceptions rather than typing 300 names out. Which
    # section a tag lands in is recomputed every run; only the value is
    # carried over, so edits survive without freezing the grouping.
    matched: dict[str, str] = {}
    guessed: dict[str, str] = {}
    groups: dict[str, str] = {}
    fresh: dict[str, str] = {}
    edited = 0
    for tag in seen:
        name, how = resolve(tag, folded)
        if how == "matched":
            section, default = matched, name
        elif looks_like_a_group(tag):
            section, default = groups, NOT_A_CHARACTER
        else:
            hint = suggest(tag, folded, where[tag], by_fandom)
            section, default = (guessed, hint) if hint else (fresh, bare_name(tag))
        value = decided.get(tag, default)
        # "Name @ " is this script's own prompt for a fandom, not something a
        # reader typed, so it does not count as an edit on the next run.
        if tag in decided and value not in (default, f"{default} @ "):
            edited += 1
        section[tag] = value

    # A tag only ever seen on crossovers, whose name the library cannot place
    # on its own, will be silently dropped by the import. Those are the ones
    # worth a person's attention, so they get their own section and a value
    # ending in "@" ready for the fandom to be typed after it.
    placeable: dict[str, set] = {}
    for meta in metas.values():
        if not meta:
            continue
        for value in _tagtool.current(meta, FIELD):
            fandom, name = split_value(value)
            if name:
                placeable.setdefault(name, set()).add(fandom)
    for book_id, found in tags.items():
        only = fandom_of(metas[str(book_id)])
        if only:
            for tag in found:
                name, _lab = split_label(matched.get(tag) or guessed.get(tag)
                                         or fresh.get(tag) or "")
                if name:
                    placeable.setdefault(name, set()).add(only)

    needs_label: dict[str, str] = {}
    for book_id, found in tags.items():
        roots = fandom_roots(metas[str(book_id)])
        if len(roots) < 2:
            continue
        for tag in found:
            if tag in groups or tag not in seen:
                continue
            bucket = (matched if tag in matched else
                      guessed if tag in guessed else
                      fresh if tag in fresh else None)
            if bucket is None:
                continue
            name, labelled = split_label(bucket[tag])
            # A tag already answered with "-" is decided, not outstanding:
            # asking for a fandom for something being dropped is noise.
            if not name or labelled or name == NOT_A_CHARACTER:
                continue
            known = placeable.get(name) or set()
            if len(known) == 1 and known & set(roots):
                continue            # the library places it without help
            needs_label[tag] = f"{name} @ "
    for tag in needs_label:
        for bucket in (matched, guessed, fresh):
            bucket.pop(tag, None)

    # Where each tag will actually end up. Grouping on this rather than on the
    # fandoms of the books it appears in is the difference between "(crossover)"
    # and "Girl Genius" for a name that one single-fandom book already places.
    destination: dict[str, set] = defaultdict(set)
    for book_id, found in tags.items():
        roots = fandom_roots(metas[str(book_id)])
        for tag in found:
            bucket = (matched if tag in matched else
                      guessed if tag in guessed else
                      groups if tag in groups else
                      fresh if tag in fresh else None)
            if bucket is None:
                continue
            name, labelled = split_label(bucket[tag])
            if not name or name == NOT_A_CHARACTER:
                continue
            if labelled:
                destination[tag].add(labelled)
            elif len(roots) == 1:
                destination[tag].add(roots[0])
            else:
                known = placeable.get(name) or set()
                hit = known & set(roots)
                if len(known) == 1 and len(hit) == 1:
                    destination[tag].add(next(iter(hit)))
    # The unplaceable ones are headed by what there is to choose between.
    for tag in needs_label:
        for book_id, found in tags.items():
            if tag in found:
                destination[tag] |= {f"choose: {' / '.join(fandom_roots(metas[str(book_id)]))}"}

    width = max([len(t) for t in seen] + [10]) + 1
    lines = [
        "# AO3 character tags -> the names this library uses.",
        "#",
        "# Every line is pre-filled with what the import would do. Change the",
        "# right-hand side to correct it, put a single '-' to drop the tag, or",
        "# blank it to leave the tag out for now. The fandom normally comes",
        "# from the book, so write the character's name on its own.",
        "#",
        "# Books filed under two fandoms are the exception: nothing says which",
        "# of them a character belongs to. Names the library already places",
        "# unambiguously are handled for you; for the rest, name the fandom",
        "# after an @:",
        "#",
        "#     Krosp                          = Krosp @ Girl Genius",
        "#",
        "# The heading above each block is the fandom the names under it will",
        "# be filed under -- not the fandom of the books they came from. An @",
        "# label is taken as final, whatever the book says.",
        "#",
        "# Rerunning --review keeps every line already here and only appends",
        "# tags it has not seen, so nothing decided is ever overwritten.",
        "",
    ]

    def section(title: str, rows: dict[str, str], note: str = "") -> None:
        # reads `destination`, filled just above
        if not rows:
            return
        lines.append(f"# ==== {title} ({len(rows)}) "
                     + "=" * max(0, 46 - len(title)))
        if note:
            lines.extend("# " + n for n in note.split("\n"))
        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for tag, value in rows.items():
            label = ", ".join(sorted(destination.get(tag) or ())) or "(dropped)"
            grouped[label].append((tag, value))
        for fandom in sorted(grouped):
            lines.append("")
            lines.append(f"#   {fandom}")
            for tag, value in sorted(grouped[fandom]):
                lines.append(f"{tag.ljust(width)}= {value}")
        lines.append("")

    section("matched a name already in the library", matched,
            "check for a wrong person; otherwise nothing to do")
    section("look like a short form of a known name -- CHECK THESE", guessed,
            "the tag gave a partial name and exactly one library name in the\n"
            "same fandom fits. Most useful section to read.")
    section("look like a group rather than a person", groups,
            "pre-set to '-' (dropped). Put a name back if one is really a person.")
    section("only on crossovers -- NAME THE FANDOM AFTER THE @", needs_label,
            "these books are filed under two fandoms and the library cannot\n"
            "place these names on its own, so they are dropped unless you\n"
            "finish the line: 'Krosp = Krosp @ Girl Genius'. Leaving the @\n"
            "empty skips the tag, which is a fine answer too.")
    section("new characters, kept under their own name", fresh,
            "not in the library yet; the author tagged them, so they come in\n"
            "as-is. Hero names needing an alias will be in here -- e.g. set\n"
            "Chat Noir to Adrien Agreste rather than letting it stand alone.")

    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    crossover = sum(1 for b in tags
                    if fandom_of(metas[str(b)]) is None)
    print(f"{len(tags)} AO3 books, {sum(seen.values())} character tags, "
          f"{len(seen)} distinct")
    print(f"   {edited:>4} carry an edit of yours, kept as written")
    print(f"   {len(matched):>4} matched an existing library name")
    print(f"   {len(guessed):>4} look like a short form  <- worth reading")
    print(f"   {len(groups):>4} look like groups, pre-dropped")
    print(f"   {len(fresh):>4} new, kept as-is")
    print(f"   {len(needs_label):>4} need a fandom after the @  <- or they are dropped")
    print(f"\n{crossover} of the books are filed under more than one fandom. Names the\n"
          f"library already places unambiguously are handled; the rest are the\n"
          f"@ section above.")
    print(f"\nwritten to {REVIEW}")
    return 0


# Filled by prepare() before any book is transformed: AO3 tag -> library name.
_decided: dict[str, str] = {}
_chars: dict[int, list[str]] = {}
# Character name -> the fandoms it has been seen belonging to, used only to
# place a name on a crossover, where the book itself cannot say.
_fandom_of_name: dict[str, set] = {}


def prepare(metas: dict) -> None:
    folded = library_names(metas)
    review = read_review()
    _decided.clear()
    _chars.clear()
    cfg = load_config(prepare.config)
    calibre = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                            cfg.calibre.password)
    for book_id in ao3_books(metas):
        try:
            fields = parse_epub(calibre.download_format(book_id, "EPUB",
                                                        prepare.library))
        except (CalibreError, zipfile.BadZipFile):
            continue
        found = tagged_characters(fields)
        if found:
            _chars[book_id] = found
    for tags in _chars.values():
        for tag in tags:
            if tag in _decided:
                continue
            # The review file wins wherever it has an opinion, so a correction
            # written there is never re-decided by the matcher underneath it.
            if tag in review:
                _decided[tag] = review[tag]
            else:
                name, how = resolve(tag, folded)
                _decided[tag] = name if how == "matched" else ""

    # Which fandom each name belongs to, learned from the books that only
    # have one. Seeded from what #majchar already holds, then extended with
    # this run's own single-fandom books, so a name first met here is still
    # available to attribute a crossover further down the library.
    _fandom_of_name.clear()
    for meta in metas.values():
        if not meta:
            continue
        for value in _tagtool.current(meta, FIELD):
            fandom, name = split_value(value)
            if name:
                _fandom_of_name.setdefault(name, set()).add(fandom)
    for book_id, tags in _chars.items():
        only = fandom_of(metas[str(book_id)])
        if not only:
            continue
        for tag in tags:
            name, labelled = split_label(_decided.get(tag, ""))
            if name and name != NOT_A_CHARACTER:
                _fandom_of_name.setdefault(name, set()).add(labelled or only)


def transform(existing: list[str], meta: dict) -> list[str]:
    book_id = int(meta.get("application_id") or 0)
    tags = _chars.get(book_id)
    if not tags:
        return existing
    roots = fandom_roots(meta)
    if not roots:
        return existing              # no fandom at all: nothing to file under
    add = []
    for tag in tags:
        name, labelled = split_label(_decided.get(tag, ""))
        if not name or name == NOT_A_CHARACTER:
            continue
        if labelled:
            add.append(f"{labelled}.{name}")
            continue
        if len(roots) == 1:
            add.append(f"{roots[0]}.{name}")
            continue
        # A crossover. Take the fandom only when the library is unanimous
        # about this name and the book is actually filed under it; anything
        # less would be a guess that no later pass could spot as wrong.
        seen = _fandom_of_name.get(name) or set()
        candidates = seen & set(roots)
        if len(seen) == 1 and len(candidates) == 1:
            add.append(f"{next(iter(candidates))}.{name}")
    # Additive, like the tag importer: whatever is already recorded stays.
    return list(existing) + add


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    ap.add_argument("--review", action="store_true",
                    help="write ao3_names.txt and stop")
    parsed = ap.parse_args()
    _cfg = load_config(parsed.config)
    FIELD = _cfg.scripts.majchar_field
    FANDOM_FIELD = _cfg.scripts.fandom_field
    if not FIELD:
        raise SystemExit(f"scripts.majchar_field is not set in {parsed.config}; "
                         "there is nowhere to put the characters found.")
    if parsed.review:
        raise SystemExit(write_review(parsed))
    prepare.config, prepare.library = parsed.config, parsed.library
    raise SystemExit(_tagtool.run(parsed, transform, "ao3-rollback", FIELD,
                                  prepare=prepare))
