"""Fetch the site's current chapter list — via FanFicFare, not custom scrapers.

`fanficfare --non-interactive -m -j --no-output <url>` prints story metadata as
JSON, including `zchapters`: a list of `[index, {"title":..., "url":..., ...}]`
entries with adapter-normalized chapter URLs (verified in FFF 4.60.0 cli.py).

This means site HTML parsing lives entirely inside FanFicFare — the same code
that will later perform the update — so the pre-flight and the update can never
disagree about what the site contains, and site redesigns are fixed by a FFF
upgrade instead of by editing this project.

Trade-off: one metadata fetch is a real page hit on the source site. The
per-site throttle below keeps a floor between hits; keep using this service
one-story-at-a-time as intended and don't wire it into anything that mass-polls.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass

from .chapterkeys import canonical_key, site_of
from .config import Config
from .epub import Chapter


class SiteFetchError(Exception):
    pass


_throttle_lock = threading.Lock()
_last_hit: dict[str, float] = {}


def _politeness_wait(site: str, min_gap: float) -> None:
    while True:
        with _throttle_lock:
            now = time.monotonic()
            wait = _last_hit.get(site, -1e9) + min_gap - now
            if wait <= 0:
                _last_hit[site] = now
                return
        time.sleep(min(wait, 1.0))


@dataclass
class RemoteStory:
    title: str
    site: str
    status: str          # e.g. "In-Progress" / "Completed" (site-dependent)
    chapters: list[Chapter]
    raw: dict            # full FFF metadata for anything else you want later


def _fff_base_cmd(cfg: Config) -> list[str]:
    cmd = [cfg.fanficfare.binary, "--non-interactive"]
    if cfg.fanficfare.config_file:
        cmd += ["-c", cfg.fanficfare.config_file]
    cmd += list(cfg.fanficfare.extra_options)
    return cmd


def fetch_remote(story_url: str, cfg: Config) -> RemoteStory:
    site = site_of(story_url)
    _politeness_wait(site, cfg.politeness.min_seconds_between_site_requests)

    cmd = _fff_base_cmd(cfg) + ["-m", "-j", "--no-output", story_url]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=cfg.fanficfare.timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise SiteFetchError(f"fanficfare metadata fetch timed out for {story_url}") from e
    except FileNotFoundError as e:
        raise SiteFetchError(f"fanficfare binary not found: {cfg.fanficfare.binary}") from e

    # With -m -j, stdout should be pure JSON; be defensive about stray
    # pre-JSON warnings anyway by parsing from the first '{'.
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        tail = (proc.stderr or out or "").strip()[-800:]
        raise SiteFetchError(f"no JSON from fanficfare (exit {proc.returncode}): {tail}")
    try:
        meta = json.loads(out[brace:])
    except json.JSONDecodeError as e:
        raise SiteFetchError(f"unparseable fanficfare JSON: {e}") from e

    z = meta.get("zchapters")
    if not isinstance(z, list):
        raise SiteFetchError(
            "fanficfare metadata has no zchapters (site adapter problem, or the "
            "story is gone). stderr tail: " + (proc.stderr or "").strip()[-400:]
        )

    chapters: list[Chapter] = []
    for entry in z:
        # entry shape: [index, {"title":..., "url":..., ...}]
        try:
            _, chap = entry
            url = chap["url"]
        except (ValueError, TypeError, KeyError) as e:
            raise SiteFetchError(f"unexpected zchapters entry shape: {entry!r}") from e
        chapters.append(Chapter(
            key=canonical_key(url), url=url,
            title=str(chap.get("title", "")).strip(),
        ))

    return RemoteStory(
        title=str(meta.get("title", "")),
        site=site,
        status=str(meta.get("status", "")),
        chapters=chapters,
        raw=meta,
    )
