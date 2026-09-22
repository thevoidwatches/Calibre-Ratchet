"""The setup wizard's web app, run against a scratch folder with the machine
stubbed out: nothing here touches a real config, Tailscale or calibre."""

import shutil
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ratchet.config import _load_env_file, load_config  # noqa: E402
from ratchet.wizard import app as wizard  # noqa: E402
from ratchet.wizard import system  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]
KEY = "test-key"
KEYED = {"X-Setup-Key": KEY}

TAILNET = {"installed": True, "running": True, "state": "Running",
           "ip": "100.64.0.7", "name": "my-pc.tail1234.ts.net",
           "short_name": "my-pc"}


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A fresh unpacked Ratchet: the example config and nothing else."""
    shutil.copy(SERVER / "config.example.toml", tmp_path / "config.example.toml")
    monkeypatch.setattr(wizard, "tailscale_self", lambda: dict(TAILNET))
    monkeypatch.setattr(wizard, "_default_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(system, "reach_status", lambda port: {
        "known": True, "enabled": False, "other": ""})
    monkeypatch.setattr(system, "autostart_status", lambda: {
        "applicable": True, "enabled": False})
    monkeypatch.setattr(system, "service_running", lambda host, port: False)
    return tmp_path


@pytest.fixture
def client(folder):
    # base_url gives requests the Host a browser on this machine would send.
    return TestClient(wizard.create_app(folder, KEY),
                      base_url="http://127.0.0.1:8485")


def save(client, **calibre):
    body = {"calibre": {"base_url": "http://127.0.0.1:8080", **calibre},
            "password": calibre.pop("password", None)}
    body["calibre"].pop("password", None)
    return client.post("/api/save", json=body, headers=KEYED)


# ---- who may call it ---------------------------------------------------

def test_a_call_without_the_key_is_refused(client):
    """Any page open in the same browser can send requests to localhost.
    What it cannot do is know a key made fresh for this run."""
    assert client.get("/api/state").status_code == 403
    assert client.get("/api/state", headers={"X-Setup-Key": "guess"}).status_code == 403
    assert client.post("/api/save", json={"calibre": {}}).status_code == 403
    assert client.get("/api/state", headers=KEYED).status_code == 200


def test_every_api_route_asks_for_the_key(folder):
    """So that one added later cannot be forgotten."""
    app = wizard.create_app(folder, KEY)
    client = TestClient(app, base_url="http://127.0.0.1:8485")
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/api/")]
    assert len(routes) >= 7
    for route in routes:
        method = "GET" if "GET" in route.methods else "POST"
        assert client.request(method, route.path, json={}).status_code == 403, route.path


def test_a_request_addressed_to_another_name_is_refused(folder):
    """DNS rebinding: a hostile page points its own domain at 127.0.0.1, and
    the browser then treats this server as that page's origin. The request
    still says which name it was meant for."""
    evil = TestClient(wizard.create_app(folder, KEY), base_url="http://evil.example:8485")
    assert evil.get("/api/state", headers=KEYED).status_code == 403
    assert evil.get("/").status_code == 403
    for good in ("http://127.0.0.1:9", "http://localhost:9"):
        ok = TestClient(wizard.create_app(folder, KEY), base_url=good)
        assert ok.get("/api/state", headers=KEYED).status_code == 200


def test_the_page_itself_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Ratchet" in r.text
    assert client.get("/wizard.js").status_code == 200


# ---- a first run -------------------------------------------------------

def test_a_fresh_folder_reports_nothing_configured(client):
    got = client.get("/api/state", headers=KEYED).json()
    assert got["configured"] is False
    assert got["calibre"]["base_url"] == "http://127.0.0.1:8080"
    assert got["phone"]["token"] == "" and got["phone"]["token_qr"] == ""


def test_a_first_save_makes_a_config_the_service_will_start_with(client, folder):
    r = save(client, username="reader", password="s3cret", library_id="Fiction",
             genre_field="#kind", fandom_field="", majchar_field="",
             row_field="", lastupdate_field="")
    assert r.status_code == 200, r.text
    cfg = load_config(folder / "config.toml")          # the service's own loader
    assert cfg.calibre.library_id == "Fiction"
    assert cfg.calibre.genre_field == "#kind"
    assert cfg.calibre.fandom_field == ""              # not the example's "#fandom"
    assert cfg.calibre.username == "reader" and cfg.calibre.password == "s3cret"
    assert len(cfg.service.auth_token) >= 32


def test_a_new_config_listens_on_this_machine_only(client, folder):
    """Tailscale is what lets the tailnet in, so nothing needs the firewall
    opened — which is the thing a setup tool should not be asking for."""
    save(client)
    assert load_config(folder / "config.toml").service.host == "127.0.0.1"


def test_a_new_config_keeps_the_examples_comments(client, folder):
    save(client)
    text = (folder / "config.toml").read_text(encoding="utf-8")
    assert text.count("#") > 40 and "[fanficfare]" in text


def test_secrets_go_to_env_and_not_into_config_toml(client, folder):
    save(client, username="reader", password="s3cret")
    config = (folder / "config.toml").read_text(encoding="utf-8")
    assert "s3cret" not in config
    env = _load_env_file(folder / ".env")
    assert env["RATCHET_CALIBRE_PASSWORD"] == "s3cret"
    assert env["RATCHET_AUTH_TOKEN"] not in config


def test_the_saved_password_is_never_sent_to_the_page(client):
    save(client, username="reader", password="s3cret")
    body = client.get("/api/state", headers=KEYED)
    assert "s3cret" not in body.text
    assert body.json()["calibre"]["has_password"] is True


# ---- a later run -------------------------------------------------------

def test_saving_again_keeps_the_token_devices_already_have(client, folder):
    save(client)
    first = _load_env_file(folder / ".env")["RATCHET_AUTH_TOKEN"]
    save(client, library_id="Other")
    assert _load_env_file(folder / ".env")["RATCHET_AUTH_TOKEN"] == first


def test_an_empty_password_box_leaves_the_saved_password_alone(client, folder):
    save(client, username="reader", password="s3cret")
    save(client, username="reader")                    # password: null
    assert _load_env_file(folder / ".env")["RATCHET_CALIBRE_PASSWORD"] == "s3cret"


def test_an_existing_config_is_edited_not_replaced(client, folder):
    """Someone's own comments, settings the wizard knows nothing about, and
    a host they chose themselves all have to survive a visit."""
    (folder / "config.toml").write_text(
        '[service]\nhost = "tailscale"   # direct, with my own firewall rule\n'
        'port = 9000\n\n[calibre]\nbase_url = "http://127.0.0.1:8080"\n'
        'library_id = ""\n\n[fanficfare]\n'
        'blocked_sites = ["archiveofourown.org"]   # temporary, 2026-08-27\n',
        encoding="utf-8")
    (folder / ".env").write_text("RATCHET_AUTH_TOKEN=mine\n", encoding="utf-8")
    r = save(client, library_id="Serials")
    assert r.status_code == 200, r.text
    text = (folder / "config.toml").read_text(encoding="utf-8")
    assert "# direct, with my own firewall rule" in text
    assert "# temporary, 2026-08-27" in text
    got = tomllib.loads(text)
    assert got["service"] == {"host": "tailscale", "port": 9000}   # untouched
    assert got["calibre"]["library_id"] == "Serials"
    assert _load_env_file(folder / ".env")["RATCHET_AUTH_TOKEN"] == "mine"


def test_what_was_there_before_is_kept_beside_it(client, folder):
    (folder / "config.toml").write_text(
        '[calibre]\nbase_url = "http://127.0.0.1:8080"\n', encoding="utf-8")
    (folder / ".env").write_text("RATCHET_AUTH_TOKEN=mine\n", encoding="utf-8")
    save(client, library_id="Serials")
    assert (folder / "config.toml.bak").read_text(encoding="utf-8") == \
        '[calibre]\nbase_url = "http://127.0.0.1:8080"\n'


def test_a_windows_config_keeps_its_line_endings(client, folder):
    original = b'[calibre]\r\nbase_url = "http://127.0.0.1:8080"\r\nlibrary_id = ""\r\n'
    (folder / "config.toml").write_bytes(original)
    (folder / ".env").write_bytes(b"RATCHET_AUTH_TOKEN=mine\r\n")
    save(client, library_id="Serials")
    after = (folder / "config.toml").read_bytes()
    assert after.count(b"\r\n") == 3 and after.count(b"\n") == 3


# ---- direct setups, and the phone --------------------------------------

def test_a_direct_setup_is_recognised_and_not_forwarded_over(client, folder):
    """Ratchet listening on the tailnet address and Tailscale forwarding the
    same port would fight, and Tailscale would win with nothing behind it."""
    (folder / "config.toml").write_text('[service]\nhost = "tailscale"\n',
                                        encoding="utf-8")
    (folder / ".env").write_text("RATCHET_AUTH_TOKEN=mine\n", encoding="utf-8")
    assert client.get("/api/state", headers=KEYED).json()["direct"] is True
    r = client.post("/api/reach", json={"enable": True}, headers=KEYED)
    assert r.status_code == 409


def test_the_phone_gets_a_name_to_type_and_a_code_to_scan(client):
    save(client)
    phone = client.get("/api/state", headers=KEYED).json()["phone"]
    assert phone["address"] == "my-pc"                         # short: typed
    assert phone["apk_url"] == "http://my-pc.tail1234.ts.net:8484/apk"  # full: scanned
    assert phone["apk_qr"].startswith("<svg") and phone["token_qr"].startswith("<svg")
    assert len(phone["token"]) >= 32


def test_a_qr_code_is_an_image_a_browser_will_draw(client):
    """The page shows each code as an <img>, and a browser draws an SVG image
    only if it declares the SVG namespace. They once did not — the text began
    "<svg", a check on that passed, and the page showed two white squares.
    So: read it as the standalone XML file a browser is handed."""
    import xml.etree.ElementTree as ET
    save(client)
    phone = client.get("/api/state", headers=KEYED).json()["phone"]
    for name in ("apk_qr", "token_qr"):
        root = ET.fromstring(phone[name])              # well-formed by itself
        assert root.tag == "{http://www.w3.org/2000/svg}svg", name
        drawn = [el for el in root.iter() if el.tag.endswith("path")]
        # A light background and the dark modules on top of it.
        colours = {el.get("fill") or el.get("stroke") for el in drawn}
        assert colours == {"#fff", "#000"}, name
        assert max(len(el.get("d", "")) for el in drawn) > 200, name


def test_without_magicdns_the_address_is_the_tailnet_ip(client, monkeypatch):
    monkeypatch.setattr(wizard, "tailscale_self", lambda: {
        **TAILNET, "name": "", "short_name": ""})
    save(client)
    phone = client.get("/api/state", headers=KEYED).json()["phone"]
    assert phone["address"] == "100.64.0.7"
    assert phone["apk_url"] == "http://100.64.0.7:8484/apk"


# ---- the files that describe the library -------------------------------

@pytest.fixture
def config_folder(folder, monkeypatch):
    """A config/ of its own, with the shipped examples in it."""
    from ratchet import configfiles
    real = configfiles.CONFIG_DIR
    scratch = folder / "config"
    scratch.mkdir()
    for example in real.glob("*.example.*"):
        shutil.copy(example, scratch / example.name)
    monkeypatch.setattr(configfiles, "CONFIG_DIR", scratch)
    return scratch


def test_the_state_says_which_library_files_exist(client, config_folder):
    (config_folder / "tag_rules.txt").write_text("FanFiction = -\n", encoding="utf-8")
    library = client.get("/api/state", headers=KEYED).json()["library"]
    assert library["tag_rules.txt"]["exists"] is True
    assert library["tag_scheme.toml"]["exists"] is False
    assert set(library) == {"tag_rules.txt", "tag_scheme.toml", "ao3_names.txt"}


def test_a_file_is_started_from_its_example(client, config_folder):
    r = client.post("/api/library/create", json={"file": "tag_scheme.toml"}, headers=KEYED)
    assert r.status_code == 200
    assert (config_folder / "tag_scheme.toml").read_bytes() == \
        (config_folder / "tag_scheme.example.toml").read_bytes()


def test_creating_never_replaces_a_file_that_is_there(client, config_folder):
    mine = config_folder / "tag_rules.txt"
    mine.write_text("# a year of decisions\n", encoding="utf-8")
    r = client.post("/api/library/create", json={"file": "tag_rules.txt"}, headers=KEYED)
    assert r.status_code == 409
    assert mine.read_text(encoding="utf-8") == "# a year of decisions\n"


@pytest.mark.parametrize("name", ["../server/.env", "..\\server\\config.toml",
                                  "C:/Windows/win.ini", "tag_rules.txt/../x", ""])
def test_only_the_three_known_files_can_be_named(client, config_folder, monkeypatch, name):
    """These calls create and open files on request, so they take a name
    from a fixed list — never a path."""
    monkeypatch.setattr(system, "open_in_editor",
                        lambda p: pytest.fail(f"opened {p}"))
    for call in ("create", "open"):
        r = client.post(f"/api/library/{call}", json={"file": name}, headers=KEYED)
        assert r.status_code == 404, (call, name)


def test_opening_hands_the_editor_the_real_file(client, config_folder, monkeypatch):
    opened = []
    monkeypatch.setattr(system, "open_in_editor",
                        lambda p: opened.append(p) or {"ok": True, "message": ""})
    (config_folder / "ao3_names.txt").write_text("A = B\n", encoding="utf-8")
    client.post("/api/library/open", json={"file": "ao3_names.txt"}, headers=KEYED)
    assert opened == [config_folder / "ao3_names.txt"]
    r = client.post("/api/library/open", json={"file": "tag_scheme.toml"}, headers=KEYED)
    assert r.status_code == 404                     # not made yet


def test_the_check_wants_the_settings_saved_first(client, config_folder):
    assert client.post("/api/library/check", json={}, headers=KEYED).status_code == 409


def test_the_check_reports_each_file_and_changes_none(client, config_folder, monkeypatch):
    from ratchet.calibre import CalibreError

    class Unreachable:
        def __init__(self, *a, **k): pass
        def libraries(self): raise CalibreError("cannot reach calibre")

    monkeypatch.setattr(wizard, "CalibreClient", Unreachable)
    save(client, genre_field="#genre", fandom_field="", majchar_field="")
    rules = config_folder / "tag_rules.txt"
    rules.write_text("Angst = genre: Angst\nThe Watch = majcher: Disc.Vimes\n"
                     "FanFiction -\n", encoding="utf-8")
    before = rules.read_bytes()

    got = client.post("/api/library/check", json={}, headers=KEYED).json()
    assert got["compared"] is False                 # calibre could not be asked
    found = got["files"]["tag_rules.txt"]["findings"]
    assert [f["line"] for f in found if f["level"] == "error"] == [2, 3]
    assert got["files"]["tag_scheme.toml"] == {
        "exists": False, "path": str(config_folder / "tag_scheme.toml"), "findings": []}
    assert rules.read_bytes() == before


def test_a_calibre_that_refuses_the_login_says_where_logins_are_set(client, monkeypatch):
    from ratchet.calibre import CalibreError

    class Refusing:
        def __init__(self, *a, **k): pass
        def libraries(self): raise CalibreError("GET /ajax/library-info -> 401: no")

    monkeypatch.setattr(wizard, "CalibreClient", Refusing)
    got = client.post("/api/calibre/test", headers=KEYED, json={
        "base_url": "http://127.0.0.1:8080", "username": "x", "password": "y"}).json()
    assert got["ok"] is False and "User accounts" in got["message"]
