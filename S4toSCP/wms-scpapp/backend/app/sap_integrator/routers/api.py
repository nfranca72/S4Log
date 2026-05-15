"""
routers/api.py — All REST endpoints + WebSocket for the frontend

Endpoints:
  GET   /status                   → live state of all integrations + stats
  GET   /config                   → current settings (non-sensitive)
  POST  /config                   → update settings (requires access key)
  POST  /config/verify-key        → verify access key without changing anything
  POST  /toggle/{integration}     → enable/disable (no key needed)
  POST  /run-now/{integration}    → trigger immediate sync
  GET   /errors                   → error queue (paginated, filterable)
  PATCH /errors/{id}              → resolve / ignore an error
  POST  /errors/{id}/retry        → re-queue error record for re-sync
  DELETE /errors/resolved         → bulk delete resolved/ignored errors
  GET   /logs                     → recent log entries (paginated, filterable)
  POST  /logs/purge               → purge old logs (requires access key)
  GET   /health                   → SAP + WMS connectivity check
  WS    /ws/status                → WebSocket real-time push
"""
from __future__ import annotations

import asyncio
import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import desc, text

from ..config import Settings, get_settings, update_env_file
from ..integrations.base import LIVE_STATE
from ..models.database import (
    ErrorStatus, SyncError, SyncLog, SyncState,
    get_session, get_error_stats, purge_old_logs,
)
from ..scheduler import get_scheduler

logger = logging.getLogger("routers.api")
router = APIRouter()


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    async def broadcast(self, data: dict):
        if not self._clients:
            return
        msg = json.dumps(data, default=str)
        dead: Set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead


ws_manager = ConnectionManager()


def _build_status_payload() -> Dict[str, Any]:
    scheduler = get_scheduler()
    job_status = scheduler.get_job_status()
    settings = get_settings()

    with get_session() as session:
        states = {s.integration: s for s in session.query(SyncState).all()}

    error_counts = get_error_stats()
    integrations: Dict[str, Any] = {}

    for name in ["items", "partners", "transfers", "stock_movements"]:
        db_state = states.get(name)
        live = LIVE_STATE.get(name, {})
        sched = job_status.get(name, {})
        integrations[name] = {
            "status":            live.get("status") or (db_state.status if db_state else "idle"),
            "current_task":      live.get("current_task"),
            "last_run_at":       db_state.last_run_at.isoformat() if db_state and db_state.last_run_at else None,
            "last_success_at":   db_state.last_success_at.isoformat() if db_state and db_state.last_success_at else None,
            "next_run":          sched.get("next_run"),
            "scheduled":         sched.get("scheduled", False),
            "last_cycle_synced": getattr(db_state, "last_cycle_synced", 0) or 0,
            "last_cycle_failed": getattr(db_state, "last_cycle_failed", 0) or 0,
            "total_synced":      db_state.records_processed if db_state else 0,
            "total_failed":      db_state.records_failed if db_state else 0,
            "pending_errors":    error_counts.get(name, 0),
            # Read enabled state directly from env var to bypass any stale cache
            "enabled":           os.environ.get(
                f"SYNC_{name.upper()}_ENABLED",
                str(getattr(settings, f"sync_{name}_enabled", False))
            ).lower() in ("true", "1", "yes"),
        }

    return {"integrations": integrations}


@router.websocket("/ws/status")
async def websocket_status(ws: WebSocket):
    """Push integration status to connected clients every 2 seconds."""
    await ws_manager.connect(ws)
    try:
        while True:
            try:
                payload = _build_status_payload()
                await ws_manager.broadcast({"type": "status", "data": payload})
            except Exception as e:
                logger.debug(f"WS broadcast error: {e}")
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        logger.warning(f"WebSocket closed unexpectedly: {e}")
        ws_manager.disconnect(ws)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ToggleRequest(BaseModel):
    enabled: bool


class VerifyKeyRequest(BaseModel):
    access_key: str


class ConfigUpdateRequest(BaseModel):
    access_key: str
    # SAP
    sap_sl_host: Optional[str] = None
    sap_sl_company: Optional[str] = None
    sap_sl_user: Optional[str] = None
    sap_sl_password: Optional[str] = None
    sap_sl_verify_ssl: Optional[bool] = None
    # WMS
    wms_db_server: Optional[str] = None
    wms_db_name: Optional[str] = None
    wms_db_user: Optional[str] = None
    wms_db_password: Optional[str] = None
    wms_db_driver: Optional[str] = None
    # Intervals
    interval_items: Optional[int] = None
    interval_partners: Optional[int] = None
    interval_transfers: Optional[int] = None
    interval_stock_movements: Optional[int] = None
    # Series
    sap_transfer_series: Optional[str] = None
    sap_goods_receipt_series: Optional[str] = None
    sap_goods_issue_series: Optional[str] = None
    # Allow changing the access key itself
    config_access_key: Optional[str] = None


