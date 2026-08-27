"""The filter query builder, run for real in node rather than string-matched."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


@pytest.fixture(scope="module")
def q():
    r = subprocess.run([node, str(HERE / "test_query.js")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_single_term(q):
    assert q["single"] == '(#genre:"~^Fantasy(\.|$)")'


def test_or_within_one_field(q):
    """'Reading List A or Reading List B'."""
    assert q["or_same_field"] == (
        '((#readinglist:"~^Unread(\.|$)") or (#readinglist:"~^Following(\.|$)"))')


def test_or_across_different_fields(q):
    """'Genre A or Tag B'."""
    assert q["or_across_fields"] == (
        '((#genre:"~^Fantasy(\.|$)") or (tags:"~^Progression(\.|$)"))')


def test_groups_are_anded(q):
    assert q["and_of_groups"] == (
        '(#genre:"~^Fantasy(\.|$)") and (tags:"~^Progression(\.|$)")')


def test_exclusion_is_and_not(q):
    assert q["and_not"] == (
        '(#genre:"~^Fantasy(\.|$)") and (not tags:"~^litrpg(\.|$)")')


def test_negated_term_inside_an_or_group_is_parenthesised(q):
    """Without the parens this would depend on calibre's not/or precedence."""
    assert q["negated_inside_or"] == (
        '((#genre:"~^Fantasy(\.|$)") or (not tags:"~^litrpg(\.|$)"))')


def test_flat_columns_use_exact_match(q):
    """A dot in an author name is punctuation, not hierarchy."""
    assert q["flat_column_exact"] == '(authors:"=R.A. Scott")'


def test_free_text_is_anded_on(q):
    assert q["with_free_text"] == '(tags:"~^x(\.|$)") and royalroad'
    assert q["free_text_only"] == "royalroad"
    assert q["empty"] == ""


def test_empty_groups_are_dropped(q):
    assert q["empty_group_skipped"] == '(tags:"~^x(\.|$)")'


def test_regex_metacharacters_in_values_are_escaped(q):
    # Parentheses must be escaped; a hyphen is only special inside a character
    # class, so it is correctly left alone.
    assert q["regex_escaped"] == '#genre:"~^Sci-Fi \(Hard\)(\.|$)"'


def test_description_reads_as_the_structure(q):
    assert q["describe"] == "(#genre: A or tags: B) and not x: y"


# --- presets used as single atoms -------------------------------------------

def test_or_of_two_whole_presets(q):
    """The case the two-level model was wrongly said to rule out: OR-ing two
    complete expressions. A preset is just an atom inside a group."""
    assert q["or_two_presets"] == (
        '((((#readinglist:"~^Rainy Day(\.|$)") or '
        '(#readinglist:"~^Reading Shortlist(\.|$)"))) or '
        '((#genre:"~^Fantasy(\.|$)") and (not tags:"~^litrpg(\.|$)")))')


def test_preset_anded_with_a_plain_term(q):
    assert q["and_preset_with_term"] == (
        '((#genre:"~^Fantasy(\.|$)") and (not tags:"~^litrpg(\.|$)")) '
        'and (tags:"~^web-serial(\.|$)")')


def test_a_preset_can_be_negated_as_a_whole(q):
    assert q["excluded_preset"].endswith(
        '(not (((#readinglist:"~^Rainy Day(\.|$)") or '
        '(#readinglist:"~^Reading Shortlist(\.|$)"))))')


def test_reference_to_a_deleted_preset_is_dropped_not_fatal(q):
    assert q["missing_preset"] == '(tags:"~^x(\.|$)")'


def test_self_and_mutual_references_terminate(q):
    """Without cycle handling these would recurse until the stack gave out."""
    assert q["self_reference"] == ""
    assert q["mutual_reference"] == ""


def test_preset_shows_by_name_in_the_preview(q):
    assert q["describe_preset"] == "([Backlog] or tags: x)"


def test_cycle_detection(q):
    assert q["cycle_direct"] is True        # a set cannot reference itself
    assert q["cycle_indirect"] is True      # A -> B -> A
    assert q["cycle_none"] is False


# --- the Downloaded pseudo-filter -------------------------------------------

def test_downloaded_expands_to_an_id_list(q):
    assert q["downloaded_ids"] == "((id:5 or id:97))"


def test_downloaded_with_nothing_on_device_matches_no_book(q):
    # Ids start at 1, so id:"<1" is the empty set — and the excluded form is
    # then every book, which is the correct reading of "not Downloaded".
    assert q["downloaded_empty"] == '(id:"<1")'
    assert q["downloaded_no_ctx"] == '(id:"<1")'
    assert q["downloaded_excluded_empty"] == '(not id:"<1")'


def test_downloaded_can_be_negated(q):
    assert q["downloaded_excluded"] == "(not (id:5))"


def test_downloaded_ors_with_a_plain_term(q):
    assert q["downloaded_or_term"] == \
        '(((id:1 or id:2)) or (tags:"~^x(\.|$)"))'


def test_downloaded_works_inside_a_preset(q):
    # One paren layer each from the atom, the preset's group, and the group
    # holding the preset reference.
    assert q["downloaded_in_preset"] == "(((id:7)))"


def test_downloaded_reads_as_its_name(q):
    assert q["describe_downloaded"] == "(not Downloaded or tags: x)"
