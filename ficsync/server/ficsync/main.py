"""ficsync HTTP service.

Run:  FICSYNC_CONFIG=/path/to/config.toml uvicorn ficsync.main:app --host ... --port ...
(or just `python -m ficsync` — see __main__.py — which reads host/port from config)

Single-user by design. Handlers are sync (FastAPI runs them in a threadpool);
a per-book lock prevents two updates of the same book racing each other.
"""

from __future__ import annotations

import fnmatch
import os
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import epub as epub_mod
from .calibre import CalibreClient, CalibreError
from .chapterkeys import site_of
from .config import Config, load_config
from .db import Sidecar
from .fff import FFFError, update_epub
from .safety import decide, verify_post_update
from .sites import RemoteStory, SiteFetchError, fetch_remote

CONFIG_PATH = os.environ.get("FICSYNC_CONFIG", "config.toml")

cfg: Config = load_config(CONFIG_PATH)
sidecar = Sidecar(cfg.db_path)
calibre = CalibreClient(
    cfg.calibre.base_url, cfg.calibre.library_id,
    cfg.calibre.username, cfg.calibre.password,
)

app = FastAPI(title="ficsync", version="0.1")


@app.exception_handler(CalibreError)
def _calibre_error_handler(request, exc: CalibreError):
    """Any calibre failure that isn't already handled locally (server down,
    auth wrong, unexpected status) becomes a clean 502 rather than a 500 with
    a traceback — the UI shows the message verbatim."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})

# Book ids repeat across libraries, so locks are keyed by both.
_book_locks: dict[tuple[str, int], threading.Lock] = defaultdict(threading.Lock)
_book_locks_guard = threading.Lock()


def _lock_for(library_id: str, book_id: int) -> threading.Lock:
    with _book_locks_guard:
        return _book_locks[(library_id, book_id)]


def _lib(library: str | None) -> str:
    """Resolve the ?library= query param to a library id.

    Omitted means the configured default, which may itself be "" — the content
    server's own default library.
    """
    return cfg.calibre.library_id if library is None else library.strip()


LIB_Q = Query(default=None, description="calibre library id; omitted = the configured default")


def require_token(authorization: str = Header(default=""),
                  x_api_token: str = Header(default="")) -> None:
    token = x_api_token or authorization.removeprefix("Bearer ").strip()
    if token != cfg.service.auth_token:
        raise HTTPException(401, "bad or missing token")


AUTH = [Depends(require_token)]


# --------------------------------------------------------------------------
# helpers

def _fetch_epub_to_temp(library_id: str, book_id: int) -> tuple[str, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory(prefix=f"ficsync-{book_id}-")
    path = str(Path(tmp.name) / f"{book_id}.epub")
    try:
        data = calibre.download_format(book_id, "EPUB", library_id)
    except CalibreError as e:
        tmp.cleanup()
        raise HTTPException(404, f"could not download EPUB for book {book_id}: {e}")
    Path(path).write_bytes(data)
    return path, tmp


def _story_url(library_id: str, book_id: int, epub_path: str) -> str:
    # Primary: the epub's own dc:source (what fanficfare -u itself will use).
    url = epub_mod.read_story_url(epub_path)
    if url:
        return url
    # Fallback: calibre identifiers (FFF plugin default key 'url').
    try:
        meta = calibre.book(book_id, library_id)
        url = calibre.story_url_from_identifiers(meta, cfg.calibre.identifier_key)
    except CalibreError:
        url = None
    if url:
        return url
    raise HTTPException(
        422, "no story URL: epub has no <dc:source> and calibre identifiers "
             f"have no '{cfg.calibre.identifier_key}' entry — not a "
             "FanFicFare-managed book?")


def _local_chapters(epub_path: str):
    chapters = epub_mod.extract_chapters(epub_path)
    if not chapters:
        raise HTTPException(
            422, "no chapters with embedded chapterurl found in the epub — "
                 "it wasn't produced by FanFicFare, so ficsync can't reason "
                 "about it safely. Update it once with the FFF plugin first.")
    return chapters


def _backup(library_id: str, book_id: int, epub_path: str) -> str:
    bdir = cfg.backups_dir / (library_id or "_default") / str(book_id)
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / (time.strftime("%Y%m%d-%H%M%S") + ".epub")
    dest.write_bytes(Path(epub_path).read_bytes())
    backups = sorted(bdir.glob("*.epub"))
    for old in backups[: max(0, len(backups) - cfg.service.backups_keep)]:
        old.unlink(missing_ok=True)
    return str(dest)


def _genre_of(meta: dict) -> list[str]:
    """The configured genre column's value, always as a list (it may be a
    single-value column, a multi-value one, or absent entirely)."""
    field = cfg.calibre.genre_field
    if not field:
        return []
    value = (meta.get("user_metadata") or {}).get(field, {}).get("#value#")
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [str(value)]


def _decision_payload(decision, remote: RemoteStory) -> dict:
    d = decision.diff
    return {
        "action": decision.action,
        "reasons": decision.reasons,
        "site_status": remote.status,
        "local_count": d.local_count,
        "remote_count": d.remote_count,
        "new_chapters": [c.as_dict() for c in d.new],
        "missing_chapters": [c.as_dict() for c in d.missing],
        "retitled": d.retitled,
        "clean_append": d.is_clean_append,
    }


# --------------------------------------------------------------------------
# endpoints

@app.get("/health")
def health() -> dict:
    out = {"ok": True, "calibre": None, "library_id": cfg.calibre.library_id or "(default)"}
    try:
        info = calibre.library_info()
        out["calibre"] = {"reachable": True,
                          "libraries": list(info.get("library_map", {}).keys())}
    except Exception as e:  # noqa: BLE001 — health endpoint reports, not raises
        out["ok"] = False
        out["calibre"] = {"reachable": False, "error": str(e)[:300]}
    return out


@app.get("/libraries", dependencies=AUTH)
def libraries() -> dict:
    """Every library on the content server, plus which one ficsync defaults to."""
    try:
        return {"libraries": calibre.libraries(), "default": cfg.calibre.library_id}
    except CalibreError as e:
        raise HTTPException(502, str(e))


@app.get("/books", dependencies=AUTH)
def list_books(q: str = Query(default=""), num: int = 50, offset: int = 0,
               library: str | None = LIB_Q) -> dict:
    lib = _lib(library)
    res = calibre.search(query=q, num=num, offset=offset, library_id=lib)
    ids = res.get("book_ids", [])
    metas = calibre.books(ids, library_id=lib) if ids else {}
    books = []
    for bid in ids:
        m = metas.get(str(bid)) or metas.get(bid) or {}
        books.append({
            "id": bid,
            "title": m.get("title"),
            "authors": m.get("authors"),
            "tags": m.get("tags"),
            "genre": _genre_of(m),
            "series": m.get("series"),
            "series_index": m.get("series_index"),
            "formats": m.get("formats"),
        })
    return {"total": res.get("total_num"), "books": books}


@app.get("/books/{book_id}", dependencies=AUTH)
def book_detail(book_id: int, library: str | None = LIB_Q) -> dict:
    lib = _lib(library)
    try:
        meta = calibre.book(book_id, lib)
    except CalibreError as e:
        raise HTTPException(404, str(e))
    return {
        "calibre": meta,
        "library_id": lib,
        "sidecar": sidecar.get_snapshot(lib, book_id),
        "events": sidecar.recent_events(lib, book_id, limit=10),
    }


@app.get("/books/{book_id}/epub", dependencies=AUTH)
def get_epub(book_id: int, library: str | None = LIB_Q) -> Response:
    try:
        data = calibre.download_format(book_id, "EPUB", _lib(library))
    except CalibreError as e:
        raise HTTPException(404, str(e))
    return Response(content=data, media_type="application/epub+zip", headers={
        "Content-Disposition": f'attachment; filename="{book_id}.epub"'})


@app.get("/books/{book_id}/cover", dependencies=AUTH)
def cover(book_id: int, sz: str = "160x213", library: str | None = LIB_Q) -> Response:
    """Cover thumbnail, scaled by calibre rather than by the phone."""
    try:
        data, content_type = calibre.cover(book_id, _lib(library), sz)
    except CalibreError as e:
        raise HTTPException(404, str(e))
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=86400"})


@app.post("/books/{book_id}/check", dependencies=AUTH)
def check(book_id: int, library: str | None = LIB_Q) -> dict:
    lib = _lib(library)
    epub_path, tmp = _fetch_epub_to_temp(lib, book_id)
    with tmp:
        url = _story_url(lib, book_id, epub_path)
        local = _local_chapters(epub_path)
        try:
            remote = fetch_remote(url, cfg)
        except SiteFetchError as e:
            sidecar.log_event(lib, book_id, "check_error", {"url": url, "error": str(e)})
            raise HTTPException(502, str(e))
        decision = decide(local, remote.chapters, cfg.fanficfare.non_append_updates)
    payload = _decision_payload(decision, remote)
    payload["story_url"] = url
    payload["library_id"] = lib
    sidecar.log_event(lib, book_id, "check", {"url": url, "action": decision.action,
                                              "new": len(decision.diff.new),
                                              "missing": len(decision.diff.missing)})
    return payload


@app.post("/books/{book_id}/update", dependencies=AUTH)
def update(book_id: int, dry_run: bool = False,
           library: str | None = LIB_Q) -> dict:
    lib = _lib(library)
    lock = _lock_for(lib, book_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "an update for this book is already running")
    try:
        epub_path, tmp = _fetch_epub_to_temp(lib, book_id)
        with tmp:
            url = _story_url(lib, book_id, epub_path)
            local = _local_chapters(epub_path)
            try:
                remote = fetch_remote(url, cfg)
            except SiteFetchError as e:
                sidecar.log_event(lib, book_id, "update_error",
                                  {"url": url, "error": str(e)})
                raise HTTPException(502, str(e))

            decision = decide(local, remote.chapters, cfg.fanficfare.non_append_updates)
            payload = _decision_payload(decision, remote)
            payload["story_url"] = url
            payload["library_id"] = lib

            if decision.action.startswith("refuse"):
                sidecar.log_event(lib, book_id, "refused", payload)
            if not decision.ok_to_update or dry_run:
                payload["updated"] = False
                payload["dry_run"] = dry_run
                return payload

            backup_path = _backup(lib, book_id, epub_path)
            try:
                fff_result = update_epub(epub_path, cfg)
            except FFFError as e:
                sidecar.log_event(lib, book_id, "fff_error", {"url": url, "error": str(e)})
                raise HTTPException(502, f"fanficfare failed (calibre copy untouched, "
                                         f"backup at {backup_path}): {e}")

            post = epub_mod.extract_chapters(epub_path)
            problems = verify_post_update(remote.chapters, post)
            if problems:
                sidecar.log_event(lib, book_id, "postcheck_failed",
                                  {"url": url, "problems": problems})
                raise HTTPException(
                    500, "post-update verification FAILED; the updated file was "
                         f"NOT pushed to calibre. Backup: {backup_path}. "
                         f"Problems: {problems}")

            try:
                calibre.replace_epub(book_id, Path(epub_path).read_bytes(), lib)
            except CalibreError as e:
                sidecar.log_event(lib, book_id, "push_error", {"url": url, "error": str(e)})
                raise HTTPException(502, f"updated epub verified but pushing to "
                                         f"calibre failed. Backup: {backup_path}. {e}")

            sidecar.save_snapshot(lib, book_id, url, site_of(url),
                                  [c.as_dict() for c in post], baseline="exact")
            payload.update({
                "updated": True,
                "final_chapter_count": len(post),
                "backup": backup_path,
                "fff_output": fff_result.stdout_tail,
            })
            sidecar.log_event(lib, book_id, "updated",
                              {"url": url, "new": len(decision.diff.new),
                               "final": len(post)})
            return payload
    finally:
        lock.release()


@app.post("/books/{book_id}/fields", dependencies=AUTH)
def set_fields(book_id: int, changes: dict = Body(embed=True),
               library: str | None = LIB_Q) -> dict:
    forbidden = {"added_formats", "removed_formats", "cover"}
    if forbidden & set(changes):
        raise HTTPException(400, "format/cover changes are not allowed via this "
                                 "endpoint; formats change only through /update")
    for field_name in changes:
        if not any(fnmatch.fnmatch(field_name, pat)
                   for pat in cfg.calibre.writable_fields):
            raise HTTPException(
                400, f"field '{field_name}' is not in calibre.writable_fields")
    lib = _lib(library)
    try:
        result = calibre.set_fields(book_id, changes, lib)
    except CalibreError as e:
        raise HTTPException(502, str(e))
    sidecar.log_event(lib, book_id, "fields", {"changed": sorted(changes)})
    return result


@app.post("/books/{book_id}/adopt", dependencies=AUTH)
def adopt(book_id: int, library: str | None = LIB_Q) -> dict:
    """(Re)build this book's sidecar snapshot from its current epub."""
    lib = _lib(library)
    epub_path, tmp = _fetch_epub_to_temp(lib, book_id)
    with tmp:
        url = _story_url(lib, book_id, epub_path)
        chapters = _local_chapters(epub_path)
        sidecar.save_snapshot(lib, book_id, url, site_of(url),
                              [c.as_dict() for c in chapters], baseline="exact")
    sidecar.log_event(lib, book_id, "adopted", {"url": url, "chapters": len(chapters)})
    return {"story_url": url, "chapters": len(chapters)}


