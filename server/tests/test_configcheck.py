"""The config checker, held to the mistakes that were actually made.

Nearly every case in the first half is a line that was really written, by
the person who designed the format, in one afternoon — and every one of them
failed silently. A checker that would not have caught those is not worth
having, so they are the specification.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet import configcheck as cc  # noqa: E402

COLUMNS = {"genre": "#genre", "fandom": "#fandom", "majchar": "#majchar"}

# Enough of a real rules file for a slip to stand out against.
GOOD = """\
Action           = genre: Fiction.Action
Adventure        = genre: Fiction.Adventure
Mystery          = genre: Fiction.Mystery
High Fantasy     = genre: Fantasy.High
Urban Fantasy    = genre: Fantasy.Urban
Female Lead      = Protagonist.Gender.Female
Male Lead        = Protagonist.Gender.Male
Anti-Hero Lead   = Protagonist.Alignment.Anti-Hero
Grimdark         = Tone.Grimdark
LitRPG           = Format.LitRPG
Progression      = Trope.Progression
In-Progress      = Serial.Ongoing
Last Update*     = -
Portal Fantasy   =
"""


def rules(extra: str = "", vocab=None, roots=None):
    return cc.check_tag_rules(GOOD + extra, COLUMNS, vocab, roots)


def said(findings, level, *needles) -> bool:
    return any(f.level == level and all(n in f.message for n in needles)
               for f in findings)


def test_a_clean_file_has_nothing_to_report_but_what_is_undecided():
    got = rules()
    assert [f.level for f in got] == ["note"]
    assert "Portal Fantasy" in got[0].message


# ---- the afternoon's mistakes ------------------------------------------

def test_a_transposed_root_is_a_second_branch():
    """Two rules said Progatonist; eight said Protagonist."""
    got = rules("Strong Lead      = Progatonist.Power Level.Overpowered\n")
    assert said(got, "warning", "Progatonist", "misspelling of 'Protagonist'")


def test_a_column_carries_on_to_the_value_after_it():
    """Cozy was meant as a genre AND a tone; both went to #genre."""
    got = rules("Cozy             = genre: Slice of Life, Tone.Cozy\n")
    assert said(got, "warning", "'Tone.Cozy' will go into #genre", "tags: Tone.Cozy")
    # The fix it suggests is not itself complained about.
    fixed = rules("Cozy             = genre: Slice of Life, tags: Tone.Cozy\n")
    assert not said(fixed, "warning", "Tone.Cozy")


def test_a_genre_written_without_its_column_becomes_a_tag():
    got = rules("Thriller         = Fiction.Thriller\n")
    assert said(got, "warning", "'Fiction.Thriller' will become a tag",
                "'genre:' missing")


def test_two_rules_making_the_same_slip_do_not_vouch_for_each_other():
    """Thriller and Apocalypse were both missing it."""
    got = rules("Thriller         = Fiction.Thriller\n"
                "Apocalypse       = Fiction.Apocalyptic\n")
    flagged = [f for f in got if "'genre:' missing" in f.message]
    assert len(flagged) == 2


def test_a_rule_naming_a_column_that_does_not_exist_is_said_to_be_dead():
    got = rules("The Watch        = Trope.Found Family, majcher: Disc.Vimes\n")
    assert said(got, "error", "no column called 'majcher'", "WHOLE rule",
                "did you mean 'majchar:'")


def test_a_tag_ruled_on_twice_says_which_line_wins():
    """'Completed = -' sat above 'Completed = Serial.Complete' for a week."""
    got = cc.check_tag_rules("Completed = -\nIn-Progress = Serial.Ongoing\n"
                             "Completed = Serial.Complete\n", COLUMNS)
    assert said(got, "warning", "ruled on twice", "Line 1 says '-'", "this one wins")
    assert [f.line for f in got if "twice" in f.message] == [3]


def test_the_same_rule_repeated_is_only_a_note():
    got = cc.check_tag_rules("FanFiction = -\nFanFiction = -\n", COLUMNS)
    assert [f.level for f in got] == ["note"]


