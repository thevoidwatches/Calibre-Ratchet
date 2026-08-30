"""Starting up when the service cannot be reached.

Every section of the page begins hidden and show() is what reveals one, so a
startup path that gives up without calling it leaves the app on a blank page
— painted in the theme colour, with nothing said about why."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.fixture(scope="module")
def b():
    if node is None:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HERE / "test_boot.js")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_an_unreachable_service_still_leaves_a_view_showing(b):
    """The blank page: boot() used to return from its catch without ever
    choosing a view, so nothing was unhidden."""
    assert b["before"] is None        # nothing shown before the app boots
    assert b["after"] == "browse"     # and something shown after it fails


def test_the_failure_is_reported_rather_than_swallowed():
    app = client.get("/ui/app.js").text
    assert 'err("could not reach Ratchet' in app
    # Never overrides the token screen a 401 has already routed itself to.
    assert 'if (viewNow() === null) show("browse", false);' in app
    # A 401 has its own screen and its own sound; it must not also be reported
    # here as an unreachable service.
    assert 'String(e.message) !== "bad token"' in app


def test_coming_back_to_the_app_retries_a_failed_boot():
    """Otherwise the error sits there until something else reloads the page,
    which for a short absence is nothing at all."""
    app = client.get("/ui/app.js").text
    assert "bootFailed = true" in app and "if (bootFailed) boot();" in app
    assert "bootFailed = false" in app        # cleared when a boot starts
