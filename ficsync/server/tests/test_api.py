"""App-level tests that don't need a live calibre or fic site.

main.py loads its config at import time, so the config file + env var must
exist before the import — hence the module-level setup.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = Path(tempfile.mkdtemp(prefix="ficsync-test-"))
(_tmp / "config.toml").write_text(
    f'''
[service]
auth_token = "testtoken"
data_dir = "{(_tmp / 'data').as_posix()}"

[calibre]
base_url = "http://127.0.0.1:9"    # closed port: only reachability behavior is tested
''',
    encoding="utf-8",
)
os.environ["FICSYNC_CONFIG"] = str(_tmp / "config.toml")

from fastapi.testclient import TestClient  # noqa: E402

from ficsync.main import app  # noqa: E402

client = TestClient(app)
TOK = {"X-Api-Token": "testtoken"}


def test_ui_serves():
    r = client.get("/ui")     # -> redirect -> /ui/ -> index.html
    assert r.status_code == 200
    assert "ficsync" in r.text
    assert "text/html" in r.headers["content-type"]


def test_ui_assets_serve():
    for name in ["ui.css", "core.js", "browse.js", "picker.js",
                 "detail.js", "actions.js", "app.js"]:
        assert client.get(f"/ui/{name}").status_code == 200, name


def test_manifest_serves():
    r = client.get("/ui/manifest.webmanifest")
    assert r.status_code == 200
    assert r.json()["start_url"] == "/ui/"


def test_ui_config_requires_token():
    assert client.get("/ui-config").status_code == 401
    r = client.get("/ui-config", headers=TOK)
    assert r.status_code == 200
    assert "tags" in r.json()["writable_fields"]


def test_bearer_auth_also_works():
    r = client.get("/ui-config", headers={"Authorization": "Bearer testtoken"})
    assert r.status_code == 200


def test_category_items_rejects_non_category_urls():
    r = client.get("/category-items", params={"url": "/cdb/set-fields/1"}, headers=TOK)
    assert r.status_code == 400


def test_health_reports_unreachable_calibre():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["calibre"]["reachable"] is False


def test_libraries_endpoint_requires_token():
    assert client.get("/libraries").status_code == 401


def test_library_param_accepted_on_book_endpoints():
    # calibre is unreachable here, so this asserts two things: the parameter is
    # part of the signature (422 would mean it is not), and an unreachable
    # server produces a clean 502 rather than an unhandled traceback.
    r = client.get("/books", params={"q": "", "library": "Serials"}, headers=TOK)
    assert r.status_code == 502


def test_unreachable_calibre_is_a_clean_502():
    assert client.get("/libraries", headers=TOK).status_code == 502


def test_sfx_module_and_folder_are_served():
    assert client.get("/ui/sfx.js").status_code == 200
    # The folder is mounted (its README proves it) even with no audio in it.
    assert client.get("/ui/sfx/README.md").status_code == 200


def test_missing_sound_404s_so_the_probe_can_detect_absence():
    r = client.head("/ui/sfx/success.mp3")
    assert r.status_code == 404


def test_ui_assets_are_revalidated_not_cached_indefinitely():
    """A phone that cached the old UI must not keep it after a redeploy."""
    for path in ["/ui/", "/ui/app.js", "/ui/sfx.js"]:
        cc = client.get(path).headers.get("cache-control", "")
        assert "no-cache" in cc, (path, cc)


def test_ui_config_reports_the_genre_field():
    body = client.get("/ui-config", headers=TOK).json()
    assert body["genre_field"] == "#genre"


def test_cover_endpoint_requires_token_and_accepts_size():
    assert client.get("/books/1/cover").status_code == 401
    # calibre is unreachable here, so a clean failure (not a 422/500) is the bar.
    r = client.get("/books/1/cover", params={"sz": "160x213"}, headers=TOK)
    assert r.status_code in (404, 502)


def test_theme_module_is_served():
    assert client.get("/ui/theme.js").status_code == 200


def test_theme_is_applied_before_first_paint():
    """The stamp must be inline in <head>, not deferred to a module, or a
    dark-mode device flashes a white page on every load."""
    html = client.get("/ui/").text
    head = html.split("</head>")[0]
    assert "ficsync_theme" in head
    assert "data-theme" in head


def test_stylesheet_defines_both_palettes():
    css = client.get("/ui/ui.css").text
    assert ":root {" in css and '[data-theme="dark"]' in css
    for token in ["--bg", "--fg", "--muted", "--faint", "--shade-1", "--shade-2"]:
        assert css.count(token + ":") >= 2, token   # defined in both themes


def test_library_select_has_a_placeholder_before_login():
    """The token screen never reaches /libraries, so the selector must not
    render as an empty box."""
    html = client.get("/ui/").text
    sel = html.split('id="librarySelect"')[1].split("</select>")[0]
    assert "disabled" in html.split('id="librarySelect"')[0][-80:] or "disabled" in sel
    assert "Library" in sel


def test_unauthorized_sound_is_wired_without_a_module_cycle():
    """core.js announces a 401; sfx.js listens. sfx.js may import core.js, but
    never the other way around, or the modules become circular."""
    core = client.get("/ui/core.js").text
    sfx = client.get("/ui/sfx.js").text
    assert "UNAUTHORIZED_EVENT" in core and "dispatchEvent" in core
    assert "UNAUTHORIZED_EVENT" in sfx and 'play("refused")' in sfx
    # An *import* of sfx.js, not a mention of it in a comment.
    assert not re.search(r"""^\s*import[^
]*["']\./sfx\.js["']""", core, re.M)


def test_login_success_sound_is_only_for_a_deliberate_sign_in():
    """boot() re-runs on every page load with a stored token; the chime must
    be tied to submitting one, not to opening the app."""
    app = client.get("/ui/app.js").text
    assert "boot({announce: true})" in app
    assert "if (announce) play(\"success\")" in app


def test_sort_options_are_published_and_default_to_last_modified():
    body = client.get("/ui-config", headers=TOK).json()
    keys = [o["key"] for o in body["sort_options"]]
    assert keys == ["title", "series", "author", "modified"]
    assert body["default_sort"] == "modified"


def test_unknown_sort_is_rejected_not_silently_ignored():
    """calibre answers 200 for a sort field it doesn't know, so ficsync has to
    be the one that refuses."""
    r = client.get("/books", params={"sort": "nonsense"}, headers=TOK)
    assert r.status_code == 400
    r = client.get("/books", params={"sort_order": "sideways"}, headers=TOK)
    assert r.status_code == 400


def test_known_sorts_reach_calibre():
    for key in ["title", "series", "author", "modified"]:
        r = client.get("/books", params={"sort": key, "sort_order": "asc"}, headers=TOK)
        assert r.status_code == 502, key   # calibre unreachable, but sort accepted


def test_book_rows_are_striped_by_rendered_position():
    css = client.get("/ui/ui.css").text
    assert "#results li:nth-child(even)" in css
    assert "--stripe" in css


def test_header_centres_the_library_selector():
    """The selector must be its own header cell, not inside the right-hand
    control group, or "centred" would only mean "centred within the buttons"."""
    html = client.get("/ui/").text
    header = html.split("<header>")[1].split("</header>")[0]
    before_controls = header.split('class="controls"')[0]
    assert 'id="librarySelect"' in before_controls
    css = client.get("/ui/ui.css").text
    assert "grid-template-columns: 1fr auto 1fr" in css
