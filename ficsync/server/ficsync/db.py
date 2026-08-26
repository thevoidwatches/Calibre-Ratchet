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
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
    book_id     INTEGER PRIMARY KEY,
    story_url   TEXT NOT NULL,
    site        TEXT,
    baseline    TEXT NOT NULL DEFAULT 'exact',   -- 'exact' | 'assumed'
    snapshot_at TEXT
);
CREATE TABLE IF NOT EXISTS chapters(
    book_id     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,                -- 1-based position in epub
    chapter_key TEXT NOT NULL,
    url         TEXT,
    title       TEXT,
    PRIMARY KEY(book_id, seq)
);
CREATE TABLE IF NOT EXISTS events(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    book_id INTEGER,
    kind    TEXT NOT NULL,
    detail  TEXT                                 -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_events_book ON events(book_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Sidecar:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def save_snapshot(self, book_id: int, story_url: str, site: str,
                      chapters: list[dict], baseline: str = "exact") -> None:
        """chapters: ordered [{'key':..., 'url':..., 'title':...}, ...]"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO books(book_id, story_url, site, baseline, snapshot_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(book_id) DO UPDATE SET story_url=excluded.story_url, "
                "site=excluded.site, baseline=excluded.baseline, snapshot_at=excluded.snapshot_at",
                (book_id, story_url, site, baseline, _now()),
            )
            self._conn.execute("DELETE FROM chapters WHERE book_id=?", (book_id,))
            self._conn.executemany(
                "INSERT INTO chapters(book_id, seq, chapter_key, url, title) VALUES(?,?,?,?,?)",
                [(book_id, i + 1, c["key"], c.get("url"), c.get("title"))
                 for i, c in enumerate(chapters)],
            )

    def get_snapshot(self, book_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT story_url, site, baseline, snapshot_at FROM books WHERE book_id=?",
                (book_id,),
            ).fetchone()
            if not row:
                return None
            chapters = self._conn.execute(
                "SELECT chapter_key, url, title FROM chapters WHERE book_id=? ORDER BY seq",
                (book_id,),
            ).fetchall()
        return {
            "story_url": row[0], "site": row[1], "baseline": row[2],
            "snapshot_at": row[3],
            "chapters": [{"key": k, "url": u, "title": t} for k, u, t in chapters],
        }

    def log_event(self, book_id: int | None, kind: str, detail: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events(ts, book_id, kind, detail) VALUES(?,?,?,?)",
                (_now(), book_id, kind, json.dumps(detail, ensure_ascii=False)),
            )

    def recent_events(self, book_id: int | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT ts, book_id, kind, detail FROM events "
        args: tuple = ()
        if book_id is not None:
            q += "WHERE book_id=? "
            args = (book_id,)
        q += "ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        out = []
        for ts, bid, kind, detail in rows:
            try:
                detail = json.loads(detail) if detail else None
            except json.JSONDecodeError:
                pass
            out.append({"ts": ts, "book_id": bid, "kind": kind, "detail": detail})
        return out
