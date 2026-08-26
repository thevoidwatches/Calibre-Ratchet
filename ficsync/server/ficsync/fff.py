"""Run `fanficfare -u` on a working copy of the epub.

Facts verified against FanFicFare 4.60.0 cli.py:

  * `-u <file.epub>` updates that file IN PLACE (output_filename = arg), using
    the <dc:source> story URL inside it.
  * Its own guard: equal chapter counts -> prints "... already contains N
    chapters." and does nothing; epub > site -> warns "... more than source"
    and does nothing; site > epub -> proceeds, rebuilding from the site's
    current chapter list and reusing local chapter text by normalized-URL
    match. That last branch is exactly where stub+add data loss happens, which
    is why this wrapper is only ever called AFTER safety.decide() approves.

`--force` is deliberately not constructible through this module.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import Config
from .sites import _fff_base_cmd  # same binary/config/options as the metadata fetch


class FFFError(Exception):
    pass


@dataclass
class FFFResult:
    changed: bool         # best-effort read of FFF's own stdout
    stdout_tail: str


def update_epub(epub_path: str, cfg: Config) -> FFFResult:
    cmd = _fff_base_cmd(cfg) + ["-u", epub_path]
    if "--force" in cmd:
        raise FFFError("refusing to run with --force")  # belt and suspenders
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=cfg.fanficfare.timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise FFFError(f"fanficfare -u timed out on {epub_path}") from e

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    tail = out.strip()[-1500:]

    if proc.returncode != 0:
        raise FFFError(f"fanficfare -u exited {proc.returncode}: {tail}")

    # Signature lines from cli.py (4.60.0). We don't *depend* on these for
    # safety — the post-verify in main.py does that — they just make results
    # readable and catch the "guard tripped after our pre-flight passed" race.
    if "more than source" in out:
        raise FFFError(
            "FFF's own count guard tripped after pre-flight passed — the site "
            "changed between our check and the update. Re-run check. " + tail
        )
    changed = "Do update - epub(" in out
    if not changed and "already contains" not in out:
        # Neither known outcome line appeared; treat cautiously.
        raise FFFError("could not interpret fanficfare output: " + tail)

    return FFFResult(changed=changed, stdout_tail=tail)
