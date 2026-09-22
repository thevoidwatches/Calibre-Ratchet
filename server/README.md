# Ratchet server

Stub-safe FanFicFare updates + calibre metadata editing, over HTTP, for one
user (you), reachable from your phone via Tailscale.

Read `../../PLAN.md` first — it explains the safety model and what was verified
against which sources. This file is just setup.

This deployment runs on **Windows** (the machine that hosts calibre); the
Linux equivalents are kept at the bottom in case it ever moves.

## Prerequisites

- Python **3.11+** on the always-on machine that hosts calibre
- calibre's **content server running** (GUI: Connect/share → Start Content
  server; or `calibre-server --port 8080`). Ratchet only ever talks to the
  running server, never to the library folder directly.
- FanFicFare comes in via requirements.txt — no separate install.

## Setup, the short way (Windows)

Double-click **`Setup.bat`** in the folder above this one. It installs the
Python packages into a folder of their own (`server\.venv`; nothing goes in
system-wide), then opens a setup wizard in your browser, which:

1. checks Tailscale is installed and connected
2. connects to calibre, and offers your libraries and custom columns to
   choose from rather than type
3. writes `config.toml` and `.env` — generating the API token — or, if they
   exist, changes only the lines for what you changed and leaves the rest of
   the file, comments included, exactly as it was (the old one is kept
   beside it as `.bak`)
4. lets your tailnet reach Ratchet (see *Reaching it from your phone*)
5. starts Ratchet, now and at login
6. fetches the Android app and shows a QR code to download it with, the
   address to give it, and the token
7. optionally, reads the hand-written files in `../config/` and says what
   looks wrong in them (see `../config/README.md`) — it changes nothing

**It never asks for administrator rights**, and that is on purpose — see the
next-but-one section. The wizard is a page served to this PC only: it answers
no other machine, wants a key made fresh each run that only the tab it opens
is given, and refuses requests addressed to any name but this machine's. Run
`Setup.bat` again whenever you want to change something.

Everything it does can be done by hand, which is the rest of this file.

## Setup, by hand (Windows / PowerShell)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

# Optional, Windows only: build .venv\Scripts\Ratchet.exe so Task Manager
# lists the service as "Ratchet" rather than "Python". Re-run it after
# recreating the venv or upgrading Python; without it Ratchet.vbs simply
# falls back to pythonw.exe.
python scripts\make_launcher_exe.py

Copy-Item config.example.toml config.toml
# Edit config.toml: auth_token (any long random string), calibre URL.
# calibre creds go in a .env file next to config.toml (both .gitignore'd):
#   RATCHET_CALIBRE_USERNAME=... / RATCHET_CALIBRE_PASSWORD=...
# Two kinds of settings, kept apart:
#   server/config.toml  running the service — where calibre is, the token,
#                       which columns the UI shows and may write
#   ../config/          describing your library — what its tags are called,
#                       which spelling is right, where a character sits.
#                       See ../config/README.md; each file has an .example.

# Sanity + baseline (no fic-site requests; local library only):
python scripts\snapshot_baseline.py --config config.toml --limit 5
python scripts\snapshot_baseline.py --config config.toml --library Serials
python scripts\snapshot_baseline.py --config config.toml --all-libraries

