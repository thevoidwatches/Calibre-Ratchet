"""Limiting a maintenance script to the books added in a date range.

A run limited to a range still reads the whole library, because some scripts
decide one book by looking at the rest; what the range limits is which books
it reports on and writes — and, where asking costs something, which books it
asks a site about.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".scripts"))

import _tagtool  # noqa: E402


class FakeCalibre:
    """Three books; a date search answers with the ones named at setup."""

    def __init__(self, in_range):
        self.in_range = in_range
        self.queries = []
        self.written = {}
        self.metas = {str(i): {"application_id": i, "title": f"Book {i}",
                               "tags": ["Old"]} for i in (1, 2, 3)}

    def search(self, query, num, library_id):
        self.queries.append(query)
        ids = [1, 2, 3] if not query else list(self.in_range)
        return {"book_ids": ids}

    def books(self, ids, library_id):
        return {str(i): self.metas[str(i)] for i in ids}

    def set_fields(self, book_id, fields, library_id):
        self.written[book_id] = fields


@pytest.fixture
def library(monkeypatch, tmp_path):
    fake = FakeCalibre(in_range=[2])
    cfg = SimpleNamespace(calibre=SimpleNamespace(
        base_url="http://calibre", username="", password=""))
    monkeypatch.setattr(_tagtool, "load_config", lambda path: cfg)
    monkeypatch.setattr(_tagtool, "CalibreClient", lambda *a: fake)
    monkeypatch.setattr(_tagtool, "BACKUPS", tmp_path)
    return fake


def args(*argv):
    return _tagtool.parser("test").parse_args(list(argv))


def test_a_date_is_passed_through_as_calibre_writes_one():
    assert _tagtool.date_query(args()) == ""
    assert _tagtool.date_query(args("--since", "2026-09")) == "date:>=2026-09"
    assert (_tagtool.date_query(args("--since", "2026-09-01", "--until", "2026"))
            == "date:>=2026-09-01 and date:<=2026")


@pytest.mark.parametrize("bad", ["sept", "2026-9", "26-09-01", "",
                                 "2026-09 or tags:Worm"])
def test_anything_but_a_date_is_refused_before_calibre_sees_it(bad):
    """calibre would read a malformed date as a search for something else."""
    with pytest.raises(SystemExit):
        args("--since", bad)


def test_a_range_limits_what_is_written_not_what_is_read(library):
    seen = {}

    def prepare(metas, wanted):
        seen["metas"], seen["wanted"] = set(metas), set(wanted)

    _tagtool.run(args("--since", "2026-09", "--apply"),
                 lambda tags, meta: tags + ["New"], "t", prepare=prepare)

    assert seen == {"metas": {"1", "2", "3"}, "wanted": {"2"}}
    assert library.written == {2: {"tags": ["Old", "New"]}}
    assert "date:>=2026-09" in library.queries


def test_without_a_range_every_book_is_in_it(library):
    seen = {}
    _tagtool.run(args("--apply"), lambda tags, meta: tags + ["New"], "t",
                 prepare=lambda metas, wanted: seen.update(wanted=set(wanted)))
    assert seen["wanted"] == {"1", "2", "3"}
    assert set(library.written) == {1, 2, 3}
    assert library.queries == [""]          # no second, date-limited search


def test_the_report_names_the_range(library, capsys):
    _tagtool.run(args("--until", "2026-08-31"), lambda tags, meta: tags, "t")
    assert "limited to 1 of 3 book(s): date:<=2026-08-31" in capsys.readouterr().out


def test_a_mapping_is_written_whole_and_undone_whole(library, tmp_path, capsys):
    """calibre replaces identifiers as a set, so the undo has to hold them all."""
    library.metas["2"]["identifiers"] = {"isbn": "123"}
    _tagtool.run_multi(
        args("--since", "2026-09", "--apply"),
        lambda meta: {"identifiers": {**(meta.get("identifiers") or {}),
                                      "url": "https://example.org/s/2"}},
        "ids")

    assert library.written == {2: {"identifiers": {
        "isbn": "123", "url": "https://example.org/s/2"}}}
    assert "+ identifiers url:https://example.org/s/2" in capsys.readouterr().out
    [undo_file] = tmp_path.glob("ids-*-1.json")
    undo = json.loads(undo_file.read_text(encoding="utf-8"))
    assert undo == {"2": {"identifiers": {"isbn": "123"}}}


class Clock:
    """Stands in for datetime in _tagtool: hands out the times given, in turn."""

    def __init__(self, *stamps):
        self.stamps = list(stamps)

    def now(self):
        return datetime.strptime(self.stamps.pop(0), "%Y%m%d-%H%M%S")


def test_runs_that_change_as_many_books_keep_their_own_undo(library, tmp_path,
                                                            monkeypatch):
    """Both once wrote t-1.json, and the second run's undo replaced the first's."""
    monkeypatch.setattr(_tagtool, "datetime",
                        Clock("20261025-120000", "20261025-120500"))
    for _ in range(2):
        _tagtool.run(args("--since", "2026-09", "--apply"),
                     lambda tags, meta: tags + ["New"], "t")
        library.metas["2"]["tags"] = ["Old"]        # as it was, so it changes again

    assert sorted(p.name for p in tmp_path.glob("t-*.json")) == [
        "t-20261025-120000-1.json", "t-20261025-120500-1.json"]


def test_an_undo_file_is_never_overwritten_nor_the_books_written_without_one(
        library, tmp_path, monkeypatch):
    monkeypatch.setattr(_tagtool, "datetime",
                        Clock("20261025-120000", "20261025-120000"))
    _tagtool.run(args("--since", "2026-09", "--apply"),
                 lambda tags, meta: tags + ["New"], "t")
    first = (tmp_path / "t-20261025-120000-1.json").read_text(encoding="utf-8")
    library.metas["2"]["tags"] = ["Changed since"]
    library.written.clear()

    with pytest.raises(FileExistsError):
        _tagtool.run(args("--since", "2026-09", "--apply"),
                     lambda tags, meta: tags + ["New"], "t")

    assert (tmp_path / "t-20261025-120000-1.json").read_text(encoding="utf-8") == first
    assert library.written == {}


def test_a_whole_library_mode_refuses_a_range():
    _tagtool.whole_library_only(args(), "--review", "why")     # no range: fine
    with pytest.raises(SystemExit, match="--review covers the whole library: why"):
        _tagtool.whole_library_only(args("--since", "2026-09"), "--review", "why")


def test_the_sites_are_asked_only_about_books_in_the_range(monkeypatch, tmp_path):
    import refresh_site_tags as rst

    asked = []

    def run_fff(argv, cfg):
        asked.append(argv[-1])
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"title": "t", "subject_tags": ["X"]}),
            stderr="")

    monkeypatch.setattr(rst.sites, "run_fff", run_fff)
    monkeypatch.setattr(rst, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(rst, "CFG", SimpleNamespace(
        calibre=SimpleNamespace(identifier_key="url")))
    monkeypatch.setattr(rst, "SITE_TAGS", {})
    metas = {str(i): {"identifiers": {"url": f"https://example.org/s/{i}"}}
             for i in (1, 2, 3)}

    rst.fetch_all(metas, {"2"}, "", pause=0)

    assert asked == ["https://example.org/s/2"]
    assert rst.SITE_TAGS == {"2": ["X"]}
