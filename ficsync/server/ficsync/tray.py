"""Ratchet as a notification-area (system tray) app.

Run with pythonw.exe and there is no console window at all: the service lives
behind a tray icon that can open the UI, show the log, and quit. The console
launcher (`python -m ficsync`) still exists and is the better choice when
something is misbehaving and you want to watch it happen.

Threading note: the tray icon owns the main thread — Windows requires the
message loop to run there — so uvicorn runs on a background thread.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path

import uvicorn

log = logging.getLogger("ficsync")

ICON_PATH = Path(__file__).resolve().parent / "static" / "icon-tray.png"
# How long to keep waiting for a bindable address before giving up. At login
# Tailscale may still be coming up, and a service that dies in that window
# would be invisible: there is no console to print to.
BIND_WAIT_SECONDS = 300
BIND_RETRY_SECONDS = 5


def _url(host: str, port: int) -> str:
    return f"http://{host}:{port}/ui/"


def _resolve_bind_host(cfg, set_status, stop: threading.Event) -> str | None:
    """cfg.bind_host, waiting for Tailscale to come up if it has to.

    Raising here would kill the app silently, so this retries and says what it
    is waiting for in the tooltip instead.
    """
    waited = 0
    while not stop.is_set():
        try:
            return cfg.bind_host
        except ValueError as e:
            if waited >= BIND_WAIT_SECONDS:
                log.error("giving up waiting for an address to bind: %s", e)
                set_status("no address to bind — is Tailscale connected?")
                return None
            if waited == 0:
                log.info("waiting for a bindable address (Tailscale not up yet)")
                set_status("waiting for Tailscale…")
            stop.wait(BIND_RETRY_SECONDS)
            waited += BIND_RETRY_SECONDS
    return None


def run(cfg, app) -> int:
    """Show the tray icon and serve until Quit. Returns a process exit code."""
    import pystray
    from PIL import Image

    stop = threading.Event()
    state = {"host": None, "server": None}

    icon = pystray.Icon("ratchet", Image.open(ICON_PATH), "Ratchet")

    def set_status(text: str) -> None:
        icon.title = f"Ratchet — {text}"

    def open_ui(*_):
        host = state["host"]
        if host:
            webbrowser.open(_url(host, cfg.service.port))

    def show_log(*_):
        path = cfg.data_dir / "ratchet.log"
        try:
            import os
            os.startfile(path)          # noqa: S606 — Windows shell open
        except OSError as e:
            log.error("could not open the log file %s: %s", path, e)

    def quit_ratchet(*_):
        log.info("quitting on request from the tray menu")
        stop.set()
        server = state["server"]
        if server is not None:
            server.should_exit = True
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Open Ratchet", open_ui, default=True,
                         enabled=lambda _: state["host"] is not None),
        pystray.MenuItem("Show log", show_log),
        pystray.Menu.SEPARATOR,
        # Last and behind a separator: quitting takes Ratchet away from the
        # phone and the ereader too, so it should be hard to hit by accident.
        pystray.MenuItem("Quit Ratchet", quit_ratchet),
    )

    def serve() -> None:
        host = _resolve_bind_host(cfg, set_status, stop)
        if host is None:
            return
        state["host"] = host
        set_status(f"http://{host}:{cfg.service.port}")
        log.info("ficsync listening on http://%s:%s  (UI at /ui/)",
                 host, cfg.service.port)
        server = uvicorn.Server(uvicorn.Config(
            app, host=host, port=cfg.service.port, access_log=False,
            log_config=None))     # keep the logging configured by logsetup
        state["server"] = server
        try:
            server.run()
        except Exception as e:                      # noqa: BLE001
            log.exception("the server stopped with an error: %s", e)
        finally:
            if not stop.is_set():
                set_status("stopped")

    set_status("starting…")
    threading.Thread(target=serve, name="uvicorn", daemon=True).start()
    icon.run()          # blocks until quit_ratchet() calls icon.stop()
    stop.set()
    return 0
