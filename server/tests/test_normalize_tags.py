"""Name fixes reach names, and nothing else.

"X!Y" is an identity compound in the tag scheme — Taylor Hebert wearing
Skitter's — but a '!' is also plain punctuation in an AO3 freeform tag, and
a fix that finds no name to fix must leave the tag exactly as it was.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".scripts"))

from ratchet import configfiles  # noqa: E402


@pytest.fixture
def normalize(monkeypatch):
    # The script reads its table on import; give it this one rather than
    # whatever the local library's tag_scheme.toml holds.
    monkeypatch.setitem(configfiles._scheme_cache,
                        configfiles.path(configfiles.SCHEME_FILE),
                        {"name_fixes": {"Izuki MIdoriya": "Izuku Midoriya",
                                        "Skiter": "Skitter"}})
    sys.modules.pop("normalize_tags", None)
    module = importlib.import_module("normalize_tags")
    yield module
    sys.modules.pop("normalize_tags", None)


def test_a_freeform_tag_with_an_exclamation_mark_is_left_alone(normalize):
    tag = "good for him! good for him"
    assert normalize.fix_tag(tag) == tag


def test_a_compound_with_a_misspelled_name_is_fixed(normalize):
    assert (normalize.fix_tag("Identity.Taylor Hebert ! Skiter")
            == "Identity.Taylor Hebert!Skitter")


def test_a_plain_name_is_fixed_wherever_it_sits(normalize):
    assert (normalize.fix_tag("Powers.Generic.Izuki MIdoriya/Katsuki Bakugo")
            == "Powers.Generic.Izuku Midoriya/Katsuki Bakugo")
