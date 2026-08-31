# Maintenance scripts

One-off and occasional jobs against a calibre library, separate from the
service. They talk to the same content server Ratchet does and read the same
`server/config.toml`, so run them from `server/`:

```
cd server
python ../.scripts/backfill_pages.py --library Serials
```

Everything here **reports by default and changes nothing**. A run that would
write says so and stops; add `--apply` to let it. The ones that rewrite
metadata drop a rollback file into `.backups/` naming every previous value,
and take `--rollback <file>` to put it all back.

## What each one is for

| script | what it does | needs configuring |
|---|---|---|
| `backfill_pages.py` | Makes calibre count the pages of books added before it computed page counts, so sorting by length works. Rewrites each epub with itself; touches no metadata. | no |
| `anthology_tidy.py` | Rebuilds an EpubMerge anthology's contents so it lists episodes rather than one entry per page. Optionally drops a title card repeated on every page. Images pass through untouched. | no |
| `mark_downloaded.py` | Sets a boolean column true on books FanFicFare can update, detected from the epub's `dc:source`, a calibre identifier, or an AO3-generated preface. Only ever sets true. | `downloaded_field` |
| `stray_tags.py` | Triages tags that arrived from source sites rather than your own scheme. Writes `stray_tags.txt` listing each one with what it would do; you edit the right-hand side, then re-run. Decisions are remembered for later imports. | `scheme_roots`, and the columns a decision can send a tag to |
| `ao3_characters.py` | Fills a character column from the character tags AO3 authors put on their own works, read out of the epubs. Writes `ao3_names.txt` for you to correct aliases before anything is applied. | `majchar_field`, `fandom_field` |
| `omnibuser_sources.py` | Repoints books downloaded from the defunct omnibuser.com at their forum source and re-fetches them. Only useful if you have some. | no |
| `_tagtool.py` | Not a script. The shared library sweep, dry-run report, write and rollback that the metadata ones are built on. | — |

## Configuring them

The columns these scripts read and write are named in a `[scripts]` section of
`server/config.toml`. The service ignores that section; it lives there so
there is only one config file to keep in step. See `config.example.toml`:

```toml
[scripts]
fandom_field = "#fandom"          # multi-value text
majchar_field = "#majchar"        # multi-value text
downloaded_field = "#downloaded"  # boolean
scheme_roots = ["Tropes", "Content", "Format"]
```

`scheme_roots` is the list of top-level tag names your own scheme owns. A tag
under any other root is taken to have come from a source site, which is what
`stray_tags.py` sorts out — so with the list empty that script has no way to
tell your tags from a site's and refuses to run rather than calling your
whole vocabulary stray.

A script whose column is left blank says so and stops. None of them guess at
a column name, because the guess would be written into whatever answered to
it.

`genre_field` is shared with the service and lives under `[calibre]`.

## Files these write

`stray_tags.txt` and `ao3_names.txt` are your decisions about your own
library — which tag means what, which character name is an alias of which.
They are not tracked, and both scripts regenerate them from scratch if
missing, keeping any decision already recorded. Rollback files go to
`.backups/`, which is not tracked either.

## Not here

Scripts that encode one particular library's tag taxonomy — renaming its
misspellings, moving its tag roots about, mapping its characters to its
fandoms — are deliberately untracked. They are descriptions of a specific
library rather than tools, and they are listed in `.gitignore` so they can
sit in this folder without being committed.
