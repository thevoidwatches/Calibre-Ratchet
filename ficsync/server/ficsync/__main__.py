"""`python -m ficsync` — run the service with host/port from config.toml."""

import logging

import uvicorn

from .main import app, cfg

if __name__ == "__main__":
    # The console narrates meaningful events only (ficsync's own log lines:
    # checks, updates, adds, epub sends). The root level stays at WARNING so
    # chatty libraries — httpx logs every outgoing calibre request at INFO —
    # say nothing unless something is wrong; only ficsync's logger runs at
    # INFO. uvicorn's access log (a line per incoming GET) is switched off in
    # the run() call; its error logger still surfaces problems.
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("ficsync").setLevel(logging.INFO)
    host = cfg.bind_host
    print(f"ficsync listening on http://{host}:{cfg.service.port}  (UI at /ui/)")
    uvicorn.run(app, host=host, port=cfg.service.port, access_log=False)
