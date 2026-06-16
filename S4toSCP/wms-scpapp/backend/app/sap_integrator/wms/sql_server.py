"""
wms/sql_server.py — WMS SQL Server connection via pyodbc
Provides a thin async-friendly wrapper around synchronous pyodbc
using run_in_executor for non-blocking usage inside FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import pyodbc

from ..config import Settings

logger = logging.getLogger("wms.sql_server")


class WMSDatabase:
    SAP_B1_SERIES_SQL = """
        SELECT TOP 1
            tcv3.Value AS SeriesValue
        FROM TableColumnsValues tcv WITH (NOLOCK)
        JOIN TableColumnsValues tcv2 WITH (NOLOCK)
          ON tcv2.TableID = '9007'
         AND tcv2.RowN = tcv.RowN
         AND tcv2.ColumnID = 1
        JOIN TableColumnsValues tcv3 WITH (NOLOCK)
          ON tcv3.TableID = '9007'
         AND tcv3.RowN = tcv.RowN
         AND tcv3.ColumnID = 2
        WHERE tcv.TableID = '9007'
          AND tcv.ColumnID = 0
          AND tcv.Value = ?
          AND tcv2.Value = ?
    """
    UPDATE_ORDER_INTEGRATION_SQL = """
        UPDATE ClientOrders
        SET IDIntegration = ?
        WHERE DocType = ? AND OrderID = ?
    """
    UPDATE_ORDER_DETAILS_INTEGRATION_SQL = """
        UPDATE ClientOrderDetails
        SET IDIntegration = ?
        WHERE DocType = ? AND OrderID = ?
    """
    UPDATE_ITEM_INTEGRATION_SQL = """
        UPDATE ItemMaster
        SET IntegrationID = ?
        WHERE ItemID = ?
    """

    def __init__(self, settings: Settings):
        self._conn_str = settings.wms_connection_string

    # ── Connection management ─────────────────────────────────────────────────

    def _open_connection(self) -> pyodbc.Connection:
        return pyodbc.connect(self._conn_str, autocommit=False, timeout=10)

    def connect(self) -> None:
        conn = self._open_connection()
        conn.close()
        logger.info("WMS SQL Server connected.")

    def disconnect(self) -> None:
        # Connections are opened per operation; nothing to keep alive here.
        return None

    def is_connected(self) -> bool:
        """Return True if a live connection exists without raising."""
        try:
            self.connect()
            return True
        except Exception:
            return False

    @contextmanager
    def transaction(self) -> Generator[pyodbc.Cursor, None, None]:
        conn = self._open_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cursor.close()
            finally:
                conn.close()

    # ── Sync helpers ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.transaction() as cur:
            cur.execute(sql, params)

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        conn = self._open_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        finally:
            cur.close()
            conn.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        conn = self._open_connection()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()
            conn.close()

    # ── Async wrappers ────────────────────────────────────────────────────────

    async def aexecute(self, sql: str, params: tuple = ()) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.execute, sql, params)

    async def afetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_one, sql, params)

    async def afetch_all(self, sql: str, params: tuple = ()) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_all, sql, params)

    def get_sap_b1_series(self, doc_type: str, year: str | int) -> Optional[str]:
        row = self.fetch_one(self.SAP_B1_SERIES_SQL, (str(doc_type).strip(), str(year).strip()))
        if not row:
            return None
        value = str(row.get("SeriesValue") or "").strip()
        return value or None

    async def aget_sap_b1_series(self, doc_type: str, year: str | int) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_sap_b1_series, doc_type, year)

    def mark_order_integration(self, doc_type: str, order_id: int, integration_id: str) -> None:
        with self.transaction() as cur:
            params = (integration_id, str(doc_type).strip(), int(order_id))
            cur.execute(self.UPDATE_ORDER_INTEGRATION_SQL, params)
            cur.execute(self.UPDATE_ORDER_DETAILS_INTEGRATION_SQL, params)

    async def amark_order_integration(self, doc_type: str, order_id: int, integration_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.mark_order_integration, doc_type, order_id, integration_id)

    def mark_item_integration(self, item_id: str, integration_id: str) -> None:
        with self.transaction() as cur:
            cur.execute(
                self.UPDATE_ITEM_INTEGRATION_SQL,
                (integration_id, str(item_id).strip()),
            )

    async def amark_item_integration(self, item_id: str, integration_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.mark_item_integration, item_id, integration_id)

    # ── Generic upsert ────────────────────────────────────────────────────────

    def upsert(self, table: str, key_col: str, key_val: Any, data: Dict[str, Any]) -> None:
        """
        MERGE-based upsert into SQL Server.
        data must include all columns (including key).
        """
        cols = list(data.keys())
        placeholders = ", ".join("?" * len(cols))
        col_names = ", ".join(f"[{c}]" for c in cols)
        updates = ", ".join(
            f"target.[{c}] = source.[{c}]" for c in cols if c != key_col
        )

        sql = f"""
            MERGE [{table}] AS target
            USING (SELECT {placeholders}) AS source ({col_names})
            ON target.[{key_col}] = source.[{key_col}]
            WHEN MATCHED THEN
                UPDATE SET {updates}
            WHEN NOT MATCHED THEN
                INSERT ({col_names}) VALUES ({placeholders});
        """
        # pyodbc MERGE needs values twice (USING + INSERT)
        values = tuple(data.values())
        with self.transaction() as cur:
            cur.execute(sql, values + values)

    async def aupsert(self, table: str, key_col: str, key_val: Any, data: Dict) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.upsert, table, key_col, key_val, data)

    def test_connection(self) -> bool:
        try:
            self.connect()
            return True
        except Exception as e:
            logger.error(f"WMS connection test failed: {e}")
            return False
