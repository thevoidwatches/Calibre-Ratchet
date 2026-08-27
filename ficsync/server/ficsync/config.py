"""Configuration: a single TOML file, loaded once at startup.

Python 3.11+ (uses stdlib tomllib).
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Tailscale hands out addresses from the CGNAT range 100.64.0.0/10.
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def tailscale_ip() -> str | None:
    """This machine's Tailscale IPv4 address, or None if it isn't on a tailnet."""
    exe = shutil.which("tailscale")
    if exe:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                                 timeout=10).stdout
            for line in out.splitlines():
                line = line.strip()
                if line and ipaddress.ip_address(line) in _TAILSCALE_NET:
                    return line
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    # Fallback: whichever local address sits in the tailnet range.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if ipaddress.ip_address(addr) in _TAILSCALE_NET:
                return addr
    except (OSError, ValueError):
        pass
    return None


def resolve_host(host: str) -> str:
    """Turn a symbolic [service] host into an address to bind.

    "tailscale" is looked up at startup rather than pinned in the config,
    because a tailnet address can change and a stale literal would leave the
    service unable to bind at all.
    """
    if host.strip().lower() != "tailscale":
        return host
    ip = tailscale_ip()
    if not ip:
        raise ValueError(
            'service.host is "tailscale" but no Tailscale IPv4 address was '
            "found — is Tailscale running and connected? Use an explicit IP, "
            'or "0.0.0.0" to listen on every interface.')
    return ip


def _default_data_dir() -> Path:
    # Platform-appropriate app-data location; overridable via [service] data_dir.
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "~/AppData/Local")) / "ficsync"
    return Path("~/.local/share/ficsync")


@dataclass
class ServiceCfg:
    # "tailscale" resolves to this machine's tailnet address at startup.
    host: str = "127.0.0.1"
    port: int = 8484
    auth_token: str = ""
    data_dir: Path = field(default_factory=_default_data_dir)
    backups_keep: int = 5


@dataclass
class CalibreCfg:
    base_url: str = "http://127.0.0.1:8080"
    library_id: str = ""  # empty = server's default library (endpoints accept it)
    username: str = ""
    password: str = ""
    identifier_key: str = "url"  # FFF plugin's default identifier for the story URL
    # Custom column shown beside tags in the book list. Blank to show none.
    genre_field: str = "#genre"
    # fnmatch patterns for fields writable via POST /books/{id}/fields
    writable_fields: list[str] = field(default_factory=lambda: ["title", "tags", "rating", "#*"])


@dataclass
class FFFCfg:
    binary: str = "fanficfare"
    config_file: str = ""  # optional personal.ini passed with -c
    extra_options: list[str] = field(default_factory=list)  # e.g. ["-o", "is_adult=true"]
    # "allow": permit updates where the site inserted/reordered chapters
    #   (safe per FFF 4.60.0 source: old chapter text is reused by
    #   normalized-URL match, and post-verify re-checks the result).
    # "refuse": only permit clean appends; anything else needs manual handling.
    non_append_updates: str = "allow"
    timeout_seconds: int = 1800  # big serials over slow sites take a while
    # Sites temporarily refused for add/check/update/convert (site outages,
    # FFF breakage) — site tags as chapterkeys.site_of returns them, e.g.
    # "archiveofourown.org". The UI hides the buttons for affected books.
    blocked_sites: list[str] = field(default_factory=list)


@dataclass
class PolitenessCfg:
    min_seconds_between_site_requests: float = 5.0


@dataclass
class Config:
    service: ServiceCfg
    calibre: CalibreCfg
    fanficfare: FFFCfg
    politeness: PolitenessCfg

    @property
    def bind_host(self) -> str:
        return resolve_host(self.service.host)

    @property
    def data_dir(self) -> Path:
        return Path(os.path.expanduser(str(self.service.data_dir)))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ficsync.sqlite3"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


def _section(cls, data: dict, name: str):
    raw = dict(data.get(name, {}))
    if name == "service" and "data_dir" in raw:
        raw["data_dir"] = Path(raw["data_dir"])
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"Unknown key(s) in [{name}]: {sorted(unknown)}")
    return cls(**raw)


def _load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, # comments, optional matched quotes. No dependency on python-dotenv for three keys."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


# Secrets can live in a .env file next to config.toml (or real env vars, which win) instead of in config.toml itself.
_ENV_OVERRIDES = [
    ("FICSYNC_AUTH_TOKEN", "service", "auth_token"),
    ("FICSYNC_CALIBRE_USERNAME", "calibre", "username"),
    ("FICSYNC_CALIBRE_PASSWORD", "calibre", "password"),
]


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg = Config(
        service=_section(ServiceCfg, data, "service"),
        calibre=_section(CalibreCfg, data, "calibre"),
        fanficfare=_section(FFFCfg, data, "fanficfare"),
        politeness=_section(PolitenessCfg, data, "politeness"),
    )
    env_file = _load_env_file(Path(path).resolve().parent / ".env")
    for var, section, attr in _ENV_OVERRIDES:
        val = os.environ.get(var) or env_file.get(var, "")
        if val:
            setattr(getattr(cfg, section), attr, val)
    if not cfg.service.auth_token:
        raise ValueError("service.auth_token must be set (any long random string)")
    if cfg.fanficfare.non_append_updates not in ("allow", "refuse"):
        raise ValueError("fanficfare.non_append_updates must be 'allow' or 'refuse'")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    return cfg
