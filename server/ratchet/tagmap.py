"""What to do with the tags a story arrives wearing.

FanFicFare copies a story's own tags into the epub and calibre imports them
when the book is added, so every import brings in whatever the author or the
site used: "In-Progress", "FanFiction", "Last Update: 2026/09/09", AO3
freeform tags, character names in the site's own spelling. Some are worth
keeping in another form, some are worth moving to a column of their own, and
some are noise.

Which is which is a judgement about one library, so it lives in a rules file
rather than in code. Each line maps a tag to what should become of it:

    In-Progress             = Serial.Ongoing      rename, staying in tags
    Stubbed                 = Serial.Stubbed
    Angst                   = genre: Angst        move to a column
    Taylor Hebert           = majchar: Worm.Taylor Hebert
    FanFiction              = -                   delete
    Last Update*            = -                   ...and by pattern
    Some New Thing          =                     (blank) leave it alone

A tag with no rule is left exactly as it is, so an import can never lose
something nobody has ruled on — it shows up in the next review instead.

Moves are additive: the value is added to the column, never replacing what is
already there, and a book that already records it simply loses the tag.

Both the service (when a book is added) and .scripts/stray_tags.py (sweeping
the library afterwards) read the same file through this module, so a decision
means the same thing whichever applied it.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from . import configfiles
from .calibre import field_values

DELETE = "-"


@dataclass
class Rules:
    """Tag rules, with the exact names kept apart from the patterns.

    An exact name always wins over a pattern, however the file is ordered —
    otherwise "Last Update*" would swallow a specific rule written below it.
    Patterns are tried in the order written, so the first one that matches is
    the one that applies.
    """
    exact: dict[str, str] = field(default_factory=dict)
    globs: list[tuple[str, str]] = field(default_factory=list)
    path: Path | None = None
    bad_lines: list[tuple[int, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.exact or self.globs)

    def target_for(self, tag: str) -> str:
        """What this tag becomes: "" when no rule covers it."""
        if tag in self.exact:
            return self.exact[tag]
        for pattern, target in self.globs:
            # Case-sensitive: calibre's tags are, and "AU" is not "au".
            if fnmatch.fnmatchcase(tag, pattern):
                return target
        return ""


def is_pattern(name: str) -> bool:
    return any(c in name for c in "*?[")


def split_values(text: str) -> list[str]:
    """What a rule's right-hand side names, which may be several things.

    A tag can stand for a group rather than one thing — "The Watch" is a
    handful of people, "Class 1-A" is twenty — and dropping it loses all of
    them:

        The Watch = majchar: Discworld.Sam Vimes, Discworld.Nobby Nobbs

    Commas are safe as the separator because calibre separates values with
    them itself, so no single tag or column value can contain one.
    """
    return [part.strip() for part in text.split(",") if part.strip()]


def load(path: str | Path | None) -> Rules:
    """Read a rules file. A missing file is not an error — it means no rules
    have been written yet, and every tag is then left alone."""
    rules = Rules(path=Path(path) if path else None)
    if rules.path is None or not rules.path.is_file():
        return rules
    text = rules.path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            rules.bad_lines.append((number, line.strip()))
            continue
        name, _, target = line.partition("=")
        name, target = name.strip(), target.strip()
        if not name:
            rules.bad_lines.append((number, line.strip()))
        elif is_pattern(name):
            rules.globs.append((name, target))
        else:
            rules.exact[name] = target
    return rules


def parse_target(target: str, columns: dict[str, str]) -> list[tuple[str, str]] | None:
    """A rule's right-hand side as [(column, value)], where an empty column
    means the value stays a tag.

    A column named part-way along applies to everything after it, so one tag
    can become several things in several places without repeating itself:

        The Watch = Tropes.Found Family, majchar: Discworld.Vimes, Discworld.Nobby

    is one trope and two characters. "tags:" names the tags themselves, so
    a rule can go back to them after naming a column:

        The Watch = majchar: Discworld.Vimes, tags: Tropes.Found Family

    None comes back when a part names a column this library has not
    configured — a rule to leave alone rather than guess at, and the whole
    rule, so half of it cannot be applied before the mistake is noticed.
    """
    out: list[tuple[str, str]] = []
    destination = ""
    for part in split_values(target):
        name, sep, rest = part.partition(":")
        if sep:
            name = name.strip()
            # "tags" is calibre's own name for the tags themselves, and the
            # way back after a rule has sent something to a column.
            column = ("" if name == "tags" else
                      columns.get(name, name if name.startswith("#") else ""))
            if not column and name != "tags":
                return None
            destination, value = column, rest.strip()
        else:
            value = part
        if value:
            out.append((destination, value))
    return out


def apply(meta: dict, rules: Rules, columns: dict[str, str]) -> dict[str, list[str]]:
    """The columns this book should end up with, or {} to leave it alone.

    `columns` maps the short names a rule may use on the left of its colon
    ("genre", "majchar") to the calibre column each writes to. A rule naming
    a column that this library has not configured is ignored rather than
    guessed at, and its tag stays put.
    """
    tags = list(meta.get("tags") or [])
    if not tags or not rules:
        return {}

    keep: list[str] = []
    additions: dict[str, list[str]] = {}
    touched = False
    for tag in tags:
        target = rules.target_for(tag)
        if not target:
            keep.append(tag)                     # no rule: leave it alone
            continue
        if target == DELETE:
            touched = True
            continue
        parsed = parse_target(target, columns)
        if parsed is None:
            keep.append(tag)                     # unknown column: leave it be
            continue
        stays = [value for column, value in parsed if not column]
        keep.extend(stays)                       # the parts that are still tags
        for column, value in parsed:
            if not column:
                continue
            into = additions.setdefault(column, field_values(meta, column))
            if value not in into:
                into.append(value)
        # Changed if anything left the tags, or what stayed is not the tag itself.
        touched = touched or stays != [tag] or len(stays) != len(parsed)

    if not touched:
        return {}
    out: dict[str, list[str]] = {}
    if keep != tags:
        out["tags"] = _dedupe(keep)
    for column, values in additions.items():
        if values != field_values(meta, column):
            out[column] = _dedupe(values)
    return out


def _dedupe(values: list[str]) -> list[str]:
    """Two spellings can be renamed onto one tag; keep the first position."""
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def columns_from(cfg) -> dict[str, str]:
    """The short names a rule may write to, from this library's configuration.
    A rule may also name a calibre column outright ("#status: Ongoing"), which
    needs no entry here."""
    named = {"genre": cfg.calibre.genre_field,
             "fandom": cfg.calibre.fandom_field,
             "majchar": cfg.calibre.majchar_field}
    return {short: column for short, column in named.items() if column}


def rules_path(cfg) -> Path:
    """Where this library's rules live: the configured path, or the project's
    config folder."""
    configured = (cfg.tags.rules_file or "").strip()
    if configured:
        return Path(configured).expanduser()
    return configfiles.path("tag_rules.txt")
