"""ficsync HTTP service.

Run:  FICSYNC_CONFIG=/path/to/config.toml uvicorn ficsync.main:app --host ... --port ...
(or just `python -m ficsync` — see __main__.py — which reads host/port from config)

Single-user by design. Handlers are sync (FastAPI runs them in a threadpool);
a per-book lock prevents two updates of the same book racing each other.
"""

from __future__ import annotations

import fnmatch
import logging
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
from .sites import (RemoteStory, SiteFetchError, download_options,
                    fetch_remote, normalize_story_url, run_fff)

log = logging.getLogger("ficsync")


def _libname(lib: str | None) -> str:
    """Console-friendly name for the default library ('' in config)."""
    return lib or "(default)"


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

# Orders offered by the UI, mapped to calibre sort keys.
#
# calibre accepts a comma-separated list and applies it as a multi-level sort,
# and sorting by "series" already orders by series_index within each series
# (verified against calibre 9.13) — so "authors,series" gives author, then
# series name, then series order, which "authors" alone does not.
SORT_OPTIONS = [
    {"key": "title",    "label": "Title",         "calibre": "title"},
    {"key": "series",   "label": "Series",        "calibre": "series"},
    {"key": "author",   "label": "Author",        "calibre": "authors,series"},
    {"key": "modified", "label": "Last modified", "calibre": "last_modified"},
]
_SORT_BY_KEY = {o["key"]: o["calibre"] for o in SORT_OPTIONS}
DEFAULT_SORT = "modified"


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


def _book_exists(library_id: str, book_id: int) -> bool:
    """Whether calibre still holds this book. calibre answers for a deleted
    id with a null entry rather than an error (verified against 9.13), so a
    real connection failure still raises instead of being read as deletion."""
    got = calibre.books([book_id], library_id)
    return got.get(str(book_id)) is not None


def _blocked_site(url: str | None) -> str | None:
    """The url's site tag when it is on the config blocklist, else None."""
    if not url:
        return None
    site = site_of(url)
    return site if site in cfg.fanficfare.blocked_sites else None


def _reject_blocked(url: str) -> None:
    site = _blocked_site(url)
    if site:
        raise HTTPException(
            403, f"{site} is currently blocked (fanficfare.blocked_sites in "
                 "config.toml — site trouble); remove it there to re-enable")


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
    # Last resort, matching the FFF plugin's behaviour: a recognisable story
    # link inside the book's own HTML (AO3-generated epubs carry one).
    url = epub_mod.find_story_url_in_html(epub_path)
    if url:
        return url
    raise HTTPException(
        422, "no story URL: epub has no <dc:source>, calibre identifiers "
             f"have no '{cfg.calibre.identifier_key}' entry, and no site link "
             "was found inside the book")


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
               sort: str = DEFAULT_SORT, sort_order: str = "desc",
               library: str | None = LIB_Q) -> dict:
    lib = _lib(library)
    # Rejected rather than silently corrected: calibre answers 200 for a sort
    # field it does not recognise, so a typo would quietly return an order
    # nobody asked for.
    if sort not in _SORT_BY_KEY:
        raise HTTPException(400, f"unknown sort '{sort}'; expected one of "
                                 f"{sorted(_SORT_BY_KEY)}")
    if sort_order not in ("asc", "desc"):
        raise HTTPException(400, "sort_order must be 'asc' or 'desc'")
    res = calibre.search(query=q, num=num, offset=offset, library_id=lib,
                         sort=_SORT_BY_KEY[sort], sort_order=sort_order)
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


