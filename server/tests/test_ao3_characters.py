"""Which epubs ao3_characters reads a character list out of.

AO3's own download, added straight into calibre, has no identifier saying it
came from AO3, and once calibre has converted it the preface is no longer in
a file called preface.xhtml. Both used to make the script skip the book
without a word; the epub itself now says whether it is AO3's.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".scripts"))

import ao3_characters as ao3  # noqa: E402

CONTAINER = ('<?xml version="1.0"?><container version="1.0" '
             'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
             '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
             '</rootfiles></container>')
OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
       '<manifest>{items}</manifest><spine>{refs}</spine></package>')

# As calibre leaves AO3's preface after converting the book.
AO3_BLOCK = (
    '<dl class="tags">'
    '<dt class="calibre3">Fandoms:</dt><dd class="calibre4">'
    '<a href="https://archiveofourown.org/tags/SPY%20x%20FAMILY">SPY x FAMILY</a></dd>'
    '<dt class="calibre3">Characters:</dt><dd class="calibre4">'
    '<a href="https://archiveofourown.org/tags/Anya%20Forger">Anya Forger</a>, '
    '<a href="https://archiveofourown.org/tags/Loid">Loid Forger | Twilight</a></dd>'
    '</dl>')
# A chapter that happens to use a definition list, on no site in particular.
GLOSSARY = '<dl><dt>Characters:</dt><dd>Anya, Loid</dd></dl>'
# FanFicFare's title page: the story title links to the story.
FFF_PAGE = ('<a href="{url}">Cold War</a><br/>'
            '<b>Characters:</b> Anya Forger, Loid Forger<br/>')


def epub(files, spine=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", OPF.format(
            items="".join(f'<item id="d{i}" href="{n}" '
                          'media-type="application/xhtml+xml"/>'
                          for i, n in enumerate(spine)),
            refs="".join(f'<itemref idref="d{i}"/>' for i in range(len(spine)))))
        for name, text in files.items():
            z.writestr(name, f"<html><body>{text}</body></html>")
    return buf.getvalue()


def test_a_converted_ao3_epub_is_read_from_its_first_documents():
    data = epub({"Cold_War_split_000.xhtml": "<img src='cover.jpg'/>",
                 "Cold_War_split_001.xhtml": AO3_BLOCK,
                 "Cold_War_split_002.xhtml": "Chapter one"},
                spine=["Cold_War_split_000.xhtml", "Cold_War_split_001.xhtml",
                       "Cold_War_split_002.xhtml"])
    assert (ao3.tagged_characters(ao3.parse_epub(data))
            == ["Anya Forger", "Loid Forger | Twilight"])


def test_a_definition_list_with_no_link_to_ao3_is_not_its_preface():
    data = epub({"ch1.xhtml": GLOSSARY}, spine=["ch1.xhtml"])
    assert ao3.parse_epub(data) == {}


def test_the_block_is_looked_for_only_near_the_front():
    spine = [f"d{i}.xhtml" for i in range(ao3.PREFACE_DOCS)] + ["late.xhtml"]
    files = {name: "text" for name in spine} | {"late.xhtml": AO3_BLOCK}
    assert ao3.parse_epub(epub(files, spine=spine)) == {}


def test_fanficfares_title_page_counts_only_for_an_ao3_story():
    ao3_story = epub({"OEBPS/title_page.xhtml": FFF_PAGE.format(
        url="https://archiveofourown.org/works/1")})
    elsewhere = epub({"OEBPS/title_page.xhtml": FFF_PAGE.format(
        url="https://www.fanfiction.net/s/1")})
    assert ao3.tagged_characters(ao3.parse_epub(ao3_story)) == ["Anya Forger",
                                                               "Loid Forger"]
    assert ao3.parse_epub(elsewhere) == {}


def test_a_review_keeps_decisions_about_tags_it_did_not_read(monkeypatch, tmp_path):
    """A review limited to a date range reads only some books; what was
    decided about the others' tags must survive it."""
    review = tmp_path / "ao3_names.txt"
    review.write_text("Bakugou Katsuki = Katsuki Bakugo\n"
                      "Some Group      = -\n"
                      "Undecided       =\n", encoding="utf-8")
    book = {"application_id": 1,
            "user_metadata": {"#fandom": {"#value#": ["Spy x Family"]},
                              "#majchar": {"#value#": []}}}
    monkeypatch.setattr(ao3, "REVIEW", review)
    monkeypatch.setattr(ao3, "FIELD", "#majchar")
    monkeypatch.setattr(ao3, "FANDOM_FIELD", "#fandom")
    monkeypatch.setattr(ao3, "collect", lambda args: (
        {1: ["Anya Forger"]}, {}, {"1": book}))

    ao3.write_review(None)

    decided = ao3.read_review()
    assert decided["Anya Forger"] == "Anya Forger"            # read this run
    assert decided["Bakugou Katsuki"] == "Katsuki Bakugo"     # kept
    assert decided["Some Group"] == "-"                       # kept
    assert decided["Undecided"] == ""                         # kept, still blank


def test_a_book_with_no_link_identifier_is_opened_one_from_elsewhere_is_not():
    def book(i, idents):
        return {"application_id": i, "identifiers": idents}
    metas = {"1": book(1, {"url": "https://archiveofourown.org/works/1"}),
             "2": book(2, {}),
             "3": book(3, {"url": "https://www.fanfiction.net/s/3"}),
             "4": book(4, {"url": "https//archiveofourown.org/works/4"}),
             "5": book(5, {"isbn": "9780000000000"})}
    assert sorted(ao3.ao3_books(metas)) == [1, 2, 4, 5]
