"""HTTP client for calibre's content server.

Routes verified against calibre master srv/ sources (Aug 2026); the payload
shapes are stable enough that this should hold for calibre 6/7/8, but see
PLAN.md for the one-command check against your installed version.

  GET  /ajax/library-info
  GET  /ajax/search/{library_id}?query=&num=&offset=&sort=&sort_order=
  GET  /ajax/book/{book_id}/{library_id}
  GET  /ajax/books/{library_id}?ids=1,2,3
  GET  /ajax/categories/{library_id}
  GET  /get/EPUB/{book_id}/{library_id}
  POST /cdb/set-fields/{book_id}/{library_id}
       body: {"changes": {...}, "loaded_book_ids": []}
       `changes` accepts metadata fields (incl. '#custom' lookup names) AND
       the special key `added_formats`:
       [{"ext": "epub", "data_url": "data:application/epub+zip;base64,<b64>"}]
       — which is how we push the updated epub back with no calibredb binary.

Auth: content server default auth-mode is 'auto' (digest over plain HTTP,
basic behind an SSL proxy). We sniff the WWW-Authenticate challenge once and
cache the right auth object.

Everything here goes through the *running* server on purpose: never touch the
library folder directly while calibre (GUI or server) has it open.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx


class CalibreError(Exception):
    pass


class CalibreClient:
    def __init__(self, base_url: str, library_id: str = "",
                 username: str = "", password: str = "", timeout: float = 120.0):
        self.base = base_url.rstrip("/")
        self.lib = library_id.strip()
        self._auth_choice: httpx.Auth | None = None
        self._creds = (username, password) if username else None
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    # -- plumbing ----------------------------------------------------------

    def _lib_suffix(self) -> str:
        return f"/{self.lib}" if self.lib else ""

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        url = self.base + path
        r = self._client.request(method, url, auth=self._auth_choice, **kw)
        if r.status_code == 401 and self._creds and self._auth_choice is None:
            challenge = r.headers.get("www-authenticate", "")
            if challenge.lower().startswith("digest"):
                self._auth_choice = httpx.DigestAuth(*self._creds)
            else:
                self._auth_choice = httpx.BasicAuth(*self._creds)
            r = self._client.request(method, url, auth=self._auth_choice, **kw)
        if r.status_code >= 400:
            raise CalibreError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r

    # -- reads -------------------------------------------------------------

    def library_info(self) -> dict:
        return self._request("GET", "/ajax/library-info").json()

    def search(self, query: str = "", num: int = 200, offset: int = 0,
               sort: str = "timestamp", sort_order: str = "desc") -> dict:
        params = {"query": query, "num": num, "offset": offset,
                  "sort": sort, "sort_order": sort_order}
        return self._request("GET", f"/ajax/search{self._lib_suffix()}",
                             params=params).json()

    def book(self, book_id: int) -> dict:
        return self._request("GET", f"/ajax/book/{book_id}{self._lib_suffix()}").json()

    def books(self, ids: list[int]) -> dict[str, Any]:
        params = {"ids": ",".join(str(i) for i in ids)}
        return self._request("GET", f"/ajax/books{self._lib_suffix()}",
                             params=params).json()

    def categories(self) -> Any:
        return self._request("GET", f"/ajax/categories{self._lib_suffix()}").json()

    def download_format(self, book_id: int, fmt: str = "EPUB") -> bytes:
        return self._request("GET",
                             f"/get/{fmt}/{book_id}{self._lib_suffix()}").content

    # -- writes ------------------------------------------------------------

    def set_fields(self, book_id: int, changes: dict) -> dict:
        payload = {"changes": changes, "loaded_book_ids": []}
        return self._request("POST",
                             f"/cdb/set-fields/{book_id}{self._lib_suffix()}",
                             json=payload).json()

    def replace_epub(self, book_id: int, epub_bytes: bytes) -> dict:
        b64 = base64.b64encode(epub_bytes).decode("ascii")
        changes = {"added_formats": [{
            "ext": "epub",
            "data_url": "data:application/epub+zip;base64," + b64,
        }]}
        return self.set_fields(book_id, changes)

    # -- helpers -----------------------------------------------------------

    def story_url_from_identifiers(self, book_meta: dict, key: str = "url") -> str | None:
        idents = book_meta.get("identifiers") or {}
        val = idents.get(key)
        if not val:
            return None
        val = str(val)
        # calibre identifier values can't contain ':' so the FFF plugin stores
        # URLs with the scheme colon dropped: "http//site/..." — restore it.
        if val.startswith(("http//", "https//")):
            val = val.replace("//", "://", 1)
        return val
