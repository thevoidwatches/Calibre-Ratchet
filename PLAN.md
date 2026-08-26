# ficsync — plan and design notes

Personal service that solves two problems with a calibre + FanFicFare +
Royal Road/AO3 web-serial library, from a phone, over Tailscale:

1. **Update serials remotely without ever losing chapters to stubbing.**
2. **Edit calibre metadata (tags, `#genre`, `#readinglist`) without the
   content-server browser UI.**

Explicit non-goals: not a reader (Moon+ stays), no mass update polling, no
multi-user anything.

Everything in `server/` was written and unit-tested against the facts below.
Confidence labels used throughout:

- **[VERIFIED src: FFF 4.60.0]** — read directly from installed FanFicFare
  4.60.0 source. Re-check only if you run a different version.
- **[VERIFIED src: calibre master]** — read from calibre's `srv/` source,
  master branch, Aug 2026. Your installed calibre may be older; one-command
  checks below.
- **[VERIFY on your setup]** — environment-specific; needs a 2-minute test.
- **[ASSUMPTION]** — believed, not proven.

---

## 1. The problem that shaped the design

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
string = default library. Auth default is mode `auto`: **digest** over plain
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
  main.py          FastAPI app; per-book locks; backup/verify/push flow
scripts/snapshot_baseline.py   local-only baseline + data-quality report
tests/                         13 tests, green (incl. the 50/60 scenario and
                               synthetic-epub extraction, both meta and legacy
                               anchor styles)
server/README.md               setup, systemd, Tailscale
android/http-shortcuts.md      phase-1 phone client
```

What the tests can't cover from here: anything that needs *your* live calibre,
*your* epubs, and real sites. Hence:

## 5. Build order from here (each step is small)

1. **S1 — env sanity (10 min).** venv, `pip install -r requirements.txt`,
   `pytest -q` (should be 13 green), `fanficfare --version`.
2. **S2 — calibre verification (10 min).** Content server running. Then:
   - `curl -su user:pass --digest http://127.0.0.1:8080/ajax/library-info`
   - download one epub via `/get/EPUB/<id>` and, on a **throwaway test book**,
     verify set-fields: change a tag, then push the same epub back through
     `POST /cdb/set-fields` with `added_formats` (or just run ficsync's
     `/update` on an already-current book — it exercises the same call).
   - **[VERIFY on your setup]**: `added_formats` in set-fields exists in
     calibre master now; if your installed calibre is old enough to lack it,
     the fallback is `calibredb add_format --with-library=http://…#LibID`.
     Check `calibre --version` and test once.
3. **S3 — FFF metadata JSON (5 min).** On one RR and one AO3 story you own:
   `fanficfare --non-interactive -m -j --no-output <url> | python3 -m json.tool | head -50`
   — confirm `zchapters` appears and URLs look as expected. (Shape is
   **[VERIFIED src]**, this just confirms your version/config behaves.)
4. **S4 — baseline.** `snapshot_baseline.py --limit 5`, then full library.
   Books flagged `no-chapterurls` are pre-chapterurl-era epubs: refresh each
   once via the desktop FFF plugin (or full re-download) before ficsync will
   touch them.
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
7. **S7 — phone.** `android/http-shortcuts.md`. You're now using it daily.
8. **Phase 2 — the Expo client** (2–3 weekends, when the API feels settled):
   - Screens: search/list (calibre query passthrough) → book detail →
     tag/`#genre`/`#readinglist` chip editors → Check / Update buttons with
     the decision JSON rendered honestly (especially refusals) → "Get epub"
     via SAF into the folder Moon+ watches.
   - Chips autocomplete from `GET /categories` — the anti-`litrpg`/`LitRPG`/
     `lit-rpg` feature that beats the web UI.
   - The app talks **only to ficsync**, never to calibre directly: one auth
     story, one place to absorb calibre endpoint drift.
   - Managed Expo works: no background execution needed. The one fiddly bit
     is SAF folder access for the epub handoff **[ASSUMPTION: workable via
     expo-file-system SAF API — verify early, it shapes the download UX]**.
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
  optionally AO3 creds in personal.ini. `chmod 600`, tailnet-only, done.
- **Politeness is a floor, not a guarantee.** The throttle spaces requests;
  the real protection is the usage pattern: user-triggered, one story at a
  time. Keep it that way.
