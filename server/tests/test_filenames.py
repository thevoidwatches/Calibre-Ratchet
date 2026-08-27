"""Exercise the UI's filename builder by running it, not by grepping for it.

format.js is deliberately free of DOM and storage access, so node can
evaluate it directly. Skipped where node isn't installed; the rest of the
suite is pure Python.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ratchet" / "static"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def filename(meta: dict) -> str:
    script = (
        # Windows needs a file:// URL here, not a bare drive-letter path.
        f"import {{ epubFilename }} from {json.dumps(STATIC.joinpath('format.js').as_uri())};"
        f"process.stdout.write(epubFilename({json.dumps(meta)}));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_series_book():
    assert filename({"title": "The Edge of the Abyss", "authors": ["Emily Skrutskie"],
                     "series": "The Abyss", "series_index": 2.0}) == \
        "The Abyss 2. The Edge of the Abyss - Emily Skrutskie.epub"


def test_fractional_series_index_keeps_its_decimal():
    assert filename({"title": "Natural Selection", "authors": ["Malinda Lo"],
                     "series": "Adaptation", "series_index": 1.5}) == \
        "Adaptation 1.5. Natural Selection - Malinda Lo.epub"


def test_book_without_a_series():
    assert filename({"title": "Blue Core", "authors": ["Ivan Kal"]}) == \
        "Blue Core - Ivan Kal.epub"


def test_multiple_authors_are_joined():
    assert filename({"title": "Good Omens",
                     "authors": ["Terry Pratchett", "Neil Gaiman"]}) == \
        "Good Omens - Terry Pratchett, Neil Gaiman.epub"


def test_path_separators_and_reserved_characters_are_replaced():
    out = filename({"title": 'A/B: "C" <D>|E?F*G\H', "authors": ["X"]})
    assert not any(c in out[:-5] for c in '<>:"/\|?*')
    assert out.endswith(".epub")


def test_no_trailing_dot_or_space_windows_rejects_those():
    out = filename({"title": "Ends With A Dot.", "authors": []})
    assert out == "Ends With A Dot.epub"


def test_very_long_name_is_truncated_but_keeps_the_extension():
    out = filename({"title": "x" * 400, "authors": ["y" * 400]})
    assert len(out) <= 185 and out.endswith(".epub")


def test_falls_back_to_the_id_when_there_is_no_metadata():
    assert filename({"id": 97}) == "97.epub"
