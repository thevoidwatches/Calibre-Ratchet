"""The metadata editors on the book page: which sections start open,
and what the "add existing" dropdowns offer."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
STATIC = HERE.parents[0] / "ratchet" / "static"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


@pytest.fixture(scope="module")
def r():
    p = subprocess.run([node, str(HERE / "field_open_harness.mjs")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_reading_list_starts_open_and_the_others_closed(r):
    assert r["default_readinglist"] is True
    assert r["default_genre"] is False
    assert r["default_tags"] is False


def test_a_stored_preference_wins_over_the_default(r):
    assert r["stored_closes_readinglist"] is False
    assert r["stored_opens_tags"] is True
    assert r["unstored_still_default"] is False


# --- suggestion list for the "add existing" dropdown -------------------------

def _suggest(all_values, current):
    script = (
        f"import {{ suggestValues }} from {json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(JSON.stringify(suggestValues("
        f"{json.dumps(all_values)}, {json.dumps(current)})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_suggestions_drop_what_the_book_already_has():
    assert _suggest(["Fantasy", "Horror", "Romance"], ["Horror"]) == \
        ["Fantasy", "Romance"]


def test_suggestions_are_sorted_since_the_vocabulary_arrives_tree_ordered():
    assert _suggest(["Science Fiction", "Comedy", "Fantasy.Xianxia"], []) == \
        ["Comedy", "Fantasy.Xianxia", "Science Fiction"]


def test_suggestions_are_deduped_and_skip_empties():
    assert _suggest(["A", "A", "", None, "B"], []) == ["A", "B"]


def test_everything_already_set_leaves_nothing_to_offer():
    # The dropdown hides itself in this case rather than showing an empty list.
    assert _suggest(["A", "B"], ["A", "B"]) == []


# --- hierarchical grouping of the suggestions --------------------------------

def _group(values):
    script = (
        f"import {{ groupSuggestions }} from {json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(JSON.stringify(groupSuggestions({json.dumps(values)})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_values_with_no_relatives_stay_loose():
    got = _group(["Comedy", "Horror"])
    assert [i["value"] for i in got["loose"]] == ["Comedy", "Horror"]
    assert got["groups"] == []


def test_a_family_becomes_a_group_with_the_heading_trimmed_from_labels():
    got = _group(["Fantasy", "Fantasy.Xianxia", "Fantasy.Epic"])
    assert got["loose"] == []
    (group,) = got["groups"]
    assert group["label"] == "Fantasy"
    # The family's own bare value leads, then its children alphabetically.
    assert [(i["value"], i["label"]) for i in group["items"]] == [
        ("Fantasy", "Fantasy"),
        ("Fantasy.Epic", "Epic"),
        ("Fantasy.Xianxia", "Xianxia"),
    ]


def test_a_child_without_its_parent_still_forms_a_group():
    """Nothing guarantees the bare parent is in use anywhere."""
    (group,) = _group(["Serial.Ongoing", "Serial.Complete"])["groups"]
    assert group["label"] == "Serial"
    assert [i["label"] for i in group["items"]] == ["Complete", "Ongoing"]


def test_deeper_paths_keep_the_rest_of_the_path_in_the_label():
    """optgroup-style grouping is one level deep, so a third level has to
    show up in the label rather than as a nested heading."""
    (group,) = _group(["Isekai.Urban.Fantasy"])["groups"]
    assert group["label"] == "Isekai"
    assert [i["label"] for i in group["items"]] == ["Urban.Fantasy"]
