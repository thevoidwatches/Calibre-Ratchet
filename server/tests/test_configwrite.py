"""The wizard edits config.toml as text, because a config that has been lived
in is mostly things a TOML writer would throw away."""

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.wizard.configwrite import (ConfigEditError, set_env,  # noqa: E402
                                        set_values, toml_value)

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"

LIVED_IN = '''\
[service]
host = "tailscale"        # looked up at startup
port = 8484

[calibre]
base_url = "http://127.0.0.1:8080"
library_id = ""            # empty = the server's default
genre_field = "#genre"     # shown beside tags
# row_field = "#old"       a setting someone commented out

[fanficfare]
blocked_sites = ["archiveofourown.org"]   # temporary: AO3 525s, 2026-08-27
'''


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b), "lines were added or lost"
    return [(x, y) for x, y in zip(a, b) if x != y]


def test_only_the_line_asked_about_changes():
    out = set_values(LIVED_IN, {("calibre", "library_id"): "Serials"})
    assert changed_lines(LIVED_IN, out) == [
        ('library_id = ""            # empty = the server\'s default',
         'library_id = "Serials"     # empty = the server\'s default')]


def test_a_trailing_comment_keeps_its_column_where_there_is_room():
    out = set_values(LIVED_IN, {("calibre", "genre_field"): "#g"})
    line = [l for l in out.splitlines() if l.startswith("genre_field")][0]
    assert line.index("# shown") == LIVED_IN.splitlines()[7].index("# shown")


def test_a_longer_value_pushes_the_comment_rather_than_eating_it():
    out = set_values(LIVED_IN, {("calibre", "library_id"): "A Very Long Library Name"})
    line = [l for l in out.splitlines() if l.startswith("library_id")][0]
    assert line == ('library_id = "A Very Long Library Name" '
                    "# empty = the server's default")


def test_a_hash_inside_a_value_is_not_a_comment():
    """Every custom column starts with one."""
    out = set_values(LIVED_IN, {("calibre", "genre_field"): "#kind"})
    assert tomllib.loads(out)["calibre"]["genre_field"] == "#kind"
    assert "# shown beside tags" in out


def test_a_commented_out_key_is_left_alone_and_the_real_one_added():
    out = set_values(LIVED_IN, {("calibre", "row_field"): "#fandom"})
    assert '# row_field = "#old"       a setting someone commented out' in out
    assert tomllib.loads(out)["calibre"]["row_field"] == "#fandom"


def test_a_missing_key_joins_the_end_of_its_own_section():
    out = set_values(LIVED_IN, {("calibre", "username"): "reader"})
    lines = out.splitlines()
    assert lines.index('username = "reader"') < lines.index("[fanficfare]")
    assert lines.index('username = "reader"') > lines.index("[calibre]")


def test_a_missing_section_is_added_at_the_end():
    out = set_values(LIVED_IN, {("tags", "rules_file"): "C:/rules.txt"})
    assert out.rstrip().endswith('[tags]\nrules_file = "C:/rules.txt"')
    assert out.startswith(LIVED_IN)             # and nothing above it moved


def test_the_same_key_in_another_section_is_not_touched():
    text = '[service]\nport = 1\n\n[other]\nport = 2\n'
    out = set_values(text, {("other", "port"): 9})
    assert tomllib.loads(out) == {"service": {"port": 1}, "other": {"port": 9}}


def test_several_values_at_once():
    out = set_values(LIVED_IN, {("service", "port"): 9000,
                                ("calibre", "base_url"): "http://10.0.0.2:8080",
                                ("calibre", "username"): "reader"})
    got = tomllib.loads(out)
    assert got["service"]["port"] == 9000
    assert got["calibre"]["base_url"] == "http://10.0.0.2:8080"
    assert got["calibre"]["username"] == "reader"
    assert got["fanficfare"]["blocked_sites"] == ["archiveofourown.org"]


def test_a_value_set_across_several_lines_is_refused_not_mangled():
    text = '[scripts]\nscheme_roots = [\n    "Trope", "Content",\n]\n'
    with pytest.raises(ConfigEditError, match="several lines"):
        set_values(text, {("scripts", "scheme_roots"): ["Trope"]})


