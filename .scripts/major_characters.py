#!/usr/bin/env python3
"""Populate the Major Characters column from the characters named in tags.

The tag scheme puts a character in the last segment of most facets, so the
library already knows who each story is about — but only in a form you cannot
ask a question of. "Everything with Taylor Hebert in it" currently means
ORing a dozen roots together. This lifts those names into #majchar, one
value per character, filed under the fandom they belong to:

    Powers.Brute.Taylor Hebert   ->  Worm.Taylor Hebert
    Romance.Miraculous.Marinette Dupain-Cheng/Adrien Agreste
                                 ->  Miraculous.Marinette Dupain-Cheng
                                     Miraculous.Adrien Agreste

WHERE THE CHARACTER IS
Every root that names people is listed in ROOTS below, with the depth its
tags reach when they carry one. Depth matters because the same root holds
both kinds: "Key Events.Generic.Coma.Izuku Midoriya" names a person and
"Key Events.Generic.Adoption" does not. Roots not listed at all (Content,
Format, Themes, Relative Time, Time Period, Group Traits) never name one.

WHICH FANDOM
In order of trust:
  1. a parenthetical on the name itself — "Taylor Hebert (Worm)", which the
     ship tags use to mark the visitor in a crossover;
  2. the fandom segment inside the tag, but only for Romance — see ROOTS;
  3. the book's own #fandom, when it has exactly one;
  4. how the rest of the library attributes that same name, when it is
     unambiguous there and the book is filed under that fandom.
A crossover the four cannot settle is left for a human: guessing which of two
fandoms a name belongs to is exactly the kind of error that is invisible
afterwards. Those are reported as UNATTRIBUTED and skipped.

Fandom names are then mapped onto the book's own #fandom values, so a branch
reads "Marvel Comics.Peter Parker" rather than "Marvel.Peter Parker".

REVIEW BEFORE APPLYING
--vocab prints every character this would create, with counts, plus every
leaf it refused and why. Read that first: NOT_A_CHARACTER below is the list
of leaves that sit where a name would but are groups, and it will need
additions as the library grows.

Usage (from server/, where config.toml lives):
    python ../.scripts/major_characters.py --vocab      # what it would create
    python ../.scripts/major_characters.py              # per-book dry run
    python ../.scripts/major_characters.py --apply
    python ../.scripts/major_characters.py --rollback majchar-rollback-<n>.json
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tagtool  # noqa: E402

FIELD = "#majchar"

# root -> [(segment count at which the leaf is a person,
#           index of the segment naming THAT PERSON'S fandom, or None)]
# Counts are 1-based, so "Gender.Female.Harry Potter" is 3.
#
# Only Romance carries a fandom that describes the characters. Everywhere
# else the fandom segment describes the facet, not the person:
# "Powers.Specific.Marvel.Rogue.Taylor Hebert" says Taylor has Rogue's
# powers, not that Taylor is a Marvel character, and reading it as hers
# attributes her to six fandoms she does not come from. Those fall through
# to the book's own #fandom, or to what the rest of the library knows.
ROOTS = {
    "Alignment":        [(3, None)],
    "Character Swap":   [(2, None)],
    "Character Traits": [(4, None)],
    "Crossover Tropes": [(3, None), (4, None)],
    "Disabilities":     [(3, None)],
    "Gender":           [(3, None)],
    "Groups":           [(4, None)],
    "Jobs":             [(4, None), (5, None)],
    "Key Events":       [(4, None), (5, None)],
    "Neurodivergency":  [(3, None)],
    "Powers":           [(3, None), (4, None), (5, None)],
    "Reincarnation":    [(2, None)],
    "Romance":          [(3, 1)],
    "Self-Insert":      [(3, None)],
    "Sexuality":        [(3, None)],
    "Species":          [(4, None), (5, None)],
    "Time Travel":      [(4, None)],
    "Tropes":           [(3, None)],
}

# Leaves that sit where a character would but are not one: groups, factions,
# families, and the placeholders used when a tag applies to everybody.
#
# The left side of an "X!Y" compound is the one to watch: Y is always a real
# person, but X is only sometimes. "Marquis!Hisashi Midoriya" and
# "Izumi Curtis!Inko Midoriya" name two people; "Robin!Izuku Midoriya" and
# "Heterodyne!Tony Stark" name a mantle and a family that the person took on.
NOT_A_CHARACTER = {
    "Multiple Characters", "Everyone", "Miraculous Cast", "PRT",
    "Dursley Family", "Tendo Family", "Stark Family", "Blacks", "Goblins",
    "Hellsing", "His Older Self", "Reader", "OC", "Female",
    # mantles, titles and family names worn by someone else
    "Wizard", "Heterodyne", "Robin", "Parker", "Boy-Who-Lived",
    "Captain America",
    # Identity Reveal's qualifiers, which share its depth
    "Accidental", "Partial", "Public",
    # Powers.Generic.<power> with nobody attached, at the same depth as
    # Powers.None.<character>
    "Vampire", "Shardspeaking",
}

# Characters whose fandom was settled by hand, because nothing in the library
# says it: a crossover one-off whose name appears nowhere unambiguous. Unlike
# the learned map these are not checked against the book's own #fandom — the
# whole point is that the book is the only place the name occurs, and some of
# those books have no #fandom recorded at all.
OVERRIDES = {
    "Percy Jackson": "Riordanverse",
    "Kratos": "God of War",
    "Yanagi Reiko": "My Hero Academia",
    "Izumi Curtis": "Fullmetal Alchemist",
    # Their books tag the fandom of the power or species, not the person:
    # "Powers.Specific.Girl Genius.Spark.Sherlock Holmes" is Holmes with a
    # Girl Genius power, and the Doctor Who one is Watson as a Time Lord.
    "Sherlock Holmes": "Sherlock",
    "John Watson": "Sherlock",
    "Acererak": "Forgotten Realms",
    "Sauron": "The Lord of the Rings",
}

# Tag-side fandom names spelled differently from the #fandom column. Only
# needed where matching against the book's own fandoms cannot resolve it.
ALIASES = {
    "avatar": "Avatar: The Last Airbender",
    "the avatar": "Avatar: The Last Airbender",
    "marvel": "Marvel Comics",
    "mcu": "Marvel Comics",
    "legend of zelda": "The Legend of Zelda",
    "dnd": "Dungeons and Dragons",
    "mha": "My Hero Academia",
}

# "Taylor Hebert (Worm)" — the fandom a crossover's visitor comes from.
PAREN = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")


# calibre writes a hierarchy as "DC Comics.Batman", with no space after the
# separator, so a dot followed by one is punctuation inside a single name --
# "Jonathan Strange and Mr. Norrell" is one fandom, not two levels.
FANDOM_SPLIT = re.compile(r"\.(?!\s)")


def fandom_root(value: str) -> str:
    return FANDOM_SPLIT.split(value)[0]


def split_names(leaf: str) -> list[str]:
    """A leaf into the people it names: "A/B" is a ship, "A!B" is one person
    wearing another's identity, and both sides are real characters."""
    parts = [leaf]
    for sep in ("/", "!"):
        parts = [q.strip() for p in parts for q in p.split(sep)]
    return [p for p in parts if p]


