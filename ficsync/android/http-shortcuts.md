# Fallback Android client: HTTP Shortcuts

> **Superseded for daily use** by the embedded web app at
> `http://<host>:8484/ui` (add it to the home screen; works on the ereader
> too). Kept because home-screen one-tap shortcuts against single endpoints
> can still be handy (e.g. a bare "Update current book" button).


Until the Expo app exists, the free **HTTP Shortcuts** app (Play Store /
F-Droid, `ch.rmy.android.http_shortcuts`) is a perfectly good client: home
screen buttons that hit ficsync and show the JSON response.

## Global setup

Create a **variable** `book_id` of type *Text input* (prompt: "Calibre book
id"), and a **variable** `token` of type *Constant* holding your auth token.
Every shortcut below sends header `X-Api-Token: {{token}}`.

Base URL below assumes `http://100.x.y.z:8484` — your Tailscale address. The
Tailscale app must be connected (it can stay connected permanently; it's
battery-cheap).

## Shortcuts

### 1. Check story
- Method: `POST`
- URL: `http://100.x.y.z:8484/books/{{book_id}}/check`
- Response handling: "Show in dialog", JSON pretty-printed.
- What you'll read: `action` (`up_to_date` / `update` / `refuse_missing`),
  `new_chapters`, `missing_chapters`.

### 2. Update story
- Method: `POST`
- URL: `http://100.x.y.z:8484/books/{{book_id}}/update`
- Timeout: raise it (2–10 min) — big serials take a while to fetch politely.
- On `refuse_missing` you get HTTP 200 with `"updated": false` and the exact
  chapters at risk; nothing was touched.

### 3. Get epub (hand to Moon+)
- Method: `GET`
- URL: `http://100.x.y.z:8484/books/{{book_id}}/epub`
- Response handling: "Save to file" (or open-with → Moon+). Keep the same
  target folder/filename each time so Moon+ sees it as the same book and your
  reading position survives the swap.

### 4. Tag it "finished" (example fields edit)
- Method: `POST`
- URL: `http://100.x.y.z:8484/books/{{book_id}}/fields`
- Body (JSON):
  ```json
  {"changes": {"#readinglist": "Finished"}}
  ```
- Content-Type: `application/json`.
- Variant to append tags rather than replace: tags are a *replace* operation
  in calibre's set-fields, so a pure append needs the current list first —
  that's a two-request scripted shortcut (HTTP Shortcuts supports scripting:
  GET `/books/{{book_id}}`, read `.calibre.tags`, push back the union). Fine
  to skip until the Expo app, where chips make this trivial.

## Finding book ids without typing them

Shortcut 0, "Find book": GET
`http://100.x.y.z:8484/books?q={{query}}&num=10` with a text-input `query`
variable; the response shows `id` + `title` pairs. calibre search syntax works
as-is (`tags:web-serial`, `#readinglist:reading`, author names, etc.).
