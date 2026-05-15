from __future__ import annotations

import logging
from pathlib import Path

from .config import get_settings
from .models.database import init_db
from .scheduler import get_scheduler

logger = logging.getLogger("sap_integrator.lifecycle")

_started = False


def start_integrator() -> None:
    global _started
    if _started:
        return

    try:
        settings = get_settings()
        Path(settings.sqlite_db_path).parent.mkdir(parents=True, exist_ok=True)
        init_db(settings.sqlite_db_path)
        get_scheduler().start()
        _started = True
        logger.info("SAP integrator runtime started.")
    except Exception:
        logger.exception("SAP integrator runtime failed to start.")


def stop_integrator() -> None:
    global _started
    if not _started:
        return

    try:
        get_scheduler().stop()
    finally:
        _started = False
        logger.info("SAP integrator runtime stopped.")
