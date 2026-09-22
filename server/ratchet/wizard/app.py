"""The wizard's web app: a page and the handful of calls behind it.

It writes configuration, asks Tailscale to forward a port and starts a
program, and it has no login — there is nothing yet to log in with, since
producing the token is part of what it is for. So what protects it is where
it listens and what it demands of a caller:

  * it is bound to 127.0.0.1, so no other machine can reach it
  * every call must carry a key made fresh each run and handed only to the
    browser tab the wizard itself opens — another page in that browser can
    send requests to localhost, but cannot know the key
  * the Host header must name this machine, which is what stops a page on a
    hostile domain re-pointing its own name at 127.0.0.1 to get past the
    browser's same-origin rule (DNS rebinding)
"""

from __future__ import annotations

import io
import secrets
import tomllib
from pathlib import Path

import segno
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import configcheck, configfiles, tagmap
from ..calibre import CalibreClient, CalibreError
from ..config import (_default_data_dir, _load_env_file, load_config,
                      tailscale_self)
from . import system
from .configwrite import ConfigEditError, set_env, set_values

STATIC = Path(__file__).parent / "static"

# The settings the page edits, as (section, key) in config.toml. Secrets are
# not among them: those go to .env, where the example says to keep them.
_CALIBRE_KEYS = ("base_url", "library_id", "genre_field", "fandom_field",
                 "majchar_field", "row_field", "lastupdate_field")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _read(path: Path) -> str:
    """As it is on disk, line endings included — configwrite keeps a file's
    own, and cannot if Python has already translated them away."""
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    """Replace a file, keeping what it was as <name>.bak beside it."""
    if path.is_file():
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _qr(text: str) -> str:
    """A QR code as a standalone SVG image. Always dark on light, whatever
    the page's theme: that is what a phone's camera expects to find.

    Standalone, namespace and all, because the page shows it as an <img>
    rather than pasting it into its own markup — and a browser will not draw
    an SVG image that does not declare itself one. segno's svg_inline()
    leaves the declaration out, being meant for pasting; used here it gave
    two blank white squares.
    """
    out = io.BytesIO()
    segno.make(text, error="m").save(
        out, kind="svg", xmldecl=False, svgns=True, nl=False,
        scale=5, border=2, dark="#000", light="#fff")
    return out.getvalue().decode("utf-8")


