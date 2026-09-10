# Maintenance scripts

Occasional jobs against a calibre library, separate from the service. They
talk to the same content server Ratchet does, read the same
`server/config.toml`, and take everything specific to your library from
`config/` — so the scripts themselves are the same for everybody. Run them
from `server/`:

```
cd server
python ../.scripts/backfill_pages.py --library Serials
```

Everything here **reports by default and changes nothing**. A run that would
write says so and stops; add `--apply` to let it. The ones that rewrite
metadata drop a rollback file into `.backups/` naming every previous value,
and take `--rollback <file>` to put it all back.

## What each one is for

| script | what it does | what it reads from `config/` |
|---|---|---|
| `backfill_pages.py` | Makes calibre count the pages of books added before it computed page counts, so sorting by length works. Rewrites each epub with itself; touches no metadata. | — |
| `anthology_tidy.py` | Rebuilds an EpubMerge anthology's contents so it lists episodes rather than one entry per page. Optionally drops a title card repeated on every page. Images pass through untouched. | — |
| `mark_downloaded.py` | Sets a boolean column true on books FanFicFare can update, detected from the epub's `dc:source`, a calibre identifier, or an AO3-generated preface. Only ever sets true. | — |
| `stray_tags.py` | Sweeps up tags the site supplied. The service already applies the rules as books arrive, so this is for the backlog and for tags nobody has ruled on: it rewrites `tag_rules.txt` listing those, for you to decide. | `tag_rules.txt` |
| `refresh_site_tags.py` | Asks the sites what your books are tagged and files that through the same rules an add would, for books that arrived before the rules did. Metadata only — no chapters are fetched and no epub is written. Where a site disagrees with a tag under `exclusive_roots` it reports rather than picks. | `tag_rules.txt` |
| `ao3_characters.py` | Fills a character column from the character tags AO3 authors put on their own works, read out of the epubs. Writes `ao3_names.txt` for you to correct aliases before anything is applied. | `ao3_names.txt` |
| `normalize_tags.py` | Spells every name in every tag the same way — misspellings, name order, bare surnames. | `tag_scheme.toml` → `name_fixes` |
| `regroup_tags.py` | Moves tags and whole branches where they belong, and carries a genre over as a tag where one is missing. | `tag_scheme.toml` → `tag_moves`, `name_fixes`, `genres_as_tags` |
| `major_characters.py` | Fills the character column from the characters already named in tags. | `tag_scheme.toml` → `characters` |
| `fill_fandom.py` | Fills an empty fandom column where the book's own tags already say what it is. | `tag_scheme.toml` → `fandom_from_tags` |
| `omnibuser_sources.py` | Repoints books downloaded from the defunct omnibuser.com at their forum source and re-fetches them. | — |
| `_tagtool.py` | Not a script. The shared library sweep, dry-run report, write and rollback the metadata ones are built on. | — |

## Order

After importing a batch, the tag scripts want running in this order — each
one leaves the tags in the shape the next expects:

```
normalize_tags.py     names spelled consistently
regroup_tags.py       tags in the right branches
refresh_site_tags.py  what the sites say, filed through the rules
stray_tags.py         site tags triaged (--review first, then edit, then apply)
major_characters.py   characters read out of the tags
ao3_characters.py     characters read out of the epubs
fill_fandom.py        fandoms filled from tags
```

## Configuring them

Nothing here hardcodes a column name or a tag root. The columns live in
`server/config.toml`:

```toml
[calibre]
genre_field = "#genre"          # also shown by the service
fandom_field = "#fandom"
majchar_field = "#majchar"

[scripts]
downloaded_field = "#downloaded"
scheme_roots = ["Trope", "Content", "Key Event"]
exclusive_roots = ["Serial"]
```

`scheme_roots` is the list of top-level tag names your own scheme owns. A tag
under any other root is taken to have come from a source site, which is what
`stray_tags.py` triages — so with the list empty that script has no way to
tell your tags from a site's and refuses to run rather than calling your
whole vocabulary stray.

`exclusive_roots` names the roots under which a book holds one value at a
time. A serial is ongoing or finished, not both, but a book can be
`Trope.Progression` and `Trope.Reincarnation` at once — nothing about a tag's
shape says which kind it is, so it has to be stated. `refresh_site_tags.py`
uses it to tell a site that has simply moved on from a decision you made
deliberately: it lists those and changes nothing.

Everything else — the spellings, the moves, the character depths — is in
`config/`. See `config/README.md`.

A script whose column or table is missing says which and stops. None of them
guess, because the guess would be written into whatever answered to it.
