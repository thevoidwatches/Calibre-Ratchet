"""The calibre client against a scripted transport: auth negotiation, the
streaming read, and error reporting — no content server involved."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.calibre import CalibreClient, CalibreError  # noqa: E402

BODY = b"PK\x03\x04" + bytes(range(256)) * 40      # 10 KB, several chunks


class FakeCalibre:
    """Digest-protected like the real content server: every request without
    credentials gets a 401 and a challenge, every one with them a 200."""

    def __init__(self, status: int = 200):
        self.status = status
        # Whether each send carried credentials, noted as it arrives: httpx's
        # DigestAuth re-sends the same request object with the header added,
        # so the objects themselves would all look authenticated afterwards.
        self.authenticated: list[bool] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.authenticated.append("authorization" in request.headers)
        if "authorization" not in request.headers:
            return httpx.Response(
                401, headers={"www-authenticate":
                              'Digest realm="calibre", nonce="abc", qop="auth"'})
        if self.status != 200:
            return httpx.Response(self.status, text="calibre says no")
        return httpx.Response(200, content=BODY,
                              headers={"content-type": "application/epub+zip"})


def client(server: FakeCalibre) -> CalibreClient:
    c = CalibreClient("http://calibre.test", "", "user", "pw")
    c._client = httpx.Client(transport=httpx.MockTransport(server))
    return c


def test_first_contact_learns_digest_then_stops_asking():
    server = FakeCalibre()
    c = client(server)
    assert c.download_format(1, "EPUB", "Books") == BODY
    assert c.download_format(2, "EPUB", "Books") == BODY
    # The client's own probe, then DigestAuth's first send (it needs the
    # challenge), then in — and the second book goes straight in, since the
    # challenge is remembered.
    assert server.authenticated == [False, False, True, True]


def test_open_format_streams_the_body_and_carries_the_length():
    c = client(FakeCalibre())
    r = c.open_format(1, "EPUB", "Books")
    assert r.headers["content-length"] == str(len(BODY))
    chunks = list(r.iter_bytes(1024))
    r.close()
    assert len(chunks) > 1 and b"".join(chunks) == BODY


def test_open_format_reports_a_refusal_with_calibre_words():
    c = client(FakeCalibre(status=404))
    with pytest.raises(CalibreError) as e:
        c.open_format(1, "EPUB", "Books")
    assert "404" in str(e.value) and "calibre says no" in str(e.value)


def test_hierarchical_fields_reads_calibres_own_preference():
    """It lives in /interface-data/init, which takes its library as a query
    parameter rather than the /ajax path suffix."""
    seen = {}

    def server(request: httpx.Request) -> httpx.Response:
        if "authorization" not in request.headers:
            return httpx.Response(401, headers={
                "www-authenticate": 'Digest realm="calibre", nonce="a", qop="auth"'})
        seen["url"] = str(request.url)
        return httpx.Response(200, json={
            "categories_using_hierarchy": ["series", "tags", "#genre"],
            "library_id": "Books"})

    c = CalibreClient("http://calibre.test", "", "user", "pw")
    c._client = httpx.Client(transport=httpx.MockTransport(server))
    assert c.hierarchical_fields("Books") == ["series", "tags", "#genre"]
    assert "/interface-data/init" in seen["url"] and "library_id=Books" in seen["url"]


def test_a_calibre_that_reports_no_hierarchy_is_not_an_error():
    def server(request: httpx.Request) -> httpx.Response:
        if "authorization" not in request.headers:
            return httpx.Response(401, headers={
                "www-authenticate": 'Digest realm="calibre", nonce="a", qop="auth"'})
        return httpx.Response(200, json={"library_id": "Books"})   # key absent

    c = CalibreClient("http://calibre.test", "", "user", "pw")
    c._client = httpx.Client(transport=httpx.MockTransport(server))
    assert c.hierarchical_fields("Books") == []


def test_unreachable_server_is_a_calibre_error():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    c = CalibreClient("http://calibre.test", "", "user", "pw")
    c._client = httpx.Client(transport=httpx.MockTransport(down))
    with pytest.raises(CalibreError) as e:
        c.open_format(1, "EPUB", "Books")
    assert "cannot reach calibre" in str(e.value)
