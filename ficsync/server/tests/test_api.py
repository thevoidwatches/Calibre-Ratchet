"""App-level tests that don't need a live calibre or fic site.

main.py loads its config at import time, so the config file + env var must
exist before the import — hence the module-level setup.
"""

import os
import re
import sys

import pytest
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


def test_epub_save_uses_a_folder_picker_where_one_exists():
    """Desktop Chromium can remember a destination folder; Android cannot, so
    the anchor fallback has to stay."""
    js = client.get("/ui/actions.js").text
    assert "showSaveFilePicker" in js and 'id: "ficsync-epub"' in js
    assert "a.download = filename" in js          # fallback still present
    assert 'e.name === "AbortError"' in js        # cancelling is not an error


def test_saved_filters_roundtrip_and_are_scoped_per_library():
    groups = [{"terms": [{"field": "#readinglist", "value": "Rainy Day"}]}]
    r = client.put("/filters/Rainy", json={"groups": groups},
                   params={"library": "Serials"}, headers=TOK)
    assert r.status_code == 200

    got = client.get("/filters", params={"library": "Serials"}, headers=TOK).json()
    assert [f["name"] for f in got["filters"]] == ["Rainy"]
    assert got["filters"][0]["groups"] == [
        {"terms": [{"field": "#readinglist", "value": "Rainy Day",
                    "exclude": False, "hierarchical": True}]}]

    other = client.get("/filters", params={"library": "Books"}, headers=TOK).json()
    assert other["filters"] == []

    assert client.delete("/filters/Rainy", params={"library": "Serials"},
                         headers=TOK).status_code == 200
    assert client.delete("/filters/Rainy", params={"library": "Serials"},
                         headers=TOK).status_code == 404


def test_saving_a_filter_overwrites_the_same_name():
    a = [{"terms": [{"field": "tags", "value": "a"}]}]
    b = [{"terms": [{"field": "tags", "value": "b"}]}]
    client.put("/filters/Dup", json={"groups": a}, headers=TOK)
    client.put("/filters/Dup", json={"groups": b}, headers=TOK)
    names = [f["name"] for f in client.get("/filters", headers=TOK).json()["filters"]]
    assert names.count("Dup") == 1
    saved = [f for f in client.get("/filters", headers=TOK).json()["filters"]
             if f["name"] == "Dup"][0]
    assert saved["groups"][0]["terms"][0]["value"] == "b"
    client.delete("/filters/Dup", headers=TOK)


@pytest.mark.parametrize("groups", [
    "not-a-list",
    [{"no_terms": []}],
    [{"terms": [{"field": "", "value": "x"}]}],
    [{"terms": [{"field": "tags"}]}],
    [{"terms": ["not-an-object"]}],
    [],                                    # nothing to save
])
def test_malformed_filters_are_rejected(groups):
    # 422 where FastAPI's own type check catches it first (a non-list), 400
    # from our structural validation; either way nothing malformed is stored.
    r = client.put("/filters/Bad", json={"groups": groups}, headers=TOK)
    assert r.status_code in (400, 422), r.status_code
    assert "Bad" not in [f["name"] for f in
                         client.get("/filters", headers=TOK).json()["filters"]]


def test_unknown_term_keys_are_not_stored():
    client.put("/filters/Clean", json={"groups": [
        {"terms": [{"field": "tags", "value": "x", "evil": "payload"}]}]}, headers=TOK)
    saved = [f for f in client.get("/filters", headers=TOK).json()["filters"]
             if f["name"] == "Clean"][0]
    assert set(saved["groups"][0]["terms"][0]) == {"field", "value", "exclude", "hierarchical"}
    client.delete("/filters/Clean", headers=TOK)


def test_filter_name_length_is_bounded():
    r = client.put("/filters/" + "x" * 200,
                   json={"groups": [{"terms": [{"field": "tags", "value": "x"}]}]},
                   headers=TOK)
    assert r.status_code == 400


