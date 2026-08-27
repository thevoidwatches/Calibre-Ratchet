"""Pin the offline-catalog record shape (format.js catalogEntry).

The served UI writes these records to Ratchet/.catalog.json and the shell's
bundled offline page reads them; the bundled side only changes with an APK
rebuild, so the shape the two agree on is worth a contract test.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ficsync" / "static"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def entry(meta: dict, book_id=97, library="Serials", genre_field="#genre") -> dict:
    script = (
        f"import {{ catalogEntry }} from "
        f"{json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(JSON.stringify(catalogEntry("
        f"{json.dumps(meta)}, {json.dumps(book_id)}, {json.dumps(library)}, "
        f"{json.dumps(genre_field)})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


FULL_META = {
    "title": "Beware of Chicken",
    "authors": ["CasualFarmer"],
    "series": "Beware of Chicken",
    "series_index": 6.0,
    "tags": ["Serial.Ongoing"],
    "last_modified": "2026-08-20T00:00:00+00:00",
    "user_metadata": {
        "#genre": {"#value#": ["Fantasy.Xianxia", "Comedy"]},
        "#readinglist": {"#value#": "Following"},
        "#downloaded": {"#value#": True},
    },
}


def test_full_record():
    got = entry(FULL_META)
    assert got == {
        "library": "Serials",
        "id": 97,
        "file": "Beware of Chicken 6. Beware of Chicken - CasualFarmer.epub",
        "title": "Beware of Chicken",
        "series": "Beware of Chicken",
        "series_index": 6.0,
        "authors": ["CasualFarmer"],
        "genres": ["Fantasy.Xianxia", "Comedy"],
        "tags": ["Serial.Ongoing"],
        "readinglist": "Following",
        "last_modified": "2026-08-20T00:00:00+00:00",
    }


def test_bare_metadata_yields_empty_but_complete_record():
    got = entry({"title": "Blue Core"}, book_id=91)
    assert got["genres"] == [] and got["tags"] == [] and got["authors"] == []
    assert got["readinglist"] == "" and got["series"] is None
    assert got["file"] == "Blue Core.epub"


def test_single_string_genre_becomes_a_list():
    meta = {"title": "X", "user_metadata": {"#genre": {"#value#": "Fantasy"}}}
    assert entry(meta)["genres"] == ["Fantasy"]


def test_genre_field_is_configurable():
    meta = {"title": "X", "user_metadata": {"#cat": {"#value#": ["A.B"]}}}
    assert entry(meta, genre_field="#cat")["genres"] == ["A.B"]
