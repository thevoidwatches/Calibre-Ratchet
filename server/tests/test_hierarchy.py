"""Which columns nest is calibre's own per-library preference, not something
Ratchet guesses from the field name — so a library whose owner made Series a
hierarchy gets the tree, and one whose owner did not gets a flat list."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

from ratchet import main as M       # noqa: E402
from ratchet.calibre import CalibreError  # noqa: E402

CATS = [{"name": "Series", "url": "/ajax/category/736572696573/Books",
         "is_category": True}]
# What calibre actually answers for these libraries.
HIER = ["series", "tags", "#fandom", "#genre", "#majchar"]


def serve(monkeypatch, hierarchical=HIER, fail=False):
    M._hier_cache.clear()
    monkeypatch.setattr(M.calibre, "categories", lambda *a, **k: CATS)

    def fields(*a, **k):
        if fail:
            raise CalibreError("GET /interface-data/init -> 404")
        return hierarchical
    monkeypatch.setattr(M.calibre, "hierarchical_fields", fields)


def test_categories_reports_what_calibre_nests(monkeypatch):
    serve(monkeypatch)
    r = client.get("/categories", params={"library": "Books"}, headers=TOK)
    assert r.status_code == 200
    body = r.json()
    assert body["categories"] == CATS
    assert body["hierarchical"] == HIER
    assert "series" in body["hierarchical"]     # the reader's own setting


def test_a_calibre_that_will_not_say_does_not_break_the_picker(monkeypatch):
    """The categories are the point of the endpoint; a missing preference
    leaves the UI to its own guess rather than failing the request."""
    serve(monkeypatch, fail=True)
    r = client.get("/categories", params={"library": "Books"}, headers=TOK)
    assert r.status_code == 200
    assert r.json()["categories"] == CATS
    assert r.json()["hierarchical"] is None


def test_the_preference_is_read_per_library_and_cached(monkeypatch):
    seen = []
    M._hier_cache.clear()
    monkeypatch.setattr(M.calibre, "categories", lambda *a, **k: CATS)
    monkeypatch.setattr(M.calibre, "hierarchical_fields",
                        lambda lib, *a, **k: seen.append(lib) or ["series"])
    for lib in ("Books", "Books", "Serials"):
        client.get("/categories", params={"library": lib}, headers=TOK)
    assert seen == ["Books", "Serials"]     # the repeat came from the cache


def test_the_ui_asks_calibre_before_guessing():
    picker = client.get("/ui/picker.js").text
    # calibre's answer first, the old field-name guess only as a fallback.
    assert "state.hierarchical ? state.hierarchical.has(field)" in picker
    assert "!NO_HIERARCHY.has(field)" in picker
    assert "new Set(resp.hierarchical)" in picker
    # One question, asked by lookup name; the display-name form defers to it.
    assert "isHierarchical = colName => fieldIsHierarchical(lookupOf(colName))" in picker
    # Nesting is per library, so it is dropped along with the vocabularies.
    core = client.get("/ui/core.js").text
    assert "state.hierarchical = null;" in core
