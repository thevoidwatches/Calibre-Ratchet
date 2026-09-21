"""What the wizard asks of the machine, with the machine played by stand-ins:
Tailscale's answers are canned, so these run anywhere and change nothing."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet import config  # noqa: E402
from ratchet.wizard import system  # noqa: E402


def done(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


# As `tailscale serve status --json` reported it on a real machine.
SERVING = json.dumps({"TCP": {"8484": {"TCPForward": "127.0.0.1:8484"}}})


# ---- letting the tailnet in --------------------------------------------

def test_reach_is_on_when_tailscale_proxies_the_port_to_ratchet(monkeypatch):
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: done(SERVING))
    assert system.reach_status(8484) == {"known": True, "enabled": True, "other": ""}


def test_another_port_being_served_is_not_this_one(monkeypatch):
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: done(SERVING))
    assert system.reach_status(9000)["enabled"] is False


def test_the_port_going_somewhere_else_is_reported_not_claimed(monkeypatch):
    """Turning this on would replace it, so the wizard has to be able to say."""
    elsewhere = json.dumps({"TCP": {"8484": {"TCPForward": "127.0.0.1:3000"}}})
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: done(elsewhere))
    got = system.reach_status(8484)
    assert got["enabled"] is False and got["other"] == "127.0.0.1:3000"


def test_the_port_serving_a_web_site_instead_is_also_something_else(monkeypatch):
    web = json.dumps({"TCP": {"8484": {"HTTP": True}}, "Web": {
        "my-pc.ts.net:8484": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:1"}}}}})
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: done(web))
    got = system.reach_status(8484)
    assert got["enabled"] is False and got["other"]


def test_nothing_served_is_a_known_no(monkeypatch):
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: done("{}"))
    assert system.reach_status(8484) == {"known": True, "enabled": False, "other": ""}


@pytest.mark.parametrize("answer", [None, done("", returncode=1), done("not json")])
def test_not_being_able_to_ask_is_not_the_same_as_no(monkeypatch, answer):
    """A check that could not look must not report that it saw nothing —
    the wizard would tell people to set up what they already had."""
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: answer)
    assert system.reach_status(8484)["known"] is False


def test_enabling_asks_tailscale_for_a_persistent_forward(monkeypatch):
    calls = []

    def tailscale(*args, **kw):
        calls.append(args)
        return done(SERVING if args[:2] == ("serve", "status") else "started")

    monkeypatch.setattr(system, "_tailscale", tailscale)
    got = system.reach_enable(8484)
    assert got["ok"] is True
    assert calls[0] == ("serve", "--bg", "--tcp=8484", "tcp://127.0.0.1:8484")


def test_enabling_reports_what_tailscale_said_when_it_did_not_take(monkeypatch):
    def tailscale(*args, **kw):
        return done("{}") if args[:2] == ("serve", "status") else \
            done("serve is not enabled on your tailnet", returncode=1)

    monkeypatch.setattr(system, "_tailscale", tailscale)
    got = system.reach_enable(8484)
    assert got["ok"] is False and "not enabled on your tailnet" in got["message"]


def test_enabling_without_tailscale_says_so(monkeypatch):
    monkeypatch.setattr(system, "_tailscale", lambda *a, **k: None)
    got = system.reach_enable(8484)
    assert got["ok"] is False and "not installed" in got["message"]


def test_nothing_here_asks_for_administrator_rights():
    """The whole point of going through Tailscale. A firewall rule would do
    the same job and need them — and "run this as administrator to open your
    firewall" is what a careful person refuses, rightly."""
    source = Path(system.__file__).read_text(encoding="utf-8")
    code = "\n".join(l for l in source.splitlines()
                     if not l.strip().startswith(("#", '"""')))
    for needle in ("RunAs", "New-NetFirewallRule", "netsh"):
        assert needle not in code, needle


# ---- what Tailscale says about this machine ----------------------------

STATUS = json.dumps({
    "BackendState": "Running",
    "Self": {"DNSName": "my-pc.tail1234.ts.net.",
             "TailscaleIPs": ["100.64.0.7", "fd7a:115c:a1e0::7"]},
    "CurrentTailnet": {"MagicDNSEnabled": True}})


def fake_status(monkeypatch, stdout, exe="tailscale"):
    monkeypatch.setattr(config, "tailscale_exe", lambda: exe)
    monkeypatch.setattr(config.subprocess, "run",
                        lambda *a, **k: done(stdout))


def test_the_name_loses_its_trailing_dot_and_offers_a_short_form(monkeypatch):
    fake_status(monkeypatch, STATUS)
    got = config.tailscale_self()
    assert got == {"installed": True, "running": True, "state": "Running",
                   "ip": "100.64.0.7", "name": "my-pc.tail1234.ts.net",
                   "short_name": "my-pc"}


def test_no_name_is_offered_when_magicdns_is_off(monkeypatch):
    """It would resolve nowhere; better none than one that does not work."""
    off = json.loads(STATUS)
    off["CurrentTailnet"]["MagicDNSEnabled"] = False
    fake_status(monkeypatch, json.dumps(off))
    got = config.tailscale_self()
    assert got["name"] == "" and got["short_name"] == "" and got["ip"] == "100.64.0.7"


def test_logged_out_is_installed_but_not_running(monkeypatch):
    fake_status(monkeypatch, json.dumps({"BackendState": "NeedsLogin", "Self": {}}))
    got = config.tailscale_self()
    assert got["installed"] is True and got["running"] is False
    assert got["state"] == "NeedsLogin"


def test_not_installed_still_answers_in_full(monkeypatch):
    monkeypatch.setattr(config, "tailscale_exe", lambda: None)
    got = config.tailscale_self()
    assert got["installed"] is False and set(got) == {
        "installed", "running", "state", "ip", "name", "short_name"}


# ---- fetching the app --------------------------------------------------

def serve_bytes(monkeypatch, status, body):
    class Stream:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            if status >= 400:
                raise httpx.HTTPStatusError("bad", request=None, response=None)

        def iter_bytes(self, n):
            yield body

    monkeypatch.setattr(system.httpx, "stream", lambda *a, **k: Stream())


def test_the_app_lands_where_the_service_serves_it_from(monkeypatch, tmp_path):
    serve_bytes(monkeypatch, 200, b"PK\x03\x04 an apk")
    got = system.apk_download(tmp_path)
    assert got["ok"] is True and got["present"] is True
    assert (tmp_path / "ratchet.apk").read_bytes() == b"PK\x03\x04 an apk"
    assert not (tmp_path / "ratchet.apk.part").exists()


def test_no_release_yet_is_said_plainly_and_leaves_the_old_app(monkeypatch, tmp_path):
    (tmp_path / "ratchet.apk").write_bytes(b"PK old")
    serve_bytes(monkeypatch, 404, b"Not Found")
    got = system.apk_download(tmp_path)
    assert got["ok"] is False and "no app has been published" in got["message"]
    assert (tmp_path / "ratchet.apk").read_bytes() == b"PK old"


def test_an_error_page_is_not_saved_as_an_app(monkeypatch, tmp_path):
    serve_bytes(monkeypatch, 200, b"<html>rate limited</html>")
    got = system.apk_download(tmp_path)
    assert got["ok"] is False
    assert not (tmp_path / "ratchet.apk").exists()
    assert not (tmp_path / "ratchet.apk.part").exists()
