"""calibre.editable_fields: which columns the book page lets you edit, in
what order, and the line between choosing a column and being allowed to
write it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def e():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "editable_harness.mjs")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_unconfigured_offers_every_writable_text_column(e):
    """The behaviour before the setting existed, kept as the default."""
    assert e["unconfigured"] == ["#fandom", "#genre", "tags", "#readinglist",
                                 "#majchar"]


def test_configuring_it_both_selects_and_orders(e):
    assert e["configured_selects_and_orders"] == ["#majchar", "tags"]


def test_the_configured_order_is_followed_exactly(e):
    assert e["configured_full_order"] == ["#readinglist", "#majchar", "#genre",
                                          "tags", "#fandom"]


def test_listing_a_field_does_not_grant_permission_to_write_it(e):
    """editable_fields chooses and orders; writable_fields is the boundary."""
    assert e["editable_cannot_grant"] == ["tags"]


def test_a_column_the_book_lacks_is_ignored(e):
    assert e["unknown_field_ignored"] == ["tags"]


def test_non_text_columns_never_get_an_editor(e):
    assert e["bool_column_skipped"] == ["tags"]


def test_ui_config_publishes_the_setting():
    body = client.get("/ui-config", headers=TOK).json()
    assert body["editable_fields"] == []          # unset in the test config
    assert "writable_fields" in body