def test_a_one_line_list_can_be_replaced():
    out = set_values(LIVED_IN, {("fanficfare", "blocked_sites"): []})
    assert tomllib.loads(out)["fanficfare"]["blocked_sites"] == []
    assert "# temporary: AO3 525s, 2026-08-27" in out


def test_awkward_strings_survive_the_round_trip():
    for value in ['say "hi"', "back\\slash", "C:\\Users\\me", "ünïcödé", ""]:
        out = set_values(LIVED_IN, {("calibre", "library_id"): value})
        assert tomllib.loads(out)["calibre"]["library_id"] == value


def test_the_shipped_example_takes_every_setting_the_wizard_writes():
    """A new install starts from config.example.toml, so its comments are
    what a new user's config.toml is born with."""
    before = EXAMPLE.read_text(encoding="utf-8")
    values = {("calibre", "base_url"): "http://127.0.0.1:8081",
              ("calibre", "library_id"): "Fiction",
              ("calibre", "genre_field"): "#kind",
              ("calibre", "fandom_field"): "",
              ("calibre", "majchar_field"): "",
              ("calibre", "row_field"): "#kind",
              ("calibre", "lastupdate_field"): "timestamp"}
    out = set_values(before, values)
    got = tomllib.loads(out)
    for (section, key), value in values.items():
        assert got[section][key] == value
    # Every one of them was already in the example: edited, never appended.
    assert len(changed_lines(before.replace("\r\n", "\n"), out)) == len(values)


def test_a_windows_file_keeps_its_line_endings():
    """Rewritten with bare LF it would differ on every line, which is not
    leaving the rest alone — found by editing a real config and watching it
    shrink by exactly one byte a line."""
    windows = LIVED_IN.replace("\n", "\r\n")
    out = set_values(windows, {("calibre", "library_id"): "Serials"})
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")
    assert out.replace("\r\n", "\n") == set_values(
        LIVED_IN, {("calibre", "library_id"): "Serials"})

    env = set_env("A=1\r\nB=2\r\n", {"B": "3", "C": "4"})
    assert env == "A=1\r\nB=3\r\nC=4\r\n"


def test_toml_value_refuses_what_it_cannot_write():
    assert toml_value(True) == "true"
    assert toml_value(["a", "#b"]) == '["a", "#b"]'
    with pytest.raises(ConfigEditError):
        toml_value(1.5)


# ---- .env --------------------------------------------------------------

def parse_env(text: str) -> dict:
    """The service's own reader, so these tests mean what it means."""
    import tempfile
    from ratchet.config import _load_env_file
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".env"
        p.write_text(text, encoding="utf-8")
        return _load_env_file(p)


def test_env_values_are_replaced_in_place_and_the_rest_kept():
    text = "# secrets\nRATCHET_AUTH_TOKEN=old\nSOMETHING_ELSE=mine\n"
    out = set_env(text, {"RATCHET_AUTH_TOKEN": "new"})
    assert out == "# secrets\nRATCHET_AUTH_TOKEN=new\nSOMETHING_ELSE=mine\n"


def test_env_values_not_there_yet_are_appended():
    out = set_env("RATCHET_AUTH_TOKEN=t\n", {"RATCHET_CALIBRE_USERNAME": "me"})
    assert parse_env(out) == {"RATCHET_AUTH_TOKEN": "t",
                              "RATCHET_CALIBRE_USERNAME": "me"}


def test_an_empty_env_file_is_a_fine_place_to_start():
    assert parse_env(set_env("", {"A": "1"})) == {"A": "1"}


@pytest.mark.parametrize("password", [
    'p@ss word', 'with=equals', '"quoted"', "'single'", " padded ", "#hash",
    'mixed"quote', "ünï"])
def test_a_password_comes_back_exactly_as_it_went_in(password):
    """The reader strips one pair of matching quotes and the edge spaces, so
    a password that has either needs protecting on the way in."""
    out = set_env("", {"RATCHET_CALIBRE_PASSWORD": password})
    assert parse_env(out)["RATCHET_CALIBRE_PASSWORD"] == password


def test_a_line_break_in_a_secret_is_refused():
    with pytest.raises(ConfigEditError):
        set_env("", {"RATCHET_AUTH_TOKEN": "a\nb"})
