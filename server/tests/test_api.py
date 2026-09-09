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


def test_sort_options_are_published_and_default_to_last_updated():
    body = client.get("/ui-config", headers=TOK).json()
    keys = [o["key"] for o in body["sort_options"]]
    assert keys == ["title", "series", "author", "updated", "pages"]
    assert body["default_sort"] == "updated"


def test_the_sort_a_device_already_remembers_still_works():
    """A phone stores the sort it was last set to. "modified" was that sort
    for a long time, and answering 400 would leave such a device unable to
    list anything until someone cleared its storage."""
    r = client.get("/books", params={"sort": "modified"}, headers=TOK)
    assert r.status_code == 502          # reached calibre, i.e. was accepted


def test_nothing_is_written_when_no_field_records_it(monkeypatch):
    """A user who has made no column must not have books written to."""
    from ratchet import main
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "")
    monkeypatch.setattr(main.calibre, "set_fields",
                        lambda *a, **k: pytest.fail("wrote to calibre"))
    main._record_last_update("Serials", 7)
    main._record_last_update("Serials", 7, new_book=True)


def test_an_update_records_when_the_content_arrived(monkeypatch):
    from ratchet import main
    written = {}
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "#lastupdate")
    monkeypatch.setattr(main.calibre, "set_fields",
                        lambda bid, changes, lib: written.update(
                            {"book": bid, "lib": lib, **changes}))
    main._record_last_update("Serials", 7)
    assert written["book"] == 7 and written["lib"] == "Serials"
    # An ISO instant, so calibre stores it as the datetime it is.
    from datetime import datetime
    assert datetime.fromisoformat(written["#lastupdate"]).tzinfo is not None


def test_adding_a_book_does_not_rewrite_the_date_calibre_just_set(monkeypatch):
    """With "timestamp" configured, calibre stamped Date moments earlier;
    writing it again would only move it by the length of the add."""
    from ratchet import main
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "timestamp")
    monkeypatch.setattr(main.calibre, "set_fields",
                        lambda *a, **k: pytest.fail("rewrote Date on add"))
    main._record_last_update("Serials", 7, new_book=True)


def test_a_failure_to_record_does_not_fail_the_update(monkeypatch):
    """The epub is already in calibre by then — a bad sort order is not worth
    reporting the update as failed."""
    from ratchet import main
    from ratchet.calibre import CalibreError

    def boom(*a, **k):
        raise CalibreError("no such column")

    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "#lastupdate")
    monkeypatch.setattr(main.calibre, "set_fields", boom)
    main._record_last_update("Serials", 7)      # must not raise


def test_unknown_sort_is_rejected_not_silently_ignored():
    """calibre answers 200 for a sort field it doesn't know, so Ratchet has to
    be the one that refuses."""
    r = client.get("/books", params={"sort": "nonsense"}, headers=TOK)
    assert r.status_code == 400
    r = client.get("/books", params={"sort_order": "sideways"}, headers=TOK)
    assert r.status_code == 400


def test_known_sorts_reach_calibre():
    for key in ["title", "series", "author", "updated"]:
        r = client.get("/books", params={"sort": key, "sort_order": "asc"}, headers=TOK)
        assert r.status_code == 502, key   # calibre unreachable, but sort accepted


def test_last_updated_reads_date_when_nothing_records_it():
    """The default: no column to make, no book written to, and a sort that
    still means something."""
    from ratchet import main
    assert main.cfg.calibre.lastupdate_field == ""
    assert main._sort_field("updated", "Whatever") == "timestamp"


def test_last_updated_reads_the_configured_column(monkeypatch):
    from ratchet import main
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "#lastupdate")
    monkeypatch.setattr(main, "_sortable", lambda lib, sort: True)
    # Date as the tie-break, so books sharing a value still have an order.
    assert main._sort_field("updated", "Serials") == "#lastupdate,timestamp"


