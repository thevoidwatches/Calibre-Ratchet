"""`python -m ratchet` — run the service with host/port from config.toml.

Two ways to run:

    python  -m ratchet            console, logs to the window (best for debugging)
    pythonw -m ratchet --tray     no window at all, tray icon, logs to a file
"""

import argparse
import sys

import uvicorn

from . import logsetup
from .main import app, cfg

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="ratchet")
    parser.add_argument("--tray", action="store_true",
                        help="run behind a notification-area icon with no "
                             "console window (Windows; needs pystray)")
    args = parser.parse_args()

    if args.tray:
        # pythonw has no usable stdout, so the log has to go to a file.
        logsetup.configure(cfg.data_dir / "ratchet.log")
        from . import tray
        sys.exit(tray.run(cfg, app))

    logsetup.configure()
    host = cfg.bind_host
    print(f"Ratchet listening on http://{host}:{cfg.service.port}  (UI at /ui/)")
    # The access log is off deliberately: it prints a line per request, and the
    # UI polls enough to bury the events worth reading.
    uvicorn.run(app, host=host, port=cfg.service.port, access_log=False)
