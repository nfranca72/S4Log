"""
models/database.py — SQLite internal database
Tables:
  - sync_errors   : records that failed to sync (operator queue)
  - sync_log      : activity log per integration run
  - sync_state    : last successful run timestamp per integration
"""
from __future__ import annotations

import enum
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

from sqlalchemy import (
    Column, DateTime, Enum, Integer, String, Text, create_engine, event, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("models.database")

# ── Engine setup ─────────────────────────────────────────────────────────────

def _get_engine(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    return engine


_engine = None
_SessionLocal = None


def init_db(db_path: str) -> None:
    global _engine, _SessionLocal
    _engine = _get_engine(db_path)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(_engine)
    logger.info(f"Internal SQLite DB initialised at {db_path}")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy session with auto commit/rollback."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_old_logs(days_to_keep: int = 30) -> int:
    """Delete sync_log entries older than `days_to_keep` days. Returns count deleted."""
    cutoff = datetime.utcnow() - timedelta(days=days_to_keep)
    with get_session() as session:
        result = session.execute(
            text("DELETE FROM sync_log WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        deleted = result.rowcount
    if deleted:
        logger.info(f"Purged {deleted} log entries older than {days_to_keep} days.")
    return deleted


def get_error_stats() -> dict:
    """Return pending error counts grouped by integration."""
    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT integration, COUNT(*) as cnt "
                "FROM sync_errors WHERE status = 'pending' "
                "GROUP BY integration"
            )
        ).fetchall()
    return {row[0]: row[1] for row in rows}


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────

class IntegrationName(str, enum.Enum):
    items = "items"
    wms_items = "wms_items"
    partners = "partners"
    transfers = "transfers"
    stock_movements = "stock_movements"
    purchase_orders = "purchase_orders"


class ErrorStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"
    ignored = "ignored"


class LogLevel(str, enum.Enum):
    info = "INFO"
    warning = "WARNING"
    error = "ERROR"


# ── Models ───────────────────────────────────────────────────────────────────

class SyncError(Base):
    """
    A record that failed to sync.
    Displayed in the frontend error queue for operator intervention.
    """
    __tablename__ = "sync_errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration = Column(String(50), nullable=False, index=True)
    sap_object_type = Column(String(50))        # e.g. Items, BusinessPartners, StockTransfers
    sap_key = Column(String(100), index=True)   # ItemCode, CardCode, DocNum …
    sap_series = Column(String(20))
    error_msg = Column(Text)
    payload = Column(Text)                      # JSON snapshot of the SAP record
    status = Column(
        Enum(ErrorStatus),
        default=ErrorStatus.pending,
        nullable=False,
        index=True,
    )
    retry_count = Column(Integer, default=0)    # how many times retried
    last_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)


class SyncLog(Base):
    """Activity log — one row per relevant event."""
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration = Column(String(50), nullable=False, index=True)
    level = Column(Enum(LogLevel), default=LogLevel.info, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SyncState(Base):
    """Tracks the last successful sync timestamp per integration."""
    __tablename__ = "sync_state"

    integration = Column(String(50), primary_key=True)
    last_run_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    records_processed = Column(Integer, default=0)   # cumulative total synced
    records_failed = Column(Integer, default=0)      # cumulative total failed
    last_cycle_synced = Column(Integer, default=0)   # last cycle only
    last_cycle_failed = Column(Integer, default=0)   # last cycle only
    status = Column(String(20), default="idle")      # idle | running | error
    current_task = Column(String(255), nullable=True)


class PurchaseOrderSync(Base):
    """
    Local linkage between WMS OC documents and SAP purchase orders.
    Used to detect changes and cancellations across scheduler runs.
    """
    __tablename__ = "purchase_order_sync"

    local_key = Column(String(50), primary_key=True)     # e.g. OC:12345
    local_doc_type = Column(String(20), nullable=False, index=True)
    local_order_id = Column(Integer, nullable=False, index=True)
    sap_doc_entry = Column(Integer, nullable=True, index=True)
    sap_doc_num = Column(Integer, nullable=True)
    fingerprint = Column(String(64), nullable=True)
    status = Column(String(20), default="active", nullable=False, index=True)
    payload = Column(Text, nullable=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