def test_a_library_without_the_column_falls_back_to_date(monkeypatch):
    """calibre answers 404 for a sort field a library has not got, so a
    library that never had the column has to be sorted by Date instead."""
    from ratchet import main
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "#lastupdate")
    monkeypatch.setattr(main, "_sortable", lambda lib, sort: False)
    assert main._sort_field("updated", "Books") == "timestamp"


def test_overwriting_date_needs_no_column_and_no_tie_break(monkeypatch):
    from ratchet import main
    monkeypatch.setattr(main.cfg.calibre, "lastupdate_field", "timestamp")
    assert main._sort_field("updated", "Serials") == "timestamp"


def test_whether_a_library_can_sort_by_something_is_asked_once(monkeypatch):
    """Once per library: a column is not added or dropped while the service
    runs, and asking again would cost a round trip on every listing."""
    from ratchet import main
    from ratchet.calibre import CalibreError
    calls = []

    def search(**kw):
        calls.append(kw["library_id"])
        if kw["library_id"] == "Books":
            raise CalibreError("not a valid sort field")
        return {"book_ids": []}

    monkeypatch.setattr(main.calibre, "search", search)
    main._sortable_cache.clear()
    for _ in range(3):
        assert main._sortable("Serials", "#lastupdate,timestamp") is True
        assert main._sortable("Books", "#lastupdate,timestamp") is False
    assert calls == ["Serials", "Books"]
    main._sortable_cache.clear()


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
    assert "\u25b6" in css and "\u25bc" in css        # closed / open markers
    assert not [c for c in css if ord(c) < 32 and c not in "\r\n\t"]
    # The same glyphs the filter bar and the value tree draw, so every place
    # that opens something reads alike.
    for path in ("/ui/browse.js", "/ui/picker.js"):
        text = client.get(path).text
        assert "\u25b6" in text and "\u25bc" in text, path
        assert not [c for c in text if ord(c) < 32 and c not in "\r\n\t"], path


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


def test_adding_a_book_applies_the_tag_rules(monkeypatch, tmp_path):
    """calibre imports the epub's own subjects as tags on add, so FanFicFare's
    "In-Progress" and "Last Update: ..." land in the library unless something
    rewrites them. The service does it as the book arrives, using the same
    rules the sweep script uses — see ratchet/tagmap.py."""
    from ratchet import main as M
    from ratchet.epub import Chapter

    rules = tmp_path / "tag_rules.txt"
    rules.write_text('In-Progress = Serial.Ongoing\n'
                     'Last Update* = -\n'
                     'Angst = genre: Angst\n', encoding="utf-8")
    monkeypatch.setattr(M.cfg.tags, "rules_file", str(rules))

    chs = [Chapter(key="c1", url="https://site/1", title="One")]
    url = "https://www.royalroad.com/fiction/626262"
    monkeypatch.setattr(M, "normalize_story_url", lambda u: url)
    monkeypatch.setattr(M, "fetch_remote", lambda u, cfg: M.RemoteStory(
        title="Tagged Story", site="royalroad.com", status="In-Progress",
        chapters=chs, raw={}))

    def fake_run_fff(args, cfg):
        out = next(a for a in args if a.startswith("output_filename=")
                   ).split("=", 1)[1]
        Path(out).write_bytes(b"stub epub")

        class Proc:
            returncode, stdout, stderr = 0, "", ""
        return Proc()
    monkeypatch.setattr(M, "run_fff", fake_run_fff)
    monkeypatch.setattr(M.epub_mod, "extract_chapters", lambda p: chs)
    monkeypatch.setattr(M.calibre, "add_book",
                        lambda *a: {"book_id": 5151, "title": "Tagged Story"})
    # What calibre holds once it has imported the epub's own subjects.
    monkeypatch.setattr(M.calibre, "books", lambda ids, lib=None, **k: {"5151": {
        "tags": ["In-Progress", "Last Update: 2026/09/09", "Angst",
                 "Tropes.Something"],
        "user_metadata": {"#genre": {"#value#": []}}}})
    written = {}
    monkeypatch.setattr(M.calibre, "set_fields",
                        lambda bid, changes, lib=None: written.update(changes))

    r = client.post("/books/add", json={"url": url}, headers=TOK)
    assert r.status_code == 200, r.text

    # Renamed, deleted by pattern, moved to a column — and the tag nobody has
    # ruled on is still there.
    assert written["tags"] == ["Serial.Ongoing", "Tropes.Something"]
    assert written["#genre"] == ["Angst"]
    assert r.json()["tags_changed"]["tags"] == ["Serial.Ongoing", "Tropes.Something"]


