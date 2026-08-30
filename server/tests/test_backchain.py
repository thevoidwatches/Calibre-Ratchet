"""Where the back button goes, so it walks out of the app rather than
closing it on the first press."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def b():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_backchain.js")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_every_sub_view_backs_out_to_the_book_list(b):
    """Back from a filter screen means 'never mind', and the list is what
    that returns to — not the screen it was reached through."""
    for view in ("detail", "pickcol", "pickval"):
        assert b[view] == "browse", view


def test_the_book_list_is_the_top_of_the_app(b):
    """Back leaves from the list, the way Android expects of a home screen —
    it is only a sub-view that must not close the app."""
    assert b["browse"] is None
    assert b["token"] is None


def test_walking_back_terminates(b):
    """One press from a book reaches the list, a second leaves."""
    assert b["walk_from_detail"] == ["browse", None]


def test_an_unrecognised_view_still_lands_somewhere_real(b):
    assert b["unknown"] == "browse"


def test_the_root_entry_is_distinguishable_from_a_view(b):
    assert b["root_entry"] not in ("browse", "token", "detail", "pickcol", "pickval")
