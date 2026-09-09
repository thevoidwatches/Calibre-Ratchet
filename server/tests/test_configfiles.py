"""The config folder: settings a reader adjusts by hand, kept out of the
code that reads them."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet import configfiles  # noqa: E402

SCHEME = """
genres_as_tags = ["Time Travel.Peggy Sue"]

[name_fixes]
"Midoriya Izuku" = "Izuku Midoriya"

[characters.depths]
"Powers" = [3, 4]

[characters]
not_characters = ["Everyone"]
"""


def scheme_file(tmp_path: Path, text: str = SCHEME) -> Path:
    path = tmp_path / "tag_scheme.toml"
    path.write_text(text, encoding="utf-8")
    configfiles._scheme_cache.pop(path, None)
    return path


def test_tables_and_lists_come_back_as_written(tmp_path):
    path = scheme_file(tmp_path)
    assert configfiles.table("name_fixes", path) == {"Midoriya Izuku": "Izuku Midoriya"}
    assert configfiles.listing("genres_as_tags", path) == ["Time Travel.Peggy Sue"]
    chars = configfiles.table("characters", path)
    assert chars["depths"] == {"Powers": [3, 4]}
    assert chars["not_characters"] == ["Everyone"]


def test_a_table_nobody_has_written_is_empty_rather_than_an_error(tmp_path):
    path = scheme_file(tmp_path)
    assert configfiles.table("tag_moves", path) == {}
    assert configfiles.listing("nothing_here", path) == []


def test_a_missing_file_is_not_an_error(tmp_path):
    """A fresh clone has no scheme; a script that needs one says so itself."""
    assert configfiles.scheme(tmp_path / "absent.toml") == {}


def test_a_table_a_script_cannot_work_without_says_which_and_where(tmp_path):
    """Better than a KeyError from the middle of a library sweep."""
    path = scheme_file(tmp_path)
    with pytest.raises(SystemExit) as exit:
        configfiles.require("tag_moves", path)
    message = str(exit.value)
    assert "tag_moves" in message
    assert "tag_scheme.toml" in message
    assert "config/README.md" in message


def test_every_file_the_folder_expects_has_an_example():
    """A shipped example is the only documentation of a format that survives
    contact with a fresh clone."""
    for name in ("tag_rules", "ao3_names"):
        assert (configfiles.CONFIG_DIR / f"{name}.example.txt").is_file(), name
    assert (configfiles.CONFIG_DIR / "tag_scheme.example.toml").is_file()


def test_the_tag_rules_example_is_a_working_rules_file():
    """An example that does not parse is worse than none: it teaches a format
    the reader nothing else accepts."""
    from ratchet import tagmap
    rules = tagmap.load(configfiles.path("tag_rules.example.txt"))
    assert not rules.bad_lines
    assert rules.exact and rules.globs      # both kinds are demonstrated

    columns = {"genre": "#genre", "fandom": "#fandom", "majchar": "#majchar"}
    book = {"tags": ["In-Progress", "Last Update: 2026/09/09", "FanFiction",
                     "Angst", "Untouched"],
            "user_metadata": {"#genre": {"#value#": []}}}
    got = tagmap.apply(book, rules, columns)
    assert got["tags"] == ["Serial.Ongoing", "Untouched"]   # renamed, pattern-dropped, kept
    assert got["#genre"] == ["Angst"]                       # moved to a column


def test_the_ao3_example_reads_as_the_script_would_read_it():
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".scripts"))
    import ao3_characters

    was = ao3_characters.REVIEW
    ao3_characters.REVIEW = configfiles.path("ao3_names.example.txt")
    try:
        decided = ao3_characters.read_review()
    finally:
        ao3_characters.REVIEW = was
    assert len(decided) >= 10
    assert decided["Bakugou Katsuki"] == "Katsuki Bakugo"   # romanised + reordered
    assert decided["Class 1-A (My Hero Academia)"] == "-"   # a group, dropped
    assert decided["Krosp"] == "Krosp @ Girl Genius"        # crossover, fandom named


def test_the_folder_is_beside_the_code_not_inside_it():
    assert configfiles.CONFIG_DIR.name == "config"
    assert (configfiles.CONFIG_DIR / "README.md").is_file()
    # The shipped example has to parse, or it is worse than no example.
    example = configfiles.CONFIG_DIR / "tag_scheme.example.toml"
    assert example.is_file()
    parsed = configfiles.scheme(example)
    assert set(parsed) >= {"name_fixes", "tag_moves", "characters"}
    assert set(parsed["characters"]) >= {"depths", "not_characters"}