def test_a_book_the_rules_do_not_touch_costs_no_calibre_write(monkeypatch, tmp_path):
    from ratchet import main as M
    rules = tmp_path / "tag_rules.txt"
    rules.write_text('FanFiction = -\n', encoding="utf-8")
    monkeypatch.setattr(M.cfg.tags, "rules_file", str(rules))
    monkeypatch.setattr(M.calibre, "books", lambda ids, lib=None, **k: {"7": {
        "tags": ["Tropes.Something"], "user_metadata": {}}})
    calls = []
    monkeypatch.setattr(M.calibre, "set_fields", lambda *a, **k: calls.append(a))
    assert M._apply_tag_rules("Fanfiction", 7) == {}
    assert calls == []


def test_tag_rules_never_fail_an_add(monkeypatch, tmp_path):
    """The book is in the library and verified by then; tags that did not get
    rewritten are a tidiness problem, not a reason to report failure."""
    from ratchet import main as M
    from ratchet.calibre import CalibreError
    rules = tmp_path / "tag_rules.txt"
    rules.write_text('In-Progress = Serial.Ongoing\n', encoding="utf-8")
    monkeypatch.setattr(M.cfg.tags, "rules_file", str(rules))

    def boom(*a, **k):
        raise CalibreError("calibre went away")
    monkeypatch.setattr(M.calibre, "books", boom)
    assert M._apply_tag_rules("Fanfiction", 7) == {}


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
    assert "VIEW_CHANGED_EVENT" in sfx and 'play("select")' in sfx
    assert not re.search(r"""^\s*import[^\n]*["']\./sfx\.js["']""", core, re.M)


def test_volume_is_persisted_and_applied_to_playback():
    """The slider is useless if the level is not reapplied on later sounds:
    each is a cached Audio element resolved once and reused."""
    sfx = client.get("/ui/sfx.js").text
    assert "ratchet_volume" in sfx
    assert "audio.volume = gain()" in sfx
    # Zero volume must silence playback outright, not just turn it down.
    assert "volume === 0" in sfx


def test_volume_popover_ships_with_the_page():
    html = client.get("/ui/").text
    assert 'id="volPop"' in html and 'id="volRange"' in html
    assert 'type="range"' in html
    css = client.get("/ui/ui.css").text
    assert ".volpop" in css


def test_apk_info_requires_a_token_and_404s_without_a_build():
    """/apk itself is deliberately open (a phone browser cannot send the
    header on a download); the metadata behind it is not."""
    assert client.get("/apk-info").status_code == 401
    # No APK is deployed in the test data dir.
    assert client.get("/apk-info", headers=TOK).status_code == 404


def test_apk_info_reports_when_the_build_was_made(tmp_path):
    from ratchet.main import cfg
    apk = cfg.data_dir / "ratchet.apk"
    apk.write_bytes(b"not really an apk")
    try:
        body = client.get("/apk-info", headers=TOK).json()
        assert body["size"] == 17
        # Milliseconds, to compare against the device's install time.
        assert body["built_at"] > 1_600_000_000_000
    finally:
        apk.unlink()


def test_shared_and_clipboard_urls_go_through_one_add_path():
    """The share sheet, the clipboard pre-fill and the button must all queue
    the same way, or only the button's careful behaviour is tested."""
    browse = client.get("/ui/browse.js").text
    assert "export function queueAdd" in browse
    assert "export function firstUrl" in browse
    app = client.get("/ui/app.js").text
    assert "queueAdd(shared)" in app
    # A share into a running app never reloads the page.
    assert "checkSharedStory" in app and "visibilitychange" in app


