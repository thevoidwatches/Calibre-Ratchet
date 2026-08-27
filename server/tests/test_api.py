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

_tmp = Path(tempfile.mkdtemp(prefix="ratchet-test-"))
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
os.environ["RATCHET_CONFIG"] = str(_tmp / "config.toml")

from fastapi.testclient import TestClient  # noqa: E402

from ratchet.main import app  # noqa: E402

client = TestClient(app)
TOK = {"X-Api-Token": "testtoken"}


def test_ui_serves():
    r = client.get("/ui")     # -> redirect -> /ui/ -> index.html
    assert r.status_code == 200
    assert "ratchet" in r.text
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
    assert "ratchet_theme" in head
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
    """calibre answers 200 for a sort field it doesn't know, so Ratchet has to
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
    assert "showSaveFilePicker" in js and 'id: "ratchet-epub"' in js
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


def test_downloaded_atom_saves_normalised():
    """The device-copy pseudo-filter stores as its own atom kind — no field or
    value — so a saved set containing it round-trips."""
    r = client.put("/filters/OnDevice", json={"groups": [
        {"terms": [{"downloaded": True, "exclude": True, "junk": 1}]}]}, headers=TOK)
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == [{"terms": [{"downloaded": True, "exclude": True}]}]
    client.delete("/filters/OnDevice", headers=TOK)


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


def test_header_wordmark_has_per_theme_art():
    assert client.get("/ui/logo-light.png").status_code == 200
    assert client.get("/ui/logo-dark.png").status_code == 200
    html = client.get("/ui/").text
    assert 'src="logo-light.png"' in html and 'alt="Ratchet"' in html
    theme = client.get("/ui/theme.js").text
    assert "logo-dark.png" in theme and "logo-light.png" in theme


def test_apk_route_404s_cleanly_until_a_build_is_deployed():
    r = client.get("/apk")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"] == "application/vnd.android.package-archive"


def test_header_toggles_are_monochrome_svg_not_emoji():
    """Emoji render as coloured glyphs on Android; the toggles must be inline
    SVGs driven by currentColor so they follow the theme."""
    theme = client.get("/ui/theme.js").text
    sfx = client.get("/ui/sfx.js").text
    for src_js in (theme, sfx):
        assert "<svg" in src_js and "currentColor" in src_js
    html = client.get("/ui/").text
    row = html.split('id="btnTheme"')[1].split("</button>")[0]
    assert "Dark" not in row          # no word label left in the markup


def test_long_lived_webview_reloads_on_return():
    """The Android shell keeps the page alive across app switches; a return
    after a real absence must pick up served changes."""
    app = client.get("/ui/app.js").text
    assert "visibilitychange" in app and "location.reload()" in app


def test_device_storage_module_is_inert_outside_the_shell():
    js = client.get("/ui/storage.js").text
    assert "RatchetNative" in js and 'directory: "EXTERNAL_STORAGE"' in js
    assert "inShell" in js            # everything gates on the bridge existing
    html = client.get("/ui/").text
    assert 'id="storageBanner"' in html and 'id="btnGrantStorage"' in html


def test_wordmark_is_a_confirmed_update_link():
    html = client.get("/ui/").text
    assert 'id="apkLink"' in html and 'href="/apk"' in html
    app = client.get("/ui/app.js").text
    assert "Download the latest version" in app and "confirm(" in app


def test_story_state_requires_token_and_fails_cleanly_offline():
    assert client.get("/books/1/story-state").status_code == 401
    r = client.get("/books/1/story-state", headers=TOK)
    assert r.status_code in (404, 502)     # calibre unreachable here


def test_convert_requires_token():
    assert client.post("/books/1/convert").status_code == 401


# --- adding a story by URL ---------------------------------------------------

def test_add_book_requires_token():
    assert client.post("/books/add", json={"url": "x"}).status_code == 401


def test_add_book_rejects_unrecognised_url():
    # No FanFicFare adapter for example.com; nothing is fetched.
    r = client.post("/books/add", json={"url": "https://example.com/nope"},
                    headers=TOK)
    assert r.status_code == 422
    assert "adapter" in r.json()["detail"]


def test_add_book_downloads_verifies_and_records(monkeypatch):
    """Happy path with the site, FFF, and calibre all stubbed — and the
    snapshot it stores must then trip the duplicate guard."""
    from ratchet import main as M
    from ratchet.epub import Chapter

    chs = [Chapter(key="c1", url="https://site/1", title="One"),
           Chapter(key="c2", url="https://site/2", title="Two")]
    url = "https://www.royalroad.com/fiction/424242"
    remote = M.RemoteStory(title="Stub Story", site="royalroad.com",
                           status="In-Progress", chapters=chs, raw={})

    monkeypatch.setattr(M, "normalize_story_url", lambda u: url)
    monkeypatch.setattr(M, "fetch_remote", lambda u, cfg: remote)

    def fake_run_fff(args, cfg):
        out = next(a for a in args if a.startswith("output_filename=")
                   ).split("=", 1)[1]
        Path(out).write_bytes(b"stub epub")
        class Proc:
            returncode, stdout, stderr = 0, "", ""
        return Proc()
    monkeypatch.setattr(M, "run_fff", fake_run_fff)
    monkeypatch.setattr(M.epub_mod, "extract_chapters", lambda p: chs)

    pushed = {}
    def fake_add(data, filename, lib):
        pushed.update(data=data, filename=filename, lib=lib)
        return {"book_id": 4242, "title": "Stub Story"}
    monkeypatch.setattr(M.calibre, "add_book", fake_add)

    r = client.post("/books/add", json={"url": url}, headers=TOK)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["book_id"] == 4242
    assert body["chapter_count"] == 2
    assert pushed["data"] == b"stub epub"
    assert pushed["filename"] == "Stub Story.epub"

    # The snapshot written on add is what makes re-adding a 409 — but only
    # once calibre confirms the book is still there.
    monkeypatch.setattr(M, "_book_exists", lambda lib, bid: True)
    dup = client.post("/books/add", json={"url": url}, headers=TOK)
    assert dup.status_code == 409
    assert "4242" in dup.json()["detail"]


def test_add_book_refuses_when_fresh_epub_fails_verification(monkeypatch):
    from ratchet import main as M
    from ratchet.epub import Chapter

    remote_chs = [Chapter(key="c1", url="u1", title="One"),
                  Chapter(key="c2", url="u2", title="Two")]
    url = "https://www.royalroad.com/fiction/515151"
    remote = M.RemoteStory(title="Short Story", site="royalroad.com",
                           status="In-Progress", chapters=remote_chs, raw={})

    monkeypatch.setattr(M, "normalize_story_url", lambda u: url)
    monkeypatch.setattr(M, "fetch_remote", lambda u, cfg: remote)

    def fake_run_fff(args, cfg):
        out = next(a for a in args if a.startswith("output_filename=")
                   ).split("=", 1)[1]
        Path(out).write_bytes(b"stub epub")
        class Proc:
            returncode, stdout, stderr = 0, "", ""
        return Proc()
    monkeypatch.setattr(M, "run_fff", fake_run_fff)
    # The fresh epub is missing a chapter the site lists.
    monkeypatch.setattr(M.epub_mod, "extract_chapters", lambda p: remote_chs[:1])

    r = client.post("/books/add", json={"url": url}, headers=TOK)
    assert r.status_code == 500
    assert "NOT added" in r.json()["detail"]


def test_blocked_site_rejects_add_before_touching_the_site(monkeypatch):
    """With a site on the blocklist, adding one of its stories is a clean 403
    — and nothing is fetched (fetch_remote would blow up if called)."""
    from ratchet import main as M
    monkeypatch.setattr(M.cfg.fanficfare, "blocked_sites", ["archiveofourown.org"])
    monkeypatch.setattr(M, "fetch_remote",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    r = client.post("/books/add",
                    json={"url": "https://archiveofourown.org/works/20024074"},
                    headers=TOK)
    assert r.status_code == 403
    assert "blocked" in r.json()["detail"]


def test_unblocked_sites_are_unaffected_by_the_blocklist(monkeypatch):
    from ratchet import main as M
    monkeypatch.setattr(M.cfg.fanficfare, "blocked_sites", ["archiveofourown.org"])
    # Royal Road passes the block check and proceeds to the site fetch, which
    # this stub fails — proving the request got past the blocklist.
    class Boom(Exception):
        pass
    def explode(*a, **k):
        raise M.SiteFetchError("stub reached the fetch stage")
    monkeypatch.setattr(M, "fetch_remote", explode)
    # An id no other test snapshots, or the duplicate guard answers first.
    r = client.post("/books/add",
                    json={"url": "https://www.royalroad.com/fiction/999001/x"},
                    headers=TOK)
    assert r.status_code == 502
    assert "fetch stage" in r.json()["detail"]


def _stub_add(monkeypatch, url, *, cover):
    """Wire up a successful add whose fresh epub yields `cover`."""
    from ratchet import main as M
    from ratchet.epub import Chapter
    chs = [Chapter(key="c1", url="u1", title="One")]
    monkeypatch.setattr(M, "normalize_story_url", lambda u: url)
    monkeypatch.setattr(M, "fetch_remote", lambda u, cfg: M.RemoteStory(
        title="Cover Story", site="royalroad.com", status="In-Progress",
        chapters=chs, raw={}))
    def fake_run_fff(args, cfg):
        out = next(a for a in args if a.startswith("output_filename=")).split("=", 1)[1]
        Path(out).write_bytes(b"stub epub")
        class Proc:
            returncode, stdout, stderr = 0, "", ""
        return Proc()
    monkeypatch.setattr(M, "run_fff", fake_run_fff)
    monkeypatch.setattr(M.epub_mod, "extract_chapters", lambda p: chs)
    monkeypatch.setattr(M.epub_mod, "extract_cover", lambda p: cover)
    monkeypatch.setattr(M.calibre, "add_book",
                        lambda data, filename, lib: {"book_id": 777, "title": "Cover Story"})
    return M


def test_add_pushes_the_cover_calibre_would_otherwise_drop(monkeypatch):
    M = _stub_add(monkeypatch, "https://www.royalroad.com/fiction/999002",
                  cover=(b"JPEGBYTES", "image/jpeg"))
    seen = {}
    monkeypatch.setattr(M.calibre, "set_cover",
                        lambda bid, data, media, lib: seen.update(
                            bid=bid, data=data, media=media, lib=lib))
    r = client.post("/books/add",
                    json={"url": "https://www.royalroad.com/fiction/999002"},
                    headers=TOK)
    assert r.status_code == 200, r.text
    assert r.json()["cover_set"] is True
    assert seen["bid"] == 777 and seen["data"] == b"JPEGBYTES"
    assert seen["media"] == "image/jpeg"


def test_add_succeeds_when_the_epub_has_no_cover(monkeypatch):
    _stub_add(monkeypatch, "https://www.royalroad.com/fiction/999003", cover=None)
    r = client.post("/books/add",
                    json={"url": "https://www.royalroad.com/fiction/999003"},
                    headers=TOK)
    assert r.status_code == 200, r.text
    assert r.json()["cover_set"] is False


def test_a_failing_cover_push_does_not_lose_the_book(monkeypatch):
    """The book is already in calibre by then; a cover error must not turn a
    successful add into an error the UI reports as failure."""
    M = _stub_add(monkeypatch, "https://www.royalroad.com/fiction/999004",
                  cover=(b"JPEGBYTES", "image/jpeg"))
    def boom(*a, **k):
        raise M.CalibreError("cover rejected")
    monkeypatch.setattr(M.calibre, "set_cover", boom)
    r = client.post("/books/add",
                    json={"url": "https://www.royalroad.com/fiction/999004"},
                    headers=TOK)
    assert r.status_code == 200, r.text
    assert r.json()["cover_set"] is False and r.json()["book_id"] == 777


def test_image_options_reach_downloads_but_never_metadata_fetches():
    """FanFicFare pulls the cover during METADATA collection when images are
    on, so a Check must not carry the option."""
    from ratchet import sites
    from ratchet.main import cfg as live_cfg
    assert sites.download_options(live_cfg) == ["-o", "include_images=true"]
    assert "include_images" not in " ".join(sites._fff_base_cmd(live_cfg))


def test_duplicate_guard_heals_when_the_book_was_deleted_from_calibre(monkeypatch):
    """Deleting a book in calibre doesn't tell Ratchet, so a stale snapshot
    must not make the story un-re-addable."""
    url = "https://www.royalroad.com/fiction/999005"
    M = _stub_add(monkeypatch, url, cover=None)
    monkeypatch.setattr(M.calibre, "set_cover", lambda *a, **k: None)
    assert client.post("/books/add", json={"url": url}, headers=TOK).status_code == 200

    # Second attempt while calibre still has it: refused.
    monkeypatch.setattr(M, "_book_exists", lambda lib, bid: True)
    dup = client.post("/books/add", json={"url": url}, headers=TOK)
    assert dup.status_code == 409

    # Same attempt once the book is gone from calibre: the stale record is
    # dropped and the add proceeds.
    monkeypatch.setattr(M, "_book_exists", lambda lib, bid: False)
    again = client.post("/books/add", json={"url": url}, headers=TOK)
    assert again.status_code == 200, again.text
    assert again.json()["book_id"] == 777


def test_an_unreachable_calibre_is_not_mistaken_for_a_deleted_book(monkeypatch):
    """_book_exists must raise, not answer False, when calibre can't be
    reached — otherwise an outage silently duplicates books."""
    from ratchet import main as M
    monkeypatch.setattr(M.calibre, "books", lambda ids, lib: (_ for _ in ()).throw(
        M.CalibreError("cannot reach calibre")))
    with pytest.raises(M.CalibreError):
        M._book_exists("Serials", 1)


def test_book_exists_reads_calibres_null_entry_as_absent(monkeypatch):
    from ratchet import main as M
    monkeypatch.setattr(M.calibre, "books", lambda ids, lib: {"5": None})
    assert M._book_exists("Serials", 5) is False
    monkeypatch.setattr(M.calibre, "books", lambda ids, lib: {"5": {"title": "T"}})
    assert M._book_exists("Serials", 5) is True


def test_every_declared_sound_has_a_file_that_ships():
    """A misspelt sound name fails silently at runtime — the UI simply plays
    nothing — so the names in sfx.js are checked against what is on disk."""
    js = client.get("/ui/sfx.js").text
    taps = re.findall(r'"([^"]+)"',
                      re.search(r"const TAPS = \[(.*?)\]", js, re.S).group(1))
    names = re.findall(r'"([^"]+)"',
                       re.search(r"const NAMES = \[(.*?)\]", js, re.S).group(1))
    exts = re.findall(r'"([^"]+)"',
                      re.search(r"const EXTS = \[(.*?)\]", js, re.S).group(1))
    sfx_dir = Path(__file__).resolve().parents[1] / "ratchet" / "static" / "sfx"
    assert len(taps) >= 2, "the random tap needs something to choose between"
    for name in set(names + taps):
        assert any((sfx_dir / f"{name}.{ext}").is_file() for ext in exts), name


def test_navigation_sounds_are_wired_through_the_view_event():
    """core.js announces view changes and sfx.js listens, the same
    one-directional arrangement as the 401 sound; an import the other way
    would make the two modules circular."""
    core = client.get("/ui/core.js").text
    sfx = client.get("/ui/sfx.js").text
    assert "VIEW_CHANGED_EVENT" in core and "dispatchEvent" in core
    assert "VIEW_CHANGED_EVENT" in sfx and '"page-shift"' in sfx
    assert not re.search(r"""^\s*import[^\n]*["']\./sfx\.js["']""", core, re.M)
