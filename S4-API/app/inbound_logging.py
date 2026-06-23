from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request


LOG_DIRECTORY = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIRECTORY / "by_ptl_inbound.log"


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("s4_api.by_ptl.inbound")
    if logger.handlers:
        return logger

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def configure_by_ptl_inbound_logging(app: FastAPI) -> None:
    logger = _get_logger()

    @app.middleware("http")
    async def log_by_ptl_inbound_request(request: Request, call_next):
        if request.method != "POST" or not request.url.path.startswith("/BY-PTL/"):
            return await call_next(request)

        started_at = perf_counter()
        body = await request.body()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            client_ip = request.client.host if request.client else None
            entry = {
                "event": "by_ptl_message_received",
                "client_ip": client_ip,
                "method": request.method,
                "path": request.url.path,
                "content_type": request.headers.get("content-type"),
                "status_code": status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                "payload": body.decode("utf-8", errors="replace"),
            }
            logger.info(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
