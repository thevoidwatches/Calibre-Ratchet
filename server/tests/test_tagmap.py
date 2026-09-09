"""What becomes of the tags a story arrives wearing.

The service applies these as a book is added and .scripts/stray_tags.py
sweeps the backlog with them, through the same module, so a rule cannot mean
two different things depending on which ran it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet import tagmap  # noqa: E402

COLUMNS = {"genre": "#genre", "fandom": "#fandom", "majchar": "#majchar"}


def rules(tmp_path: Path, text: str) -> tagmap.Rules:
    path = tmp_path / "tag_rules.txt"
    path.write_text(text, encoding="utf-8")
    return tagmap.load(path)


def book(tags, **columns) -> dict:
    return {"tags": list(tags),
            "user_metadata": {name: {"#value#": value}
                              for name, value in columns.items()}}


def test_a_tag_can_be_renamed_deleted_or_moved(tmp_path):
    r = rules(tmp_path, "In-Progress = Serial.Ongoing\n"
                        "FanFiction = -\n"
                        "Angst = genre: Angst\n")
    got = tagmap.apply(book(["In-Progress", "FanFiction", "Angst"]), r, COLUMNS)
    assert got["tags"] == ["Serial.Ongoing"]
    assert got["#genre"] == ["Angst"]


def test_a_tag_no_rule_covers_is_left_alone(tmp_path):
    """An import must never quietly lose something nobody has ruled on."""
    r = rules(tmp_path, "FanFiction = -\n")
    got = tagmap.apply(book(["FanFiction", "Something New"]), r, COLUMNS)
    assert got["tags"] == ["Something New"]


def test_a_blank_rule_is_a_decision_not_yet_made(tmp_path):
    r = rules(tmp_path, "Undecided =\n")
    assert tagmap.apply(book(["Undecided"]), r, COLUMNS) == {}


def test_moving_to_a_column_adds_rather_than_replaces(tmp_path):
    r = rules(tmp_path, "Angst = genre: Angst\n")
    got = tagmap.apply(book(["Angst"], **{"#genre": ["Fantasy"]}), r, COLUMNS)
    assert got["#genre"] == ["Fantasy", "Angst"]


def test_a_book_that_already_records_it_just_loses_the_tag(tmp_path):
    r = rules(tmp_path, "Angst = genre: Angst\n")
    got = tagmap.apply(book(["Angst"], **{"#genre": ["Angst"]}), r, COLUMNS)
    assert got == {"tags": []}          # the column was already right


def test_a_rule_may_name_a_column_outright(tmp_path):
    """Beyond the short names configured under [calibre]."""
    r = rules(tmp_path, "Ongoing = #status: Ongoing\n")
    got = tagmap.apply(book(["Ongoing"], **{"#status": []}), r, COLUMNS)
    assert got["#status"] == ["Ongoing"]


def test_a_rule_naming_a_column_this_library_lacks_leaves_the_tag(tmp_path):
    """Rather than guessing at where it meant."""
    r = rules(tmp_path, "Angst = nosuchkind: Angst\n")
    assert tagmap.apply(book(["Angst"]), r, COLUMNS) == {}


def test_a_pattern_covers_a_family_of_tags(tmp_path):
    """FanFicFare emits "Last Update: 2026/09/09" — a different tag every day,
    so no list of exact names can keep up."""
    r = rules(tmp_path, "Last Update* = -\n")
    got = tagmap.apply(book(["Last Update: 2026/09/09",
                             "Last Update Year/Month: 2026/09", "Keep"]),
                       r, COLUMNS)
    assert got["tags"] == ["Keep"]


def test_an_exact_name_beats_a_pattern_whatever_the_order(tmp_path):
    r = rules(tmp_path, "Last Update* = -\nLast Update: 2026/09/09 = Kept\n")
    got = tagmap.apply(book(["Last Update: 2026/09/09",
                             "Last Update Year/Month: 2026/09"]), r, COLUMNS)
    assert got["tags"] == ["Kept"]


def test_patterns_are_tried_in_the_order_written(tmp_path):
    r = rules(tmp_path, "Foo bar* = First\nFoo* = Second\n")
    assert tagmap.apply(book(["Foo bar baz"]), r, COLUMNS)["tags"] == ["First"]


def test_matching_is_case_sensitive(tmp_path):
    """calibre's tags are, and "AU" is not "au"."""
    r = rules(tmp_path, "AU = Alternate Universe\n")
    assert tagmap.apply(book(["au"]), r, COLUMNS) == {}


