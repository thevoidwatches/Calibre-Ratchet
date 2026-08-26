# ficsync — plan and design notes

Personal service that removes the friction in the e-reading loop
(calibre + FanFicFare on the desktop -> Calibre Sync -> Moon+ on an Android
ereader), from the ereader or phone, over Tailscale. One embedded mobile web
app (`/ui`, installable to the home screen; served by the service itself, no
client app to build) provides:

1. **Browse the library with real filtering** — any column; hierarchical
   values matched at any level (filtering on `Science Fiction` also finds
   `Science Fiction.Space Opera`, and vice versa the narrower filter works
   too); multiple filters ANDed; negative filters ("everything on this
   reading list except this tag"). Replaces calibre's content-server web UI,
   which made this miserable on an ereader.
2. **Edit a book's metadata right after reading it** — add/remove tags,
   adjust `#genre`, switch `#readinglist` — no browser trip to calibre's UI,
   no walk to the computer.
3. **Fetch new chapters of a just-finished serial immediately** — with the
   stub-safety invariant below as a hard requirement (kept from the original
   design): updating must never silently lose locally-held chapters.

Explicit non-goals: not a reader (Moon+ stays), not the delivery channel
(Calibre Sync keeps doing ereader downloads), no mass update polling, no
multi-user anything.

Everything in `server/` was written and unit-tested against the facts below.
Confidence labels used throughout:

- **[VERIFIED src: FFF 4.60.0]** — read directly from installed FanFicFare
  4.60.0 source. Re-check only if you run a different version.
- **[VERIFIED src: calibre master]** — read from calibre's `srv/` source,
  master branch, Aug 2026.
- **[VERIFIED live: calibre 9.13]** — exercised against this machine's running
  content server on 2026-08-26, including a create/write/replace/delete cycle
  on a throwaway book.
- **[VERIFY on your setup]** — environment-specific; needs a 2-minute test.
- **[ASSUMPTION]** — believed, not proven.

---

## 1. The safety problem that shaped the update path

FanFicFare's update guard is a **chapter-count comparison**, nothing more.
**[VERIFIED src: FFF 4.60.0, cli.py]**:

- site count == epub count → "already contains N chapters", do nothing
- epub count > site count → warn "more than source", do nothing
- **site count > epub count → proceed**

When it proceeds, it **rebuilds the epub from the site's *current* chapter
list**, reusing your locally cached chapter text wherever the (normalized)
chapter URL still exists on the site, and fetching the rest.
**[VERIFIED src: FFF 4.60.0, cli.py + epubutils.py + base_adapter.py]**

Consequence: if an author stubs 50 chapters and has posted 60 new ones since
you last updated (100 local → 110 on site), the guard passes and the rebuilt
epub contains the site's 110 chapters — **your 50 stubbed chapters are
silently dropped**. Not garbled, not spliced: cleanly, invisibly gone. (This
corrects an earlier working theory that the failure mode was an index-offset
splice; the real mechanism is drop-on-rebuild, which is tidier and therefore
more dangerous — nothing looks wrong afterward.)

The fix is equally clean: compare chapter **identity sets**, not counts,
*before* FFF ever runs.

> **The invariant:** FanFicFare is never invoked while any locally-held
> chapter is absent from the site's current chapter list. `--force` is not
> reachable through this service at all.

This is implementable with high reliability because a FanFicFare epub is
**self-describing**:

- Story URL lives in the OPF as `<dc:source>` — it's what `fanficfare -u`
  itself reads. **[VERIFIED src: FFF 4.60.0, epubutils.get_dcsource_chaptercount]**
- Every chapter XHTML contains `<meta name="chapterurl" content="…"/>` (and
  usually `<meta name="chapterorigtitle" …>`); very old FFF epubs used
  `<a class="chapterurl">`, which FFF still falls back to and so do we.
  **[VERIFIED src: FFF 4.60.0, writer_epub.py + epubutils.py]**

So the **epub is the local source of truth** — extraction survives out-of-band
updates you make from the desktop plugin. The sidecar SQLite DB is history and
audit (especially: every refusal, with the exact chapters at risk), never the
basis for a decision.

### Chapter identity

Titles change; Royal Road URLs embed title slugs that change on retitle. Both
sites carry a stable numeric chapter id in the URL, so identity keys are
`rr:<chapter_id>` / `ao3:<chapter_id>`:

- RR long form `/fiction/<fid>/<slug>/chapter/<cid>/<slug>` and short form
  `/fiction/chapter/<cid>` both reduce to the same id — mirrors FFF's own
  `normalize_chapterurl`, which it applies to *old epub URLs before matching*,
  so retitled chapters are correctly reused, not refetched-and-dropped.
  **[VERIFIED src: FFF 4.60.0, adapter_royalroadcom.py + base_adapter.py L231]**
- AO3 chapter URLs `/works/<wid>/chapters/<cid>` are slug-free and stable;
  the chapter list comes from the story's `/navigate` page, and **one-shots
  also get a real `/chapters/<cid>` URL there**, so single-chapter works need
  no special casing. **[VERIFIED src: FFF 4.60.0, base_otw_adapter.py]**

### Remote chapter lists come from FanFicFare itself

`fanficfare --non-interactive -m -j --no-output <url>` prints story metadata
as JSON including `zchapters`: `[[1, {"title": …, "url": …}], …]` with
adapter-normalized URLs. **[VERIFIED src: FFF 4.60.0, cli.py]** — confirmed
against the CLI help too (`-z` exists specifically to *exclude* zchapters, so
they're included by default).

This kills the custom-scraper idea entirely: the pre-flight and the update use
the *same* parsing code, so they cannot disagree about what the site contains,
and site redesigns are fixed by upgrading FFF, not by patching this project.
It also means AO3 logins/adult flags configured for FFF apply to the
pre-flight automatically.

Cost: a check is a real page hit. The service throttles per-site
(`politeness.min_seconds_between_site_requests`, default 5s) and the intended
usage stays what it is today — one story at a time, when you're about to read
it. FFF's author explicitly warns against mass update-checking; don't wire
this into a poller.

---

## 2. Decision table (implemented in `safety.py`, unit-tested)

Let `L` = ordered local chapter keys (extracted from the epub), `R` = ordered
remote keys (from FFF metadata).

| Condition | Decision | Notes |
|---|---|---|
| `L == R` | `up_to_date` | Retitles (same key, new title) reported informationally |
| `L` is a strict prefix of `R` | `update` | The normal case: clean append |
| `set(L) ⊂ set(R)`, not a prefix | `update` or `refuse_non_append` (config) | Insertion/reorder. Safe per FFF's URL-keyed reuse **[VERIFIED src]** + post-verify; default `allow`, set `refuse` if you want eyes on these |
| `set(L) − set(R) ≠ ∅` | **`refuse_missing`** | Stub/deletion. *Always* refused, even if `len(R) > len(L)` — this is exactly the 50-stubbed/60-added case |
| No chapterurls extractable | error, no action | Non-FFF epub; refresh once via desktop plugin |
| Site fetch fails / story gone | error, no action | Reported; epub untouched |

Full update flow (`POST /books/{id}/update`):

1. Download epub from the content server → temp dir.
2. Extract local chapters from the epub itself.
3. Fetch remote list via FFF metadata call (politeness-throttled).
4. `decide()` per the table. Refusals return HTTP 200 with `updated: false`,
   the reason, and the exact chapter lists — and are written to the audit log.
5. If updating: timestamped **backup** of the pre-update epub
   (`data_dir/backups/<book_id>/`, pruned to `backups_keep`).
6. Run `fanficfare -u` on the temp copy (updates in place —
   **[VERIFIED src: FFF 4.60.0]** `output_filename = arg`). calibre's copy is
   untouched so far.
7. **Post-verify**: re-extract the temp epub; its chapter keys must equal `R`
   exactly, in order. Any mismatch → nothing is pushed, backup path reported.
8. Push the epub back and refresh the sidecar snapshot.

### Pushing the epub back — no calibredb needed

calibre's `/cdb/set-fields/{book_id}/{library_id}` accepts, inside `changes`,
the special key `added_formats`:
`[{"ext": "epub", "data_url": "data:application/epub+zip;base64,<b64>"}]` —
i.e. **format replacement over plain HTTP**, same endpoint as metadata edits.
**[VERIFIED src: calibre master, srv/cdb.py]** This removed the planned
`calibredb --with-library` dependency entirely (it remains a documented
fallback if your calibre predates the feature — see spike S2).

All calibre access goes through the running content server; the library folder
is never touched directly while calibre has it open (hard rule from calibre's
own docs — concurrent direct DB access corrupts).

### calibre endpoints used **[VERIFIED src: calibre master, srv/]**

```
GET  /ajax/library-info
GET  /ajax/search/{lib}?query=&num=&offset=&sort=&sort_order=   → {book_ids,…}
GET  /ajax/book/{id}/{lib}         GET /ajax/books/{lib}?ids=1,2,3
GET  /ajax/categories/{lib}        GET /get/EPUB/{id}/{lib}
POST /cdb/set-fields/{id}/{lib}    body {"changes":{…},"loaded_book_ids":[]}
```

`{lib}` is optional everywhere (`{library_id=None}` in the routes) — empty
string = default library. This setup has four libraries (Books, Fanfiction,
Erotica, Serials), so the library is chosen **per request**: every ficsync
endpoint takes `?library=`, `GET /libraries` lists them, and the UI has a
library selector. Book ids are only unique within a library, so the sidecar
DB and the per-book update locks are keyed by `(library_id, book_id)`.
**[VERIFIED live: calibre 9.13]** Auth default is mode `auto`: **digest** over plain
HTTP, basic behind SSL **[VERIFIED src: calibre master, srv/opts.py]**; the
client sniffs the challenge and handles both.

---

## 3. Threat cases, spelled out

| Scenario | What happens |
|---|---|
| Author stubs 50, adds 60 (the motivating case) | `refuse_missing` with all 50 listed; audit-logged; epub untouched. FFF alone would have silently dropped them. Unit test `test_stub_plus_add_exceeding_count_refused` encodes this exact scenario. |
| Pure stub (site < local) | `refuse_missing` (FFF would also have refused — count guard — but we never even get there). |
| Author retitles chapters | Keys unchanged → invisible to safety. RR slug changes are absorbed by canonical keys, matching FFF's own normalization. Reported as `retitled`. |
| Author inserts an interlude mid-list | Not a clean append. Default: proceed (FFF reuses existing text by URL, inserts the new chapter in site order — verified mechanism + post-verify). Config `refuse` if you want to eyeball these. |
| Site changes between check and update | The update re-runs the full pre-flight itself; `/check` is advisory only. If the site changes between *pre-flight and FFF run* (seconds), FFF's own count guard is still active for shrinkage, the post-verify catches everything else, and nothing is pushed on mismatch. |
| FFF or network dies mid-update | Work happened on a temp copy; calibre copy untouched; backup exists. |
| Push to calibre fails after verify | Updated file exists in temp + backup dir; error message includes the backup path. |
| Story deleted from site entirely | Metadata fetch fails → error, epub untouched. |
| Concurrent update taps on the same book | Per-book lock → HTTP 409. |
| Random person on your tailnet | Bearer token on everything but `/health`. Don't expose beyond the tailnet. |

### Manual recovery when `refuse_missing` fires

The refusal means: *the site no longer has chapters you possess.* The service
will not resolve this automatically, by design. Your options, best first:

1. **Keep the old epub as an archive.** In calibre, duplicate the book or
   rename the old one ("Title — pre-stub archive"), then do a **fresh
   download** of the story as a new book for the go-forward version. You keep
   everything; reading position in Moon+ restarts for the new file.
2. Live with the frozen epub (don't update this book anymore).
3. Advanced: `fanficfare -b/-e` ranged fetches + the EpubMerge calibre plugin
   to hand-build a combined epub. Fiddly; only worth it for favorites.

The audit log (`GET /books/{id}/events`) keeps the refusal with the exact
chapter list, so nothing is ever *silently* at risk.

---

## 4. What's already built (this repo)

```
server/ficsync/
  chapterkeys.py   canonical chapter identity (RR/AO3 patterns mirror FFF's)
  epub.py          dc:source + ordered chapter extraction from FFF epubs
  sites.py         remote list via `fanficfare -m -j --no-output` + throttle
  fff.py           `fanficfare -u` wrapper; interprets FFF's outcome lines;
                   --force not constructible
  safety.py        the decision table; pure functions
  calibre.py       content-server client (digest/basic sniffing, set-fields,
                   base64 format push)
  db.py            sidecar SQLite: snapshots + audit events
  main.py          FastAPI app; per-book locks; backup/verify/push flow;
                   serves the embedded UI + a constrained /category-items proxy
  static/          the phone/ereader web app (index.html + ui.css + small JS
                   modules; no build step): filter-browse (hierarchy-aware,
                   include/exclude), chip metadata editors driven by
                   writable_fields + column datatypes, Check/Update with
                   refusals rendered honestly, epub download. PWA manifest.
scripts/snapshot_baseline.py   local-only baseline + data-quality report
tests/                         19 tests, green (incl. the 50/60 scenario,
                               synthetic-epub extraction in both meta and
                               legacy anchor styles, and app-level API tests)
server/README.md               setup (Windows-first), Tailscale, autostart
android/http-shortcuts.md      fallback client (superseded by /ui)
```

What the tests can't cover from here: anything that needs *your* live calibre,
*your* epubs, and real sites. Hence:

## 5. Build order from here (each step is small)

> **Windows note:** this deploys on the Windows 10 machine that hosts calibre.
> Command equivalents for the steps below: `python` not `python3`; in
> PowerShell use `curl.exe` (bare `curl` aliases Invoke-WebRequest); activate
> the venv with `.venv\Scripts\Activate.ps1`; autostart is a Task Scheduler
> task, not systemd — see `ficsync/server/README.md` for the full Windows setup.

1. **S1 — env sanity (10 min).** venv, `pip install -r requirements.txt`,
   `pytest -q` (should be 13 green), `fanficfare --version`.
2. **S2 — calibre verification — DONE 2026-08-26.** Content server is
   calibre **9.13** on this machine. Verified live: digest auth; four
   libraries; `/ajax/search` with the hierarchy filter syntax below;
   `/ajax/categories` + per-category walking; `/get/EPUB`; and a full
   create → set-fields → **`added_formats` replace** → delete cycle on a
   throwaway book. `added_formats`/`removed_formats` confirmed present in
   9.13's `cdb_set_fields`, so the calibredb fallback is not needed. Also
   confirmed: `/get/EPUB` returns a *metadata-injected* copy (calibre rewrites
   the OPF and adds a cover), but `dc:source` and every `chapterurl` meta
   survive it, so extraction and `fanficfare -u` are unaffected.

   Hierarchy filtering is done client-side as a calibre search, verified
   against the live library: `#genre:"~^Science Fiction(\.|$)"` returns the
   parent *and* its descendants (12), vs `#genre:"=Science Fiction"` for the
   parent alone (6); `not` negates; filters AND together. Non-hierarchical
   columns (authors, series, …) use `="value"` instead, so a dot inside an
   author name is not read as hierarchy.

   The `/ajax/category/<hex>/<lib>` shape is the one thing worth re-checking
   on a calibre upgrade: the hex segment decodes to the real lookup name
   (`Genre` -> `#genre`), rows with `is_category: false` are browse buckets
   rather than columns, and a hierarchical column returns only the values at
   the current node plus a `subcategories` list that has to be walked — the
   full value is the node path plus the item name. The UI walk was checked
   against ground truth: it reproduces all 38 stored `#genre` values exactly.

   ~~**S2 — calibre verification (10 min).**~~ Content server running. Then:
   - `curl -su user:pass --digest http://127.0.0.1:8080/ajax/library-info`
   - download one epub via `/get/EPUB/<id>` and, on a **throwaway test book**,
     verify set-fields: change a tag, then push the same epub back through
     `POST /cdb/set-fields` with `added_formats` (or just run ficsync's
     `/update` on an already-current book — it exercises the same call).
   - **[VERIFY on your setup]**: `added_formats` in set-fields exists in
     calibre master now; if your installed calibre is old enough to lack it,
     the fallback is `calibredb add_format --with-library=http://…#LibID`.
     Check `calibre --version` and test once.
3. **S3 — FFF metadata JSON — DONE 2026-08-26.** FanFicFare **4.60.0** (the
   exact version every `[VERIFIED src]` claim was checked against). A live
   metadata fetch on a Royal Road story returned `zchapters` in the expected
   shape, keys resolved to `rr:<id>`, and `decide()` produced a correct
   `update` / clean-append verdict against the real epub.

   ~~**S3 — FFF metadata JSON (5 min).**~~ On one RR and one AO3 story you own:
   `fanficfare --non-interactive -m -j --no-output <url> | python3 -m json.tool | head -50`
   — confirm `zchapters` appears and URLs look as expected. (Shape is
   **[VERIFIED src]**, this just confirms your version/config behaves.)
4. **S4 — baseline — DONE for Serials 2026-08-26** (91 of 99 books snapshotted;
   `--library Serials`). Remaining libraries are a re-run away:
   `python scripts/snapshot_baseline.py --config config.toml --all-libraries`.

   The 8 exceptions in Serials, and what each needs:
   - `no-chapterurls` (pre-chapterurl-era FFF epubs) — refresh once via the
     desktop FFF plugin before ficsync will update them: **24** (Shrouding the
     Heavens), **87** (A Record of a Mortal's Journey to Immortality).
   - `no dc:source` (not FanFicFare epubs at all — bought/sideloaded) — these
     are not updatable by any tool and simply aren't ficsync's business;
     metadata editing still works on them: **90–94** (Beware of Chicken 1–5),
     **95** (Blue Core).

   Site spread in Serials: 87 Royal Road, 2 AO3, 2 SpaceBattles. The two
   SpaceBattles stories fall back to `url:`-normalized chapter keys (no
   site-specific pattern in `chapterkeys.py`), which is safe as long as
   SpaceBattles post URLs stay stable — worth a `[VERIFY on your setup]` the
   first time one of them updates.
5. **S5 — first supervised update.** Pick a story you know has new chapters.
   `/check`, read the JSON, then `/update?dry_run=true`, then `/update`.
   Confirm in calibre that the epub grew and metadata (tags etc.) survived.
   **[VERIFY on your setup]**: FFF plugin custom columns you rely on are
   populated from the *plugin*, not the epub — a CLI update won't refresh
   plugin-managed columns like "last updated". Decide whether you care; if
   yes, easiest fix is updating those fields from ficsync's own data
   (`remote.raw` has everything) via set-fields — small follow-up.
6. **S6 — insertion live test (optional, one evening).** If you want
   empirical confirmation of the non-append path before trusting
   `non_append_updates = "allow"`: take any story, delete a *middle* chapter
   file + spine entry from a copy of its epub (or set the config to `refuse`
   and just wait until a real interlude-insertion happens), run `/update`,
   confirm the post-verify passes and the chapter text is intact.
7. **S7 — the UI, live.** Service now binds `host = "tailscale"` (resolved at
   startup; currently 100.123.75.89) and needs the one-time inbound firewall
   rule in `server/README.md` before a phone or ereader can connect.
   ~~**S7 — the UI, live.**~~ Open `http://<host>:8484/ui` on the ereader and
   the phone, paste the token once, add to home screen. Verify against the
   real library: the filter picker's column list and value trees populate
   (the `/ajax/categories` and per-category item response *shapes* are the
   one **[VERIFY on your setup]** piece of the UI — parsing is defensive, and
   the picker degrades to typed filter values if a shape surprises us; fix is
   client-side only), hierarchy filtering matches at every level, chip edits
   round-trip, Check/Update renders refusals loudly. `android/http-shortcuts.md`
   is now a fallback, not the plan.
8. **Phase 2 — a native (Expo) client: only if `/ui` proves insufficient.**
   The embedded web app covers the original phase-2 screen list (search →
   detail → chip editors → Check/Update → epub). Reasons that would justify
   going native anyway: SAF folder handoff directly into Moon+'s watched
   folder, offline caching, nicer e-ink rendering than the browser manages.
   Decide after a few weeks of daily `/ui` use.
9. **Phase 3 (optional) — RR watchlist.** RR syndication feed
   (`royalroad.com/fiction/syndication/<id>`, comma-separable, ~10-item cap)
   polled *gently* could badge "has updates" in the phase-2 app. Deliberately
   excluded until the core has run for a while; it's the only feature that
   tempts mass polling.

## 6. Known limitations & maintenance

- **FFF version drift.** The safety design leans on FFF internals that are
  stable and load-bearing for FFF itself (chapterurl metas, dc:source,
  normalize-before-match, zchapters). Pin FFF; on upgrade, re-run S3 and
  `pytest`. If FFF ever changes epub internals, `extract_chapters` is the one
  choke point to fix.
- **calibre version drift.** Endpoints used are old and stable; the youngest
  dependency is `added_formats` in set-fields (S2 verifies; calibredb is the
  fallback).
- **Plugin-managed calibre columns don't auto-refresh** on CLI updates (S5).
- **The service trusts its config file** — it holds the calibre password and
  optionally AO3 creds in personal.ini. Keep it in your user profile on this
  single-user machine (`chmod 600` on Linux), tailnet-only, gitignored, done.
- **Politeness is a floor, not a guarantee.** The throttle spaces requests;
  the real protection is the usage pattern: user-triggered, one story at a
  time. Keep it that way.
