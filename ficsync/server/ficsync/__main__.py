"""`python -m ficsync` — run the service with host/port from config.toml."""

import uvicorn

from .main import app, cfg

if __name__ == "__main__":
    uvicorn.run(app, host=cfg.service.host, port=cfg.service.port)
