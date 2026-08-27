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
    monkeypatch.setattr(c, "tailscale_ip", lambda: "100.123.75.89")
    assert c.resolve_host("tailscale") == "100.123.75.89"
    assert c.resolve_host("TailScale") == "100.123.75.89"


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
