# config/

Everything here describes **one library**: what its tags are called, which
name is the right spelling, where a character sits in the hierarchy. None of
it is logic, so none of it lives in the `.py` files — the service and the
scripts read it from here, and are the same for everybody.

The files themselves are not tracked, for the same reason: they are your
library, not the project. Each has an `.example` beside it showing the shape:

```
tag_rules.example.txt      tag_scheme.example.toml      ao3_names.example.txt
```

Copy one and edit it, or let the script write the real thing — `stray_tags.py
--review` and `ao3_characters.py --review` both generate their file from your
library, every line pre-filled with what the import would do, so reviewing is
a matter of correcting the exceptions rather than typing the list out.

| file | what it says | who reads it |
|---|---|---|
| `tag_rules.txt` | what to do with a tag a story arrives wearing | the service, on every add; `.scripts/stray_tags.py`, sweeping the backlog |
| `tag_scheme.toml` | this library's own tag vocabulary | `.scripts/normalize_tags.py`, `regroup_tags.py`, `major_characters.py`, `fill_fandom.py` |
| `ao3_names.txt` | which AO3 character tag means which character | `.scripts/ao3_characters.py` |

The service's own settings — where calibre is, the auth token, which columns
it shows — stay in `server/config.toml`, because they are about running the
service rather than about the library's vocabulary.

## Checking them

All three are written by hand, and nearly every slip in them is silent: a
rule naming a column that does not exist is skipped, a root typed
`Progatonist` quietly becomes a second branch beside `Protagonist`, a value
meant as a tag lands in `#genre` because the column named before it carries
on. Nothing errors; the library just ends up subtly wrong. So:

```
cd server
python -m ratchet.configcheck
```

reads all three, compares them with the tags and columns your libraries
really have, and reports each finding with its line. It changes nothing.
`Setup.bat`'s last step shows the same findings in the browser, with buttons
to open each file or start one from its example.

| | |
|---|---|
| **error** | it will not do what it says — the line, rule or file is ignored |
| **warning** | it will do something, probably not what was meant: a likely misspelling of a name you use elsewhere, a value going to the wrong column, a tag ruled on twice, a rule relying on another rule's result (rules do not chain) |
| **note** | worth knowing; nothing is wrong |

## tag_rules.txt

One line per tag, written by `stray_tags.py --review` and edited by you:

```
In-Progress          = Serial.Ongoing      rename, staying in tags
Stubbed              = Serial.Stubbed
Angst                = genre: Angst        move it to a column
Taylor Hebert        = majchar: Worm.Taylor Hebert
FanFiction           = -                   delete it
Last Update*         = -                   ...and by pattern
Some New Thing       =                     (blank) leave it alone for now
```

A name may use `*` and `?` to cover a family of tags whose values keep
changing — FanFicFare emits `Last Update: 2026/09/09`, a different tag every
day. An exact name always beats a pattern, whatever the order in the file.

The left of a colon is either one of the short names configured under
`[calibre]` (`genre`, `fandom`, `majchar`) or a calibre column outright
(`#status: Ongoing`). Moves are additive: the value is added to the column,
never replacing what is there.

**A tag no rule covers is left alone**, so an import can never quietly lose
something nobody has ruled on. It turns up in the next `--review` instead.

## tag_scheme.toml

Tables rather than a list of decisions, so this one is TOML.

- `name_fixes` — one name spelled two ways, or spelled wrongly. Applied to
  every segment of every tag and to each side of an `X!Y` compound.
- `tag_moves` — a tag, and everything filed under it, moves elsewhere.
- `fandom_from_tags` — a tag prefix that settles a book's fandom; longest
  match wins.
- `genres_as_tags` — genres worth carrying over as a tag as well.
- `characters.depths` — which segment counts hold a character, per root.
- `characters.fandom_segment` — roots whose tags name the character's own
  fandom, and where.
- `characters.fandoms` — characters whose fandom nothing else settles.
- `characters.not_characters` — leaves that sit where a character would but
  are not one: groups, factions, mantles worn by someone else.

## ao3_names.txt

Written by `ao3_characters.py --review`. Accents, romanisation, name order
and `(Fandom)` suffixes are handled mechanically; what remains are the two
things that need a person — hero names (`Chat Noir` is Adrien Agreste) and
tags giving only a first name.