@app.post("/books/add", dependencies=AUTH)
def add_book(url: str = Body(embed=True), library: str | None = LIB_Q) -> dict:
    """Add a NEW story to the library from its URL: preflight the site,
    download a fresh epub with FanFicFare, verify it against the site's own
    chapter list, then push it into calibre as a new book.

    The new-download analogue of /convert: no local chapters exist yet, so
    there is nothing for the ratchet to protect — the post-verify (fresh epub
    matches the site's chapter list exactly) is the whole guarantee. Two
    duplicate guards: ficsync's own records by story URL, and calibre's
    title+author check on add.
    """
    lib = _lib(library)
    norm = normalize_story_url(url)
    if not norm:
        raise HTTPException(
            422, f"no FanFicFare adapter recognises this URL: {url!r}")
    _reject_blocked(norm)
    existing = sidecar.find_by_url(lib, norm)
    if existing is not None:
        # The record outlives the book: deleting from calibre does not tell
        # ficsync. Confirm the book is really still there before refusing,
        # otherwise a deleted story could never be re-added. A calibre that
        # is merely unreachable raises here rather than reading as deleted.
        if _book_exists(lib, existing):
            raise HTTPException(
                409, f"already in this library as book {existing}")
        log.info("add: book %s (%s) is gone from calibre — dropping its stale "
                 "record and re-adding", existing, _libname(lib))
        sidecar.forget_book(lib, existing)
    log.info("add: %s → checking the site…", norm)
    try:
        remote = fetch_remote(norm, cfg)
    except SiteFetchError as e:
        sidecar.log_event(lib, None, "add_error", {"url": norm, "error": str(e)})
        raise HTTPException(502, str(e))

    log.info('add: "%s" — %d chapters, FanFicFare downloading…',
             remote.title, len(remote.chapters))
    with tempfile.TemporaryDirectory(prefix="ficsync_add_") as tmp:
        fresh_path = str(Path(tmp) / "fresh.epub")
        try:
            proc = run_fff(download_options(cfg) +
                           ["-o", f"output_filename={fresh_path}", norm], cfg)
        except Exception as e:  # timeout, missing binary, --force guard
            raise HTTPException(502, f"download failed: {e}")
        if proc.returncode != 0 or not Path(fresh_path).is_file():
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-800:]
            sidecar.log_event(lib, None, "add_error", {"url": norm, "error": tail})
            raise HTTPException(502, f"download failed: {tail}")

        post = epub_mod.extract_chapters(fresh_path)
        problems = verify_post_update(remote.chapters, post)
        if problems:
            sidecar.log_event(lib, None, "add_postcheck_failed",
                              {"url": norm, "problems": problems})
            raise HTTPException(
                500, "fresh download failed verification; NOT added to "
                     f"calibre. Problems: {problems}")
        epub_bytes = Path(fresh_path).read_bytes()
        try:
            cover = epub_mod.extract_cover(fresh_path)
        except Exception:      # a malformed epub must not cost us the book
            cover = None

    try:
        res = calibre.add_book(epub_bytes, f"{remote.title or 'story'}.epub", lib)
    except CalibreError as e:
        sidecar.log_event(lib, None, "add_error", {"url": norm, "error": str(e)})
        raise HTTPException(502, "epub downloaded and verified but adding to "
                                 f"calibre failed: {e}")
    book_id = res.get("book_id")
    if book_id is None:
        # add_duplicates='n': calibre matched an existing title+author and
        # created nothing.
        raise HTTPException(
            409, "calibre reports a book with this title and author already "
                 f"exists: {res.get('duplicates') or res}")

    # calibre's add-book ignores the epub's own cover, so it is pushed
    # separately. A book without a cover is still a good book: this never
    # fails the add.
    cover_set = False
    if cover:
        try:
            calibre.set_cover(book_id, cover[0], cover[1], lib)
            cover_set = True
        except CalibreError as e:
            log.warning("add: cover for book %s could not be set — %s", book_id, e)

    sidecar.save_snapshot(lib, book_id, norm, site_of(norm),
                          [c.as_dict() for c in post], baseline="exact")
    log.info('add: "%s" → book %s in %s (%d chapters%s)',
             res.get("title") or remote.title, book_id, _libname(lib), len(post),
             "" if cover_set else ", no cover")
    sidecar.log_event(lib, book_id, "added", {"url": norm, "chapters": len(post)})
    return {"book_id": book_id, "title": res.get("title") or remote.title,
            "chapter_count": len(post), "story_url": norm,
            "site_status": remote.status, "cover_set": cover_set}


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
    lib = _lib(library)
    try:
        data = calibre.download_format(book_id, "EPUB", lib)
    except CalibreError as e:
        raise HTTPException(404, str(e))
    log.info("epub: book %s (%s) sent (%.1f MB)",
             book_id, _libname(lib), len(data) / 1e6)
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
        _reject_blocked(url)
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
    log.info('check: book %s (%s) "%s" — local %d / site %d → %s',
             book_id, _libname(lib), remote.title,
             len(local), len(remote.chapters), decision.action)
    sidecar.log_event(lib, book_id, "check", {"url": url, "action": decision.action,
                                              "new": len(decision.diff.new),
                                              "missing": len(decision.diff.missing)})
    return payload