def test_preset_references_are_accepted_and_normalised():
    client.put("/filters/Base", json={"groups": [
        {"terms": [{"field": "tags", "value": "x"}]}]}, headers=TOK)
    r = client.put("/filters/Uses", json={"groups": [
        {"terms": [{"preset": "Base"}, {"field": "tags", "value": "y"}]}]}, headers=TOK)
    assert r.status_code == 200
    saved = [f for f in client.get("/filters", headers=TOK).json()["filters"]
             if f["name"] == "Uses"][0]
    assert saved["groups"][0]["terms"][0] == {"preset": "Base", "exclude": False}
    client.delete("/filters/Uses", headers=TOK)
    client.delete("/filters/Base", headers=TOK)


def test_a_set_cannot_reference_itself():
    r = client.put("/filters/Loop", json={"groups": [
        {"terms": [{"preset": "Loop"}]}]}, headers=TOK)
    assert r.status_code == 400


def test_empty_preset_name_is_rejected():
    r = client.put("/filters/Bad2", json={"groups": [
        {"terms": [{"preset": "  "}]}]}, headers=TOK)
    assert r.status_code == 400


def test_include_exclude_is_a_tab_selector_beside_the_value_input():
    html = client.get("/ui/").text
    section = html.split('id="vPickVal"')[1].split("</section>")[0]
    assert 'name="mode"' not in section          # the radios are gone
    assert 'id="tabInclude"' in section and 'id="tabExclude"' in section
    # Same row as the free-value input, per the requested layout.
    row = [r for r in section.split('<div class="row">') if "freeValue" in r][0]
    assert 'id="tabInclude"' in row
    # The chosen mode is read from the tab, not from a stale radio group.
    assert 'input[name="mode"]' not in client.get("/ui/picker.js").text


def test_include_exclude_is_a_tab_selector_beside_the_value_input():
    html = client.get("/ui/").text
    section = html.split('id="vPickVal"')[1].split("</section>")[0]
    assert 'name="mode"' not in section          # the radios are gone
    assert 'id="tabInclude"' in section and 'id="tabExclude"' in section
    # Same row as the free-value input, per the requested layout.
    row = [r for r in section.split('<div class="row">') if "freeValue" in r][0]
    assert 'id="tabInclude"' in row
    # The mode is read from the tab, not from a stale radio group.
    assert 'input[name="mode"]' not in client.get("/ui/picker.js").text


def test_collapse_markers_are_real_arrows_and_match_the_filter_bar():
    """These have been mangled twice by escaping layers: once into an octal
    escape (a 0x15 control byte), once into a literal backslash sequence."""
    css = client.get("/ui/ui.css").text
    assert "\u25b8" in css and "\u25be" in css        # closed / open markers
    assert not [c for c in css if ord(c) < 32 and c not in "\r\n\t"]
    # The same glyphs the filter bar draws, so the two read alike.
    assert "\u25b8" in client.get("/ui/browse.js").text
    assert "\u25be" in client.get("/ui/browse.js").text


def test_icon_set_is_served_and_declared():
    for path in ["/ui/icon.svg", "/ui/icon-192.png", "/ui/icon-512.png",
                 "/ui/icon-maskable-512.png"]:
        assert client.get(path).status_code == 200, path
    assert "<svg" in client.get("/ui/icon.svg").text
    icons = client.get("/ui/manifest.webmanifest").json()["icons"]
    assert {i["src"] for i in icons} == {"icon-192.png", "icon-512.png",
                                         "icon-maskable-512.png"}
    assert any(i.get("purpose") == "maskable" for i in icons)
    assert 'rel="icon"' in client.get("/ui/").text


def test_views_participate_in_history_for_the_android_back_button():
    assert "pushState" in client.get("/ui/core.js").text
    app = client.get("/ui/app.js").text
    assert "popstate" in app and "history.back()" in app


def test_header_wordmark_is_wired_and_inverts_in_dark_mode():
    assert client.get("/ui/logo.png").status_code == 200
    html = client.get("/ui/").text
    assert 'src="logo.png"' in html and 'alt="Ratchet"' in html
    css = client.get("/ui/ui.css").text
    assert "invert(1)" in css      # dark-mode flip for the black-outline art