def create_app(server_dir: Path, key: str) -> FastAPI:
    """The wizard for the Ratchet whose config.toml lives in `server_dir`."""
    config_path = server_dir / "config.toml"
    example_path = server_dir / "config.example.toml"
    env_path = server_dir / ".env"
    app = FastAPI(title="Ratchet setup", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def this_machine_only(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host.strip("[]") not in _LOOPBACK:
            return JSONResponse({"detail": "the setup wizard answers only "
                                           "to this machine"}, status_code=403)
        return await call_next(request)

    def keyed(x_setup_key: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_setup_key, key):
            raise HTTPException(403, "missing or wrong setup key — open the "
                                     "wizard from its own window")

    KEYED = [Depends(keyed)]

    # ---- what is already there -----------------------------------------

    def saved() -> dict:
        """config.toml and .env as they stand, read leniently: the service's
        own loader refuses a config with no token, and a half-finished
        config is exactly what this has to be able to look at."""
        try:
            data = tomllib.loads(_read(config_path)) if config_path.is_file() else {}
        except tomllib.TOMLDecodeError:
            data = {}
        env = _load_env_file(env_path)
        return {"toml": data, "env": env}

    def service_settings() -> tuple[str, int, Path]:
        service = saved()["toml"].get("service", {})
        data_dir = service.get("data_dir")
        return (str(service.get("host", system.LOCAL_HOST)),
                int(service.get("port", 8484)),
                Path(data_dir).expanduser() if data_dir else
                _default_data_dir().expanduser())

    def state() -> dict:
        now = saved()
        calibre = now["toml"].get("calibre", {})
        host, port, data_dir = service_settings()
        tailnet = tailscale_self()
        direct = config_path.is_file() and host not in _LOOPBACK
        # How a device on the tailnet names this machine. The full name for
        # anything scanned, since it always resolves; the short one for
        # anything typed, since Tailscale on the device completes it.
        named = tailnet["name"] or tailnet["ip"]
        typed = tailnet["short_name"] or tailnet["ip"]
        token = now["env"].get("RATCHET_AUTH_TOKEN") or \
            now["toml"].get("service", {}).get("auth_token", "")
        apk_url = f"http://{named}:{port}/apk" if named else ""
        return {
            "configured": config_path.is_file() and bool(token),
            "calibre": {
                **{k: calibre.get(k, "") for k in _CALIBRE_KEYS},
                "base_url": calibre.get("base_url", "http://127.0.0.1:8080"),
                "username": now["env"].get("RATCHET_CALIBRE_USERNAME")
                or calibre.get("username", ""),
                # Whether one is saved, never what it is.
                "has_password": bool(now["env"].get("RATCHET_CALIBRE_PASSWORD")
                                     or calibre.get("password")),
            },
            "port": port,
            "direct": direct,
            "tailscale": tailnet,
            "reach": system.reach_status(port),
            "autostart": system.autostart_status(),
            "apk": system.apk_status(data_dir),
            "running": system.service_running(
                system.LOCAL_HOST if not direct else (tailnet["ip"] or host), port),
            "library": {name: {"exists": library_file(name).is_file(),
                               "path": str(library_file(name))}
                        for name in configcheck.FILES},
            "phone": {
                "address": typed, "address_full": named, "apk_url": apk_url,
                "token": token,
                "apk_qr": _qr(apk_url) if apk_url else "",
                "token_qr": _qr(token) if token else "",
            },
        }

    @app.get("/api/state", dependencies=KEYED)
    def get_state() -> dict:
        return state()

    # ---- calibre -------------------------------------------------------

    @app.post("/api/calibre/test", dependencies=KEYED)
    def calibre_test(base_url: str = Body(...), username: str = Body(""),
                     password: str | None = Body(None)) -> dict:
        """Try the connection and report what is on the other end: the
        libraries, and each one's custom columns to choose settings from."""
        if password is None:          # "the one already saved"
            now = saved()
            password = now["env"].get("RATCHET_CALIBRE_PASSWORD") or \
                now["toml"].get("calibre", {}).get("password", "")
        client = CalibreClient(base_url.strip(), "", username.strip(), password,
                               timeout=15)
        try:
            libraries = client.libraries()
            columns = {lib["id"]: client.custom_columns(lib["id"])
                       for lib in libraries}
        except CalibreError as e:
            text = str(e)
            if "401" in text:
                hint = ("calibre refused the username or password. They are "
                        "set in calibre under Preferences → Sharing over the "
                        "net → User accounts.")
            elif "cannot reach" in text:
                hint = ("nothing answered there. In calibre: Preferences → "
                        "Sharing over the net → Start server — and tick "
                        "'Run server automatically when calibre starts'.")
            else:
                hint = text
            return {"ok": False, "message": hint}
        return {"ok": True, "libraries": libraries, "columns": columns,
                "message": f"connected — {len(libraries)} "
                           f"librar{'y' if len(libraries) == 1 else 'ies'}"}

    # ---- saving --------------------------------------------------------

    @app.post("/api/save", dependencies=KEYED)
    def save(calibre: dict = Body(...), password: str | None = Body(None)) -> dict:
        """Write config.toml and .env.

        A first run starts from config.example.toml, so a new config is born
        with the example's comments. A later one edits the file that is
        there: only the lines for these settings change.
        """
        now = saved()
        first_time = not config_path.is_file()
        base = _read(example_path) if first_time else _read(config_path)
        values = {("calibre", k): str(calibre.get(k, "")).strip()
                  for k in _CALIBRE_KEYS if k in calibre}
        if first_time:
            # Listen on this machine alone; Tailscale is what lets the
            # tailnet in, so that nothing here needs the firewall opened.
            values[("service", "host")] = system.LOCAL_HOST

        secrets_out = {"RATCHET_CALIBRE_USERNAME": str(calibre.get("username", "")).strip()}
        if password is not None:
            secrets_out["RATCHET_CALIBRE_PASSWORD"] = password
        if not (now["env"].get("RATCHET_AUTH_TOKEN")
                or now["toml"].get("service", {}).get("auth_token")):
            secrets_out["RATCHET_AUTH_TOKEN"] = secrets.token_urlsafe(32)

        try:
            new_config = set_values(base, values)
            new_env = set_env(_read(env_path), secrets_out)
        except ConfigEditError as e:
            raise HTTPException(400, str(e))
        _write(config_path, new_config)
        _write(env_path, new_env)

        # The service's own loader has the last word on whether what was
        # written is a config it will start with.
        try:
            load_config(config_path)
        except (ValueError, OSError, tomllib.TOMLDecodeError) as e:
            raise HTTPException(400, f"saved, but Ratchet will not accept it: {e}")
        return state()

    @app.post("/api/token/new", dependencies=KEYED)
    def new_token() -> dict:
        """A fresh token. Every device already signed in has to be given it."""
        _write(env_path, set_env(_read(env_path),
                                 {"RATCHET_AUTH_TOKEN": secrets.token_urlsafe(32)}))
        return state()

    # ---- the machine ---------------------------------------------------

    @app.post("/api/reach", dependencies=KEYED)
    def reach(enable: bool = Body(..., embed=True)) -> dict:
        _, port, _ = service_settings()
        if enable and state()["direct"]:
            raise HTTPException(409, "Ratchet is set to listen on the tailnet "
                                     "address itself (service.host); Tailscale "
                                     "forwarding the same port would take its "
                                     "traffic and find nothing behind it")
        result = system.reach_enable(port) if enable else system.reach_disable(port)
        return {**state(), "result": result}

    @app.post("/api/autostart", dependencies=KEYED)
    def autostart(enable: bool = Body(..., embed=True)) -> dict:
        return {**state(), "result": system.autostart_set(enable)}

    @app.post("/api/apk/download", dependencies=KEYED)
    def apk_download() -> dict:
        _, _, data_dir = service_settings()
        return {**state(), "result": system.apk_download(data_dir)}

    @app.post("/api/service/start", dependencies=KEYED)
    def service_start() -> dict:
        return {**state(), "result": system.service_start()}

    # ---- the files that describe the library ----------------------------

    def library_file(name: str) -> Path:
        """One of the three files in config/, by name. By name and from a
        fixed list, never a path: this opens and creates files on request."""
        if name not in configcheck.FILES:
            raise HTTPException(404, f"no such file; there are: "
                                     f"{', '.join(configcheck.FILES)}")
        if name == "tag_rules.txt" and config_path.is_file():
            try:
                return tagmap.rules_path(load_config(config_path))
            except (ValueError, OSError, tomllib.TOMLDecodeError):
                pass
        return configfiles.path(name)

    @app.post("/api/library/check", dependencies=KEYED)
    def library_check() -> dict:
        """Read config/ and say what looks wrong. Changes nothing."""
        try:
            cfg = load_config(config_path)
        except (ValueError, OSError, tomllib.TOMLDecodeError):
            raise HTTPException(409, "save the settings above first — the "
                                     "check needs to know which columns a "
                                     "rule may name, and where calibre is")
        client = CalibreClient(cfg.calibre.base_url, "", cfg.calibre.username,
                               cfg.calibre.password, timeout=60)
        return configcheck.check_all(cfg, client)

    @app.post("/api/library/create", dependencies=KEYED)
    def library_create(file: str = Body(..., embed=True)) -> dict:
        """Start a file from its example. Never over one that is there."""
        target = library_file(file)
        if target.exists():
            raise HTTPException(409, f"{file} already exists; it was left alone")
        example = configcheck.example_for(file)
        if not example.is_file():
            raise HTTPException(404, f"there is no example for {file}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(example.read_bytes())
        return {"ok": True, "path": str(target)}

    @app.post("/api/library/open", dependencies=KEYED)
    def library_open(file: str = Body(..., embed=True)) -> dict:
        target = library_file(file)
        if not target.is_file():
            raise HTTPException(404, f"{file} does not exist yet")
        return system.open_in_editor(target)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="page")
    return app