def test_two_tags_renamed_onto_one_do_not_duplicate_it(tmp_path):
    r = rules(tmp_path, "MHA = My Hero Academia\nBNHA = My Hero Academia\n")
    got = tagmap.apply(book(["MHA", "BNHA"]), r, COLUMNS)
    assert got["tags"] == ["My Hero Academia"]


def test_a_book_nothing_applies_to_is_not_written_at_all(tmp_path):
    """An add must not cost a calibre write per book for no reason."""
    r = rules(tmp_path, "FanFiction = -\n")
    assert tagmap.apply(book(["Tropes.Something"]), r, COLUMNS) == {}


def test_no_rules_file_means_every_tag_is_left_alone(tmp_path):
    r = tagmap.load(tmp_path / "absent.txt")
    assert not r
    assert tagmap.apply(book(["Anything"]), r, COLUMNS) == {}


def test_unreadable_lines_are_reported_not_guessed_at(tmp_path):
    r = rules(tmp_path, "# a comment\n\nGood = Fine\nthis line has no equals\n")
    assert r.exact == {"Good": "Fine"}
    assert r.bad_lines == [(4, "this line has no equals")]


def test_a_group_tag_can_stand_for_several_characters(tmp_path):
    """"The Watch" is several people; dropping it loses all of them."""
    r = rules(tmp_path, "The Watch = majchar: Disc.Vimes, Disc.Nobby\n")
    got = tagmap.apply(book(["The Watch"], **{"#majchar": []}), r, COLUMNS)
    assert got["#majchar"] == ["Disc.Vimes", "Disc.Nobby"]
    assert got["tags"] == []


def test_a_rename_can_produce_several_tags(tmp_path):
    r = rules(tmp_path, "Trio = Tropes.Friendship, Tropes.Team\n")
    got = tagmap.apply(book(["Trio"]), r, COLUMNS)
    assert got["tags"] == ["Tropes.Friendship", "Tropes.Team"]


def test_several_names_join_what_the_book_already_records(tmp_path):
    r = rules(tmp_path, "Cast = majchar: F.One, F.Two\n")
    got = tagmap.apply(book(["Cast"], **{"#majchar": ["F.Zero"]}), r, COLUMNS)
    assert got["#majchar"] == ["F.Zero", "F.One", "F.Two"]


def test_a_name_the_book_already_has_is_not_added_twice(tmp_path):
    r = rules(tmp_path, "Cast = majchar: F.One, F.Two\n")
    got = tagmap.apply(book(["Cast"], **{"#majchar": ["F.Two"]}), r, COLUMNS)
    assert got["#majchar"] == ["F.Two", "F.One"]


def test_spacing_round_the_separator_does_not_matter(tmp_path):
    r = rules(tmp_path, "Cast = majchar: F.One ,F.Two , , F.Three\n")
    got = tagmap.apply(book(["Cast"], **{"#majchar": []}), r, COLUMNS)
    assert got["#majchar"] == ["F.One", "F.Two", "F.Three"]


def test_one_tag_can_become_things_in_several_columns(tmp_path):
    """"The Watch" is a trope and three people. A column named part-way
    along applies to everything after it, so each column is named once."""
    r = rules(tmp_path, "The Watch = Tropes.Found Family, "
                        "majchar: Disc.Vimes, Disc.Carrot, Disc.Nobby\n")
    got = tagmap.apply(book(["The Watch"], **{"#majchar": []}), r, COLUMNS)
    assert got["tags"] == ["Tropes.Found Family"]
    assert got["#majchar"] == ["Disc.Vimes", "Disc.Carrot", "Disc.Nobby"]


def test_tags_is_the_way_back_after_naming_a_column(tmp_path):
    """Otherwise a rule could never return to the tags once it had left."""
    r = rules(tmp_path, "The Watch = majchar: Disc.Vimes, Disc.Nobby, "
                        "tags: Tropes.Found Family, Tropes.Team\n")
    got = tagmap.apply(book(["The Watch"], **{"#majchar": []}), r, COLUMNS)
    assert got["tags"] == ["Tropes.Found Family", "Tropes.Team"]
    assert got["#majchar"] == ["Disc.Vimes", "Disc.Nobby"]


