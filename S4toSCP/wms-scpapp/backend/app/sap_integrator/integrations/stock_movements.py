"""
integrations/stock_movements.py — Sync SAP Goods Receipts + Goods Issues → WMS

SAP entities:
  GoodsReceiptsPO / InventoryGenEntries  (OGRPO / OIGE) → MovType = 'E' (entrada)
  GoodsIssues    / InventoryGenExits     (OOGI / OIGE)  → MovType = 'S' (saída)

Both update Stockmov and Inventory.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from ..config import Settings
from .base import BaseIntegration
from ..sap.service_layer import ServiceLayerClient, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.stock_movements")


class StockMovementsIntegration(BaseIntegration):
    name = "stock_movements"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms

    async def run(self) -> None:
        async with get_sap_client(self._settings) as sl:
            await self._sync_entity(
                sl,
                entity="InventoryGenEntries",
                lines_key="DocumentLines",
                mov_type="E",
                qty_sign=+1,
                series_list=self._settings.goods_receipt_series_list,
                label="Goods Receipts",
            )
            await self._sync_entity(
                sl,
                entity="InventoryGenExits",
                lines_key="DocumentLines",
                mov_type="S",
                qty_sign=-1,
                series_list=self._settings.goods_issue_series_list,
                label="Goods Issues",
            )

    # ── Generic entity sync ───────────────────────────────────────────────────

    async def _sync_entity(
        self,
        sl: ServiceLayerClient,
        entity: str,
        lines_key: str,
        mov_type: str,
        qty_sign: int,
        series_list: List[str],
        label: str,
    ) -> None:
        self._set_task(f"Querying SAP {label}…")

        filter_parts = [sl.not_synced_filter("U_WMS_Synced")]
        if series_list:
            filter_parts.append(sl.series_filter(series_list))
        filter_str = " and ".join(filter_parts)

        synced = 0
        failed = 0

        async for doc in sl.get_all(
            entity,
            filter=filter_str,
            expand=lines_key,
            select=f"DocEntry,DocNum,DocDate,Series,Comments,{lines_key}",
        ):
            doc_num = doc.get("DocNum")
            doc_entry = doc.get("DocEntry")
            sap_key = str(doc_entry if doc_entry is not None else doc_num)
            if await self._wms.ais_sap_integration_synced(self.name, entity, sap_key):
                continue
            self._set_task(f"Processing {label} DocNum {doc_num}…")
            try:
                await self._process_document(doc, lines_key, mov_type, qty_sign)
                mark_error = None
                try:
                    await sl.mark_synced(entity, doc_num)
                except Exception as exc:
                    mark_error = str(exc)
                    self.log_warning(
                        f"{label} {doc_num} refletido no S3, mas o SAP recusou atualizar U_WMS_Synced.",
                        details=mark_error,
                    )
                await self._wms.amark_sap_integration_synced(
                    self.name,
                    entity,
                    sap_key,
                    sap_doc_entry=int(doc_entry) if doc_entry is not None else None,
                    sap_doc_num=int(doc_num) if doc_num is not None else None,
                    sap_series=str(doc.get("Series") or ""),
                    s3_reference=f"S3 Stockmov {mov_type}.{doc_num}",
                    last_error=mark_error,
                )
                synced += 1
                self._inc_synced()
            except Exception as e:
                failed += 1
                logger.warning(f"{label} {doc_num} failed: {e}")
                self.record_error(
                    sap_key=str(doc_num),
                    sap_series=str(doc.get("Series", "")),
                    error_msg=str(e),
                    payload=doc,
                    sap_object_type=entity,
                )
                try:
                    await sl.mark_sync_failed(entity, doc_num)
                except Exception:
                    pass

        self.log_info(f"{label} — synced: {synced}, failed: {failed}")

    # ── Document processing ───────────────────────────────────────────────────

    async def _process_document(
        self,
        doc: Dict[str, Any],
        lines_key: str,
        mov_type: str,
        qty_sign: int,
    ) -> None:
        doc_num = doc.get("DocNum")
        doc_date = (doc.get("DocDate") or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        comments = doc.get("Comments", "")
        lines: List[Dict] = doc.get(lines_key, [])

        for line in lines:
            item_code = line.get("ItemCode", "")
            qty = float(line.get("Quantity", 0)) * qty_sign
            warehouse = line.get("WarehouseCode", "")
            batch = line.get("BatchNum") or (
                line.get("BatchNumbers", [{}])[0].get("BatchNumber", "") if line.get("BatchNumbers") else ""
            )
            serial = line.get("SerialNum", "")

            # Insert Stockmov row (idempotent)
            await self._wms.aexecute(
                """
                IF NOT EXISTS (
                    SELECT 1 FROM [Stockmov]
                    WHERE DocNum=? AND LineNum=? AND MovType=?
                )
                INSERT INTO [Stockmov]
                  (DocNum, LineNum, MovSide, ItemID, Qty, WarehouseID,
                   MovType, MovDate, BatchNum, SerialNum, Comments, SAPDocNum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_num, line.get("LineNum", 0), mov_type,
                    doc_num, line.get("LineNum", 0), mov_type,
                    item_code, qty, warehouse,
                    mov_type, doc_date, batch, serial, comments, doc_num,
                ),
            )

            # Update Inventory balance
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
                (item_code, warehouse, batch, qty, item_code, warehouse, batch, qty),
            )