class ErrorResolveRequest(BaseModel):
    status: ErrorStatus
    notes: Optional[str] = None
    resolved_by: Optional[str] = None


class PurgeLogsRequest(BaseModel):
    access_key: str
    days_to_keep: int = 30


class ErrorOut(BaseModel):
    id: int
    integration: str
    sap_object_type: Optional[str] = None
    sap_key: Optional[str] = None
    sap_series: Optional[str] = None
    error_msg: Optional[str] = None
    payload: Optional[str] = None
    status: str
    retry_count: Optional[int] = 0
    last_retry_at: Optional[datetime] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class LogOut(BaseModel):
    id: int
    integration: str
    level: str
    message: str
    details: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    """REST fallback for clients that cannot use WebSocket."""
    return _build_status_payload()


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config():
    s = get_settings()
    return {
        "sap_sl_host":                  s.sap_sl_host,
        "sap_sl_company":               s.sap_sl_company,
        "sap_sl_user":                  s.sap_sl_user,
        "sap_sl_verify_ssl":            s.sap_sl_verify_ssl,
        "wms_db_server":                s.wms_db_server,
        "wms_db_name":                  s.wms_db_name,
        "wms_db_user":                  s.wms_db_user,
        "wms_db_driver":                s.wms_db_driver,
        "interval_items":               s.interval_items,
        "interval_partners":            s.interval_partners,
        "interval_transfers":           s.interval_transfers,
        "interval_stock_movements":     s.interval_stock_movements,
        "sync_items_enabled":           s.sync_items_enabled,
        "sync_partners_enabled":        s.sync_partners_enabled,
        "sync_transfers_enabled":       s.sync_transfers_enabled,
        "sync_stock_movements_enabled": s.sync_stock_movements_enabled,
        "sap_transfer_series":          s.sap_transfer_series,
        "sap_goods_receipt_series":     s.sap_goods_receipt_series,
        "sap_goods_issue_series":       s.sap_goods_issue_series,
    }


@router.post("/config/verify-key")
async def verify_key(req: VerifyKeyRequest):
    s = get_settings()
    if req.access_key != s.config_access_key:
        raise HTTPException(status_code=403, detail="Chave de acesso inválida.")
    return {"valid": True}


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
    s = get_settings()
    if req.access_key != s.config_access_key:
        raise HTTPException(status_code=403, detail="Chave de acesso inválida.")

    updates = req.dict(exclude={"access_key"}, exclude_none=True)
    if not updates:
        return {"message": "Sem alterações."}

    env_updates = {k.upper(): str(v) for k, v in updates.items()}
    update_env_file(env_updates)
    get_scheduler().reload()

    return {"message": "Configuração actualizada e scheduler recarregado."}


# ── Toggle ────────────────────────────────────────────────────────────────────

VALID_INTEGRATIONS = {"items", "partners", "transfers", "stock_movements"}


@router.post("/toggle/{integration}")
async def toggle_integration(integration: str, req: ToggleRequest):
    if integration not in VALID_INTEGRATIONS:
        raise HTTPException(status_code=404, detail="Integração desconhecida.")

    env_key = f"SYNC_{integration.upper()}_ENABLED"
    # Write to .env and clear settings cache before scheduler reads it
    update_env_file({env_key: str(req.enabled).lower()})
    get_scheduler().toggle(integration, req.enabled)

    # Verify the setting was persisted correctly
    fresh = get_settings()
    actual_enabled = getattr(fresh, f"sync_{integration}_enabled", req.enabled)

    return {"integration": integration, "enabled": actual_enabled}


# ── Run Now ───────────────────────────────────────────────────────────────────

@router.post("/run-now/{integration}")
async def run_now(integration: str):
    if integration not in VALID_INTEGRATIONS:
        raise HTTPException(status_code=404, detail="Integração desconhecida.")
    get_scheduler().run_now(integration)
    return {"message": f"Execução manual iniciada: {integration}."}


# ── Errors ────────────────────────────────────────────────────────────────────

