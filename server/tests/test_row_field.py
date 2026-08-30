"""calibre.row_field: a column of the reader's choosing at the right of each
row's title line, standing in where a book with a series shows its series."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

from ratchet import main as M      # noqa: E402

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def r():
    if node is None:
        pytest.skip("node not installed")
    p = subprocess.run([node, str(HERE / "test_row_field.js")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_the_column_shows_when_there_is_no_series(r):
    assert r["one"] == "Worm"


def test_several_values_read_as_one_list(r):
    """Custom columns can be multi-valued; the separator matches the genre
    and tag lines below."""
    assert r["several"] == "Worm · My Hero Academia"
    assert r["hierarchical"] == "Riordanverse.Olympian"


def test_a_series_keeps_the_space_it_already_had(r):
    assert r["series_wins"] == ""
    assert r["series_without_index_still_wins"] == ""


def test_a_library_without_the_column_shows_nothing(r):
    for key in ("absent", "empty_list", "nothing"):
        assert r[key] == "", key


def serve(monkeypatch, meta, row_field="#fandom"):
    monkeypatch.setattr(M.cfg.calibre, "row_field", row_field)
    monkeypatch.setattr(M.calibre, "search",
                        lambda **k: {"book_ids": [7], "total_num": 1})
    monkeypatch.setattr(M.calibre, "books", lambda ids, library_id=None: {"7": meta})


def test_the_listing_carries_the_configured_columns_value(monkeypatch):
    serve(monkeypatch, {"title": "A Fic", "user_metadata": {
        "#fandom": {"datatype": "text", "is_multiple": "|", "#value#": ["Worm"]}}})
    r = client.get("/books", params={"library": "Fanfiction"}, headers=TOK)
    assert r.status_code == 200
    assert r.json()["books"][0]["row_values"] == ["Worm"]


def test_a_book_lacking_the_column_carries_an_empty_list(monkeypatch):
    """Every other library: the field is configured, the column is not there,
    and the row simply has nothing to show."""
    serve(monkeypatch, {"title": "A Novel", "user_metadata": {}})
    r = client.get("/books", params={"library": "Books"}, headers=TOK)
    assert r.json()["books"][0]["row_values"] == []


def test_leaving_it_unset_costs_the_listing_nothing(monkeypatch):
    serve(monkeypatch, {"title": "A Novel", "user_metadata": {
        "#fandom": {"datatype": "text", "#value#": ["Worm"]}}}, row_field="")
    r = client.get("/books", params={"library": "Fanfiction"}, headers=TOK)
    assert r.json()["books"][0]["row_values"] == []


def test_the_two_spans_are_separate_so_each_keeps_its_own_format():
    """The series is italic and small; the configured column is set in the
    title's own face, so they cannot share one span."""
    css = client.get("/ui/ui.css").text
    assert ".list li .titlerow .rowfield" in css
    assert ".list li .titlerow .rowfield:empty { display: none; }" in css
    browse = client.get("/ui/browse.js").text
    assert 'querySelector(".rowfield").textContent = rowFieldLabel(b)' in browse
