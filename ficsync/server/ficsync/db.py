"""Sidecar SQLite store.

Design note: the *epub itself* is the source of truth for what chapters you
have locally (FanFicFare embeds `<meta name="chapterurl">` in every chapter
file, so the epub is self-describing and survives out-of-band updates from the
desktop plugin). This DB is therefore history + audit, not truth:

  - last-known snapshot per book (for drift reporting and the baseline script)
  - an append-only event log, most importantly every REFUSAL with the exact
    list of chapters that would have been lost

Never make update decisions from this table alone; always re-extract from the
current epub.

Every row is keyed by (library_id, book_id): calibre book ids are only unique
*within* a library, and this setup has several (Books / Fanfiction / Serials /
…), so book 99 exists more than once. The empty string means "the content
server's default library".
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
    library_id  TEXT NOT NULL DEFAULT '',
    book_id     INTEGER NOT NULL,
    story_url   TEXT NOT NULL,
    site        TEXT,
    baseline    TEXT NOT NULL DEFAULT 'exact',   -- 'exact' | 'assumed'
    snapshot_at TEXT,
    PRIMARY KEY(library_id, book_id)
);
CREATE TABLE IF NOT EXISTS chapters(
    library_id  TEXT NOT NULL DEFAULT '',
    book_id     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,                -- 1-based position in epub
    chapter_key TEXT NOT NULL,
    url         TEXT,
    title       TEXT,
    PRIMARY KEY(library_id, book_id, seq)
);
CREATE TABLE IF NOT EXISTS events(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    library_id TEXT NOT NULL DEFAULT '',
    book_id    INTEGER,
    kind       TEXT NOT NULL,
    detail     TEXT                              -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_events_book ON events(library_id, book_id, id);
CREATE TABLE IF NOT EXISTS saved_filters(
    library_id TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL,
    groups     TEXT NOT NULL,               -- JSON: [{"terms":[...]}, ...]
    saved_at   TEXT NOT NULL,
    PRIMARY KEY(library_id, name)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Sidecar:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def save_snapshot(self, library_id: str, book_id: int, story_url: str, site: str,
                      chapters: list[dict], baseline: str = "exact") -> None:
        """chapters: ordered [{'key':..., 'url':..., 'title':...}, ...]"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO books(library_id, book_id, story_url, site, baseline, snapshot_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(library_id, book_id) DO UPDATE SET story_url=excluded.story_url, "
                "site=excluded.site, baseline=excluded.baseline, snapshot_at=excluded.snapshot_at",
                (library_id, book_id, story_url, site, baseline, _now()),
            )
            self._conn.execute("DELETE FROM chapters WHERE library_id=? AND book_id=?",
                               (library_id, book_id))
            self._conn.executemany(
                "INSERT INTO chapters(library_id, book_id, seq, chapter_key, url, title) "
                "VALUES(?,?,?,?,?,?)",
                [(library_id, book_id, i + 1, c["key"], c.get("url"), c.get("title"))
                 for i, c in enumerate(chapters)],
            )

    def find_by_url(self, library_id: str, story_url: str) -> int | None:
        """Book id already recorded for this story in this library, if any —
        the duplicate guard for adding by URL. Only sees books ficsync has
        snapshotted (added, checked, or updated through it)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT book_id FROM books WHERE library_id=? AND story_url=?",
                (library_id, story_url)).fetchone()
        return row[0] if row else None

    def get_snapshot(self, library_id: str, book_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT story_url, site, baseline, snapshot_at FROM books "
                "WHERE library_id=? AND book_id=?",
                (library_id, book_id),
            ).fetchone()
            if not row:
                return None
            chapters = self._conn.execute(
                "SELECT chapter_key, url, title FROM chapters "
                "WHERE library_id=? AND book_id=? ORDER BY seq",
                (library_id, book_id),
            ).fetchall()
        return {
            "story_url": row[0], "site": row[1], "baseline": row[2],
            "snapshot_at": row[3],
            "chapters": [{"key": k, "url": u, "title": t} for k, u, t in chapters],
        }

    def log_event(self, library_id: str, book_id: int | None,
                  kind: str, detail: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events(ts, library_id, book_id, kind, detail) VALUES(?,?,?,?,?)",
                (_now(), library_id, book_id, kind, json.dumps(detail, ensure_ascii=False)),
            )

    def recent_events(self, library_id: str, book_id: int | None = None,
                      limit: int = 50) -> list[dict]:
        q = "SELECT ts, library_id, book_id, kind, detail FROM events WHERE library_id=? "
        args: tuple = (library_id,)
        if book_id is not None:
            q += "AND book_id=? "
            args += (book_id,)
        q += "ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        out = []
        for ts, lib, bid, kind, detail in rows:
            try:
                detail = json.loads(detail) if detail else None
            except json.JSONDecodeError:
                pass
            out.append({"ts": ts, "library_id": lib, "book_id": bid,
                        "kind": kind, "detail": detail})
        return out

    # -- saved filters ------------------------------------------------------
    #
    # Kept on the server rather than in each device's localStorage so a set
    # saved on the phone is there on the ereader. Scoped per library because a
    # filter naming '#genre' is meaningless in a library without that column.

    def save_filter(self, library_id: str, name: str, groups: list) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO saved_filters(library_id, name, groups, saved_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(library_id, name) DO UPDATE SET "
                "groups=excluded.groups, saved_at=excluded.saved_at",
                (library_id, name, json.dumps(groups, ensure_ascii=False), _now()),
            )

    def list_filters(self, library_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, groups, saved_at FROM saved_filters "
                "WHERE library_id=? ORDER BY name COLLATE NOCASE",
                (library_id,),
            ).fetchall()
        out = []
        for name, groups, saved_at in rows:
            try:
                parsed = json.loads(groups)
            except json.JSONDecodeError:
                continue
            out.append({"name": name, "groups": parsed, "saved_at": saved_at})
        return out

    def delete_filter(self, library_id: str, name: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM saved_filters WHERE library_id=? AND name=?",
                (library_id, name))
        return cur.rowcount > 0
