# ficsync server

Stub-safe FanFicFare updates + calibre metadata editing, over HTTP, for one
user (you), reachable from your phone via Tailscale.

Read `../PLAN.md` first — it explains the safety model and what was verified
against which sources. This file is just setup.

## Prerequisites

- Python **3.11+** on the always-on machine that hosts calibre
- calibre's **content server running** (GUI: Connect/share → Start Content
  server; or `calibre-server --port 8080`). ficsync only ever talks to the
  running server, never to the library folder directly.
- `pip install FanFicFare` on the same machine (comes in via requirements.txt)

## Setup

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp config.example.toml config.toml     # edit: auth_token, calibre URL/creds
chmod 600 config.toml                  # it holds secrets

# Sanity + baseline (no fic-site requests; local library only):
python scripts/snapshot_baseline.py --config config.toml --limit 5
python scripts/snapshot_baseline.py --config config.toml   # whole library

# Run:
FICSYNC_CONFIG=config.toml python -m ficsync
```

Smoke test from another terminal:

```bash
curl -s http://127.0.0.1:8484/health | python3 -m json.tool
TOKEN='...your token...'
curl -s -H "X-Api-Token: $TOKEN" 'http://127.0.0.1:8484/books?q=royalroad&num=5' | python3 -m json.tool
curl -s -X POST -H "X-Api-Token: $TOKEN" http://127.0.0.1:8484/books/123/check | python3 -m json.tool
curl -s -X POST -H "X-Api-Token: $TOKEN" 'http://127.0.0.1:8484/books/123/update?dry_run=true'
```

## Reaching it from your phone

Two options, pick one:

1. **Bind to the Tailscale IP**: set `[service] host = "100.x.y.z"` (your
   tailnet address). Phone hits `http://100.x.y.z:8484`.
2. **`tailscale serve`**: keep host `127.0.0.1` and run
   `tailscale serve --bg --https=443 localhost:8484` for HTTPS inside the
   tailnet.

Never expose this to the open internet; the bearer token is the only lock.

## systemd unit

`/etc/systemd/system/ficsync.service` (adjust user/paths):

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

## API summary

| Method | Path | What |
|---|---|---|
| GET | `/health` | service + calibre reachability, library list |
| GET | `/books?q=&num=&offset=` | search (full calibre search syntax) |
| GET | `/books/{id}` | calibre metadata + sidecar snapshot + recent events |
| GET | `/books/{id}/epub` | download the epub (for Moon+) |
| POST | `/books/{id}/check` | pre-flight only: diff local vs site, no writes |
| POST | `/books/{id}/update?dry_run=` | the full safe update flow |
| POST | `/books/{id}/fields` | `{"changes": {"tags": [...], "#genre": "..."}}` |
| POST | `/books/{id}/adopt` | rebuild sidecar snapshot from current epub |
| GET | `/books/{id}/events` | audit log (incl. refusals) |
| GET | `/categories` | tag/custom-column vocabularies (for chip UIs) |

Auth on everything except `/health`: `X-Api-Token: <token>` or
`Authorization: Bearer <token>`.

## Tests

```bash
python -m pytest tests/ -q
```
