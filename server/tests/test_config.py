import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.config import load_config  # noqa: E402


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[service]\nauth_token = "tok"\ndata_dir = "{(tmp_path / "data").as_posix()}"\n'
        '[calibre]\nusername = "from-toml"\n',
        encoding="utf-8",
    )
    return cfg


def test_env_file_overrides_toml(tmp_path):
    cfg_path = _write_config(tmp_path)
    (tmp_path / ".env").write_text(
        'RATCHET_CALIBRE_USERNAME=bob\n'
        'RATCHET_CALIBRE_PASSWORD="p w"\n'
        '# comment\n\nnot a kv line\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.calibre.username == "bob"
    assert cfg.calibre.password == "p w"      # matched quotes stripped
    assert cfg.service.auth_token == "tok"    # untouched: not in .env


def test_process_env_beats_env_file(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path)
    (tmp_path / ".env").write_text("RATCHET_CALIBRE_PASSWORD=filepw\n", encoding="utf-8")
    monkeypatch.setenv("RATCHET_CALIBRE_PASSWORD", "envpw")
    cfg = load_config(cfg_path)
    assert cfg.calibre.password == "envpw"


def test_no_env_file_is_fine(tmp_path):
    cfg = load_config(_write_config(tmp_path))
    assert cfg.calibre.username == "from-toml"


def test_resolve_host_passes_literals_through():
    from ratchet.config import resolve_host
    assert resolve_host("127.0.0.1") == "127.0.0.1"
    assert resolve_host("0.0.0.0") == "0.0.0.0"
    assert resolve_host("100.1.2.3") == "100.1.2.3"


def test_resolve_host_tailscale_returns_a_tailnet_address(monkeypatch):
    import ratchet.config as c
    monkeypatch.setattr(c, "tailscale_ip", lambda: "100.64.0.1")
    assert c.resolve_host("tailscale") == "100.64.0.1"
    assert c.resolve_host("TailScale") == "100.64.0.1"


def test_resolve_host_tailscale_errors_clearly_when_offline(monkeypatch):
    import ratchet.config as c
    monkeypatch.setattr(c, "tailscale_ip", lambda: None)
    try:
        c.resolve_host("tailscale")
    except ValueError as e:
        assert "Tailscale" in str(e)
    else:
        raise AssertionError("expected ValueError when Tailscale is unavailable")


def test_bind_host_property(tmp_path, monkeypatch):
    import ratchet.config as c
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[service]\nauth_token = "t"\nhost = "tailscale"\n'
        f'data_dir = "{(tmp_path / "d").as_posix()}"\n', encoding="utf-8")
    monkeypatch.setattr(c, "tailscale_ip", lambda: "100.9.9.9")
    cfg = c.load_config(cfg_path)
    assert cfg.service.host == "tailscale"     # config keeps the symbolic value
    assert cfg.bind_host == "100.9.9.9"        # resolved only when binding


def test_the_columns_a_library_files_under_have_the_usual_names(tmp_path):
    """genre, fandom and majchar sit together under [calibre]: the service
    shows them, the tag rules move tags into them, and the scripts read and
    write them. A config that says nothing about them still loads."""
    cfg = load_config(_write_config(tmp_path))
    assert cfg.calibre.genre_field == "#genre"
    assert cfg.calibre.fandom_field == "#fandom"
    assert cfg.calibre.majchar_field == "#majchar"
    assert cfg.scripts.downloaded_field == "#downloaded"   # script-only


def test_a_library_names_its_own_tag_roots(tmp_path):
    """scheme_roots describes one library, so it has no useful default: a
    script that needs it refuses rather than treating every tag as stray."""
    cfg = load_config(_write_config(tmp_path))
    assert cfg.scripts.scheme_roots == []

    path = tmp_path / "own.toml"
    path.write_text(
        f'[service]\nauth_token = "tok"\ndata_dir = "{(tmp_path / "d").as_posix()}"\n'
        '[calibre]\nmajchar_field = "#characters"\n'
        '[scripts]\nscheme_roots = ["Tropes", "Content"]\n',
        encoding="utf-8")
    cfg = load_config(path)
    assert cfg.scripts.scheme_roots == ["Tropes", "Content"]
    assert cfg.calibre.majchar_field == "#characters"
    assert cfg.calibre.fandom_field == "#fandom"     # unlisted keys keep theirs


def test_a_library_says_which_tag_families_hold_one_value(tmp_path):
    """Nothing about a tag's shape says whether a second value under the same
    root contradicts the first or simply adds to it, so it is declared."""
    cfg = load_config(_write_config(tmp_path))
    assert cfg.scripts.exclusive_roots == []

    path = tmp_path / "exclusive.toml"
    path.write_text(
        f'[service]\nauth_token = "tok"\ndata_dir = "{(tmp_path / "d").as_posix()}"\n'
        '[scripts]\nexclusive_roots = ["Serial"]\n',
        encoding="utf-8")
    assert load_config(path).scripts.exclusive_roots == ["Serial"]


def test_where_last_updated_is_recorded_is_the_librarys_to_say(tmp_path):
    """Blank by default: recording it needs either a column of your own or
    calibre's Date overwritten, and neither is a decision to make for
    someone."""
    cfg = load_config(_write_config(tmp_path))
    assert cfg.calibre.lastupdate_field == ""

    path = tmp_path / "lastupdate.toml"
    path.write_text(
        f'[service]\nauth_token = "tok"\ndata_dir = "{(tmp_path / "d").as_posix()}"\n'
        '[calibre]\nlastupdate_field = "#lastupdated"\n',
        encoding="utf-8")
    assert load_config(path).calibre.lastupdate_field == "#lastupdated"


def test_the_tag_rules_file_defaults_into_the_config_folder(tmp_path):
    """Files a reader edits by hand live together in config/, not beside the
    code that reads them."""
    from ratchet import tagmap
    cfg = load_config(_write_config(tmp_path))
    assert cfg.tags.rules_file == ""
    assert tagmap.rules_path(cfg).name == "tag_rules.txt"
    assert tagmap.rules_path(cfg).parent.name == "config"

    path = tmp_path / "own.toml"
    path.write_text(
        f'[service]\nauth_token = "tok"\ndata_dir = "{(tmp_path / "d").as_posix()}"\n'
        f'[tags]\nrules_file = "{(tmp_path / "mine.txt").as_posix()}"\n',
        encoding="utf-8")
    assert tagmap.rules_path(load_config(path)).name == "mine.txt"