# Run (reads config.toml from the current directory by default):
python -m ratchet
# elsewhere: $env:RATCHET_CONFIG = "C:\path\to\config.toml"; python -m ratchet
```

Smoke test from another terminal. **PowerShell note:** bare `curl` is an alias
for `Invoke-WebRequest` — use `curl.exe` (ships with Windows 10):

```powershell
curl.exe -s http://127.0.0.1:8484/health | python -m json.tool
$TOKEN = "...your token..."
curl.exe -s -H "X-Api-Token: $TOKEN" "http://127.0.0.1:8484/books?q=royalroad&num=5" | python -m json.tool
curl.exe -s -X POST -H "X-Api-Token: $TOKEN" http://127.0.0.1:8484/books/123/check | python -m json.tool
curl.exe -s -X POST -H "X-Api-Token: $TOKEN" "http://127.0.0.1:8484/books/123/update?dry_run=true"
```

## The phone/ereader UI

`http://<host>:8484/ui` — the primary client. Enter the API token once
(stored in that browser's localStorage), then in Chrome: menu → *Add to Home
screen* for an app-like icon. Do this on both the phone and the Android
ereader — the whole loop (finish book in Moon+ → retag / switch reading list
→ fetch new chapters → re-sync via Calibre Sync) then stays on one device.

What it does:

- **Pick a library**: the selector in the header lists every library on the
  content server (Books / Fanfiction / Erotica / Serials here). Each device
  reopens on whichever library it last used; with nothing remembered it opens
  on `[calibre] library_id` from config.toml, or the content server's own
  default library (Books) when that is blank. Book ids repeat across libraries, so everything —
  search, edits, updates, the audit log — is scoped to the selected one.
- **Browse/filter**: tap *+ filter* → column → value. Hierarchical columns
  (`#genre`, and `tags` here too) render as a tree; picking `Science Fiction`
  matches `Science Fiction.Space Opera` as well. Flat columns (authors,
  series) match exactly, so a dot in a name isn't treated as hierarchy.
  Filters AND together; *exclude* mode blocks a value (`not tags:...`). The
  text box additionally takes raw calibre search syntax and combines with the
  filters.
- **Edit metadata**: chip editors for `tags` and any custom column matching
  `writable_fields` (single-value columns like `#readinglist` are exclusive
  chips; multi-value ones get add/remove chips with autocomplete).
- **Check / Update**: the safe-update flow with refusals displayed loudly,
  including the exact chapters that would have been lost.
- **Get EPUB**: browser download (Calibre Sync remains the normal delivery
  path to the ereader).
- **Sounds**: drop your own audio into `ratchet/static/sfx/` as `success`,
  `refused`, and `error` (`.mp3`/`.ogg`/`.wav`/`.m4a` — the UI probes for
  whichever you provide, and each is optional). They fire on update/save
  success, on a safe refusal, and on any failure. The speaker button in the
  header mutes them, remembered per device. See that folder's README.

The UI is plain static files under `ratchet/static/` (index.html + ui.css +
a handful of small JS modules) served by the service itself — no build step,
no separate deployment.

## Reaching it from your phone

Each device needs the Tailscale app installed and signed in to the same
tailnet. Two ways to let it in; the first is the default.

**Through Tailscale — no firewall rule, no administrator rights.** Ratchet
listens on this machine only (`[service] host = "127.0.0.1"`), where nothing
outside can reach it, and Tailscale hands it the tailnet's traffic on its
port:

```powershell
tailscale serve --bg --tcp=8484 tcp://127.0.0.1:8484
tailscale serve status              # what is being forwarded
tailscale serve --tcp=8484 off      # undo it
```

`--bg` makes it part of Tailscale's own configuration, so it survives a
restart. The setup wizard does exactly this. It is the default because the
other way needs an administrator to open the firewall, and "run this as
administrator to open your firewall" is what a careful person refuses from a
tool they downloaded an hour ago — rightly. It also means a misconfigured
Ratchet can never end up listening to your home network.

**Directly — faster, but needs a firewall rule.** Measured on one machine,
going through Tailscale costs about 10 ms a request (3 ms direct, 12 ms
forwarded): Tailscale carries the bytes through its own process rather than
the system's network code. Large downloads are unaffected; moving between
pages is a touch less crisp. If that matters to you, set
`host = "tailscale"` — this machine's tailnet address, looked up at startup
rather than pinned, since it can change — turn the forwarding above off (the
two would fight over the port, and Tailscale would win with nothing behind
it), and allow the port through Windows Firewall, **once**, in an
**Administrator** PowerShell. It allows only TCP 8484, only from tailnet
addresses (100.64.0.0/10), so it does not open the port to your LAN:

```powershell
New-NetFirewallRule -DisplayName "Ratchet (tailnet only)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8484 `
  -Profile Any -RemoteAddress 100.64.0.0/10

netsh advfirewall firewall show rule name="Ratchet (tailnet only)"   # check
Remove-NetFirewallRule -DisplayName "Ratchet (tailnet only)"          # remove
```

`-Profile Any` because which profile Windows files the Tailscale adapter
under varies between machines, and a rule on the wrong one fails silently;
the address restriction is what keeps it narrow. (`netsh` to check it rather
than `Get-NetFirewallRule`, which answers "Access is denied" unless elevated
— easily mistaken for the rule being absent.) The wizard recognises a setup
like this and leaves it alone.

Either way, in the browser it is `http://<machine name>:8484/ui/`; paste the
token once, and use Chrome's *Add to Home screen*. The Android app asks for
the address itself — see *The Android shell*.

Never expose this to the open internet; the bearer token is the only lock.

## Autostart (Task Scheduler)

Task Scheduler → Create Task:

- **General**: name `ratchet`; "Run whether user is logged on or not" if you
  want it up before you log in (stores your Windows password), otherwise
  "Run only when user is logged on" is fine for a desktop that auto-logs-in.
- **Triggers**: At log on (or At startup with the "whether logged on" option).
- **Actions**: Start a program —
  - Program: `C:\...\Calibre-Ratchet\server\.venv\Scripts\python.exe`
  - Arguments: `-m ratchet`
  - With `host = "tailscale"`, make the trigger *At log on* with a short delay
    (or add "restart on failure" below): Tailscale has to be connected before
    the address can be resolved and bound.
  - **Start in**: `C:\...\Calibre-Ratchet\server` (this is how it
    finds `config.toml`; Task Scheduler has no env-var field)
- **Settings**: "If the task fails, restart every 1 minute", 3 attempts.

The venv is deliberately *not* activated here — the `.venv` python is invoked
directly, and Ratchet finds FanFicFare through its own interpreter when the
console script isn't on PATH.

Make the calibre content server autostart too (calibre Preferences →
Sharing over the net → "Run server automatically when calibre starts", plus
calibre itself in `shell:startup` — or run `calibre-server` as its own task).

## The Android shell

`shell/` wraps the served UI in a native Android app (Capacitor). The WebView
loads `<your server>:8484/ui/` — the same files the browser gets — so UI
changes ship by editing the server, never by rebuilding the APK. The shell
exists to hold native permissions (filesystem, opening files in other apps);
it rebuilds only when the native side or a bundled page changes.

**The app asks where the server is the first time it opens**, and remembers.
Nothing about any one machine is built into it, so one APK serves anybody
and using Ratchet does not mean building it: only changing the shell does.
Type the machine's name in Tailscale (its tray menu shows it) — the short
name is usually enough, Tailscale on the device completing the rest, and is
steadier than the tailnet IP; the port is assumed to be 8484 unless given.
Whatever is typed first is worth keeping to: what the UI remembers on a
device (the token included) is kept per address, so the short name and the
full one count as two different servers.
To change it later, the offline page — what the app shows when the server
does not answer, a wrong address included — names the address and has a
*Change* button.

Two pages are bundled: `www/index.html` (that first question) and
`www/error.html` (the offline library). The second is generated, because
Capacitor will only serve it as one self-contained file, and is tracked so
that a fresh clone builds without running the generator. After editing
`error.template.html`, `www/offline.js` or `www/offline.css`:

```powershell
node build-error-page.mjs      # the tests fail if this is forgotten
```

Build (needs JDK 21 and the Android SDK; here they live under
`C:\Users\Cassandra\android-dev`, installed without Android Studio):

```powershell
cd shell
npx cap sync android
cd android
$env:JAVA_HOME = "C:\Users\Cassandra\android-dev\jdk-21.0.12.1+1"
$env:ANDROID_HOME = "C:\Users\Cassandra\android-dev\sdk"
.\gradlew assembleDebug
Copy-Item app\build\outputs\apk\debug\app-debug.apk `
          $env:LOCALAPPDATA\Ratchet\ratchet.apk
```

Install on a device: open `http://<server>:8484/apk` in the device's browser,
download, and allow the install ("install unknown apps" prompt). The route is
unauthenticated because a browser download cannot send the token header and
the APK holds no secrets. Icons and splashes regenerate from `shell/assets/`
via `npx @capacitor/assets generate --android` (sources derive from
`scripts/make_icons.py` geometry).

## API summary

| Method | Path | What |
|---|---|---|
| GET | `/health` | service + calibre reachability, library list |
| GET | `/ping` | `{"ratchet": true}` and nothing else, readable from any origin — how the app's bundled pages tell Ratchet from whatever else might answer at an address |
| GET | `/libraries` | every library on the content server |
| GET | `/books?q=&num=&offset=` | search (full calibre search syntax) |
| GET | `/books/{id}` | calibre metadata + sidecar snapshot + recent events |
| GET | `/books/{id}/epub` | the epub, streamed through from calibre (for Moon+) |
| POST | `/books/{id}/check` | pre-flight only: diff local vs site, no writes |
| POST | `/books/{id}/update?dry_run=` | the full safe update flow |
| POST | `/books/{id}/fields` | `{"changes": {"tags": [...], "#genre": "..."}}` |
| POST | `/books/{id}/adopt` | rebuild sidecar snapshot from current epub |
| GET | `/books/{id}/events` | audit log (incl. refusals) |
| GET | `/categories` | tag/custom-column vocabularies (for chip UIs), plus which columns calibre nests |

Auth on everything except `/health` and the static `/ui` files:
`X-Api-Token: <token>` or `Authorization: Bearer <token>`.

Every book/category endpoint also accepts `?library=<id>`; omitting it uses
`[calibre] library_id` from config.toml, and an empty value there means the
content server's own default library.

## Tags a story arrives with

FanFicFare copies a story's own tags into the epub, and calibre imports them
when a book is added — so `POST /books/add` brings in whatever the author or
the site used: `In-Progress`, `FanFiction`, `Last Update: 2026-09-09`, AO3
freeform tags, character names in the site's spelling.

`../config/tag_rules.txt` says what becomes of each: renamed, moved to a
column, deleted, or (by default) left alone. The service applies the rules as
the book arrives; `../.scripts/stray_tags.py` sweeps the backlog and rewrites
the file listing whatever nobody has ruled on yet. Both go through
`ratchet/tagmap.py`, so a rule means the same thing either way.

A tag no rule covers is never touched, so an import cannot quietly lose
something you have not decided about.

## Tests

```powershell
python -m pytest tests -q
```

## Linux equivalents (if the service ever moves)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml && chmod 600 config.toml
RATCHET_CONFIG=config.toml python -m ratchet
```

systemd unit `/etc/systemd/system/ratchet.service` (adjust user/paths):

```ini
[Unit]
Description=Ratchet
After=network-online.target

[Service]
User=YOU
WorkingDirectory=/home/YOU/server
Environment=RATCHET_CONFIG=/home/YOU/server/config.toml
ExecStart=/home/YOU/server/.venv/bin/python -m ratchet
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now ratchet
```
