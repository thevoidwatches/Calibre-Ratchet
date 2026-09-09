"""The project's config folder, and the files in it.

Everything a reader adjusts by hand lives in config/ rather than inside the
code that reads it: what a site's tags should become, how names are spelled,
where a character sits in the tag hierarchy. None of that is logic — it is a
description of one library — and keeping it out of the .py files means it can
be edited without opening an editor that highlights Python, and that the
scripts themselves are the same for everybody.

    config/tag_rules.txt      what to do with a tag a story arrives wearing
    config/tag_scheme.toml    this library's own tag vocabulary
    config/ao3_names.txt      which AO3 character tag means which character

tag_rules.txt and ao3_names.txt stay plain text because the scripts rewrite
them, grouped and commented, for you to edit and hand back; tag_scheme.toml
is TOML because its contents are tables rather than a list of decisions.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# server/ratchet/configfiles.py -> the repository root -> config/
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

SCHEME_FILE = "tag_scheme.toml"


def path(name: str) -> Path:
    return CONFIG_DIR / name


_scheme_cache: dict[Path, dict] = {}


def scheme(file: str | Path | None = None) -> dict:
    """This library's tag vocabulary, or {} when it has not been written.

    A missing file is not an error: a script that needs a table says which
    one and stops, which is a better message than a KeyError from the middle
    of a sweep.
    """
    target = Path(file) if file else path(SCHEME_FILE)
    if target not in _scheme_cache:
        _scheme_cache[target] = (tomllib.loads(target.read_text(encoding="utf-8"))
                                 if target.is_file() else {})
    return _scheme_cache[target]


def table(name: str, file: str | Path | None = None) -> dict:
    """One table from tag_scheme.toml, e.g. "name_fixes"."""
    value = scheme(file).get(name, {})
    return value if isinstance(value, dict) else {}


def listing(name: str, file: str | Path | None = None) -> list:
    """One list from tag_scheme.toml, e.g. "genres_as_tags"."""
    value = scheme(file).get(name, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def require(name: str, file: str | Path | None = None) -> dict:
    """A table a script cannot work without, or a clear exit explaining what
    to write and where."""
    got = table(name, file)
    if not got:
        target = Path(file) if file else path(SCHEME_FILE)
        raise SystemExit(
            f"[{name}] is empty or missing in {target}.\n"
            f"That table describes your own library, so there is no sensible "
            f"default — see config/README.md for what belongs in it.")
    return got
