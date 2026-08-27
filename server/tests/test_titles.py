import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.epub import _decode  # noqa: E402
from ratchet.titles import normalize_title  # noqa: E402


def test_entities_unescaped():
    assert normalize_title("Intro &amp; Roses") == "Intro & Roses"
    assert normalize_title("a &lt;b&gt; c") == "a <b> c"


def test_double_escaped_entities():
    assert normalize_title("Intro &amp;amp; Roses") == "Intro & Roses"


def test_whitespace_collapsed():
    assert normalize_title("  a\n\t b  ") == "a b"
    assert normalize_title("") == ""


def test_both_sides_agree_on_apostrophes():
    """The real-world false retitle: epub said &#8217;, site said the char."""
    assert normalize_title("Kayra&#8217;s True Form") == normalize_title("Kayra\u2019s True Form")


def test_decode_cp1252_bytes_without_replacement_chars():
    # 0x92 is a cp1252 right single quote and invalid UTF-8; a plain
    # utf-8/replace decode would yield U+FFFD and fake a retitle.
    raw = b"<html><head><title>Kayra\x92s True Form</title></head></html>"
    assert "\ufffd" not in _decode(raw)
    assert "Kayra" in _decode(raw)


def test_decode_honors_declared_encoding():
    raw = '<?xml version="1.0" encoding="iso-8859-1"?><title>caf\xe9</title>'.encode("iso-8859-1")
    assert "café" in _decode(raw)


def test_decode_prefers_utf8_when_valid():
    raw = "<title>caf\u00e9 \u2019</title>".encode("utf-8")
    assert "café" in _decode(raw) and "\u2019" in _decode(raw)


def test_title_key_folds_typographic_variants():
    from ratchet.titles import title_key
    assert title_key("Kayra\u2019s True Form") == title_key("Kayra's True Form")
    assert title_key("A \u2014 B") == title_key("A - B")
    assert title_key("\u201cQuoted\u201d") == title_key('"Quoted"')


def test_title_key_still_sees_real_retitles():
    from ratchet.titles import title_key
    assert title_key("Chapter One") != title_key("Chapter Two")