def character_leaves(tag: str) -> tuple[list[str], str | None]:
    """The people a tag names, and the fandom its own path claims, if any."""
    segs = tag.split(".")
    for depth, fandom_at in ROOTS.get(segs[0], []):
        if len(segs) == depth:
            fandom = segs[fandom_at] if fandom_at is not None else None
            return split_names(segs[-1]), fandom
    return [], None


def resolve_fandom(claim: str | None, book_fandoms: list[str]) -> str | None:
    """A fandom name written the way the #fandom column writes it.

    Matched against the book's own fandoms first, so "Marvel Comics.MCU" on
    the book answers a tag that only says "Marvel"."""
    roots: list[str] = []
    for f in book_fandoms:
        root = fandom_root(f)
        if root not in roots:
            roots.append(root)
    if claim is None:
        return roots[0] if len(roots) == 1 else None
    want = ALIASES.get(claim.strip().lower(), claim.strip())
    for root in roots:
        if root.lower() == want.lower():
            return root
    # "Avatar" against "Avatar: The Last Airbender"; "Tortall" against a book
    # filed under "Tortall.Protector of the Small".
    for root in roots:
        if root.lower().startswith(want.lower()) or want.lower().startswith(root.lower()):
            return root
    # The claim matches nothing the book is filed under. On a book with one
    # fandom the claim was only ever a disambiguator and is redundant, so the
    # book wins: "Boromir (LotR)" on a book filed as The Lord of the Rings is
    # that fandom, not a new one called LotR. Only a crossover, where the book
    # cannot say which half a name belongs to, has to fall back to the claim.
    if len(roots) == 1:
        return roots[0]
    return want or None


# Learned from the books whose attribution is certain: character name -> the
# fandoms it has been seen belonging to. Filled by learn() before any book is
# transformed, and used only to attribute a name on a crossover, where the
# tag says nothing and the book's own fandoms are ambiguous.
LEARNED: dict[str, set[str]] = {}