# story-state means downloading and reading the epub, and the UI asks on
# every book-detail open — cache per (library, book) keyed on calibre's
# last_modified, so only a changed book pays for a re-read. In-memory only:
# the process restarting just repopulates it.
_story_state_cache: dict[tuple[str, int], tuple[str, dict]] = {}
_story_state_lock = threading.Lock()


@app.get("/books/{book_id}/story-state", dependencies=AUTH)
def story_state(book_id: int, library: str | None = LIB_Q) -> dict:
    """How this book relates to FanFicFare, driving which actions the UI
    offers: fff_managed -> Check/Update; convertible (a story URL is
    discoverable but the epub is not FFF-made) -> Convert; neither -> none."""
    lib = _lib(library)
    try:
        meta = calibre.book(book_id, lib)
    except CalibreError as e:
        raise HTTPException(404, str(e))
    stamp = str(meta.get("last_modified") or "")
    with _story_state_lock:
        cached = _story_state_cache.get((lib, book_id))
        if cached and cached[0] == stamp:
            return cached[1]

    epub_path, tmp = _fetch_epub_to_temp(lib, book_id)
    with tmp:
        chapters = epub_mod.extract_chapters(epub_path)
        url = (epub_mod.read_story_url(epub_path)
               or calibre.story_url_from_identifiers(meta, cfg.calibre.identifier_key)
               or epub_mod.find_story_url_in_html(epub_path))
    managed = bool(chapters)
    result = {
        "story_url": url,
        "fff_managed": managed,
        "chapter_count": len(chapters),
        "convertible": bool(url) and not managed,
        # The UI hides Check/Update/Convert while the book's site is on the
        # config blocklist; the endpoints refuse independently anyway.
        "site_blocked": bool(_blocked_site(url)),
    }
    with _story_state_lock:
        _story_state_cache[(lib, book_id)] = (stamp, result)
    return result


