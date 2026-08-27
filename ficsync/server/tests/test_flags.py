"""isDownloadedManaged, run for real in node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ficsync" / "static"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def flag(meta) -> bool:
    script = (
        f"import {{ isDownloadedManaged }} from {json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(JSON.stringify(isDownloadedManaged({json.dumps(meta)})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def um(value):
    return {"user_metadata": {"#downloaded": {"datatype": "bool", "#value#": value}}}


def test_true_bool_shows_the_buttons():
    assert flag(um(True)) is True


def test_false_or_unset_hides_them():
    assert flag(um(False)) is False
    assert flag(um(None)) is False


def test_library_without_the_column_hides_them():
    """Books has no #downloaded column at all — plain purchased books get no
    Check/Update."""
    assert flag({"user_metadata": {"#genre": {"#value#": ["x"]}}}) is False
    assert flag({}) is False


def test_string_values_do_not_sneak_through():
    """The live column is a real bool; a string 'yes' from some other setup
    must not count as managed."""
    assert flag(um("yes")) is False
