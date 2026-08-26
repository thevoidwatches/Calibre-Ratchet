"""Default open/closed state of the metadata editors on the book page."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


@pytest.fixture(scope="module")
def r():
    p = subprocess.run([node, str(HERE / "field_open_harness.mjs")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_reading_list_starts_open_and_the_others_closed(r):
    assert r["default_readinglist"] is True
    assert r["default_genre"] is False
    assert r["default_tags"] is False


def test_a_stored_preference_wins_over_the_default(r):
    assert r["stored_closes_readinglist"] is False
    assert r["stored_opens_tags"] is True
    assert r["unstored_still_default"] is False