@router.get("/errors", response_model=List[ErrorOut])
async def list_errors(
    integration: Optional[str] = None,
    status: Optional[str] = "pending",
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    with get_session() as session:
        q = session.query(SyncError)
        if integration:
            q = q.filter(SyncError.integration == integration)
        if status:
            q = q.filter(SyncError.status == status)
        rows = q.order_by(desc(SyncError.created_at)).offset(offset).limit(limit).all()
        result = [ErrorOut.model_validate(r, from_attributes=True) for r in rows]
    return result


@router.get("/errors/count")
async def count_errors(integration: Optional[str] = None):
    counts = get_error_stats()
    if integration:
        return {"count": counts.get(integration, 0)}
    return {"counts": counts, "total": sum(counts.values())}


@router.patch("/errors/{error_id}", response_model=ErrorOut)
async def resolve_error(error_id: int, req: ErrorResolveRequest):
    with get_session() as session:
        error = session.get(SyncError, error_id)
        if not error:
            raise HTTPException(status_code=404, detail="Erro não encontrado.")
        error.status = req.status
        error.notes = req.notes
        error.resolved_by = req.resolved_by
        error.resolved_at = datetime.utcnow() if req.status != ErrorStatus.pending else None
        result = ErrorOut.model_validate(error, from_attributes=True)
    return result


@router.post("/errors/{error_id}/retry")
async def retry_error(error_id: int):
    """Re-mark a failed record as pending and trigger an immediate sync."""
    with get_session() as session:
        error = session.get(SyncError, error_id)
        if not error:
            raise HTTPException(status_code=404, detail="Erro não encontrado.")
        integration = error.integration
        error.status = ErrorStatus.pending
        error.resolved_at = None
        error.last_retry_at = datetime.utcnow()
        error.retry_count = (error.retry_count or 0) + 1

    try:
        get_scheduler().run_now(integration)
    except Exception as e:
        logger.warning(f"run_now after retry failed: {e}")

    return {"message": f"Registo re-agendado para re-sincronização ({integration})."}


@router.delete("/errors/resolved")
async def delete_resolved_errors(access_key: str = Query(...)):
    s = get_settings()
    if access_key != s.config_access_key:
        raise HTTPException(status_code=403, detail="Chave de acesso inválida.")

    with get_session() as session:
        result = session.execute(
            text("DELETE FROM sync_errors WHERE status IN ('resolved', 'ignored')")
        )
        deleted = result.rowcount

    return {"deleted": deleted}


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs", response_model=List[LogOut])
async def list_logs(
    integration: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    with get_session() as session:
        q = session.query(SyncLog)
        if integration:
            q = q.filter(SyncLog.integration == integration)
        if level:
            q = q.filter(SyncLog.level == level)
        rows = q.order_by(desc(SyncLog.created_at)).offset(offset).limit(limit).all()
        result = [LogOut.model_validate(r, from_attributes=True) for r in rows]
    return result


@router.post("/logs/purge")
async def purge_logs(req: PurgeLogsRequest):
    s = get_settings()
    if req.access_key != s.config_access_key:
        raise HTTPException(status_code=403, detail="Chave de acesso inválida.")
    deleted = purge_old_logs(req.days_to_keep)
    return {"deleted": deleted, "days_kept": req.days_to_keep}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    settings = get_settings()
    from ..sap.service_layer import ServiceLayerClient
    from ..wms.sql_server import WMSDatabase

    # Check if credentials are still the defaults
    wms_configured = bool(
        settings.wms_db_server
        and settings.wms_db_server != "your-sql-server"
        and settings.wms_db_name
    )
    sap_configured = bool(
        settings.sap_sl_host
        and "your-sap-server" not in settings.sap_sl_host
        and settings.sap_sl_company
        and settings.sap_sl_user
    )

    # WMS connectivity
    wms_ok = False
    wms_error = None
    if wms_configured:
        try:
            wms = WMSDatabase(settings)
            wms_ok = wms.test_connection()
            if not wms_ok:
                wms_error = "Connection test failed — check server name, credentials and firewall."
        except Exception as e:
            wms_error = str(e)[:300]
    else:
        wms_error = "Not configured — edit the .env file with WMS SQL Server credentials."

    # SAP connectivity
    sap_ok = False
    sap_error = None
    if sap_configured:
        try:
            async with ServiceLayerClient(settings) as _:
                sap_ok = True
        except Exception as e:
            sap_error = str(e)[:300]
    else:
        sap_error = "Not configured — edit the .env file with SAP Service Layer credentials."

    return {
        "wms": {
            "connected": wms_ok,
            "configured": wms_configured,
            "error": wms_error,
            "server": settings.wms_db_server if wms_configured else None,
            "database": settings.wms_db_name if wms_configured else None,
        },
        "sap": {
            "connected": sap_ok,
            "configured": sap_configured,
            "error": sap_error,
            "host": settings.sap_sl_host if sap_configured else None,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