def test_metadata_links_are_wired_without_a_module_cycle():
    """browse.js already imports detail.js for openBook, so the book page
    asks for a filter by event rather than importing back."""
    detail = client.get("/ui/detail.js").text
    browse = client.get("/ui/browse.js").text
    assert "FILTER_BY_EVENT" in detail and "dispatchEvent" in detail
    assert "FILTER_BY_EVENT" in browse and "addEventListener" in browse
    assert not re.search(r"""^\s*import[^\n]*["']\./browse\.js["']""", detail, re.M)


def test_filter_picker_sorts_and_filters_its_values():
    """The vocabulary arrives in category-walk order, which reads as random;
    and a long one needs to be reachable by typing, not only by scrolling."""
    picker = client.get("/ui/picker.js").text
    # Values sorted, and the tree's children sorted per level too.
    assert "localeCompare" in picker
    assert picker.count("localeCompare") >= 3, "values, tree levels, saved sets"
    # The existing "type a value" box doubles as the filter.
    assert 'freeValue").addEventListener("input"' in picker
    html = client.get("/ui/").text
    assert 'placeholder="filter, or type a value"' in html


UI_MODULES = ["app.js", "browse.js", "picker.js", "detail.js", "actions.js",
              "filters.js", "storage.js", "catalog.js", "theme.js"]


def test_every_error_message_sounds_exactly_once():
    """core.js announces err(); sfx.js plays it — so no caller may also play
    "error" beside an err() call, or a failure would sound twice. Same
    event-not-import arrangement as the 401 and the view changes."""
    core = client.get("/ui/core.js").text
    sfx = client.get("/ui/sfx.js").text
    assert "ERROR_EVENT" in core and "dispatchEvent(new CustomEvent(ERROR_EVENT" in core
    assert "ERROR_EVENT" in sfx and 'play((e.detail && e.detail.kind) || "error")' in sfx
    for name in UI_MODULES:
        js = client.get("/ui/" + name).text
        for m in re.finditer(r"(?<![A-Za-z])err\(", js):
            window = js[m.start():m.start() + 160]
            assert 'play("error")' not in window, f"{name}: {window!r}"
    # The one refusal shown through err() says so, and sounds so.
    assert '"refused");' in client.get("/ui/picker.js").text


def test_one_action_one_sound():
    """Controls whose click ends in a view change sound for that, not for the
    click as well; a filter chip's body, which does nothing, sounds not at
    all while its × still does."""
    sfx = client.get("/ui/sfx.js").text
    elsewhere = sfx.split("const SOUNDED_ELSEWHERE")[1].split("].join")[0]
    for sel in ['"#btnFreeValue"', '".gofilter"', '"[data-nav]"', '"#results li"']:
        assert sel in elsewhere, sel
    assert 'INERT = "#filterChips .chip"' in sfx
    assert "const hit = t.closest(TAPPABLE)" in sfx and "hit.matches(INERT)" in sfx


def test_the_quiet_corners_now_sound():
    """The overlay, the dropdown choices, the saved-set buttons, the Read
    hand-off, and the Enter key where there is no form to submit."""
    detail = client.get("/ui/detail.js").text
    assert detail.count('play("select")') >= 3      # cover open, cover close, link out
    app = client.get("/ui/app.js").text
    assert app.count('play("select")') >= 3          # library, sort, apk link
    assert 'tokenInput").addEventListener("keydown"' in app
    filters = client.get("/ui/filters.js").text
    assert filters.count('play("success")') == 2 and 'play("select")' in filters
    picker = client.get("/ui/picker.js").text
    assert 'freeValue").addEventListener("keydown"' in picker
    actions = client.get("/ui/actions.js").text
    assert 'if (d.action === "update") play("success")' in actions
    assert actions.count('play("success")') >= 5     # + read hand-off
    sfx = client.get("/ui/sfx.js").text
    assert 'play("tap")' in sfx.split("function openVolume")[1].split("}")[0]
