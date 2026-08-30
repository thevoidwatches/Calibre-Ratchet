"""The epub endpoint streams calibre's body through and logs what actually
went out — the line a phone-side download failure is diagnosed from."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_api import TOK, client   # noqa: F401  (shares the module-level config)

from ratchet import main as M       # noqa: E402
from ratchet.calibre import CalibreError  # noqa: E402

BODY = bytes(range(256)) * 16       # 4 KB


class FakeStream:
    """What CalibreClient.open_format hands back: headers, chunks, close."""

    def __init__(self, body: bytes, advertised: int | None = None):
        self.body = body
        self.headers = {"content-length": str(len(body) if advertised is None
                                              else advertised)}
        self.closed = False

    def iter_bytes(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def close(self):
        self.closed = True


def serve(monkeypatch, stream):
    monkeypatch.setattr(M, "_EPUB_CHUNK", 1024)     # several chunks per body
    monkeypatch.setattr(M.calibre, "open_format", lambda *a, **k: stream)


def test_body_passes_through_with_its_length(monkeypatch, caplog):
    stream = FakeStream(BODY)
    serve(monkeypatch, stream)
    caplog.set_level(logging.INFO, logger="ratchet")
    r = client.get("/books/7/epub", params={"library": "Books"}, headers=TOK)
    assert r.status_code == 200
    assert r.content == BODY
    assert r.headers["content-length"] == str(len(BODY))
    assert r.headers["content-type"].startswith("application/epub+zip")
    assert 'filename="7.epub"' in r.headers["content-disposition"]
    assert stream.closed
    sent = [rec for rec in caplog.records if rec.getMessage().startswith("epub: book 7")]
    assert len(sent) == 1 and sent[0].levelno == logging.INFO
    assert "sent (0.0 MB in" in sent[0].getMessage()


def test_a_short_body_is_logged_as_cut_off(monkeypatch, caplog):
    """calibre (or the network) dying mid-file must show up in the log as
    such, not as a normal send."""
    stream = FakeStream(BODY, advertised=len(BODY) * 3)
    serve(monkeypatch, stream)
    caplog.set_level(logging.INFO, logger="ratchet")
    try:
        client.get("/books/7/epub", params={"library": "Books"}, headers=TOK)
    except Exception:
        pass    # the test client may object to the short body; the log is the point
    assert stream.closed
    warned = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warned) == 1
    assert "cut off at 0.0 of 0.0 MB" in warned[0].getMessage()


def test_a_missing_format_is_a_404_before_any_body(monkeypatch):
    def refuse(*a, **k):
        raise CalibreError("GET /get/EPUB/7 -> 404: no such format")
    monkeypatch.setattr(M.calibre, "open_format", refuse)
    r = client.get("/books/7/epub", params={"library": "Books"}, headers=TOK)
    assert r.status_code == 404
    assert "no such format" in r.json()["detail"]


def test_the_phone_downloads_natively_with_progress():
    """The shell must never pull a book through the WebView again: the plugin
    streams it to disk, and the page only watches it arrive."""
    js = client.get("/ui/storage.js").text
    assert "downloadFile(" in js and '"X-Api-Token"' in js
    assert "readAsDataURL" not in js and "blobToBase64" not in js
    assert '.rename(' in js and ".part" in js      # never a truncated epub in place
    html = client.get("/ui/").text
    assert 'id="busy"' in html
    actions = client.get("/ui/actions.js").text
    assert actions.count("await downloadToDevice(id, meta)") == 2   # Read and Get
    # Downloads run side by side and lock only their own book's buttons;
    # page-bound operations still lock every page.
    assert "downloads.has(state.bookId)" in actions
    assert "operations.size > 0" in actions
    # The box outlives the page it started on, so every line names its book
    # when the open page is another's — as do the failure messages.
    assert 'whose(d.id, d.title) + "to this device' in actions
    assert "whose(o.id, o.title) + o.text" in actions
    assert actions.count("whose(id, meta.title)") >= 5
    # Relabelled and re-locked the moment a page opens.
    assert "renderBusy();" in actions.split("export async function refreshActions")[1]
