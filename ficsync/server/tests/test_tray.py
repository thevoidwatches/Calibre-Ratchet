"""The tray app's logic, minus the Windows message loop.

pystray's icon.run() needs a desktop session, so what is tested here is
everything around it: log destination, the wait-for-an-address behaviour that
keeps a login-time start from dying invisibly, and the icon asset existing.
"""

import logging
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ficsync import logsetup  # noqa: E402
from ficsync import tray  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    yield
    root.handlers, root.level = saved[0], saved[1]


def test_tray_icon_asset_ships_with_the_package():
    assert tray.ICON_PATH.is_file(), tray.ICON_PATH
    from PIL import Image
    im = Image.open(tray.ICON_PATH)
    # Transparent corners: a square badge would sit in the tray as a white box.
    assert im.mode == "RGBA"
    assert im.getpixel((0, 0))[3] == 0


def test_logging_to_a_file_writes_ficsync_lines(tmp_path):
    path = tmp_path / "sub" / "ratchet.log"
    logsetup.configure(path)
    logging.getLogger("ficsync").info("hello from the test")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "hello from the test" in path.read_text(encoding="utf-8")


def test_logging_does_not_double_up_when_configured_twice(tmp_path):
    path = tmp_path / "ratchet.log"
    logsetup.configure(path)
    logsetup.configure(path)
    logging.getLogger("ficsync").info("only once")
    for h in logging.getLogger().handlers:
        h.flush()
    assert path.read_text(encoding="utf-8").count("only once") == 1


def test_third_party_chatter_stays_out_of_the_log(tmp_path):
    """httpx logs every calibre request at INFO; the log is for events."""
    path = tmp_path / "ratchet.log"
    logsetup.configure(path)
    logging.getLogger("httpx").info("HTTP Request: GET /ajax/whatever")
    logging.getLogger("ficsync").warning("something real")
    for h in logging.getLogger().handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "HTTP Request" not in text and "something real" in text


class _Cfg:
    """Stands in for Config: bind_host raises until Tailscale is 'up'."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    @property
    def bind_host(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ValueError("no Tailscale IPv4 address was found")
        return "100.64.0.1"


def test_bind_host_is_awaited_rather_than_fatal(monkeypatch):
    """At login Tailscale may not be up yet. With no console, an exception
    here would kill Ratchet with nothing on screen to explain it."""
    monkeypatch.setattr(tray, "BIND_RETRY_SECONDS", 0)
    cfg = _Cfg(fail_times=3)
    status = []
    host = tray._resolve_bind_host(cfg, status.append, threading.Event())
    assert host == "100.64.0.1"
    assert cfg.calls == 4
    assert any("Tailscale" in s for s in status)


def test_waiting_for_an_address_gives_up_eventually(monkeypatch):
    monkeypatch.setattr(tray, "BIND_RETRY_SECONDS", 0)
    monkeypatch.setattr(tray, "BIND_WAIT_SECONDS", 0)
    cfg = _Cfg(fail_times=99)
    status = []
    assert tray._resolve_bind_host(cfg, status.append, threading.Event()) is None
    assert any("Tailscale" in s for s in status)


def test_quitting_stops_the_wait_immediately(monkeypatch):
    """Quit while it is still waiting for an address must not hang."""
    monkeypatch.setattr(tray, "BIND_RETRY_SECONDS", 0)
    stop = threading.Event()
    stop.set()
    assert tray._resolve_bind_host(_Cfg(fail_times=99), lambda _: None, stop) is None


def test_ui_url_points_at_the_app_not_the_api_root():
    assert tray._url("100.64.0.1", 8484) == "http://100.64.0.1:8484/ui/"
