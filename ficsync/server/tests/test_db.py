import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ficsync.db import Sidecar  # noqa: E402


def _chs(*keys):
    return [{"key": k, "url": "u/" + k, "title": k} for k in keys]


def test_same_book_id_in_two_libraries_stays_separate(tmp_path):
    """calibre book ids repeat across libraries — book 99 exists in both
    Serials and Fanfiction here, so the sidecar must key on both."""
    sc = Sidecar(tmp_path / "t.sqlite3")
    sc.save_snapshot("Serials", 99, "https://rr/1", "royalroad.com", _chs("rr:1", "rr:2"))
    sc.save_snapshot("Fanfiction", 99, "https://ao3/2", "archiveofourown.org", _chs("ao3:9"))

    s = sc.get_snapshot("Serials", 99)
    f = sc.get_snapshot("Fanfiction", 99)
    assert s["story_url"] == "https://rr/1"
    assert [c["key"] for c in s["chapters"]] == ["rr:1", "rr:2"]
    assert f["story_url"] == "https://ao3/2"
    assert [c["key"] for c in f["chapters"]] == ["ao3:9"]


def test_snapshot_replaces_only_its_own_library(tmp_path):
    sc = Sidecar(tmp_path / "t.sqlite3")
    sc.save_snapshot("A", 1, "u", "s", _chs("k:1", "k:2"))
    sc.save_snapshot("B", 1, "u", "s", _chs("k:9"))
    sc.save_snapshot("A", 1, "u", "s", _chs("k:1"))       # re-snapshot A
    assert len(sc.get_snapshot("A", 1)["chapters"]) == 1
    assert len(sc.get_snapshot("B", 1)["chapters"]) == 1


def test_events_scoped_by_library(tmp_path):
    sc = Sidecar(tmp_path / "t.sqlite3")
    sc.log_event("Serials", 99, "refused", {"why": "stub"})
    sc.log_event("Fanfiction", 99, "updated", {"n": 1})
    ser = sc.recent_events("Serials", 99)
    fic = sc.recent_events("Fanfiction", 99)
    assert [e["kind"] for e in ser] == ["refused"]
    assert [e["kind"] for e in fic] == ["updated"]


def test_missing_snapshot_is_none(tmp_path):
    sc = Sidecar(tmp_path / "t.sqlite3")
    assert sc.get_snapshot("Serials", 12345) is None
