# ficsync server

Stub-safe FanFicFare updates + calibre metadata editing, over HTTP, for one
user (you), reachable from your phone via Tailscale.

Read `../../PLAN.md` first — it explains the safety model and what was verified
against which sources. This file is just setup.

This deployment runs on **Windows** (the machine that hosts calibre); the
Linux equivalents are kept at the bottom in case it ever moves.

## Prerequisites

- Python **3.11+** on the always-on machine that hosts calibre
- calibre's **content server running** (GUI: Connect/share → Start Content
  server; or `calibre-server --port 8080`). ficsync only ever talks to the
  running server, never to the library folder directly.
- FanFicFare comes in via requirements.txt — no separate install.

## Setup (Windows / PowerShell)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

Copy-Item config.example.toml config.toml
# Edit config.toml: auth_token (any long random string), calibre URL.
# calibre creds go in a .env file next to config.toml (both .gitignore'd):
#   FICSYNC_CALIBRE_USERNAME=... / FICSYNC_CALIBRE_PASSWORD=...

# Sanity + baseline (no fic-site requests; local library only):
python scripts\snapshot_baseline.py --config config.toml --limit 5
python scripts\snapshot_baseline.py --config config.toml --library Serials
python scripts\snapshot_baseline.py --config config.toml --all-libraries

# Run (reads config.toml from the current directory by default):
python -m ficsync
# elsewhere: $env:FICSYNC_CONFIG = "C:\path\to\config.toml"; python -m ficsync
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
- **Sounds**: drop your own audio into `ficsync/static/sfx/` as `success`,
  `refused`, and `error` (`.mp3`/`.ogg`/`.wav`/`.m4a` — the UI probes for
  whichever you provide, and each is optional). They fire on update/save
  success, on a safe refusal, and on any failure. The speaker button in the
  header mutes them, remembered per device. See that folder's README.

The UI is plain static files under `ficsync/static/` (index.html + ui.css +
a handful of small JS modules) served by the service itself — no build step,
no separate deployment.

## Reaching it from your phone

`[service] host = "tailscale"` (the configured value) resolves this machine's
tailnet address at startup instead of pinning a literal IP — tailnet addresses
can change, and a stale literal would leave the service unable to bind at all.
The startup line prints the address it chose. `host` also accepts a literal IP,
`"127.0.0.1"` for local-only, or `"0.0.0.0"` for every interface (LAN
included — not recommended).

**One-time firewall rule.** Windows blocks inbound connections by default, so
the phone and ereader are refused until a rule exists. Run this **once** in an
**Administrator** PowerShell. It allows only TCP 8484, only from tailnet
addresses (100.64.0.0/10), so it does not open the port to your LAN even
though the Ethernet adapter is also on the Private profile:

```powershell
New-NetFirewallRule -DisplayName "ficsync (tailnet only)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8484 `
  -Profile Private -RemoteAddress 100.64.0.0/10
```

To check or remove it later:

```powershell
Get-NetFirewallRule -DisplayName "ficsync (tailnet only)"
Remove-NetFirewallRule -DisplayName "ficsync (tailnet only)"
```

Each device needs the Tailscale app installed and connected, signed into the
same tailnet. Then open `http://<tailnet-ip>:8484/ui/`, paste the token once,
and use Chrome's *Add to Home screen*.

**Alternative — `tailscale serve`:** keep `host = "127.0.0.1"` and run
`tailscale serve --bg --https=443 localhost:8484`. This needs no firewall rule
(Tailscale connects locally) and gives HTTPS on a stable MagicDNS name, but
requires HTTPS certificates enabled for your tailnet in the admin console.

Never expose this to the open internet; the bearer token is the only lock.

## Autostart (Task Scheduler)

Task Scheduler → Create Task:

- **General**: name `ficsync`; "Run whether user is logged on or not" if you
  want it up before you log in (stores your Windows password), otherwise
  "Run only when user is logged on" is fine for a desktop that auto-logs-in.
- **Triggers**: At log on (or At startup with the "whether logged on" option).
- **Actions**: Start a program —
  - Program: `C:\...\Calibre-Ratchet\ficsync\server\.venv\Scripts\python.exe`
  - Arguments: `-m ficsync`
  - With `host = "tailscale"`, make the trigger *At log on* with a short delay
    (or add "restart on failure" below): Tailscale has to be connected before
    the address can be resolved and bound.
  - **Start in**: `C:\...\Calibre-Ratchet\ficsync\server` (this is how it
    finds `config.toml`; Task Scheduler has no env-var field)
- **Settings**: "If the task fails, restart every 1 minute", 3 attempts.

The venv is deliberately *not* activated here — the `.venv` python is invoked
directly, and ficsync finds FanFicFare through its own interpreter when the
console script isn't on PATH.

Make the calibre content server autostart too (calibre Preferences →
Sharing over the net → "Run server automatically when calibre starts", plus
calibre itself in `shell:startup` — or run `calibre-server` as its own task).

## The Android shell

`shell/` wraps the served UI in a native Android app (Capacitor). The WebView
loads `http://desktop-2mmhpaf.tail77896d.ts.net:8484/ui/` — the same files the
browser gets — so UI changes ship by editing the server, never by rebuilding
the APK. The shell exists to hold native permissions (filesystem, opening
files in other apps); it rebuilds only when the native plugin list changes.

Build (JDK 21 and the Android SDK live under `C:\Users\Cassandra\android-dev`,
installed without Android Studio):

```powershell
cd shell
npx cap sync android
cd android
$env:JAVA_HOME = "C:\Users\Cassandra\android-dev\jdk-21.0.12.1+1"
$env:ANDROID_HOME = "C:\Users\Cassandra\android-dev\sdk"
.\gradlew assembleDebug
Copy-Item app\build\outputs\apk\debug\app-debug.apk `
          $env:LOCALAPPDATA\ficsync\ratchet.apk
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
| GET | `/libraries` | every library on the content server |
| GET | `/books?q=&num=&offset=` | search (full calibre search syntax) |
| GET | `/books/{id}` | calibre metadata + sidecar snapshot + recent events |
| GET | `/books/{id}/epub` | download the epub (for Moon+) |
| POST | `/books/{id}/check` | pre-flight only: diff local vs site, no writes |
| POST | `/books/{id}/update?dry_run=` | the full safe update flow |
| POST | `/books/{id}/fields` | `{"changes": {"tags": [...], "#genre": "..."}}` |
| POST | `/books/{id}/adopt` | rebuild sidecar snapshot from current epub |
| GET | `/books/{id}/events` | audit log (incl. refusals) |
| GET | `/categories` | tag/custom-column vocabularies (for chip UIs) |

Auth on everything except `/health` and the static `/ui` files:
`X-Api-Token: <token>` or `Authorization: Bearer <token>`.

Every book/category endpoint also accepts `?library=<id>`; omitting it uses
`[calibre] library_id` from config.toml, and an empty value there means the
content server's own default library.

## Tests

```powershell
python -m pytest tests -q
```

## Linux equivalents (if the service ever moves)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml && chmod 600 config.toml
FICSYNC_CONFIG=config.toml python -m ficsync
```

systemd unit `/etc/systemd/system/ficsync.service` (adjust user/paths):

```ini
[Unit]
Description=ficsync
After=network-online.target

[Service]
User=YOU
WorkingDirectory=/home/YOU/ficsync/server
Environment=FICSYNC_CONFIG=/home/YOU/ficsync/server/config.toml
ExecStart=/home/YOU/ficsync/server/.venv/bin/python -m ficsync
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now ficsync
```
