"""Where a book is judged to have come from.

<dc:source> is a plain Dublin Core field, so a published epub commonly holds
its ISBN there. Treating any non-empty value as a story URL made real books
look site-sourced, which offered Convert on them."""

import sys
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

from ratchet import main as M       # noqa: E402

STORY = "https://www.royalroad.com/fiction/12345/a-serial"


def test_an_isbn_is_not_a_story_url():
    """The two that were reported, and the shapes around them."""
    assert M._http_url("9780593135204") is None          # Project Hail Mary
    assert M._http_url("urn:isbn:9780804179034") is None  # Uprooted
    assert M._http_url("") is None
    assert M._http_url(None) is None
    assert M._http_url("www.royalroad.com/fiction/1") is None   # no scheme
    assert M._http_url("ftp://host/file") is None


def test_a_real_link_survives_unchanged_but_trimmed():
    assert M._http_url(STORY) == STORY
    assert M._http_url("  " + STORY + "  ") == STORY
    assert M._http_url("http://host/s") == "http://host/s"


def sources(monkeypatch, dc=None, ident=None, html=None):
    monkeypatch.setattr(M.epub_mod, "read_story_url", lambda p: dc)
    monkeypatch.setattr(M.epub_mod, "find_story_url_in_html", lambda p: html)
    monkeypatch.setattr(M.calibre, "story_url_from_identifiers",
                        lambda meta, key: ident)


def test_a_book_whose_source_is_an_isbn_has_no_story_url(monkeypatch):
    sources(monkeypatch, dc="9780593135204")
    assert M.find_story_url("Books", 1, "x.epub", meta={}) is None


def test_an_isbn_does_not_hide_a_real_link_further_down(monkeypatch):
    """The chain used to stop at the first non-empty value, so a book with an
    ISBN source and a genuine link inside it resolved to the ISBN."""
    sources(monkeypatch, dc="urn:isbn:9780804179034", html=STORY)
    assert M.find_story_url("Books", 1, "x.epub", meta={}) == STORY


def test_the_epubs_own_source_still_wins_when_it_is_a_link(monkeypatch):
    sources(monkeypatch, dc=STORY, ident="https://other.test/s",
            html="https://third.test/s")
    assert M.find_story_url("Books", 1, "x.epub", meta={}) == STORY


def test_the_html_scan_is_not_run_while_something_earlier_answers(monkeypatch):
    """It reads every chapter of the book; it is a last resort, not a step."""
    scanned = []
    monkeypatch.setattr(M.epub_mod, "read_story_url", lambda p: STORY)
    monkeypatch.setattr(M.calibre, "story_url_from_identifiers",
                        lambda meta, key: None)
    monkeypatch.setattr(M.epub_mod, "find_story_url_in_html",
                        lambda p: scanned.append(p) or None)
    assert M.find_story_url("Books", 1, "x.epub", meta={}) == STORY
    assert scanned == []


def test_actions_that_need_a_url_still_refuse_without_one(monkeypatch):
    """_story_url is the raising form; an ISBN must not satisfy it."""
    sources(monkeypatch, dc="9780593135204")
    with pytest.raises(HTTPException) as exc:
        M._story_url("Books", 1, "x.epub")
    assert exc.value.status_code == 422


def test_story_state_does_not_offer_convert_for_a_real_book(monkeypatch):
    """The reported bug, end to end: a published epub with an ISBN source and
    no FanFicFare chapters is neither managed nor convertible."""
    M._story_state_cache.clear()
    monkeypatch.setattr(M.calibre, "book",
                        lambda *a, **k: {"last_modified": "2026-08-30T00:00:00+00:00"})
    monkeypatch.setattr(M, "_fetch_epub_to_temp",
                        lambda lib, bid: ("x.epub", nullcontext()))
    monkeypatch.setattr(M.epub_mod, "extract_chapters", lambda p: [])
    sources(monkeypatch, dc="9780593135204")

    r = client.get("/books/2850/story-state", params={"library": "Books"}, headers=TOK)
    assert r.status_code == 200
    body = r.json()
    assert body["story_url"] is None
    assert body["fff_managed"] is False
    assert body["convertible"] is False
