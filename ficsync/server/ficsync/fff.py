"""Run `fanficfare -u` on a working copy of the epub.

Facts verified against FanFicFare 4.60.0 cli.py:

  * `-u <file.epub>` updates that file IN PLACE (output_filename = arg), using
    the <dc:source> story URL inside it.
  * Chapter-count guard (cli.py L474): equal counts -> prints "... already
    contains N chapters." and does nothing; epub > site -> warns "... more
    than source" and does nothing; site > epub -> proceeds, rebuilding from
    the site's current chapter list and reusing local chapter text by
    normalized-URL match. That last branch is exactly where stub+add data loss
    happens, which is why this wrapper is only ever called AFTER
    safety.decide() approves.
  * File-date guard (writers/base_writer.py L207): unless `always_overwrite`
    is set, FFF compares the output file's **filesystem mtime** against the
    story's dateUpdated and skips writing when the file looks newer.

Why `always_overwrite=true` is passed here
------------------------------------------
ficsync hands FFF a temp file it just wrote by downloading the epub from
calibre, so its mtime is *always* "now" by construction — it says nothing
about when the story content was last written. The date guard therefore
misfires on every story whose last site update was before today, and FFF
silently writes nothing; the post-verify then fails with "chapters expected
but absent after update". (Observed on book 97: epub mtime 2026-08-26 vs
story dateUpdated 2026-08-25.)

`always_overwrite` is one of the two things FFF's own `--force` turns on
(cli.py L634), so this is worth being precise about. The other, dangerous one
is `--force` skipping the entire cli.py L474 block — which is also the block
that calls get_update_data() to pre-populate your existing chapters. That is
what makes `--force` destructive, and it is NOT enabled here: run_fff still
refuses the flag outright, so the count guard and old-chapter reuse both stay
fully active. Only the meaningless file-mtime comparison is bypassed.

ficsync's own protections are unaffected and strictly stronger: chapter
identity sets are compared before FFF runs, and the epub is re-extracted and
matched against the site list afterwards before anything reaches calibre.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import Config
from .sites import run_fff  # same binary/config/options/encoding as the metadata fetch


class FFFError(Exception):
    pass


@dataclass
class FFFResult:
    changed: bool         # best-effort read of FFF's own stdout
    stdout_tail: str


# See the module docstring: bypasses only the file-mtime check, never the
# chapter-count guard or old-chapter reuse.
_ALWAYS_OVERWRITE = ["-o", "always_overwrite=true"]


def update_epub(epub_path: str, cfg: Config) -> FFFResult:
    try:
        proc = run_fff(_ALWAYS_OVERWRITE + ["-u", epub_path], cfg)
    except subprocess.TimeoutExpired as e:
        raise FFFError(f"fanficfare -u timed out on {epub_path}") from e
    except FileNotFoundError as e:
        raise FFFError(f"fanficfare binary not found: {cfg.fanficfare.binary}") from e
    except ValueError as e:  # the --force guard
        raise FFFError(str(e)) from e

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
    if "more recently than Story" in out:
        # The file-date guard fired despite always_overwrite — FFF changed
        # something. Fail loudly rather than pushing an unchanged epub.
        raise FFFError(
            "FanFicFare skipped the write on its file-date guard even though "
            "always_overwrite was set; nothing was updated. " + tail)

    changed = "Do update - epub(" in out
    if not changed and "already contains" not in out:
        # Neither known outcome line appeared; treat cautiously.
        raise FFFError("could not interpret fanficfare output: " + tail)

    return FFFResult(changed=changed, stdout_tail=tail)
