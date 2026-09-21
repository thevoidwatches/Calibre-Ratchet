"""What the wizard asks of this machine: letting the tailnet reach Ratchet,
starting at login, fetching the app, and starting the service.

Kept apart from the web app so that each is a plain function returning a
plain dict, and the parts that only make sense on Windows say so in one
place rather than at every call.

Nothing here asks for administrator rights, and that is a decision rather
than a happy accident. The obvious way to let a phone in is a Windows
Firewall rule, which needs them — and "run this as administrator to open
your firewall" is exactly what a careful person refuses, from a setup tool
they downloaded an hour ago, and they are right to. So Ratchet listens on
this machine alone and Tailscale, which is already trusted with the traffic
and already allowed through the firewall, hands it over locally.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

from ..config import tailscale_exe

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SERVER_DIR.parent
SCRIPTS = SERVER_DIR / "scripts"

# The app asks where its server is when first opened, so one build serves
# everybody and is published once rather than built by each person. GitHub
# redirects "latest" to the newest release by itself.
APK_URL = ("https://github.com/thevoidwatches/Calibre-Ratchet/"
           "releases/latest/download/ratchet.apk")

# Where Ratchet listens when Tailscale is what lets other devices in: this
# machine only, so nothing but Tailscale can reach it from outside.
LOCAL_HOST = "127.0.0.1"

AUTOSTART_TASK = "Ratchet"

WINDOWS = sys.platform == "win32"


def _powershell(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout)


def _said(proc: subprocess.CompletedProcess) -> str:
    """The last thing a program printed — what it has to say for itself."""
    lines = [l.strip() for l in (proc.stdout + "\n" + proc.stderr).splitlines()
             if l.strip()]
    return lines[-1] if lines else ""


# ---- letting the tailnet in --------------------------------------------

def _tailscale(*args: str, timeout: float = 60) -> subprocess.CompletedProcess | None:
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _forward_target(port: int) -> str:
    return f"{LOCAL_HOST}:{port}"


def reach_status(port: int) -> dict:
    """Whether Tailscale is handing this port's traffic to Ratchet.

        known     Tailscale could be asked at all
        enabled   the tailnet's port `port` is forwarded to Ratchet's
        other     ...or is in use for something else, which turning this on
                  would replace
    """
    status = {"known": False, "enabled": False, "other": ""}
    proc = _tailscale("serve", "status", "--json")
    if proc is None or proc.returncode != 0:
        return status
    try:
        config = json.loads(proc.stdout or "{}") or {}
    except ValueError:
        return status
    status["known"] = True
    handler = (config.get("TCP") or {}).get(str(port))
    if isinstance(handler, dict):
        target = str(handler.get("TCPForward") or "")
        if target == _forward_target(port):
            status["enabled"] = True
        else:
            status["other"] = target or "a web server Tailscale is serving"
    return status


def reach_enable(port: int) -> dict:
    """Have Tailscale pass the tailnet's traffic on `port` to Ratchet.

    `--bg` makes it part of Tailscale's own configuration, so it is still
    there after a restart and needs no process of ours kept alive.

    Forwarded as raw TCP rather than through Tailscale's web proxy. Measured
    against each other the two cost the same — about 10 ms a request over a
    direct connection, which is Tailscale carrying the bytes in its own
    process, not the proxying — but the web proxy answers only to the
    machine's name, so an app pointed at the 100.x address gets a 404, and
    forwarding answers to either. Unencrypted HTTP either way, which inside a
    tailnet is already encrypted by Tailscale; HTTPS would need certificates
    switched on in the tailnet's admin console, for nothing gained.
    """
    proc = _tailscale("serve", "--bg", f"--tcp={port}",
                      f"tcp://{_forward_target(port)}")
    if proc is None:
        return {"ok": False, "message": "Tailscale is not installed"}
    status = reach_status(port)
    if status["enabled"]:
        message = "devices on your tailnet can now reach Ratchet"
    else:
        message = _said(proc) or "Tailscale would not set it up"
    return {"ok": status["enabled"], "message": message, **status}


def reach_disable(port: int) -> dict:
    proc = _tailscale("serve", f"--tcp={port}", "off")
    status = reach_status(port)
    return {"ok": not status["enabled"],
            "message": "" if proc is None else _said(proc), **status}


# ---- starting at login -------------------------------------------------

def autostart_status() -> dict:
    if not WINDOWS:
        return {"applicable": False, "enabled": False}
    proc = _powershell(
        "-Command",
        f"if (Get-ScheduledTask -TaskName '{AUTOSTART_TASK}' "
        "-ErrorAction SilentlyContinue) { 'present' } else { 'absent' }",
        timeout=30)
    return {"applicable": True, "enabled": _said(proc) == "present"}


def autostart_set(enabled: bool) -> dict:
    """Add or remove the login task. No administrator rights needed: it is a
    per-user task, which is also all a tray icon can use."""
    if not WINDOWS:
        return {"ok": False, "message": "only set up for Windows; see the "
                                        "README for a systemd unit"}
    args = ["-File", str(SCRIPTS / "install_autostart.ps1")]
    if not enabled:
        args.append("-Remove")
    proc = _powershell(*args)
    status = autostart_status()
    return {"ok": status["enabled"] == enabled, "message": _said(proc), **status}


# ---- the app -----------------------------------------------------------

def apk_status(data_dir: Path) -> dict:
    path = data_dir / "ratchet.apk"
    return {"present": path.is_file(),
            "size": path.stat().st_size if path.is_file() else 0}


def apk_download(data_dir: Path, url: str = APK_URL) -> dict:
    """Fetch the published app into the folder the service serves it from.

    Written beside its destination and renamed into place, so a download that
    dies part-way leaves the old app — or none — rather than half of one for
    a phone to try to install.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "ratchet.apk"
    part = data_dir / "ratchet.apk.part"
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            if r.status_code == 404:
                return {"ok": False, "message":
                        "no app has been published yet — there is no release "
                        "with a ratchet.apk attached"}
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        # Every APK is a zip; an error page saved under the name is not.
        with open(part, "rb") as f:
            if f.read(2) != b"PK":
                part.unlink(missing_ok=True)
                return {"ok": False, "message": "what came back was not an app"}
        part.replace(target)
    except (httpx.HTTPError, OSError) as e:
        part.unlink(missing_ok=True)
        return {"ok": False, "message": f"the download failed: {e}"}
    return {"ok": True, "message": "downloaded", **apk_status(data_dir)}


# ---- the service -------------------------------------------------------

def service_running(host: str, port: int) -> bool:
    """Whether Ratchet — not merely something — answers there."""
    try:
        r = httpx.get(f"http://{host}:{port}/ping", timeout=4)
        return r.status_code == 200 and r.json().get("ratchet") is True
    except (httpx.HTTPError, ValueError):
        return False


def service_start() -> dict:
    """Start Ratchet the way it will start at login — in the notification
    area, no console — so what works now is what works tomorrow."""
    try:
        if WINDOWS:
            subprocess.Popen(["wscript.exe", str(REPO_DIR / "Ratchet.vbs")],
                             cwd=str(REPO_DIR))
        else:
            subprocess.Popen([sys.executable, "-m", "ratchet"],
                             cwd=str(SERVER_DIR), start_new_session=True)
    except OSError as e:
        return {"ok": False, "message": f"could not start it: {e}"}
    return {"ok": True, "message": "starting"}
