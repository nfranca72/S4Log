"""
integrations/transfers.py — Sync SAP Stock Transfers → WMS Stockmov + Inventory

SAP entity: StockTransfers (OWTR / WTR1)
Movement type in WMS Stockmov: 'T' (transfer)

Logic:
  1. Query unsynced transfers filtered by configured series
  2. For each document line → insert Stockmov row
  3. Update Inventory (FROM warehouse −qty, TO warehouse +qty)
  4. Mark SAP document U_WMS_Synced = 'Y'
  5. On error → record to error queue, mark U_WMS_Synced = 'E'
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from ..config import Settings
from .base import BaseIntegration
from ..sap.service_layer import ServiceLayerClient, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.transfers")


class TransfersIntegration(BaseIntegration):
    name = "transfers"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms

    async def run(self) -> None:
        series = self._settings.transfer_series_list

        async with get_sap_client(self._settings) as sl:
            filter_parts = [sl.not_synced_filter("U_WMS_Synced")]
            if series:
                filter_parts.append(sl.series_filter(series))
            filter_str = " and ".join(filter_parts)

            self._set_task("Querying SAP Stock Transfers…")

            async for doc in sl.get_all(
                "StockTransfers",
                filter=filter_str,
                expand="StockTransferLines",
                select=(
                    "DocNum,DocDate,Series,Comments,FromWarehouse,ToWarehouse,"
                    "U_WMS_Synced,StockTransferLines"
                ),
            ):
                doc_num = doc.get("DocNum")
                self._set_task(f"Processing transfer DocNum {doc_num}…")
                try:
                    await self._process_transfer(doc)
                    await sl.mark_synced("StockTransfers", doc_num)
                    self._inc_synced()
                except Exception as e:
                    logger.warning(f"Transfer {doc_num} failed: {e}")
                    self.record_error(
                        sap_key=str(doc_num),
                        sap_series=str(doc.get("Series", "")),
                        error_msg=str(e),
                        payload=doc,
                        sap_object_type="StockTransfers",
                    )
                    try:
                        await sl.mark_sync_failed("StockTransfers", doc_num)
                    except Exception:
                        pass

    # ── Document processing ───────────────────────────────────────────────────

    async def _process_transfer(self, doc: Dict[str, Any]) -> None:
        doc_num = doc.get("DocNum")
        doc_date = self._parse_date(doc.get("DocDate"))
        from_wh = doc.get("FromWarehouse", "")
        to_wh = doc.get("ToWarehouse", "")
        comments = doc.get("Comments", "")
        lines: List[Dict] = doc.get("StockTransferLines", [])

        for line in lines:
            item_code = line.get("ItemCode", "")
            qty = float(line.get("Quantity", 0))
            batch = line.get("BatchNum", "")
            serial = line.get("SerialNum", "")

            # Stockmov — FROM side (negative / out)
            await self._insert_stockmov(
                doc_num=doc_num,
                line_num=line.get("LineNum", 0),
                suffix="F",
                item_code=item_code,
                qty=-qty,
                warehouse=from_wh,
                mov_type="T",
                doc_date=doc_date,
                batch=batch,
                serial=serial,
                comments=comments,
            )

            # Stockmov — TO side (positive / in)
            await self._insert_stockmov(
                doc_num=doc_num,
                line_num=line.get("LineNum", 0),
                suffix="T",
                item_code=item_code,
                qty=qty,
                warehouse=to_wh,
                mov_type="T",
                doc_date=doc_date,
                batch=batch,
                serial=serial,
                comments=comments,
            )

            # Update Inventory
            await self._update_inventory(item_code, from_wh, -qty, batch)
            await self._update_inventory(item_code, to_wh, qty, batch)

    async def _insert_stockmov(
        self,
        doc_num: int,
        line_num: int,
        suffix: str,
        item_code: str,
        qty: float,
        warehouse: str,
        mov_type: str,
        doc_date: str,
        batch: str,
        serial: str,
        comments: str,
    ) -> None:
        await self._wms.aexecute(
            """
            IF NOT EXISTS (
                SELECT 1 FROM [Stockmov]
                WHERE DocNum=? AND LineNum=? AND MovSide=?
            )
            INSERT INTO [Stockmov]
              (DocNum, LineNum, MovSide, ItemID, Qty, WarehouseID,
               MovType, MovDate, BatchNum, SerialNum, Comments, SAPDocNum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_num, line_num, suffix,
                doc_num, line_num, suffix,
                item_code, qty, warehouse,
                mov_type, doc_date, batch, serial, comments, doc_num,
            ),
        )

    async def _update_inventory(
        self, item_code: str, warehouse: str, qty_delta: float, batch: str
    ) -> None:
        await self._wms.aexecute(
            """
            MERGE [Inventory] AS target
            USING (SELECT ? AS ItemID, ? AS WarehouseID, ? AS BatchNum) AS source
              ON target.ItemID = source.ItemID
             AND target.WarehouseID = source.WarehouseID
             AND ISNULL(target.BatchNum,'') = ISNULL(source.BatchNum,'')
            WHEN MATCHED THEN
                UPDATE SET Qty = ISNULL(target.Qty, 0) + ?
            WHEN NOT MATCHED THEN
                INSERT (ItemID, WarehouseID, BatchNum, Qty)
                VALUES (?, ?, ?, ?);
            """,
            (item_code, warehouse, batch, qty_delta, item_code, warehouse, batch, qty_delta),
        )

    @staticmethod
    def _parse_date(date_str: str | None) -> str:
        if not date_str:
            return datetime.utcnow().strftime("%Y-%m-%d")
        try:
            return date_str[:10]
        except Exception:
            return datetime.utcnow().strftime("%Y-%m-%d")
