"""A hierarchical value is one unbreakable word to a browser, so a row that
has to wrap one splits it mid-word. Offering a break after each dot puts the
split between segments, where the meaning already divides."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def m():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_meta_line.js")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_deep_value_may_break_at_every_dot(m):
    assert m["deep"] == ("Nonfiction.<>Informational.<>Science.<>Physics.<>"
                         "Astrophysics")


def test_each_value_on_the_line_is_treated_the_same(m):
    assert m["shallow"] == "Comedy.<>Dark Humor · Isekai.<>Urban.<>Fantasy"
    assert m["separator"] == "A.<>B · C.<>D"


def test_flat_values_gain_nothing(m):
    """Royal Road's genres are not a hierarchy; there is nothing to break."""
    assert m["flat"] == "Action · Adventure · Cozy"
    assert m["flat_untouched"] is False


def test_an_abbreviation_is_left_alone(m):
    """A dot followed by a space can already break there, and "Mr. Norrell"
    is a name rather than a path."""
    assert m["abbreviation"] == "Jonathan Strange and Mr. Norrell"


def test_nothing_in_nothing_out(m):
    assert m["empty"] == "" and m["missing"] == ""


def test_the_breaks_are_invisible(m):
    """A zero-width space renders as nothing; the line must read exactly as
    it did before."""
    assert m["reads_the_same"] is True


def test_the_break_is_a_real_character_not_an_escape():
    """Guarding a mistake this project has made before: an escape sequence
    written through several layers can arrive as literal backslash-u text,
    or as a stray control byte."""
    js = client.get("/ui/format.js").text
    assert "​" in js                      # the character itself
    assert "\\u200b" not in js.replace("​", "")   # not an escape
    assert not [c for c in js if ord(c) < 32 and c not in "\n\r\t"]


def test_the_book_list_uses_it_for_both_sides_of_the_row():
    browse = client.get("/ui/browse.js").text
    assert 'querySelector(".genres").textContent = metaLine(b.genre)' in browse
    assert 'querySelector(".tags").textContent = metaLine(b.tags)' in browse


def test_a_dot_inside_a_name_is_not_a_level(m):
    """The reported case: "Dr. Greta Helsing" is one series, and was being
    shown as a "Dr" family with "Greta Helsing" beneath it."""
    assert m["seg_title"] == ["Dr. Greta Helsing"]
    assert m["seg_fandom"] == ["Jonathan Strange and Mr. Norrell"]


def test_a_real_hierarchy_still_splits(m):
    assert m["seg_deep"] == ["Nonfiction", "Informational", "Science"]
    assert m["seg_colon"] == ["Cosmere", "Mistborn", "1: Fall of the Empire"]
    assert m["seg_mixed"] == ["A", "B. C"]      # one of each in the same value
    assert m["seg_flat"] == ["Romance"]
    assert m["seg_empty"] == [""] and m["seg_missing"] == [""]


def test_the_levels_rejoin_to_what_they_came_from(m):
    """The value picker names each level by rejoining the ones above it, so a
    split that did not round-trip would filter on a path no book has."""
    assert m["seg_roundtrip"] is True


def test_the_value_picker_and_the_suggestions_split_the_same_way():
    """One rule, in one place: a tree that disagreed with the suggestion
    groups would file the same value under two different families."""
    fmt = client.get("/ui/format.js").text
    assert "export function segments(" in fmt
    assert "const head = segments(v)[0];" in fmt          # suggestion families
    picker = client.get("/ui/picker.js").text
    assert "const parts = segments(n);" in picker          # the value tree
    assert 'split(".")' not in picker
