"""`python -m ficsync` — run the service with host/port from config.toml."""

import uvicorn

from .main import app, cfg

if __name__ == "__main__":
    host = cfg.bind_host
    print(f"ficsync listening on http://{host}:{cfg.service.port}  (UI at /ui/)")
    uvicorn.run(app, host=host, port=cfg.service.port)
