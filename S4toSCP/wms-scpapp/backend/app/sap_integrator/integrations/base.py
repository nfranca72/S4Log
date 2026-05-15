"""
integrations/base.py — Abstract base for all integrations

Each integration subclass implements:
  - run()  : full sync cycle, must call _inc_synced() / _inc_failed()
  - name   : integration identifier

The base class handles:
  - SyncState tracking (start/end/error) with per-cycle counters
  - SyncLog writing
  - SyncError recording for failed records
  - Current task broadcasting (via shared state dict)
"""
from __future__ import annotations

import json
import logging
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

from ..models.database import (
    ErrorStatus, LogLevel,
    SyncError, SyncLog, SyncState, get_session,
)

logger = logging.getLogger("integration.base")

# Shared in-memory state for real-time frontend updates
# { integration_name: { "status": str, "current_task": str, "last_update": str } }
LIVE_STATE: Dict[str, Dict[str, Any]] = {}


class BaseIntegration(ABC):
    name: str  # must be one of IntegrationName values

    def __init__(self):
        self._cycle_synced: int = 0
        self._cycle_failed: int = 0

    # ── Abstract ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def run(self) -> None:
        """Execute a full sync cycle."""

    # ── Counters ──────────────────────────────────────────────────────────────

    def _inc_synced(self, n: int = 1) -> None:
        self._cycle_synced += n

    def _inc_failed(self, n: int = 1) -> None:
        self._cycle_failed += n

    # ── State & Logging ───────────────────────────────────────────────────────

    def _set_task(self, task: str) -> None:
        """Broadcast the current task description to the frontend."""
        LIVE_STATE.setdefault(self.name, {})["current_task"] = task
        LIVE_STATE[self.name]["last_update"] = datetime.utcnow().isoformat()
        logger.info(f"[{self.name}] {task}")

    def _set_status(self, status: str) -> None:
        LIVE_STATE.setdefault(self.name, {})["status"] = status
        LIVE_STATE[self.name]["last_update"] = datetime.utcnow().isoformat()

    def _log(self, level: LogLevel, message: str, details: str | None = None) -> None:
        try:
            with get_session() as session:
                session.add(SyncLog(
                    integration=self.name,
                    level=level,
                    message=message,
                    details=details,
                ))
        except Exception as e:
            logger.error(f"Failed to write log: {e}")

    def log_info(self, message: str, details: str | None = None) -> None:
        self._log(LogLevel.info, message, details)

    def log_warning(self, message: str, details: str | None = None) -> None:
        self._log(LogLevel.warning, message, details)

    def log_error(self, message: str, details: str | None = None) -> None:
        self._log(LogLevel.error, message, details)

    def record_error(
        self,
        sap_key: str,
        error_msg: str,
        payload: Dict[str, Any],
        sap_object_type: str | None = None,
        sap_series: str | None = None,
    ) -> None:
        """Save a failed record to the error queue for operator review."""
        self._inc_failed()
        try:
            with get_session() as session:
                # Avoid duplicate pending errors for the same key
                existing = (
                    session.query(SyncError)
                    .filter_by(
                        integration=self.name,
                        sap_key=sap_key,
                        status=ErrorStatus.pending,
                    )
                    .first()
                )
                if existing:
                    existing.error_msg = error_msg
                    existing.payload = json.dumps(payload, default=str)
                    existing.retry_count = (existing.retry_count or 0) + 1
                    existing.last_retry_at = datetime.utcnow()
                else:
                    session.add(SyncError(
                        integration=self.name,
                        sap_object_type=sap_object_type or self.name,
                        sap_key=sap_key,
                        sap_series=sap_series,
                        error_msg=error_msg,
                        payload=json.dumps(payload, default=str),
                        status=ErrorStatus.pending,
                    ))
        except Exception as e:
            logger.error(f"Failed to record sync error: {e}")

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    async def execute(self) -> None:
        """Called by the scheduler. Wraps run() with state management."""
        self._cycle_synced = 0
        self._cycle_failed = 0

        self._set_status("running")
        self._update_sync_state(status="running", current_task="A iniciar…")

        try:
            await self.run()
            self._set_status("idle")
            self._set_task(
                f"Concluído — {self._cycle_synced} sincronizados, "
                f"{self._cycle_failed} erros."
            )
            self._update_sync_state(
                status="idle",
                last_success_at=datetime.utcnow(),
                current_task=None,
                last_cycle_synced=self._cycle_synced,
                last_cycle_failed=self._cycle_failed,
            )
            self.log_info(
                f"Ciclo completo — sincronizados: {self._cycle_synced}, "
                f"erros: {self._cycle_failed}"
            )
        except Exception as e:
            self._set_status("error")
            tb = traceback.format_exc()
            self.log_error(f"Erro não tratado no ciclo de sync: {e}", details=tb)
            self._update_sync_state(
                status="error",
                current_task=str(e)[:255],
                last_cycle_synced=self._cycle_synced,
                last_cycle_failed=self._cycle_failed,
            )
            logger.exception(f"[{self.name}] Unhandled exception in execute()")

    def _update_sync_state(self, **kwargs) -> None:
        try:
            with get_session() as session:
                state = session.get(SyncState, self.name)
                if state is None:
                    state = SyncState(integration=self.name)
                    session.add(state)
                for k, v in kwargs.items():
                    setattr(state, k, v)
                state.last_run_at = datetime.utcnow()
                # Accumulate lifetime counters
                if "last_cycle_synced" in kwargs:
                    state.records_processed = (state.records_processed or 0) + kwargs["last_cycle_synced"]
                if "last_cycle_failed" in kwargs:
                    state.records_failed = (state.records_failed or 0) + kwargs["last_cycle_failed"]
        except Exception as e:
            logger.error(f"Failed to update sync state: {e}")
