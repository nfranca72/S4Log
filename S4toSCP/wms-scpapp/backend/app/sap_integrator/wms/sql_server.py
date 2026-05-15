"""
wms/sql_server.py — WMS SQL Server connection via pyodbc
Provides a thin async-friendly wrapper around synchronous pyodbc
using run_in_executor for non-blocking usage inside FastAPI.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import pyodbc

from ..config import Settings

logger = logging.getLogger("wms.sql_server")


class WMSDatabase:
    def __init__(self, settings: Settings):
        self._conn_str = settings.wms_connection_string
        self._conn: Optional[pyodbc.Connection] = None

    # ── Connection management ─────────────────────────────────────────────────

    def connect(self) -> None:
        self._conn = pyodbc.connect(self._conn_str, autocommit=False)
        logger.info("WMS SQL Server connected.")

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None

    def _ensure_connected(self) -> pyodbc.Connection:
        if self._conn is None:
            self.connect()
        else:
            # Test connection is alive with a lightweight ping
            try:
                self._conn.cursor().execute("SELECT 1")
            except pyodbc.Error:
                logger.warning("WMS connection lost — reconnecting.")
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                self.connect()
        return self._conn

    def is_connected(self) -> bool:
        """Return True if a live connection exists without raising."""
        try:
            self._ensure_connected()
            return True
        except Exception:
            return False

    @contextmanager
    def transaction(self) -> Generator[pyodbc.Cursor, None, None]:
        conn = self._ensure_connected()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    # ── Sync helpers ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.transaction() as cur:
            cur.execute(sql, params)

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        conn = self._ensure_connected()
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in cur.description]
        cur.close()
        return dict(zip(cols, row))

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        conn = self._ensure_connected()
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows

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
            self._ensure_connected()
            return True
        except Exception as e:
            logger.error(f"WMS connection test failed: {e}")
            return False
