"""The shell's setup page (shell/www/setup.js) and the pages bundled with it.

The app asks where its server is on first launch rather than having the
address built in, so one APK serves anybody. What is typed there is typed on
a phone, so the parsing is forgiving — and it is a pure function, which node
can import directly, the DOM half sitting behind a `document` guard.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SHELL = Path(__file__).resolve().parents[2] / "shell"
SETUP = SHELL / "www" / "setup.js"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def normalise(text) -> dict:
    script = (f"import * as s from {json.dumps(SETUP.as_uri())};"
              f"process.stdout.write(JSON.stringify("
              f"s.normaliseServer({json.dumps(text)})));")
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("typed", [
    "my-pc.tail1234.ts.net",
    "  my-pc.tail1234.ts.net  ",
    "my-pc.tail1234.ts.net:8484",
    "http://my-pc.tail1234.ts.net:8484",
    "http://my-pc.tail1234.ts.net:8484/",
    "http://my-pc.tail1234.ts.net:8484/ui/",
    "MY-PC.tail1234.ts.net",
])
def test_every_way_of_typing_one_server_means_that_server(typed):
    assert normalise(typed) == {"origin": "http://my-pc.tail1234.ts.net:8484"}


def test_a_bare_address_gets_the_port_ratchet_listens_on():
    assert normalise("100.64.0.1") == {"origin": "http://100.64.0.1:8484"}


def test_the_short_machine_name_is_an_address():
    """Tailscale on the device completes it, and it is what anyone would
    rather type on a phone — or on an ereader with no keyboard to speak of."""
    assert normalise("my-pc") == {"origin": "http://my-pc:8484"}


def test_a_port_that_was_typed_is_kept():
    assert normalise("my-pc.ts.net:9000") == {"origin": "http://my-pc.ts.net:9000"}


def test_a_typed_port_80_is_not_mistaken_for_no_port():
    """The URL parser reports a scheme's own port as no port at all, which
    would have 8484 added to an address that said 80."""
    assert normalise("my-pc.ts.net:80") == {"origin": "http://my-pc.ts.net"}


def test_a_scheme_that_was_typed_is_taken_at_its_word():
    """`tailscale serve` puts Ratchet on https at 443; adding :8484 to that
    would point the app at nothing."""
    assert normalise("https://my-pc.ts.net") == {"origin": "https://my-pc.ts.net"}
    assert normalise("http://my-pc.ts.net") == {"origin": "http://my-pc.ts.net"}


@pytest.mark.parametrize("typed", ["", "   ", None])
def test_nothing_typed_is_said_plainly(typed):
    assert "error" in normalise(typed)


@pytest.mark.parametrize("typed", ["ftp://my-pc.ts.net", "file:///sdcard/x",
                                   "javascript://alert(1)"])
def test_only_http_addresses_are_accepted(typed):
    """The app would load whatever this returns."""
    assert "error" in normalise(typed)


def test_nonsense_is_an_error_not_a_crash():
    assert "error" in normalise("http://")
    assert "error" in normalise("my pc")


# ---- the bundle --------------------------------------------------------

def test_the_generated_offline_page_matches_its_sources():
    """error.html is generated and tracked, so that a fresh clone can build
    without running the generator first. This is what stops it drifting."""
    r = subprocess.run([node, str(SHELL / "build-error-page.mjs"), "--check"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_server_address_is_built_into_the_app():
    """One APK serves anybody only while nothing in the bundle, and nothing
    in the config baked into it, names a particular machine."""
    config = json.loads((SHELL / "capacitor.config.json").read_text("utf-8"))
    assert "url" not in config.get("server", {})
    # The offline page has to be able to fall back, all the same.
    assert config["server"]["errorPath"] == "error.html"

    offline = (SHELL / "www" / "offline.js").read_text("utf-8")
    assert "RatchetShell.getServer()" in offline
    assert "export const SERVER" not in offline
