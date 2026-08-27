"""Behavioural tests for the shell's bundled offline page (shell/www/offline.js).

The page keeps everything DOM-touching behind a `document` guard, so node can
import the pure helpers directly: the filtering, sorting, and chip-vocabulary
logic the offline library applies to the device catalog.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

OFFLINE = Path(__file__).resolve().parents[2] / "shell" / "www" / "offline.js"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def run(expr: str, **data) -> object:
    script = (
        f"import * as o from {json.dumps(OFFLINE.as_uri())};"
        + "".join(f"const {k} = {json.dumps(v)};" for k, v in data.items())
        + f"process.stdout.write(JSON.stringify({expr}));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


BOOKS = [
    {"library": "Serials", "id": 97, "file": "a.epub", "title": "Beware of Chicken",
     "authors": ["CasualFarmer"], "series": "Beware of Chicken", "series_index": 6,
     "genres": ["Fantasy.Xianxia"], "tags": ["Serial.Ongoing"],
     "readinglist": "Following", "last_modified": "2026-08-20T00:00:00+00:00"},
    {"library": "Fanfiction", "id": 5, "file": "b.epub", "title": "another story",
     "authors": ["Zed"], "series": None, "series_index": None,
     "genres": ["Fantasy"], "tags": [],
     "readinglist": "", "last_modified": "2026-08-25T00:00:00+00:00"},
    {"library": "Serials", "id": 91, "file": "c.epub", "title": "Blue Core",
     "authors": ["Ivan Kal"], "series": "Blue Core", "series_index": 1,
     "genres": ["Science Fiction"], "tags": ["Serial.Complete"],
     "readinglist": "Unread", "last_modified": "2026-08-01T00:00:00+00:00"},
]

NONE_PICKED = {"library": "", "genres": [], "tags": [], "readinglist": []}


def picked(**kw):
    return {**NONE_PICKED, **kw}


# ---- hierHit ----

def test_hierhit_exact_and_child():
    assert run('o.hierHit(["Fantasy.Xianxia"], "Fantasy")') is True
    assert run('o.hierHit(["Fantasy"], "Fantasy")') is True


def test_hierhit_is_a_level_match_not_a_prefix_match():
    # "Fant" must not hit "Fantasy" — only whole hierarchy levels count.
    assert run('o.hierHit(["Fantasy"], "Fant")') is False


# ---- matches ----

def test_no_filters_match_everything():
    got = run("BOOKS.filter(b => o.matches(b, SEL, ''))", BOOKS=BOOKS,
              SEL=NONE_PICKED)
    assert len(got) == 3


def test_genre_chip_matches_hierarchically():
    got = run("BOOKS.filter(b => o.matches(b, SEL, '')).map(b => b.id)",
              BOOKS=BOOKS, SEL=picked(genres=["Fantasy"]))
    assert got == [97, 5]


def test_chips_within_a_section_or_together():
    got = run("BOOKS.filter(b => o.matches(b, SEL, '')).map(b => b.id)",
              BOOKS=BOOKS,
              SEL=picked(readinglist=["Following", "Unread"]))
    assert got == [97, 91]


def test_sections_and_together():
    got = run("BOOKS.filter(b => o.matches(b, SEL, '')).map(b => b.id)",
              BOOKS=BOOKS,
              SEL=picked(genres=["Fantasy"], tags=["Serial"]))
    assert got == [97]     # only the Serials book has both


def test_library_chip_narrows():
    got = run("BOOKS.filter(b => o.matches(b, SEL, '')).map(b => b.id)",
              BOOKS=BOOKS, SEL=picked(library="Fanfiction"))
    assert got == [5]


def test_search_is_case_insensitive_over_title_author_series():
    got = run("BOOKS.filter(b => o.matches(b, SEL, 'IVAN')).map(b => b.id)",
              BOOKS=BOOKS, SEL=NONE_PICKED)
    assert got == [91]


# ---- sortBooks ----

def test_recent_sort_is_newest_first():
    got = run("o.sortBooks(BOOKS, 'recent').map(b => b.id)", BOOKS=BOOKS)
    assert got == [5, 97, 91]


def test_title_sort_ignores_case():
    got = run("o.sortBooks(BOOKS, 'title').map(b => b.id)", BOOKS=BOOKS)
    assert got == [5, 97, 91]   # "another" < "Beware" < "Blue"


def test_unknown_sort_key_falls_back_to_recent():
    got = run("o.sortBooks(BOOKS, 'bogus').map(b => b.id)", BOOKS=BOOKS)
    assert got == [5, 97, 91]


# ---- chipValues ----

def test_chip_values_offer_every_hierarchy_level():
    got = run("o.chipValues(BOOKS)", BOOKS=BOOKS)
    assert got["genres"] == ["Fantasy", "Fantasy.Xianxia", "Science Fiction"]
    assert got["tags"] == ["Serial", "Serial.Complete", "Serial.Ongoing"]


def test_chip_values_skip_empty_reading_lists():
    got = run("o.chipValues(BOOKS)", BOOKS=BOOKS)
    assert got["readinglists"] == ["Following", "Unread"]
    assert got["libraries"] == ["Fanfiction", "Serials"]


# ---- seriesText ----

def test_series_text_matches_the_served_ui_shape():
    assert run("o.seriesText(B)", B=BOOKS[0]) == "Beware of Chicken #6"
    assert run("o.seriesText(B)", B=BOOKS[1]) == ""
