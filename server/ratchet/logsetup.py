"""One place that decides where Ratchet's log lines go.

Shared by the console launcher and the tray app so the two cannot drift: the
same events are narrated either way, only the destination differs.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s  %(message)s"
DATEFMT = "%H:%M:%S"
# With a date in it, since a log file outlives a console session.
FILE_FORMAT = "%(asctime)s  %(message)s"
FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 1_000_000
BACKUPS = 3


def configure(log_file: Path | None = None) -> None:
    """Send Ratchet's own INFO lines to the console, or to `log_file`.

    The root logger stays at WARNING so chatty libraries say nothing unless
    something is wrong — httpx logs every outgoing calibre request at INFO,
    and the category walk alone makes hundreds of those.
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    if log_file is None:
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
    else:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FILE_FORMAT, FILE_DATEFMT))

    # Replace rather than append, so calling this twice cannot double every line.
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    logging.getLogger("ratchet").setLevel(logging.INFO)
