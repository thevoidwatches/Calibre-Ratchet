import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ficsync.epub import Chapter  # noqa: E402
from ficsync.safety import compute_diff, decide, verify_post_update  # noqa: E402


def ch(n: int, title: str | None = None) -> Chapter:
    return Chapter(key=f"rr:{n}", url=f"https://www.royalroad.com/fiction/1/x/chapter/{n}/y",
                   title=title or f"Chapter {n}")


def seq(*ns: int) -> list[Chapter]:
    return [ch(n) for n in ns]


def test_identical_is_up_to_date():
    d = decide(seq(1, 2, 3), seq(1, 2, 3))
    assert d.action == "up_to_date"


def test_clean_append():
    d = decide(seq(1, 2, 3), seq(1, 2, 3, 4, 5))
    assert d.action == "update"
    assert d.diff.is_clean_append
    assert [c.key for c in d.diff.new] == ["rr:4", "rr:5"]


def test_pure_stub_refused():
    d = decide(seq(1, 2, 3, 4, 5), seq(1, 2))
    assert d.action == "refuse_missing"
    assert len(d.diff.missing) == 3


def test_stub_plus_add_exceeding_count_refused():
    """The scenario that motivated this project: 100 local, 50 stubbed,
    60 added -> site has 110 (> 100), FFF's count guard would pass and
    silently drop 50. We must refuse."""
    local = seq(*range(1, 101))
    remote = seq(*(list(range(51, 101)) + list(range(101, 161))))
    assert len(remote) == 110 and len(remote) > len(local)
    d = decide(local, remote)
    assert d.action == "refuse_missing"
    assert {c.key for c in d.diff.missing} == {f"rr:{n}" for n in range(1, 51)}
    assert len(d.diff.new) == 60  # reported so the user knows what they'd gain


def test_insertion_allowed_by_default():
    d = decide(seq(1, 2, 3), seq(1, 2, 99, 3), non_append_updates="allow")
    assert d.action == "update"
    assert not d.diff.is_clean_append


def test_insertion_refused_when_configured():
    d = decide(seq(1, 2, 3), seq(1, 2, 99, 3), non_append_updates="refuse")
    assert d.action == "refuse_non_append"


def test_reorder_flagged():
    diff = compute_diff(seq(1, 2, 3), seq(2, 1, 3))
    assert diff.common_reordered
    assert not diff.new and not diff.missing


def test_retitle_only_is_up_to_date_but_reported():
    local = [ch(1, "Old Name"), ch(2)]
    remote = [ch(1, "New Name"), ch(2)]
    d = decide(local, remote)
    assert d.action == "up_to_date"
    assert d.diff.retitled == [
        {"key": "rr:1", "old_title": "Old Name", "new_title": "New Name"}]


def test_duplicate_keys_fail_loudly():
    with pytest.raises(ValueError):
        compute_diff(seq(1, 1), seq(1, 2))


def test_verify_post_update():
    remote = seq(1, 2, 3)
    assert verify_post_update(remote, seq(1, 2, 3)) == []
    assert verify_post_update(remote, seq(1, 2))            # missing -> problems
    assert verify_post_update(remote, seq(1, 3, 2))         # order -> problems
    assert verify_post_update(remote, seq(1, 2, 3, 4))      # extra -> problems
