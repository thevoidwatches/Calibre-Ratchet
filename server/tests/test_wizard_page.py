"""The setup wizard's page logic (ratchet/wizard/static/wizard.js). Its DOM
half sits behind a `document` guard, so node can import the pure helpers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parents[1] / "ratchet" / "wizard" / "static"
        / "wizard.js")
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def run(expr: str, **data) -> object:
    script = (f"import * as w from {json.dumps(PAGE.as_uri())};"
              + "".join(f"const {k} = {json.dumps(v)};" for k, v in data.items())
              + f"process.stdout.write(JSON.stringify({expr}));")
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


LIBRARIES = {
    "Serials": [{"lookup": "#genre", "name": "Genre", "datatype": "text"},
                {"lookup": "#lastupdated", "name": "Last Updated", "datatype": "datetime"},
                {"lookup": "#downloaded", "name": "Downloaded", "datatype": "bool"}],
    "Fanfiction": [{"lookup": "#genre", "name": "Genre", "datatype": "text"},
                   {"lookup": "#fandom", "name": "Fandom", "datatype": "text"},
                   {"lookup": "#readinglist", "name": "Reading List",
                    "datatype": "enumeration"}],
}


def values(kind, saved=""):
    return [c["value"] for c in
            run("w.columnChoices(libs, kind, saved)", libs=LIBRARIES, kind=kind,
                saved=saved)]


def test_a_setting_is_offered_only_columns_it_could_sensibly_use():
    """A genre kept in a Yes/No column is nobody's intention."""
    assert values("genre") == ["", "#fandom", "#genre", "#readinglist"]
    assert "#downloaded" not in values("genre")
    assert "#lastupdated" not in values("genre")


def test_nothing_is_always_a_choice_and_always_first():
    for kind in ("genre", "fandom", "majchar", "row", "lastupdate"):
        assert values(kind)[0] == ""


def test_last_updated_takes_a_date_column_or_calibres_own_date():
    assert values("lastupdate") == ["", "#lastupdated", "timestamp"]


def test_overwriting_calibres_date_says_what_it_costs():
    got = run("w.columnChoices(libs, 'lastupdate', '')", libs=LIBRARIES)
    label = [c["label"] for c in got if c["value"] == "timestamp"][0]
    # In words that need no knowledge of calibre's internals: an earlier
    # label said "overwrites date-added, for good" and had to be explained.
    assert "date you added" in label and "permanently" in label


def test_a_column_shared_by_libraries_is_offered_once_naming_them():
    got = run("w.columnChoices(libs, 'genre', '')", libs=LIBRARIES)
    genre = [c for c in got if c["value"] == "#genre"]
    assert len(genre) == 1
    assert "Serials" in genre[0]["label"] and "Fanfiction" in genre[0]["label"]


def test_a_saved_column_no_library_has_now_is_kept_and_flagged():
    """Rather than the select quietly showing something else, and the next
    save writing that instead."""
    got = run("w.columnChoices(libs, 'genre', '#gone')", libs=LIBRARIES)
    gone = [c for c in got if c["value"] == "#gone"]
    assert len(gone) == 1 and "not in any library" in gone[0]["label"]


def test_no_libraries_yet_still_gives_a_usable_list():
    assert run("w.columnChoices({}, 'genre', '')") == [{"value": "", "label": "(none)"}]
    assert run("w.columnChoices(null, 'lastupdate', '').map(c => c.value)") == ["", "timestamp"]


def test_an_empty_password_box_means_keep_the_saved_one():
    """The page is never sent the saved password, so empty has to be able
    to mean "leave it alone" rather than "there is none"."""
    assert run("w.passwordToSend('', true)") is None
    assert run("w.passwordToSend('', false)") == ""
    assert run("w.passwordToSend('typed', true)") == "typed"


FOUND = [{"line": 0, "level": "note", "message": "2 undecided"},
         {"line": 74, "level": "warning", "message": "ruled on twice"},
         {"line": 12, "level": "error", "message": "no '='"},
         {"line": 80, "level": "warning", "message": "twice again"}]


def test_a_files_findings_are_summed_up_worst_first():
    assert run("w.summarise(found)", found=FOUND) == "1 problem, 2 warnings, 1 note"
    assert run("w.summarise([])") == "nothing to report"


def test_findings_read_top_to_bottom_with_the_whole_file_ones_last():
    got = run("w.inReadingOrder(found).map(f => f.line)", found=FOUND)
    assert got == [12, 74, 80, 0]


def test_every_library_file_says_what_it_is_for():
    """Shown before the file exists: "what would this even do?" comes
    before "make one"."""
    got = run("w.LIBRARY_FILES")
    assert set(got) == {"tag_rules.txt", "tag_scheme.toml", "ao3_names.txt"}
    assert all(len(text) > 40 for text in got.values())


def test_a_step_shows_how_it_stands():
    assert run("w.stepClass({done: true})") == "done"
    assert run("w.stepClass({done: false})") == "todo"
    assert run("w.stepClass({problem: true})") == "stuck"
    # Waiting on an earlier step outranks the rest: nothing here to fix yet.
    assert run("w.stepClass({problem: true, blocked: true})") == "waiting"