@app.post("/books/{book_id}/convert", dependencies=AUTH)
def convert(book_id: int, library: str | None = LIB_Q) -> dict:
    """Turn a site-sourced but non-FFF epub (e.g. AO3's own download) into a
    FanFicFare-managed one by fetching a FRESH copy from the site.

    This is the one deliberate exception to the ratchet invariant: the old
    epub has no chapter identities, so a diff against it is impossible — if
    the author deleted chapters since the original download, the fresh copy
    silently lacks them. The old file is backed up first, and the post-verify
    still requires the fresh epub to match the site's chapter list exactly.
    After conversion the book is a normal FFF epub and fully guarded.
    """
    lib = _lib(library)
    lock = _lock_for(lib, book_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "an update for this book is already running")
    try:
        epub_path, tmp = _fetch_epub_to_temp(lib, book_id)
        with tmp:
            if epub_mod.extract_chapters(epub_path):
                raise HTTPException(409, "already FanFicFare-managed — use "
                                         "/update, which can protect chapters")
            url = _story_url(lib, book_id, epub_path)
            _reject_blocked(url)
            try:
                remote = fetch_remote(url, cfg)
            except SiteFetchError as e:
                sidecar.log_event(lib, book_id, "convert_error",
                                  {"url": url, "error": str(e)})
                raise HTTPException(502, str(e))

            log.info('convert: book %s (%s) "%s" — %d chapters, FanFicFare '
                     'downloading a fresh copy…',
                     book_id, _libname(lib), remote.title, len(remote.chapters))
            backup_path = _backup(lib, book_id, epub_path)
            fresh_path = str(Path(tmp.name) / "fresh.epub")
            try:
                proc = run_fff(download_options(cfg) +
                               ["-o", f"output_filename={fresh_path}", url], cfg)
            except Exception as e:  # timeout, missing binary, --force guard
                raise HTTPException(502, f"fresh download failed (calibre copy "
                                         f"untouched, backup at {backup_path}): {e}")
            if proc.returncode != 0 or not Path(fresh_path).is_file():
                tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-800:]
                sidecar.log_event(lib, book_id, "convert_error",
                                  {"url": url, "error": tail})
                raise HTTPException(502, f"fresh download failed (calibre copy "
                                         f"untouched, backup at {backup_path}): {tail}")

            post = epub_mod.extract_chapters(fresh_path)
            problems = verify_post_update(remote.chapters, post)
            if problems:
                sidecar.log_event(lib, book_id, "convert_postcheck_failed",
                                  {"url": url, "problems": problems})
                raise HTTPException(
                    500, "fresh copy failed verification; NOT pushed to "
                         f"calibre. Backup: {backup_path}. Problems: {problems}")

            try:
                calibre.replace_epub(book_id, Path(fresh_path).read_bytes(), lib)
            except CalibreError as e:
                sidecar.log_event(lib, book_id, "push_error",
                                  {"url": url, "error": str(e)})
                raise HTTPException(502, f"fresh epub verified but pushing to "
                                         f"calibre failed. Backup: {backup_path}. {e}")

            sidecar.save_snapshot(lib, book_id, url, site_of(url),
                                  [c.as_dict() for c in post], baseline="exact")
            log.info('convert: book %s "%s" done — now FFF-managed, %d chapters',
                     book_id, remote.title, len(post))
            sidecar.log_event(lib, book_id, "converted",
                              {"url": url, "chapters": len(post)})
            return {"converted": True, "story_url": url,
                    "chapter_count": len(post), "backup": backup_path,
                    "site_status": remote.status}
    finally:
        lock.release()


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
            _reject_blocked(url)
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
                log.info('update: book %s (%s) "%s" — %s, nothing written',
                         book_id, _libname(lib), remote.title, decision.action)
                payload["updated"] = False
                payload["dry_run"] = dry_run
                return payload

            log.info('update: book %s (%s) "%s" — %d new chapters, '
                     'FanFicFare downloading…',
                     book_id, _libname(lib), remote.title, len(decision.diff.new))
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
            log.info('update: book %s "%s" done — %d chapters (was %d)',
                     book_id, remote.title, len(post), len(local))
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
    log.info("fields: book %s (%s) changed %s",
             book_id, _libname(lib), ", ".join(sorted(changes)))
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


MAX_FILTER_NAME = 60
MAX_FILTER_TERMS = 100


