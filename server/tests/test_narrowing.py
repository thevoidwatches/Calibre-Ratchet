"""Narrowing the filter picker to the values present in the current results.

The rule itself lives in format.js and is run for real in node; the endpoint
that answers "which values are in these books" is checked here directly.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def v():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_narrowing.js")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# --- which values the picker draws ------------------------------------------

def test_without_a_present_set_the_whole_vocabulary_shows(v):
    assert len(v["not_narrowed"]) == 5


def test_narrowing_keeps_only_values_in_the_results(v):
    assert v["narrowed"] == ["Powers.Brute.Taylor Hebert",
                             "Tropes.Redemption.Anakin Skywalker"]


def test_show_all_defeats_the_narrowing(v):
    assert len(v["show_all_overrides"]) == 5


def test_typing_filters_inside_the_narrowed_set(v):
    """Not the whole vocabulary: 'Powers.Changer.Taylor Hebert' also matches
    'taylor' but is not in these results, so it must not come back."""
    assert v["typed_within_narrowed"] == ["Powers.Brute.Taylor Hebert"]
    assert v["typed_within_all"] == ["Powers.Brute.Taylor Hebert",
                                     "Powers.Changer.Taylor Hebert"]


def test_typing_matches_anywhere_in_the_path(v):
    assert v["typed_matches_leaf"] == [
        "Romance.Miraculous.Marinette Dupain-Cheng/Adrien Agreste"]


def test_typing_ignores_case_and_surrounding_space(v):
    assert v["typed_is_case_insensitive"] == ["Tropes.Redemption.Anakin Skywalker"]
    assert v["typed_trims"] == v["typed_is_case_insensitive"]


def test_degenerate_inputs_do_not_throw(v):
    assert v["narrowed_to_nothing"] == []
    assert v["empty_vocabulary"] == []
    assert v["missing_vocabulary"] == []


# --- the endpoint behind it -------------------------------------------------

def test_field_values_needs_a_token():
    assert client.get("/field-values?field=tags").status_code == 401


def test_field_values_reports_calibre_being_unreachable():
    r = client.get("/field-values?field=tags&q=x", headers=TOK)
    assert r.status_code == 502


def test_field_values_requires_a_field():
    assert client.get("/field-values", headers=TOK).status_code == 422


# --- pulling one column's value off a book, whatever shape it has -----------

def _fv(meta, field):
    from ratchet.main import _field_values
    return _field_values(meta, field)


def test_standard_multi_value_column():
    assert _fv({"tags": ["A", "B"]}, "tags") == ["A", "B"]


def test_standard_single_value_column():
    assert _fv({"series": "Rivers of London"}, "series") == ["Rivers of London"]


def test_custom_column_reads_through_user_metadata():
    meta = {"user_metadata": {"#genre": {"#value#": ["Romance", "AU.Modern"]}}}
    assert _fv(meta, "#genre") == ["Romance", "AU.Modern"]


def test_custom_single_value_column_becomes_a_list():
    meta = {"user_metadata": {"#readinglist": {"#value#": "Unread"}}}
    assert _fv(meta, "#readinglist") == ["Unread"]


def test_numbers_become_strings_so_they_can_be_compared_to_tree_values():
    assert _fv({"series_index": 2.0}, "series_index") == ["2.0"]


def test_absent_null_and_empty_all_give_nothing():
    assert _fv({}, "tags") == []
    assert _fv({"tags": None}, "tags") == []
    assert _fv({"user_metadata": {}}, "#genre") == []
    assert _fv({"tags": ["A", "", None]}, "tags") == ["A"]
    assert _fv({"tags": ["A"]}, "") == []
