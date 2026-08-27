import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ficsync.chapterkeys import canonical_key  # noqa: E402
from ficsync import epub  # noqa: E402
from ficsync.epub import extract_chapters, read_story_url  # noqa: E402

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
 <rootfiles><rootfile full-path="OEBPS/content.opf"
  media-type="application/oebps-package+xml"/></rootfiles></container>"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
 <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>Test Serial</dc:title>
  <dc:source>https://www.royalroad.com/fiction/12345/test-serial</dc:source>
 </metadata>
 <manifest>
  <item id="tp" href="title_page.xhtml" media-type="application/xhtml+xml"/>
  <item id="c1" href="file0001.xhtml" media-type="application/xhtml+xml"/>
  <item id="c2" href="file0002.xhtml" media-type="application/xhtml+xml"/>
  <item id="c3" href="file0003.xhtml" media-type="application/xhtml+xml"/>
 </manifest>
 <spine><itemref idref="tp"/><itemref idref="c1"/>
        <itemref idref="c2"/><itemref idref="c3"/></spine>
</package>"""

TITLE_PAGE = "<html><head><title>Test Serial</title></head><body>by A. Author</body></html>"


def chapter_xhtml(url: str, title: str, style: str = "meta") -> str:
    if style == "meta":  # modern FFF: <meta name="chapterurl">
        head = (f'<meta name="chapterurl" content="{url}" />'
                f'<meta name="chapterorigtitle" content="{title}" />'
                f"<title>{title}</title>")
        return f"<html><head>{head}</head><body><h3>{title}</h3>words</body></html>"
    # legacy FFF: <a class="chapterurl">
    return (f"<html><head><title>{title}</title></head>"
            f'<body><h3><a class="chapterurl" href="{url}">{title}</a></h3>'
            f"words</body></html>")


def build_epub(path: Path, style: str = "meta") -> None:
    urls = [
        ("https://www.royalroad.com/fiction/12345/test-serial/chapter/111/one", "1. One"),
        ("https://www.royalroad.com/fiction/12345/test-serial/chapter/222/two", "2. Two"),
        ("https://www.royalroad.com/fiction/12345/test-serial/chapter/333/three", "3. Three"),
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/title_page.xhtml", TITLE_PAGE)
        for i, (u, t) in enumerate(urls, 1):
            zf.writestr(f"OEBPS/file{i:04d}.xhtml", chapter_xhtml(u, t, style))


def test_story_url_and_chapters_modern(tmp_path):
    p = tmp_path / "a.epub"
    build_epub(p, "meta")
    assert read_story_url(str(p)) == "https://www.royalroad.com/fiction/12345/test-serial"
    chs = extract_chapters(str(p))
    assert [c.key for c in chs] == ["rr:111", "rr:222", "rr:333"]
    assert chs[0].title == "1. One"          # title page correctly skipped


def test_chapters_legacy_anchor_style(tmp_path):
    p = tmp_path / "b.epub"
    build_epub(p, "anchor")
    assert [c.key for c in extract_chapters(str(p))] == ["rr:111", "rr:222", "rr:333"]


def test_canonical_keys_slug_and_form_insensitive():
    long1 = "https://www.royalroad.com/fiction/1/old-slug/chapter/777/old-title"
    long2 = "http://royalroad.com/fiction/1/NEW-slug/chapter/777/renamed-title/"
    short = "https://www.royalroad.com/fiction/chapter/777"
    assert canonical_key(long1) == canonical_key(long2) == canonical_key(short) == "rr:777"

    ao3a = "https://archiveofourown.org/works/123/chapters/456"
    ao3b = "http://www.archiveofourown.org/works/123/chapters/456?view_adult=true"
    assert canonical_key(ao3a) == canonical_key(ao3b) == "ao3:456"

    other = "https://forums.example.com/threads/story.1/post-99"
    assert canonical_key(other).startswith("url:")


# --- cover extraction (calibre's add-book ignores the epub's own cover) ------

def _epub_with_cover(path, *, opf_dir="", epub3=False, media="image/jpeg",
                     cover_name="cover.jpg", declare=True):
    """Minimal epub whose OPF may live in a subdirectory, so the relative
    href resolution is actually exercised."""
    opf_path = (opf_dir + "/" if opf_dir else "") + "content.opf"
    meta = "" if epub3 else '<meta name="cover" content="cvr"/>'
    props = ' properties="cover-image"' if epub3 else ""
    item = (f'<item id="cvr" href="{cover_name}" media-type="{media}"{props}/>'
            if declare else "")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   f'<rootfiles><rootfile full-path="{opf_path}" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr(opf_path, f'''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title>
<dc:identifier id="id">x</dc:identifier>{meta}</metadata>
<manifest>{item}</manifest><spine/></package>''')
        if declare:
            z.writestr((opf_dir + "/" if opf_dir else "") + cover_name, b"IMAGEBYTES")


def test_cover_is_extracted_from_an_epub2_meta(tmp_path):
    p = tmp_path / "a.epub"
    _epub_with_cover(p)
    assert epub.extract_cover(str(p)) == (b"IMAGEBYTES", "image/jpeg")


def test_cover_is_extracted_from_an_epub3_manifest_property(tmp_path):
    p = tmp_path / "b.epub"
    _epub_with_cover(p, epub3=True, media="image/png", cover_name="c.png")
    assert epub.extract_cover(str(p)) == (b"IMAGEBYTES", "image/png")


def test_cover_href_resolves_relative_to_the_opf_not_the_zip_root(tmp_path):
    p = tmp_path / "c.epub"
    _epub_with_cover(p, opf_dir="OEBPS")
    assert epub.extract_cover(str(p)) == (b"IMAGEBYTES", "image/jpeg")


def test_no_cover_returns_none_rather_than_raising(tmp_path):
    p = tmp_path / "d.epub"
    _epub_with_cover(p, declare=False)
    assert epub.extract_cover(str(p)) is None
