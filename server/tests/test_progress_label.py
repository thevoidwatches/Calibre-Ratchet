"""The download progress line, evaluated by node like the filename builder."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ratchet" / "static"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def label(done: int, total: int) -> str:
    script = (
        f"import {{ progressLabel }} from {json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(progressLabel({done}, {total}));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_percent_and_sizes_when_the_total_is_known():
    assert label(360_000_000, 876_804_494) == "41% — 360 of 877 MB"


def test_small_files_keep_a_decimal():
    assert label(1_250_000, 12_400_000) == "10% — 1.3 of 12 MB"


def test_bytes_alone_when_the_server_gave_no_length():
    assert label(360_000_000, 0) == "360 MB so far"


def test_never_reports_past_the_whole():
    assert label(900_000_000, 876_804_494).startswith("100% — ")