def test_rules_do_not_chain_and_one_that_relies_on_it_is_caught():
    """GameLit = LitRPG leaves a bare LitRPG, the tag the next rule tidies."""
    got = rules("GameLit          = LitRPG\n")
    assert said(got, "warning", "stays 'LitRPG'", "Write 'Format.LitRPG' here")


def test_a_comma_with_nothing_after_it_is_mentioned_not_mourned():
    got = rules("Tower            = genre: Fantasy.Dungeon,\n")
    assert said(got, "note", "comma with nothing after it")
    assert not [f for f in got if f.level == "error"]


def test_a_line_with_no_equals_is_an_error_with_its_number():
    got = cc.check_tag_rules("# heading\n\nFanFiction -\n", COLUMNS)
    assert got[0].level == "error" and got[0].line == 3


# ---- what it must NOT complain about -----------------------------------

def test_a_new_root_is_not_a_typo():
    """Tone and Transfer were both invented that day, deliberately."""
    got = rules("FanFiction       = Transfer.Fanfiction\n")
    assert not [f for f in got if f.level != "note"]


def test_several_tropes_on_one_line_are_fine():
    got = rules("Tower            = Trope.Progression, genre: Fantasy.Dungeon\n")
    assert not [f for f in got if f.level != "note"]


def test_a_group_of_characters_under_one_column_is_what_carrying_on_is_for():
    got = rules("The Watch        = majchar: Disc.Vimes, Disc.Carrot, Disc.Nobby\n")
    assert not [f for f in got if f.level != "note"]


def test_a_calibre_column_named_outright_is_accepted():
    got = rules("Ongoing          = #status: Ongoing\n")
    assert not [f for f in got if f.level == "error"]


# ---- with the library to compare against -------------------------------

def library():
    return cc.Vocabulary(
        tags=Counter({"Trope.Progression": 54, "Format.LitRPG": 41,
                      "Serial.Ongoing": 54, "Key Event.Generic.Death": 3}),
        columns={"#genre": Counter({"Fiction.Action": 8, "Fiction.Action.Martial Arts": 9,
                                    "Fantasy.High": 43, "Fantasy.Urban": 16}),
                 "#fandom": Counter({"Worm": 200, "My Hero Academia": 90}),
                 "#majchar": Counter({"Worm.Taylor Hebert": 150,
                                      "My Hero Academia.Izuku Midoriya": 60})},
        existing_columns={"#genre", "#fandom", "#majchar"})


def test_the_library_settles_what_the_file_alone_cannot():
    """Nothing else in this file mentions Fantasy; the library knows it is
    1413 genres and not one tag."""
    got = cc.check_tag_rules("Supernatural = Fantasy.Urban\n", COLUMNS, library())
    assert said(got, "warning", "will become a tag", "'genre:' missing")


def test_a_value_one_letter_off_a_real_one_is_queried():
    got = cc.check_tag_rules("Kung Fu = genre: Fiction.Action.Martial Art\n",
                             COLUMNS, library())
    assert said(got, "warning", "'Fiction.Action.Martial Arts' is")


def test_a_short_name_is_not_a_slip_for_another_short_name():
    """'Trope.VR' was reported as a slip for 'Trope.AI': two letters out of
    eight, comparing whole strings — and two out of two where it matters."""
    vocab = library()
    vocab.tags["Trope.AI"] = 9
    got = cc.check_tag_rules("Virtual Reality = Trope.VR\n", COLUMNS, vocab)
    assert not [f for f in got if f.level != "note"]


def test_a_slip_is_found_at_whatever_depth_it_was_made():
    got = cc.check_tag_rules("Dead = Key Event.Genric.Death\n", COLUMNS, library())
    assert said(got, "warning", "'Key Event.Generic.Death' is")


def test_a_plural_root_the_library_spells_singular():
    """Tropes. in the rules, Trope. on 140 books."""
    got = cc.check_tag_rules("Unreliable Narrator = Tropes.Unreliable Narrator\n",
                             COLUMNS, library())
    assert said(got, "warning", "'Tropes'", "misspelling of 'Trope'")


