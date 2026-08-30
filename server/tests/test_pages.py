"""Sorting by calibre's page count, and how an uncounted book is shown."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def p():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_pages.js")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_measured_book_reads_naturally(p):
    assert p["many"] == "312 pages"
    assert p["one"] == "1 page"
    assert p["thousands"] == "7,950 pages"


def test_zero_means_unmeasured_and_shows_nothing(p):
    """calibre only counts pages when a format is written, so most older
    books report 0. That is 'unknown', and must not render as '0 pages'."""
    assert p["zero"] == ""


def test_absent_or_nonsense_values_show_nothing(p):
    for key in ("missing", "null_", "empty", "negative", "nonsense"):
        assert p[key] == "", key


def test_a_numeric_string_still_counts(p):
    assert p["numeric_string"] == "204 pages"


# --- the sort option itself -------------------------------------------------

def test_pages_is_offered_as_a_sort():
    body = client.get("/ui-config", headers=TOK).json()
    keys = [o["key"] for o in body["sort_options"]]
    assert "pages" in keys
    label = next(o["label"] for o in body["sort_options"] if o["key"] == "pages")
    assert label == "Pages"


def test_books_accepts_the_new_sort():
    """Reaches calibre, which is unreachable in tests — a 502 proves the sort
    key passed validation, where an unknown one is rejected as a 400."""
    r = client.get("/books?sort=pages", headers=TOK)
    assert r.status_code == 502


def test_an_unknown_sort_is_still_refused():
    r = client.get("/books?sort=nonsense", headers=TOK)
    assert r.status_code == 400
    assert "pages" in r.json()["detail"]
