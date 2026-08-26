"""App-level tests that don't need a live calibre or fic site.

main.py loads its config at import time, so the config file + env var must
exist before the import — hence the module-level setup.
"""

import os
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