def test_a_column_no_library_has_is_queried():
    got = cc.check_tag_rules("Ongoing = #status: Ongoing\n", COLUMNS, library())
    assert said(got, "warning", "no library has a column #status")


def test_roots_missing_from_scheme_roots_are_a_note_for_script_users():
    got = rules(roots=["Trope", "Format", "Serial"])
    assert said(got, "note", "scheme_roots", "Protagonist", "Tone")


# ---- tag_scheme.toml ---------------------------------------------------

def test_a_scheme_that_is_not_toml_says_nothing_can_read_it():
    got = cc.check_tag_scheme('[name_fixes]\n"Vimes = "Sam Vimes"\n')
    assert len(got) == 1 and got[0].level == "error"
    assert "no script can read ANY of it" in got[0].message and got[0].line == 2


def test_a_mistyped_table_name_is_read_by_nothing():
    got = cc.check_tag_scheme('[name_fixs]\n"A" = "B"\n')
    assert said(got, "warning", "nothing reads a table called 'name_fixs'",
                "did you mean 'name_fixes'")


def test_fixes_that_undo_each_other_are_an_error():
    got = cc.check_tag_scheme('[name_fixes]\n"Kacchan" = "Katsuki"\n"Katsuki" = "Kacchan"\n')
    assert said(got, "error", "swap back and forth")


def test_a_fix_whose_result_is_itself_fixed_takes_two_runs():
    got = cc.check_tag_scheme(
        '[name_fixes]\n"Midoriya" = "Midoriya Izuku"\n"Midoriya Izuku" = "Izuku Midoriya"\n')
    assert said(got, "warning", "takes two", '"Midoriya" = "Izuku Midoriya"')


def test_character_depths_have_to_be_lists_of_whole_numbers():
    got = cc.check_tag_scheme('[characters.depths]\n"Gender" = 3\n"Powers" = [3, 4]\n')
    assert said(got, "error", '"Gender"', "list of whole numbers")
    assert not said(got, "error", '"Powers"')


def test_a_depth_for_a_root_no_tag_starts_with_reads_nothing():
    got = cc.check_tag_scheme('[characters.depths]\n"Tropes" = [3]\n', library())
    assert said(got, "warning", 'no tag in the library starts with "Tropes"',
                'did you mean "Trope"')


def test_the_shipped_scheme_example_is_clean():
    example = Path(__file__).resolve().parents[2] / "config" / "tag_scheme.example.toml"
    assert cc.check_tag_scheme(example.read_text(encoding="utf-8")) == []


def test_the_shipped_rules_example_has_no_errors_or_warnings():
    example = Path(__file__).resolve().parents[2] / "config" / "tag_rules.example.txt"
    got = cc.check_tag_rules(example.read_text(encoding="utf-8"), COLUMNS)
    assert [f for f in got if f.level != "note"] == []


# ---- ao3_names.txt -----------------------------------------------------

def test_a_name_one_letter_off_a_character_the_library_has():
    got = cc.check_ao3_names("Deku = Izuku Midorya\n", library(), "#majchar", "#fandom")
    assert said(got, "warning", "no 'Izuku Midorya'", "'Izuku Midoriya'", "second person")


def test_a_new_character_is_not_a_typo():
    got = cc.check_ao3_names("Sophia = Sophia Hess\n", library(), "#majchar", "#fandom")
    assert got == []


def test_a_fandom_after_the_at_that_no_book_is_filed_under():
    got = cc.check_ao3_names("Taylor = Taylor Hebert @ Wurm\n", library(),
                             "#majchar", "#fandom")
    assert said(got, "warning", "fandom 'Wurm'", "did you mean 'Worm'")


def test_a_dropped_tag_written_without_its_equals():
    got = cc.check_ao3_names("Everyone -\nClass 1-A = -\n")
    assert [f.level for f in got] == ["error"] and "'Tag = -'" in got[0].message


def test_groups_and_drops_and_blanks_are_all_fine():
    got = cc.check_ao3_names("Family = Tom Dupain, Sabine Cheng\nEveryone = -\nLater =\n")
    assert [f.level for f in got] == ["note"]
