# Sound effects

Drop audio files here with these exact base names. The extension may be
`.mp3`, `.ogg`, `.wav`, or `.m4a` — the UI probes for whichever is present, so
you don't have to convert anything.

| Base name | Plays when |
|---|---|
| `success` | an update finished and was pushed to calibre, or a metadata edit saved |
| `refused`  | a safe-refusal: chapters would have been lost, or a non-append update was declined |
| `error`    | anything failed — network, calibre, FanFicFare, post-verify |
| `page-shift` | the whole page changes: opening a book, returning to the list, entering the filter picker |
| `select`   | a smaller move: stepping deeper into the filter picker, opening or closing a collapsible section |
| `tap_01` … `tap_05` | any other button, chip or control — one of the five is chosen at random per press, so repeated presses don't sound mechanical |

Every file is optional; a missing one just means no sound in that case.

Notes:
- Keep them short (under ~2s) and small. They're fetched over the tailnet and
  cached by the browser.
- `mp3` is the safest bet for Android Chrome; `ogg` also works. `wav` is fine
  but larger.
- Mobile browsers block audio until the page has had a user interaction. Since
  every sound here follows a button tap, that requirement is already met; the
  files are also preloaded on your first tap so a chime after a long update
  isn't waiting on a download.
- If a change to the UI doesn't seem to take effect on a device, it is a stale
  cache. The server sends `no-cache` on everything under `/ui`, so a plain
  reload is enough — but a page loaded *before* that header existed may need
  one hard reload (Chrome: long-press reload, or clear the site's data).
- Sound can be toggled off in the app (the speaker button in the header); the
  setting is remembered per device.
