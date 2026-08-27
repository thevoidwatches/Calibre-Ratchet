"""Every UI module evaluates, with all imports and references resolving.

Syntax checking cannot catch a function that moved to another module or a name
that no longer exists; loading the graph can.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node not installed")
def test_ui_module_graph_loads():
    r = subprocess.run([node, str(HERE / "module_harness.mjs")],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=str(HERE))
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "ok" in r.stdout
