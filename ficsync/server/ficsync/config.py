"""Configuration: a single TOML file, loaded once at startup.

Python 3.11+ (uses stdlib tomllib).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServiceCfg:
    host: str = "127.0.0.1"
    port: int = 8484
    auth_token: str = ""
    data_dir: Path = Path("~/.local/share/ficsync")
    backups_keep: int = 5


@dataclass
class CalibreCfg:
    base_url: str = "http://127.0.0.1:8080"
    library_id: str = ""  # empty = server's default library (endpoints accept it)
    username: str = ""
    password: str = ""
    identifier_key: str = "url"  # FFF plugin's default identifier for the story URL
    # fnmatch patterns for fields writable via POST /books/{id}/fields
    writable_fields: list[str] = field(default_factory=lambda: ["tags", "rating", "#*"])


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


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg = Config(
        service=_section(ServiceCfg, data, "service"),
        calibre=_section(CalibreCfg, data, "calibre"),
        fanficfare=_section(FFFCfg, data, "fanficfare"),
        politeness=_section(PolitenessCfg, data, "politeness"),
    )
    if not cfg.service.auth_token:
        raise ValueError("service.auth_token must be set (any long random string)")
    if cfg.fanficfare.non_append_updates not in ("allow", "refuse"):
        raise ValueError("fanficfare.non_append_updates must be 'allow' or 'refuse'")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    return cfg
