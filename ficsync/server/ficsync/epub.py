"""Read FanFicFare-produced EPUBs without modifying them.

Two facts verified against FanFicFare 4.60.0 source make this reliable:

1. The story URL is stored in the OPF as <dc:source> (epubutils.
   get_dcsource_chaptercount reads it; it's how `fanficfare -u file.epub`
   knows what to fetch).
2. Every chapter XHTML file carries `<meta name="chapterurl" content="..."/>`
   (writer_epub.py), and optionally `<meta name="chapterorigtitle" .../>`.
   Much older FFF epubs used `<a class="chapterurl">` instead; epubutils still
   falls back to that, and so do we.

Files in the spine *without* a chapterurl (title page, update log) are simply
not chapters, which gives us an exact chapter list and count for free.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .chapterkeys import canonical_key
from .titles import normalize_title

_META_URL_RE = re.compile(
    r'<meta\s+name=(["\'])chapterurl\1\s+content=(["\'])(?P<url>[^"\']+)\2', re.I)
_META_ORIGTITLE_RE = re.compile(
    r'<meta\s+name=(["\'])chapterorigtitle\1\s+content=(["\'])(?P<t>[^"\']*)\2', re.I)
_A_URL_RE = re.compile(
    r'<a[^>]+class=(["\'])chapterurl\1[^>]+href=(["\'])(?P<url>[^"\']+)\2', re.I)
_A_URL_RE2 = re.compile(  # attribute order swapped
    r'<a[^>]+href=(["\'])(?P<url>[^"\']+)\1[^>]+class=(["\'])chapterurl\3', re.I)
_TITLE_RE = re.compile(r"<title>(?P<t>.*?)</title>", re.I | re.S)
_XML_DECL_ENC_RE = re.compile(rb"""<\?xml[^>]*encoding=["']([\w.-]+)["']""", re.I)
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset=["']?([\w.-]+)""", re.I)


def _decode(data: bytes) -> str:
    """Decode a chapter document using its own declared encoding.

    EPUB mandates UTF-8/UTF-16, but epubs that have been through other tools
    (or very old FanFicFare output) can carry cp1252 bytes. Blind UTF-8
    decoding turns a curly apostrophe into U+FFFD, which then shows up as a
    phantom "retitled" report on every check.
    """
    head = data[:1024]
    m = _XML_DECL_ENC_RE.search(head) or _META_CHARSET_RE.search(head)
    encodings = []
    if m:
        encodings.append(m.group(1).decode("ascii", "replace"))
    encodings += ["utf-8", "cp1252"]
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")

_NS = {
    "cnt": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class Chapter:
    key: str
    url: str
    title: str

    def as_dict(self) -> dict:
        return {"key": self.key, "url": self.url, "title": self.title}


class EpubReadError(Exception):
    pass


def _opf(zf: zipfile.ZipFile) -> tuple[str, ET.Element]:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
    except KeyError as e:
        raise EpubReadError("not an epub: missing META-INF/container.xml") from e
    rootfile = container.find(".//cnt:rootfile", _NS)
    if rootfile is None or not rootfile.get("full-path"):
        raise EpubReadError("container.xml has no rootfile entry")
    opf_path = rootfile.get("full-path")
    return opf_path, ET.fromstring(zf.read(opf_path))


def read_story_url(epub_path: str) -> str | None:
    """The <dc:source> story URL, or None if absent (non-FFF epub)."""
    with zipfile.ZipFile(epub_path) as zf:
        _, opf = _opf(zf)
        el = opf.find(".//dc:source", _NS)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return None


def extract_chapters(epub_path: str) -> list[Chapter]:
    """Ordered chapters (spine order), identified by embedded chapterurl."""
    chapters: list[Chapter] = []
    with zipfile.ZipFile(epub_path) as zf:
        opf_path, opf = _opf(zf)
        base = posixpath.dirname(opf_path)

        manifest = {}
        for item in opf.findall(".//opf:manifest/opf:item", _NS):
            manifest[item.get("id")] = item.get("href")

        for itemref in opf.findall(".//opf:spine/opf:itemref", _NS):
            href = manifest.get(itemref.get("idref"))
            if not href:
                continue
            path = posixpath.normpath(posixpath.join(base, href)) if base else href
            try:
                data = _decode(zf.read(path))
            except KeyError:
                continue

            m = _META_URL_RE.search(data) or _A_URL_RE.search(data) or _A_URL_RE2.search(data)
            if not m:
                continue  # title page, log page, etc.
            url = m.group("url").strip()

            tm = _META_ORIGTITLE_RE.search(data) or _TITLE_RE.search(data)
            title = normalize_title(tm.group("t")) if tm else ""

            chapters.append(Chapter(key=canonical_key(url), url=url, title=title))
    return chapters