@app.get("/books/{book_id}/events", dependencies=AUTH)
def events(book_id: int, limit: int = 50,
           library: str | None = LIB_Q) -> list[dict]:
    return sidecar.recent_events(_lib(library), book_id, limit=limit)


@app.get("/categories", dependencies=AUTH)
def categories(library: str | None = LIB_Q):
    """Tag-browser data (tag/custom-column vocabularies) for the chip UI."""
    return calibre.categories(_lib(library))


@app.get("/category-items", dependencies=AUTH)
def category_items(url: str, num: int = 500, offset: int = 0):
    # `url` already carries its own library segment (calibre builds it that
    # way), so no library param is needed here.
    """Proxy one category's item list. `url` must be a category URL exactly as returned by /categories — anything else is rejected so this can't be used as a general proxy into calibre."""
    if not url.startswith("/ajax/category/"):
        raise HTTPException(400, "not a category url from /categories")
    try:
        return calibre.ajax(url, {"num": num, "offset": offset})
    except CalibreError as e:
        raise HTTPException(502, str(e))


# --------------------------------------------------------------------------
# embedded phone/ereader UI — plain static files (index.html + ui.css + small
# JS modules), no build step. The static shell carries no data and needs no
# token; every API call it makes is authenticated normally (token entered
# once, kept in localStorage).

class _RevalidatingStatic(StaticFiles):
    """StaticFiles that always revalidates.

    The UI is edited in place and reloaded on a phone/ereader that may keep the
    old HTML and JS for a long time — which shows up as new features simply not
    existing on the device. `no-cache` still allows a 304 against the ETag, so
    a reload costs a couple of small conditional requests over the tailnet and
    never serves stale code. Audio and other assets revalidate the same way and
    stay byte-cached when unchanged.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.mount("/ui", _RevalidatingStatic(directory=Path(__file__).parent / "static",
                                     html=True),
          name="ui")


@app.get("/ui-config", dependencies=AUTH)
def ui_config() -> dict:
    """What the embedded UI needs to render itself."""
    return {"writable_fields": cfg.calibre.writable_fields,
            "genre_field": cfg.calibre.genre_field}