def test_three_destinations_in_one_rule(tmp_path):
    r = rules(tmp_path, "Everything = genre: Angst, majchar: W.Taylor, "
                        "tags: Tropes.Solo\n")
    got = tagmap.apply(book(["Everything"], **{"#genre": [], "#majchar": []}),
                       r, COLUMNS)
    assert got["#genre"] == ["Angst"]
    assert got["#majchar"] == ["W.Taylor"]
    assert got["tags"] == ["Tropes.Solo"]


def test_a_mistyped_column_leaves_the_whole_rule_alone(tmp_path):
    """Not half of it: applying the parts before the mistake would be worse
    than applying none, because nothing later could tell it had happened."""
    r = rules(tmp_path, "The Watch = Tropes.Found Family, majcher: Disc.Vimes\n")
    assert tagmap.apply(book(["The Watch"]), r, COLUMNS) == {}


def test_a_deeper_value_replaces_the_one_it_already_implies(tmp_path):
    """RoyalRoad tags a story "Fantasy" and "High Fantasy" at once, and
    "Fantasy.High" already says it is fantasy."""
    r = rules(tmp_path, "Fantasy = genre: Fantasy\n"
                        "High Fantasy = genre: Fantasy.High\n")
    got = tagmap.apply(book(["Fantasy", "High Fantasy"], **{"#genre": []}),
                       r, COLUMNS)
    assert got["#genre"] == ["Fantasy.High"]


def test_a_parent_with_no_child_present_stays(tmp_path):
    r = rules(tmp_path, "Fantasy = genre: Fantasy\nAngst = genre: Angst\n")
    got = tagmap.apply(book(["Fantasy", "Angst"], **{"#genre": []}), r, COLUMNS)
    assert got["#genre"] == ["Fantasy", "Angst"]


def test_only_the_deepest_of_a_chain_survives(tmp_path):
    r = rules(tmp_path, "X = genre: Fiction, Fiction.Time Travel, "
                        "Fiction.Time Travel.Loop\n")
    got = tagmap.apply(book(["X"], **{"#genre": []}), r, COLUMNS)
    assert got["#genre"] == ["Fiction.Time Travel.Loop"]


def test_a_dot_inside_a_name_does_not_make_one_value_imply_another(tmp_path):
    """"Dr. Greta Helsing" is one series, not "Greta Helsing" under "Dr" —
    the same rule the UI splits hierarchies on."""
    r = rules(tmp_path, "A = genre: Dr, Dr. Greta Helsing\n")
    got = tagmap.apply(book(["A"], **{"#genre": []}), r, COLUMNS)
    assert got["#genre"] == ["Dr", "Dr. Greta Helsing"]


def test_a_parent_the_book_already_had_gives_way_to_the_new_child(tmp_path):
    r = rules(tmp_path, "High Fantasy = genre: Fantasy.High\n")
    got = tagmap.apply(book(["High Fantasy"], **{"#genre": ["Fantasy"]}),
                       r, COLUMNS)
    assert got["#genre"] == ["Fantasy.High"]


def test_the_tags_collapse_the_same_way(tmp_path):
    r = rules(tmp_path, "LitRPG = Format.LitRPG\n")
    got = tagmap.apply(book(["LitRPG", "Format"]), r, COLUMNS)
    assert got["tags"] == ["Format.LitRPG"]


def test_a_book_no_rule_fires_on_keeps_even_a_redundant_parent(tmp_path):
    """Collapsing is a consequence of applying a rule, not a licence to tidy
    a book nobody has ruled on."""
    r = rules(tmp_path, "Something Else = -\n")
    assert tagmap.apply(book(["Fantasy", "Fantasy.High"]), r, COLUMNS) == {}


def test_implies_reads_depth_not_a_shared_prefix():
    assert tagmap.implies("Fantasy", "Fantasy.High")
    assert not tagmap.implies("Fantasy", "Fantasy High")
    assert not tagmap.implies("Fan", "Fantasy.High")
    assert not tagmap.implies("Dr", "Dr. Greta Helsing")
    assert not tagmap.implies("Fantasy.High", "Fantasy")


def test_the_rules_file_lives_in_the_config_folder():
    from ratchet import configfiles
    assert configfiles.CONFIG_DIR.name == "config"
    assert configfiles.path("tag_rules.txt").parent == configfiles.CONFIG_DIR
