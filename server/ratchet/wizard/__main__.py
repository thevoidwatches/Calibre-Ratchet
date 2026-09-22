"""`python -m ratchet.wizard` — open the setup wizard in the browser.

Setup.bat runs this once the packages are installed. It serves one page to
this machine only, and stops when its window is closed or Ctrl+C is pressed.
"""

import argparse
import secrets
import socket
import threading
import webbrowser

import uvicorn

from .app import create_app
from .system import SERVER_DIR


def _free_port() -> int:
    """Any port nobody is using, chosen by the system: the wizard runs for a
    few minutes, and a fixed port would be one more thing to collide with."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="ratchet.wizard")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the address instead of opening it")
    args = parser.parse_args()

    port = _free_port()
    # Made fresh each run and handed only to the tab opened below, in the
    # part of the address a browser never sends anywhere (the fragment).
    key = secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{port}/#{key}"

    print("Ratchet setup is running.  Leave this window open while you use it;")
    print("close it, or press Ctrl+C, when you are done.\n")
    if args.no_browser:
        print(f"    {url}\n")
    else:
        print("It should open in your browser by itself.  If it does not, the")
        print(f"address is:\n\n    {url}\n")
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    uvicorn.run(create_app(SERVER_DIR, key), host="127.0.0.1", port=port,
                log_level="warning")
