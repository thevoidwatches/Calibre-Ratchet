"""Read the files in config/ the way a careful colleague would, and say what
looks wrong.

Those files are written by hand, and nearly every mistake in them is silent.
A rule naming a column that does not exist is skipped. A root typed
"Progatonist" quietly becomes a second branch beside "Protagonist". A value
that was meant as a tag lands in #genre because the column named before it
carries on. Nothing errors; the library just ends up subtly wrong, and the
first anyone knows is a tag browser that looks odd weeks later. All three of
those happened, in one afternoon, to the person who designed the format.

So this does not change anything and does not decide anything. It reads,
compares what it reads with what the library actually contains where it can
ask, and reports — each finding with its line, how much it matters, and what
to do about it:

    error     it will not do what it says: the line, rule or file is ignored
    warning   it will do something, probably not what was meant
    note      worth knowing; nothing is wrong

    python -m ratchet.configcheck           (from server/)

The setup wizard shows the same findings.
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import configfiles, tagmap
from .calibre import CalibreClient, CalibreError, field_values

ERROR, WARNING, NOTE = "error", "warning", "note"


@dataclass
class Finding:
    file: str
    line: int                 # 0 when it is about the file as a whole
    level: str
    message: str


@dataclass
class Vocabulary:
    """What the library actually contains: every tag, every value of each
    column a rule can write to, and which custom columns exist at all."""
    tags: Counter = field(default_factory=Counter)
    columns: dict[str, Counter] = field(default_factory=dict)
    existing_columns: set[str] = field(default_factory=set)

    def roots(self, column: str = "") -> Counter:
        """How often each top-level name is used, in the tags ("") or in a
        column."""
        values = self.columns.get(column, Counter()) if column else self.tags
        out: Counter = Counter()
        for value, n in values.items():
            out[_root(value)] += n
        return out

    def _children(self, column: str) -> dict[str, set[str]]:
        """Which names sit directly under each path, the top level included
        (under ""). Worked out once per column and kept."""
        cache = self.__dict__.setdefault("_children_cache", {})
        if column not in cache:
            values = self.columns.get(column, Counter()) if column else self.tags
            tree: dict[str, set[str]] = {}
            for value in values:
                parts = [p.strip() for p in tagmap.HIERARCHY_DOT.split(value)]
                for i, part in enumerate(parts):
                    tree.setdefault(".".join(parts[:i]), set()).add(part)
            cache[column] = tree
        return cache[column]

    def slip_for(self, column: str, value: str) -> str:
        """The existing value `value` looks like a slip for, or "".

        Walked level by level, comparing only the first level the library
        does not have against its real siblings there. A whole-string
        comparison gets this wrong in both directions: it lets "Trope.VR"
        pass for "Trope.AI" (two letters out of eight) while the only part
        that differs is two letters out of two. Below the top level only —
        a mistyped root is its own, louder, finding.
        """
        parts = [p.strip() for p in tagmap.HIERARCHY_DOT.split(value)]
        tree = self._children(column)
        for i, part in enumerate(parts):
            siblings = tree.get(".".join(parts[:i]), set())
            if part in siblings:
                continue
            likely = _close(part, siblings) if i else ""
            return ".".join([*parts[:i], likely, *parts[i + 1:]]) if likely else ""
        return ""


def _root(value: str) -> str:
    return tagmap.HIERARCHY_DOT.split(value)[0].strip()


def _edits(a: str, b: str, limit: int) -> int:
    """How many single-letter changes turn `a` into `b`, giving up (and
    answering limit + 1) as soon as it is certain to be more than `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _close(word: str, candidates) -> str:
    """The candidate `word` is most likely a slip for, or "".

    Counted in letters changed rather than scored for likeness, because a
    likeness score punishes short words — "Wurm" for "Worm" is one letter in
    four, and scores worse than two unrelated long names with a shared
    surname. One change is a slip in a word of any length; two only in a
    long one, where "Progatonist" is plainly "Protagonist" and "Tone" is
    plainly not "Trope".
    """
    limit = 1 if len(word) < 8 else 2
    best, best_edits = "", limit + 1
    for candidate in candidates:
        if candidate == word:
            continue
        edits = _edits(word.lower(), candidate.lower(), limit)
        if edits < best_edits or (edits == best_edits and edits <= limit
                                  and candidate < best):
            best, best_edits = candidate, edits
    return best if best_edits <= limit else ""


def load_vocabulary(client: CalibreClient, columns: dict[str, str]) -> Vocabulary:
    """Ask calibre what every library contains. Raises CalibreError when it
    cannot be asked; the checks that need this are then skipped, not failed."""
    vocab = Vocabulary(columns={c: Counter() for c in columns.values()})
    for library in client.libraries():
        lib = library["id"]
        vocab.existing_columns.update(
            c["lookup"] for c in client.custom_columns(lib))
        ids = client.search(query="", num=1000000, library_id=lib)["book_ids"]
        for i in range(0, len(ids), 200):
            for meta in client.books(ids[i:i + 200], library_id=lib).values():
                if not meta:
                    continue
                vocab.tags.update(meta.get("tags") or [])
                for column in vocab.columns:
                    vocab.columns[column].update(field_values(meta, column))
    return vocab


# ---- tag_rules.txt ------------------------------------------------------

@dataclass
class _Rule:
    line: int
    name: str
    target: str
    parts: list[tuple[str, str, bool]]   # (column, value, column was named here)


def _read_rules(text: str, columns: dict[str, str], file: str,
                findings: list[Finding]) -> list[_Rule]:
    rules: list[_Rule] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            findings.append(Finding(file, number, ERROR,
                f"no '=' on this line, so it is ignored: {line.strip()!r}"))
            continue
        name, _, target = line.partition("=")
        name, target = name.strip(), target.strip()
        if not name:
            findings.append(Finding(file, number, ERROR,
                "nothing to the left of the '=', so this is ignored"))
            continue
        parts: list[tuple[str, str, bool]] = []
        if target and target != tagmap.DELETE:
            parsed = tagmap.parse_target(target, columns)
            if parsed is None:
                named = [p.partition(":")[0].strip()
                         for p in tagmap.split_values(target) if ":" in p]
                unknown = [n for n in named if n != "tags"
                           and n not in columns and not n.startswith("#")]
                guess = _close(unknown[0], [*columns, "tags"]) if unknown else ""
                findings.append(Finding(file, number, ERROR,
                    f"'{name}': there is no column called "
                    f"'{unknown[0] if unknown else '?'}', so the WHOLE rule is "
                    "ignored and the tag is left as it arrived"
                    + (f" — did you mean '{guess}:'?" if guess else "")
                    + f". Columns a rule can name: {', '.join([*columns, 'tags'])}"
                      ", or a calibre column outright such as '#status'."))
            else:
                named_here = [":" in p for p in tagmap.split_values(target)
                              if (p.partition(":")[2].strip() if ":" in p else p)]
                parts = [(c, v, h) for (c, v), h in zip(parsed, named_here)]
            if target.rstrip().endswith(",") or re.search(r",\s*,", target):
                findings.append(Finding(file, number, NOTE,
                    f"'{name}': a comma with nothing after it — harmless, but "
                    "it looks like a value that was never finished"))
        rules.append(_Rule(number, name, target, parts))
    return rules


def check_tag_rules(text: str, columns: dict[str, str],
                    vocab: Vocabulary | None = None,
                    scheme_roots: list[str] | None = None,
                    file: str = "tag_rules.txt") -> list[Finding]:
    findings: list[Finding] = []
    rules = _read_rules(text, columns, file, findings)

    # -- the same tag ruled on twice: the later line wins, silently ------
    seen: dict[str, _Rule] = {}
    for rule in rules:
        if tagmap.is_pattern(rule.name):
            continue
        first = seen.get(rule.name)
        if first is None:
            seen[rule.name] = rule
        elif first.target == rule.target:
            findings.append(Finding(file, rule.line, NOTE,
                f"'{rule.name}' is also on line {first.line}, saying the same"))
        else:
            findings.append(Finding(file, rule.line, WARNING,
                f"'{rule.name}' is ruled on twice. Line {first.line} says "
                f"'{first.target or '(leave alone)'}', this line says "
                f"'{rule.target or '(leave alone)'}' — this one wins, and "
                f"line {first.line} does nothing."))
            seen[rule.name] = rule

    # -- a rule whose result another rule was meant to catch ---------------
    # Rules are applied to what a story arrives with, never to each other's
    # results, so "GameLit = LitRPG" beside "LitRPG = Format.LitRPG" leaves a
    # bare "LitRPG" on the book — the very tag the second rule exists to
    # tidy away.
    finals = {name: rule for name, rule in seen.items()}
    for rule in rules:
        for column, value, _ in rule.parts:
            onward = finals.get(value)
            if column or onward is None or onward is rule:
                continue
            if onward.target and onward.target != value:
                findings.append(Finding(file, rule.line, WARNING,
                    f"'{rule.name}' becomes the tag '{value}', and line "
                    f"{onward.line} would turn '{value}' into "
                    f"'{onward.target}' — but rules are not applied to each "
                    f"other's results, so it stays '{value}'. Write "
                    f"'{onward.target}' here instead."))

    # -- where each root belongs ------------------------------------------
    # Two kinds of evidence. What THIS FILE does: a root someone names a
    # column for belongs there, one written bare is a tag. And what the
    # LIBRARY holds, when it could be asked, which outranks the file — two
    # rules making the same slip would otherwise vouch for each other.
    # A value that merely inherited its column (see below) is evidence of
    # nothing, being exactly the thing under suspicion.
    bare: Counter = Counter()
    named: dict[str, Counter] = {}
    for rule in rules:
        for column, value, named_here in rule.parts:
            if not column:
                bare[_root(value)] += 1
            elif named_here:
                named.setdefault(column, Counter())[_root(value)] += 1
    library_tags = vocab.roots() if vocab else Counter()

    def in_column(column: str, root: str) -> int:
        return named.get(column, Counter()).get(root, 0) +             (vocab.roots(column).get(root, 0) if vocab else 0)

    every_column = set(columns.values()) | set(named)

    for rule in rules:
        for column, value, named_here in rule.parts:
            root = _root(value)
            where = column or "the tags"
            # A column carries on to everything after it on the line.
            if column and not named_here and not in_column(column, root)                     and (library_tags.get(root) or bare.get(root)):
                findings.append(Finding(file, rule.line, WARNING,
                    f"'{rule.name}': '{value}' will go into {column}, not the "
                    "tags — a column named part-way along a line applies to "
                    f"everything after it. '{root}' is otherwise only ever a "
                    f"tag; if this was meant as one, write 'tags: {value}'."))
            # ...and the opposite slip: a column's value with no column named.
            if not column and not library_tags.get(root):
                homes = sorted(every_column, key=lambda c: -in_column(c, root))
                if homes and in_column(homes[0], root) > bare[root]:
                    short = next((s for s, c in columns.items() if c == homes[0]),
                                 homes[0])
                    findings.append(Finding(file, rule.line, WARNING,
                        f"'{rule.name}': '{value}' will become a tag, but "
                        f"'{root}' is otherwise only ever used in {homes[0]} "
                        f"— is a '{short}:' missing in front of it?"))
            # A root nearly, but not quite, like a well-used one.
            if column:
                peers = Counter(named.get(column, Counter()))
                if vocab:
                    peers.update(vocab.roots(column))
            else:
                peers = bare + library_tags
            if peers.get(root, 0) <= 2:
                likely = _close(root, [r for r, n in peers.items()
                                       if n > peers.get(root, 0)])
                if likely:
                    findings.append(Finding(file, rule.line, WARNING,
                        f"'{rule.name}': '{root}' looks like a misspelling of "
                        f"'{likely}', which is used far more in {where}. As "
                        "written it starts a separate branch."))
            # A value one slip away from something the library has.
            if vocab:
                likely = vocab.slip_for(column, value)
                if likely:
                    findings.append(Finding(file, rule.line, WARNING,
                        f"'{rule.name}': '{value}' is not in {where}, but "
                        f"'{likely}' is — a slip, or a new value?"))
            if column.startswith("#") and vocab and column not in vocab.existing_columns:
                findings.append(Finding(file, rule.line, WARNING,
                    f"'{rule.name}': no library has a column {column}, so "
                    "calibre will refuse this when a book arrives"))

    undecided = [r for r in rules if not r.target]
    if undecided:
        findings.append(Finding(file, 0, NOTE,
            f"{len(undecided)} tag(s) still have nothing after the '=' and "
            "are left as they arrive: "
            + ", ".join(r.name for r in undecided[:6])
            + (" …" if len(undecided) > 6 else "")))
    if scheme_roots:
        stray = sorted({_root(v) for r in rules for c, v, _ in r.parts if not c}
                       - set(scheme_roots))
        if stray:
            findings.append(Finding(file, 0, NOTE,
                "these rules make tags under roots that scripts.scheme_roots "
                f"does not list, so stray_tags.py will treat them as having "
                f"come from a site: {', '.join(stray)}"))
    return sorted(findings, key=lambda f: (f.line == 0, f.line))


# ---- tag_scheme.toml ----------------------------------------------------

_STR_TABLES = ("name_fixes", "tag_moves", "fandom_from_tags")
_CHARACTER_KEYS = ("depths", "fandom_segment", "fandoms", "not_characters")
_KNOWN = ("genres_as_tags", *_STR_TABLES, "characters")


def _line_of(text: str, pattern: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if re.search(pattern, line):
            return number
    return 0


def _key_line(text: str, key: str) -> int:
    return _line_of(text, rf'^\s*"?{re.escape(key)}"?\s*=')


def check_tag_scheme(text: str, vocab: Vocabulary | None = None,
                     file: str = "tag_scheme.toml") -> list[Finding]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        at = re.search(r"at line (\d+)", str(e))
        return [Finding(file, int(at.group(1)) if at else 0, ERROR,
                        f"this is not valid TOML, so no script can read ANY of "
                        f"it: {e}. A common cause is a backslash or a quote "
                        "inside a \"quoted\" name.")]
    findings: list[Finding] = []

    for key in data:
        if key not in _KNOWN:
            likely = _close(key, _KNOWN)
            findings.append(Finding(file, _line_of(text, rf"^\s*\[?{re.escape(key)}\b"),
                WARNING, f"nothing reads a table called '{key}'"
                + (f" — did you mean '{likely}'?" if likely else "")
                + f" The scripts know: {', '.join(_KNOWN)}."))

    listing = data.get("genres_as_tags", [])
    if not isinstance(listing, list) or not all(isinstance(v, str) for v in listing):
        findings.append(Finding(file, _key_line(text, "genres_as_tags"), ERROR,
            "genres_as_tags has to be a list of names in \"quotes\""))

    for name in _STR_TABLES:
        table = data.get(name, {})
        if not isinstance(table, dict):
            findings.append(Finding(file, _line_of(text, rf"^\s*\[{name}\]"), ERROR,
                f"{name} has to be a table of \"from\" = \"to\" lines"))
            continue
        for key, value in table.items():
            line = _key_line(text, key)
            if not isinstance(value, str):
                findings.append(Finding(file, line, ERROR,
                    f"{name}: \"{key}\" has to map to a name in \"quotes\""))
            elif key == value:
                findings.append(Finding(file, line, NOTE,
                    f"{name}: \"{key}\" is mapped to itself, which does nothing"))
            elif table.get(value) == key:
                findings.append(Finding(file, line, ERROR,
                    f"{name}: \"{key}\" becomes \"{value}\" and \"{value}\" "
                    f"becomes \"{key}\" — they would swap back and forth on "
                    "every run"))
            elif value in table and table[value] != value:
                findings.append(Finding(file, line, WARNING,
                    f"{name}: \"{key}\" becomes \"{value}\", which itself "
                    f"becomes \"{table[value]}\". Each run applies one step, "
                    f"so this takes two — write \"{key}\" = \"{table[value]}\"."))

    characters = data.get("characters", {})
    if not isinstance(characters, dict):
        findings.append(Finding(file, _line_of(text, r"^\s*\[characters"), ERROR,
            "characters has to be a table"))
        characters = {}
    for key in characters:
        if key not in _CHARACTER_KEYS:
            likely = _close(key, _CHARACTER_KEYS)
            findings.append(Finding(file, _line_of(text, re.escape(key)), WARNING,
                f"nothing reads characters.{key}"
                + (f" — did you mean '{likely}'?" if likely else "")))
    for root, depths in (characters.get("depths") or {}).items():
        ok = isinstance(depths, list) and depths and all(
            isinstance(d, int) and not isinstance(d, bool) and d >= 1 for d in depths)
        if not ok:
            findings.append(Finding(file, _key_line(text, root), ERROR,
                f"characters.depths: \"{root}\" needs a list of whole numbers "
                "from 1 up, such as [3] or [3, 4] — how many segments a tag "
                "has when its last one is a character"))
    for root, segment in (characters.get("fandom_segment") or {}).items():
        if not isinstance(segment, int) or isinstance(segment, bool) or segment < 0:
            findings.append(Finding(file, _key_line(text, root), ERROR,
                f"characters.fandom_segment: \"{root}\" needs one whole number"))

    if vocab and vocab.tags:
        roots = vocab.roots()
        for table in ("depths", "fandom_segment"):
            for root in characters.get(table) or {}:
                if root not in roots:
                    likely = _close(root, roots)
                    findings.append(Finding(file, _key_line(text, root), WARNING,
                        f"characters.{table}: no tag in the library starts "
                        f"with \"{root}\", so nothing is read from it"
                        + (f" — did you mean \"{likely}\"?" if likely else "")))
        for prefix in data.get("fandom_from_tags") or {}:
            if isinstance(prefix, str) and not any(t.startswith(prefix) for t in vocab.tags):
                findings.append(Finding(file, _key_line(text, prefix), WARNING,
                    f"fandom_from_tags: no tag in the library starts with "
                    f"\"{prefix}\", so it never fills anything in"))
    return sorted(findings, key=lambda f: (f.line == 0, f.line))


# ---- ao3_names.txt ------------------------------------------------------

def check_ao3_names(text: str, vocab: Vocabulary | None = None,
                    majchar_column: str = "", fandom_column: str = "",
                    file: str = "ao3_names.txt") -> list[Finding]:
    findings: list[Finding] = []
    seen: dict[str, tuple[int, str]] = {}
    known_names: set[str] = set()
    known_fandoms: set[str] = set()
    if vocab:
        for value in vocab.columns.get(majchar_column, {}):
            parts = tagmap.HIERARCHY_DOT.split(value)
            known_names.add(parts[-1].strip())
            if len(parts) > 1:
                known_fandoms.add(parts[0].strip())
        known_fandoms.update(_root(v) for v in vocab.columns.get(fandom_column, {}))

    undecided = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            findings.append(Finding(file, number, ERROR,
                f"no '=' on this line, so it is ignored: {line.strip()!r}. A "
                "dropped tag is written 'Tag = -', not 'Tag -'."))
            continue
        left, _, right = line.partition("=")
        left, right = left.strip(), right.strip()
        if left in seen and seen[left][1] != right:
            findings.append(Finding(file, number, WARNING,
                f"'{left}' is also on line {seen[left][0]}, saying "
                f"'{seen[left][1] or '(leave out)'}' — this line wins"))
        seen[left] = (number, right)
        if not right:
            undecided += 1
            continue
        if right == "-":
            continue
        for part in [p.strip() for p in right.split(",") if p.strip()]:
            name, at, fandom = part.partition("@")
            name, fandom = name.strip(), fandom.strip()
            if at and (not name or not fandom):
                findings.append(Finding(file, number, ERROR,
                    f"'{left}': '{part}' has an @ with nothing on one side of "
                    "it; write 'Name @ Fandom'"))
                continue
            if known_names and name not in known_names:
                likely = _close(name, known_names)
                if likely:
                    findings.append(Finding(file, number, WARNING,
                        f"'{left}': the library has no '{name}' but does have "
                        f"'{likely}' — as written this files a second person"))
            if fandom and known_fandoms and fandom not in known_fandoms:
                likely = _close(fandom, known_fandoms)
                findings.append(Finding(file, number, WARNING,
                    f"'{left}': no book is filed under a fandom '{fandom}'"
                    + (f" — did you mean '{likely}'?" if likely else "")))
    if undecided:
        findings.append(Finding(file, 0, NOTE,
            f"{undecided} tag(s) have nothing after the '=' and are left out "
            "for now"))
    return sorted(findings, key=lambda f: (f.line == 0, f.line))


# ---- all three ----------------------------------------------------------

FILES = ("tag_rules.txt", "tag_scheme.toml", "ao3_names.txt")


def example_for(name: str) -> Path:
    stem, dot, ext = name.rpartition(".")
    return configfiles.path(f"{stem}.example.{ext}")


def check_all(cfg, client: CalibreClient | None = None) -> dict:
    """{"compared": whether the library could be asked, "files": {name:
    {"exists", "findings"}}} — every file, whether or not it is there yet."""
    columns = tagmap.columns_from(cfg)
    vocab, problem = None, ""
    if client is not None:
        try:
            vocab = load_vocabulary(client, columns)
        except CalibreError as e:
            problem = str(e)

    paths = {"tag_rules.txt": tagmap.rules_path(cfg),
             "tag_scheme.toml": configfiles.path(configfiles.SCHEME_FILE),
             "ao3_names.txt": configfiles.path("ao3_names.txt")}
    checks = {
        "tag_rules.txt": lambda t: check_tag_rules(
            t, columns, vocab, list(cfg.scripts.scheme_roots)),
        "tag_scheme.toml": lambda t: check_tag_scheme(t, vocab),
        "ao3_names.txt": lambda t: check_ao3_names(
            t, vocab, cfg.calibre.majchar_field, cfg.calibre.fandom_field),
    }
    files = {}
    for name in FILES:
        path = paths[name]
        if not path.is_file():
            files[name] = {"exists": False, "path": str(path), "findings": []}
            continue
        text = path.read_text(encoding="utf-8")
        files[name] = {"exists": True, "path": str(path),
                       "findings": [asdict(f) for f in checks[name](text)]}
    return {"compared": vocab is not None, "problem": problem, "files": files}


if __name__ == "__main__":
    from .config import load_config
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else "config.toml")
    calibre = CalibreClient(config.calibre.base_url, "", config.calibre.username,
                            config.calibre.password)
    print("Reading the library, to compare the files against…\n")
    result = check_all(config, calibre)
    if not result["compared"]:
        print(f"(calibre could not be asked — {result['problem']} — so only "
              "the files' own shape was checked)\n")
    worst = 0
    for name, got in result["files"].items():
        if not got["exists"]:
            print(f"{name}: not there yet  ({got['path']})\n")
            continue
        count = Counter(f["level"] for f in got["findings"])
        print(f"{name}: {count[ERROR]} error(s), {count[WARNING]} warning(s), "
              f"{count[NOTE]} note(s)")
        for f in got["findings"]:
            where = f"line {f['line']:>4}" if f["line"] else "         "
            print(f"  {f['level']:8} {where}  {f['message']}")
        print()
        worst = max(worst, 2 if count[ERROR] else 1 if count[WARNING] else 0)
    raise SystemExit(worst)