def characters_for(meta: dict, learned: dict[str, set[str]] | None = None
                   ) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """This book's (fandom, character) pairs, and what was skipped.

    Pairs rather than "Fandom.Character" strings, and joined only at the
    moment of writing: "Harry Potter" names both a fandom and a character, so
    "Harry Potter.Harry Potter" cannot be taken apart again by any rule.
    Nothing here ever splits a stored value back into its halves.
    """
    fandoms = _tagtool.current(meta, "#fandom")
    found: list[tuple[str, str]] = []
    skipped: list[tuple[str, str, str]] = []
    for tag in meta.get("tags") or []:
        names, claim = character_leaves(tag)
        for name in names:
            hint = None
            m = PAREN.match(name)
            if m:
                name, hint = m.group(1).strip(), m.group(2).strip()
            if not name or name in NOT_A_CHARACTER:
                skipped.append((tag, name, "not a character"))
                continue
            fandom = resolve_fandom(hint or claim, fandoms)
            if not fandom and learned is not None:
                fandom = learn_fandom(name, fandoms, learned) or OVERRIDES.get(name)
            if not fandom:
                skipped.append((tag, name, "UNATTRIBUTED"))
                continue
            found.append((fandom, name))
    return found, skipped


def learn_fandom(name: str, book_fandoms: list[str],
                 learned: dict[str, set[str]]) -> str | None:
    """Attribute a name on a crossover from how it is attributed elsewhere.

    Two guards, because a wrong fandom here is invisible afterwards: the name
    must have been seen in exactly one fandom across the whole library, and
    that fandom must be one this book is actually filed under. A name that is
    ambiguous library-wide, or that would drag in a fandom the book is not
    in, stays unattributed and is reported instead."""
    seen = learned.get(name)
    if not seen or len(seen) != 1:
        return None
    only = next(iter(seen))
    roots = {fandom_root(f) for f in book_fandoms}
    return only if only in roots else None


def learn(metas: dict) -> None:
    """Build LEARNED from every book whose attribution needed no guessing."""
    LEARNED.clear()
    for meta in metas.values():
        if not meta:
            continue
        found, _ = characters_for(meta)          # no learned map: certain only
        for fandom, name in found:
            LEARNED.setdefault(name, set()).add(fandom)


def transform(existing: list[str], meta: dict) -> list[str]:
    """Additive: whatever is already in the column stays. Tags are one source
    of characters, not the only one, so a hand-added value has to survive a
    rerun."""
    found, _ = characters_for(meta, LEARNED)
    return list(existing) + [f"{fandom}.{name}" for fandom, name in found]


def report_vocab(args) -> int:
    """Everything this would create, for review before anything is written."""
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

    learn(metas)

    vocab: collections.Counter = collections.Counter()
    refused: collections.Counter = collections.Counter()
    unattributed: list[tuple[str, str, str]] = []
    guessed: collections.Counter = collections.Counter()
    for book_id, meta in metas.items():
        if not meta:
            continue
        sure, _ = characters_for(meta)
        all_found, skipped = characters_for(meta, LEARNED)
        vocab.update(all_found)
        for pair in all_found:
            if pair not in sure:
                guessed[pair] += 1
        for tag, name, why in skipped:
            if why == "UNATTRIBUTED":
                unattributed.append((book_id, name, tag))
            else:
                refused[name] += 1

    by_fandom: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    for (fandom, name), n in vocab.items():
        by_fandom[fandom].append((name, n))
    ambiguous = {n: f for n, f in LEARNED.items() if len(f) > 1}
    print(f"=== {len(vocab)} characters across {len(by_fandom)} fandoms ===")
    for fandom in sorted(by_fandom):
        people = sorted(by_fandom[fandom])
        print(f"\n--- {fandom}  [{len(people)}]")
        for name, n in people:
            print(f"   {n:>3}  {name}")

    print(f"\n=== refused as not-a-character ({sum(refused.values())} uses) ===")
    for name, n in sorted(refused.items()):
        print(f"   {n:>3}  {name}")

    print(f"\n=== attributed from the rest of the library ({sum(guessed.values())} uses) ===")
    print("    crossovers whose tag named no fandom, resolved because the name")
    print("    belongs to one fandom everywhere else and the book is in it")
    for (fandom, name), n in sorted(guessed.items()):
        print(f"   {n:>3}  {name}  ->  {fandom}")

    print(f"\n=== names seen in more than one fandom, so never guessed ({len(ambiguous)}) ===")
    for name, fandoms in sorted(ambiguous.items()):
        print(f"        {name:<26} {sorted(fandoms)}")

    print(f"\n=== still unattributed ({len(unattributed)}) ===")
    for book_id, name, tag in unattributed:
        print(f"   {book_id:>5}  {name:<26} {tag}")
    return 0


if __name__ == "__main__":
    ap = _tagtool.parser(__doc__)
    ap.add_argument("--vocab", action="store_true",
                    help="print the characters this would create, and what it "
                         "refused, without touching anything")
    parsed = ap.parse_args()
    if parsed.vocab:
        raise SystemExit(report_vocab(parsed))
    raise SystemExit(_tagtool.run(parsed, transform, "majchar-rollback", FIELD,
                                  prepare=learn))