def _clean_filter_groups(groups) -> list[dict]:
    """Validate and normalise a saved filter's structure.

    These come back out of the database and are turned into a calibre query by
    the UI, so only the known shape is stored — unrecognised keys are dropped
    rather than round-tripped.
    """
    if not isinstance(groups, list):
        raise HTTPException(400, "groups must be a list")
    cleaned, total = [], 0
    for group in groups:
        terms_in = (group or {}).get("terms") if isinstance(group, dict) else None
        if not isinstance(terms_in, list):
            raise HTTPException(400, "each group needs a 'terms' list")
        terms = []
        for t in terms_in:
            if not isinstance(t, dict):
                raise HTTPException(400, "each term must be an object")
            # An atom is a reference to another saved set, the device-side
            # "Downloaded" pseudo-filter (expanded by the UI from its device
            # catalog), or a term.
            if t.get("downloaded") is True:
                terms.append({"downloaded": True, "exclude": bool(t.get("exclude"))})
                total += 1
                continue
            preset = t.get("preset")
            if preset is not None:
                if not isinstance(preset, str) or not preset.strip():
                    raise HTTPException(400, "'preset' must be a non-empty name")
                terms.append({"preset": preset, "exclude": bool(t.get("exclude"))})
                total += 1
                continue
            field, value = t.get("field"), t.get("value")
            if not isinstance(field, str) or not field.strip():
                raise HTTPException(400, "each term needs a non-empty 'field'")
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(400, "each term needs a non-empty 'value'")
            terms.append({"field": field, "value": value,
                          "exclude": bool(t.get("exclude")),
                          "hierarchical": t.get("hierarchical") is not False})
            total += 1
        if terms:
            cleaned.append({"terms": terms})
    if total > MAX_FILTER_TERMS:
        raise HTTPException(400, f"too many terms (max {MAX_FILTER_TERMS})")
    if not cleaned:
        raise HTTPException(400, "nothing to save: no filter terms")
    return cleaned


@app.get("/filters", dependencies=AUTH)
def list_filters(library: str | None = LIB_Q) -> dict:
    return {"filters": sidecar.list_filters(_lib(library))}


@app.put("/filters/{name}", dependencies=AUTH)
def save_filter(name: str, groups: list = Body(embed=True),
                library: str | None = LIB_Q) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(400, "filter name is required")
    if len(name) > MAX_FILTER_NAME:
        raise HTTPException(400, f"name too long (max {MAX_FILTER_NAME})")
    cleaned = _clean_filter_groups(groups)
    lib = _lib(library)
    # A set that references itself would expand forever. The UI blocks the
    # obvious case, but the check belongs where the data is stored.
    if any(t.get("preset") == name for g in cleaned for t in g["terms"]):
        raise HTTPException(400, f"'{name}' cannot reference itself")
    sidecar.save_filter(lib, name, cleaned)
    return {"name": name, "groups": cleaned}


@app.delete("/filters/{name}", dependencies=AUTH)
def delete_filter(name: str, library: str | None = LIB_Q) -> dict:
    if not sidecar.delete_filter(_lib(library), name.strip()):
        raise HTTPException(404, f"no saved filter named '{name}'")
    return {"deleted": name}


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


@app.get("/apk")
def apk() -> Response:
    """The built Android shell, downloadable from a device's browser.

    Unauthenticated on purpose: a phone browser cannot attach the token header
    to a download, and the APK is just the app binary — it contains no
    secrets (the token is entered inside the app, same as the web UI).
    """
    path = cfg.data_dir / "ratchet.apk"
    if not path.is_file():
        raise HTTPException(404, "no APK deployed; build the shell and copy "
                                 "ratchet.apk into the data directory")
    return Response(
        content=path.read_bytes(),
        media_type="application/vnd.android.package-archive",
        headers={"Content-Disposition": 'attachment; filename="ratchet.apk"',
                 "Cache-Control": "no-cache"},
    )


@app.get("/ui-config", dependencies=AUTH)
def ui_config() -> dict:
    """What the embedded UI needs to render itself."""
    return {"writable_fields": cfg.calibre.writable_fields,
            "genre_field": cfg.calibre.genre_field,
            "sort_options": [{"key": o["key"], "label": o["label"]}
                             for o in SORT_OPTIONS],
            "default_sort": DEFAULT_SORT}
