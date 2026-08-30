"""Coming back from a book lands where the list was left, and nothing else
inherits a scroll position it should not."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def s():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_scroll.js")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_the_book_list_comes_back_where_it_was_left(s):
    assert s["list_comes_back_where_it_was"] == 1200


def test_it_survives_a_detour_through_the_filter_picker(s):
    assert s["list_survives_a_detour"] == 800


def test_every_other_view_starts_at_the_top(s):
    assert s["book_page_starts_at_the_top"] == 0
    assert s["picker_starts_at_the_top"] == 0


def test_a_book_page_never_inherits_another_books_position(s):
    assert s["each_book_starts_at_the_top"] == 0


def test_re_showing_the_current_view_does_not_move_the_page(s):
    """Applying a filter from the list calls show("browse") again; that must
    not throw the reader back to the top."""
    assert s["same_view_does_not_move"] == 450


def test_a_fresh_search_starts_at_the_top(s):
    assert s["a_new_search_starts_at_the_top"] == 0


def test_the_browser_is_not_left_to_restore_scroll_itself():
    """On "auto" the browser restores a position of its own after popstate
    has run, which would overwrite the one show() just put back."""
    app = client.get("/ui/app.js").text
    assert 'history.scrollRestoration = "manual"' in app
    assert '"scrollRestoration" in history' in app      # guarded for old engines


def test_the_restore_survives_a_late_layout():
    core = client.get("/ui/core.js").text
    assert "requestAnimationFrame(() => window.scrollTo(0, y))" in core


def test_search_forgets_the_place_when_it_replaces_the_list():
    """"more" appends and keeps the position; a fresh search must not."""
    js = client.get("/ui/browse.js").text
    body = js.split("export async function search")[1].split("try {")[0]
    assert "forgetBrowseScroll()" in body and "if (!more)" in body
    assert "forgetBrowseScroll" in client.get("/ui/core.js").text
