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


def test_it_looks_the_same_as_the_series_it_stands_in_for():
    """One place, one look, whichever of the two is filling it — so the pair
    share a rule rather than drifting apart."""
    css = client.get("/ui/ui.css").text
    shared = css.split(".list li .titlerow .ser,")[1].split("}")[0]
    assert "font-style: italic" in shared and "font-size: 0.85rem" in shared
    assert ".list li .titlerow .rowfield" in shared
    # Still its own span: only one of the two is ever filled, and each
    # collapses when empty so the row gains no gap.
    assert ".list li .titlerow .rowfield:empty { display: none; }" in css
    browse = client.get("/ui/browse.js").text
    assert 'querySelector(".rowfield").textContent = rowFieldLabel(b)' in browse


def test_a_long_value_gives_way_to_the_title():
    """A series name is short; a multi-valued column need not be."""
    css = client.get("/ui/ui.css").text
    own = css.split(".list li .titlerow .rowfield { flex: 0 1 auto;")[1].split("}")[0]
    assert "text-overflow: ellipsis" in own
