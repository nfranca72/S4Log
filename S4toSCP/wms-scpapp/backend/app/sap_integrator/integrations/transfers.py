"""
integrations/transfers.py - Sync SAP Stock Transfers to WMS Stockmov + Inventory.

SAP entity: StockTransfers (OWTR / WTR1)
Movement type in WMS Stockmov: 'T' (transfer)

The SAP UDF configured in SAP_TRANSFER_SYNC_FIELD is used as the sync flag and
link back to the S3 movement. The default SAP field is U_SEI_DocONS3.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from ..config import Settings
from .base import BaseIntegration
from ..sap.service_layer import SAPRequestError
from ..sap.service_layer import get_sap_client
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
        sync_field = self._normalize_udf_field(self._settings.sap_transfer_sync_field)

        async with get_sap_client(self._settings) as sl:
            filter_parts = [self._empty_udf_filter(sync_field)]
            if series:
                filter_parts.append(sl.series_filter(series))
            filter_str = " and ".join(filter_parts)

            self._set_task("Querying SAP Stock Transfers...")

            async for header in sl.get_all(
                "StockTransfers",
                filter=filter_str,
                select=(
                    "DocEntry,DocNum,DocDate,Series,Comments,FromWarehouse,ToWarehouse,"
                    f"{sync_field}"
                ),
            ):
                doc = await sl.get_by_key("StockTransfers", int(header["DocEntry"]))
                doc_num = doc.get("DocNum")
                doc_entry = doc.get("DocEntry")
                if await self._is_locally_synced(int(doc_entry)):
                    continue
                self._set_task(f"Processing transfer DocNum {doc_num}...")
                try:
                    await self._process_transfer(doc)
                    s3_reference = self._build_s3_reference(doc)
                    sap_mark_error = None
                    try:
                        await sl.patch(
                            "StockTransfers",
                            int(doc_entry),
                            {sync_field: s3_reference},
                        )
                    except SAPRequestError as exc:
                        sap_mark_error = str(exc)
                        self.log_warning(
                            f"Transfer {doc_num} refletida no S3, mas o SAP recusou atualizar {sync_field}.",
                            details=sap_mark_error,
                        )
                    await self._mark_locally_synced(doc, s3_reference, sap_mark_error)
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

    async def _process_transfer(self, doc: Dict[str, Any]) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._process_transfer_sync, doc)

    def _process_transfer_sync(self, doc: Dict[str, Any]) -> None:
        doc_num = int(doc.get("DocNum"))
        doc_date = self._parse_date(doc.get("DocDate"))
        comments = doc.get("Comments", "") or ""
        lines: List[Dict] = doc.get("StockTransferLines", [])

        with self._wms.transaction() as cursor:
            for line in lines:
                line_num = int(line.get("LineNum", 0))
                item_code = str(line.get("ItemCode") or "").strip()
                qty = float(line.get("Quantity", 0) or 0)
                if not item_code or qty <= 0:
                    continue

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM StockMov
                    WHERE DocTypeOrig = 'SAPTR'
                      AND DocOrig = ?
                      AND DocRowOrig = ?
                      AND MovDir IN ('O', 'I')
                    """,
                    (str(doc_num), line_num),
                )
                if int(cursor.fetchone()[0] or 0) >= 2:
                    continue

                from_wh = self._parse_wh_id(
                    line.get("FromWarehouseCode") or doc.get("FromWarehouse")
                )
                to_wh = self._parse_wh_id(
                    line.get("WarehouseCode") or doc.get("ToWarehouse")
                )
                source = self._find_source_inventory(cursor, from_wh, item_code, qty)
                dest_location = self._default_location(cursor, to_wh)
                mov_unit = self._item_unit(cursor, item_code, line.get("MeasureUnit"))
                unit_value = float(line.get("UnitPrice") or line.get("Price") or 0)
                obs = f"SAP Transfer {doc_num}. {comments}".strip()

                self._insert_stockmov(
                    cursor,
                    wh_orig=from_wh,
                    wh_dest=to_wh,
                    loc_orig=source["LocationID"],
                    loc_dest=dest_location,
                    mov_datetime=doc_date,
                    item_id=item_code,
                    lot=source["Lot"],
                    serial_num=source["SerialNum"],
                    qty=qty,
                    mov_unit=mov_unit,
                    doc_orig=str(doc_num),
                    doc_row_orig=line_num,
                    mov_dir="O",
                    unit_value=unit_value,
                    obs=obs,
                    version=source["Version"],
                    vol_num=source["VolNum"],
                    color_id=source["ColorID"],
                    size_id=source["SizeID"],
                    country=source["Country"],
                )
                self._adjust_inventory(
                    cursor,
                    wh_id=from_wh,
                    location_id=source["LocationID"],
                    item_id=item_code,
                    lot=source["Lot"],
                    serial_num=source["SerialNum"],
                    version=source["Version"],
                    vol_num=source["VolNum"],
                    color_id=source["ColorID"],
                    size_id=source["SizeID"],
                    country=source["Country"],
                    delta=-qty,
                    date_column="LastOutput",
                )

                self._insert_stockmov(
                    cursor,
                    wh_orig=from_wh,
                    wh_dest=to_wh,
                    loc_orig=source["LocationID"],
                    loc_dest=dest_location,
                    mov_datetime=doc_date,
                    item_id=item_code,
                    lot=source["Lot"],
                    serial_num=source["SerialNum"],
                    qty=qty,
                    mov_unit=mov_unit,
                    doc_orig=str(doc_num),
                    doc_row_orig=line_num,
                    mov_dir="I",
                    unit_value=unit_value,
                    obs=obs,
                    version=source["Version"],
                    vol_num=source["VolNum"],
                    color_id=source["ColorID"],
                    size_id=source["SizeID"],
                    country=source["Country"],
                )
                self._upsert_inventory(
                    cursor,
                    wh_id=to_wh,
                    location_id=dest_location,
                    item_id=item_code,
                    lot=source["Lot"],
                    serial_num=source["SerialNum"],
                    version=source["Version"],
                    vol_num=source["VolNum"],
                    color_id=source["ColorID"],
                    size_id=source["SizeID"],
                    country=source["Country"],
                    qty=qty,
                )

    @staticmethod
    def _parse_date(date_str: str | None) -> str:
        if not date_str:
            return datetime.utcnow().strftime("%Y-%m-%d")
        try:
            return date_str[:10]
        except Exception:
            return datetime.utcnow().strftime("%Y-%m-%d")

    @staticmethod
    def _parse_wh_id(value: Any) -> int:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("Warehouse code is empty")
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Warehouse code '{raw}' must be numeric for S3 WHID") from exc

    @staticmethod
    def _find_source_inventory(cursor, wh_id: int, item_id: str, qty: float) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT TOP 1
                WHID,
                LocationID,
                ItemID,
                Lot,
                SerialNum,
                Qty,
                [Version],
                VolNum,
                ColorID,
                SizeID,
                Country
            FROM Inventory
            WHERE WHID = ?
              AND ItemID = ?
              AND Qty >= ?
            ORDER BY
                CASE WHEN ISNULL(LocationID, '') = '' THEN 1 ELSE 0 END,
                Qty DESC
            """,
            (wh_id, item_id, qty),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(
                f"Insufficient S3 stock for item {item_id} in WHID {wh_id}: required {qty}"
            )
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def _default_location(cursor, wh_id: int) -> str:
        cursor.execute(
            """
            SELECT TOP 1 LocationID
            FROM Locations
            WHERE WHID = ?
              AND ISNULL(LocationID, '') <> ''
            ORDER BY ReceptionPlace DESC, StatusID DESC, Priority DESC, LocationID
            """,
            (wh_id,),
        )
        row = cursor.fetchone()
        if not row or not str(row[0] or "").strip():
            raise ValueError(f"No default S3 location found for WHID {wh_id}")
        return str(row[0]).strip()

    @staticmethod
    def _item_unit(cursor, item_id: str, fallback: Any) -> str:
        cursor.execute(
            "SELECT ISNULL(StkUnit, '') FROM ItemMaster WHERE ItemID = ?",
            (item_id,),
        )
        row = cursor.fetchone()
        value = str((row[0] if row else "") or fallback or "UN").strip()
        return value[:10] or "UN"

    @staticmethod
    def _insert_stockmov(
        cursor,
        *,
        wh_orig: int,
        wh_dest: int,
        loc_orig: str,
        loc_dest: str,
        mov_datetime: str,
        item_id: str,
        lot: str,
        serial_num: str,
        qty: float,
        mov_unit: str,
        doc_orig: str,
        doc_row_orig: int,
        mov_dir: str,
        unit_value: float,
        obs: str,
        version: int,
        vol_num: str,
        color_id: str,
        size_id: str,
        country: str,
    ) -> int | None:
        cursor.execute(
            """
            INSERT INTO StockMov (
                WHIDOrig, WHIDDest,
                LocOrig, LocDest,
                MovDateTime,
                ItemID, Lot, SerialNum, Qty, MovUnit,
                DocTypeOrig, DocOrig, DocRowOrig,
                MovDir, EquipmentID,
                CreationUser, CreationDateTime,
                UnitValue, TotValue, Obs, MovType, VolTypeID,
                QtyPVolume, QtyVols, [Version], VolNum,
                ColorID, SizeID, Country
            )
            OUTPUT INSERTED.MovID
            VALUES (
                ?, ?,
                ?, ?,
                ?,
                ?, ?, ?, ?, ?,
                'SAPTR', ?, ?,
                ?, '',
                'SAPINT', GETDATE(),
                ?, ?, ?, 'T', '',
                1, 1, ?, ?,
                ?, ?, ?
            )
            """,
            (
                wh_orig,
                wh_dest,
                loc_orig,
                loc_dest,
                mov_datetime,
                item_id,
                lot or "",
                serial_num or "",
                qty,
                mov_unit,
                doc_orig,
                doc_row_orig,
                mov_dir,
                unit_value,
                unit_value * qty,
                obs,
                int(version or 0),
                vol_num or "",
                color_id or "",
                size_id or "",
                country or "",
            ),
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    @staticmethod
    def _adjust_inventory(
        cursor,
        *,
        wh_id: int,
        location_id: str,
        item_id: str,
        lot: str,
        serial_num: str,
        version: int,
        vol_num: str,
        color_id: str,
        size_id: str,
        country: str,
        delta: float,
        date_column: str,
    ) -> None:
        if date_column not in {"LastInput", "LastOutput"}:
            raise ValueError("Invalid inventory date column")
        cursor.execute(
            f"""
            UPDATE Inventory
            SET Qty = Qty + ?, {date_column} = GETDATE()
            WHERE WHID = ?
              AND LocationID = ?
              AND ItemID = ?
              AND Lot = ?
              AND SerialNum = ?
              AND [Version] = ?
              AND VolNum = ?
              AND ColorID = ?
              AND ISNULL(SizeID, '') = ISNULL(?, '')
              AND Country = ?
            """,
            (
                delta,
                wh_id,
                location_id,
                item_id,
                lot or "",
                serial_num or "",
                int(version or 0),
                vol_num or "",
                color_id or "",
                size_id or "",
                country or "",
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"S3 inventory row not found for item {item_id} in WHID {wh_id}")

    @staticmethod
    def _upsert_inventory(
        cursor,
        *,
        wh_id: int,
        location_id: str,
        item_id: str,
        lot: str,
        serial_num: str,
        version: int,
        vol_num: str,
        color_id: str,
        size_id: str,
        country: str,
        qty: float,
    ) -> None:
        cursor.execute(
            """
            SELECT Qty
            FROM Inventory
            WHERE WHID = ?
              AND LocationID = ?
              AND ItemID = ?
              AND Lot = ?
              AND SerialNum = ?
              AND [Version] = ?
              AND VolNum = ?
              AND ColorID = ?
              AND ISNULL(SizeID, '') = ISNULL(?, '')
              AND Country = ?
            """,
            (
                wh_id,
                location_id,
                item_id,
                lot or "",
                serial_num or "",
                int(version or 0),
                vol_num or "",
                color_id or "",
                size_id or "",
                country or "",
            ),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE Inventory
                SET Qty = Qty + ?, LastInput = GETDATE()
                WHERE WHID = ?
                  AND LocationID = ?
                  AND ItemID = ?
                  AND Lot = ?
                  AND SerialNum = ?
                  AND [Version] = ?
                  AND VolNum = ?
                  AND ColorID = ?
                  AND ISNULL(SizeID, '') = ISNULL(?, '')
                  AND Country = ?
                """,
                (
                    qty,
                    wh_id,
                    location_id,
                    item_id,
                    lot or "",
                    serial_num or "",
                    int(version or 0),
                    vol_num or "",
                    color_id or "",
                    size_id or "",
                    country or "",
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO Inventory (
                    WHID, LocationID, ItemID,
                    Lot, SerialNum, Qty,
                    LastInput, [Version], VolNum,
                    ColorID, SizeID, Country
                )
                VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    GETDATE(), ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    wh_id,
                    location_id,
                    item_id,
                    lot or "",
                    serial_num or "",
                    qty,
                    int(version or 0),
                    vol_num or "",
                    color_id or "",
                    size_id or "",
                    country or "",
                ),
            )

    @staticmethod
    def _normalize_udf_field(value: Any) -> str:
        raw = str(value or "").strip() or "SEI_DocONS3"
        return raw if raw.upper().startswith("U_") else f"U_{raw}"

    @staticmethod
    def _empty_udf_filter(field_name: str) -> str:
        return f"({field_name} eq null or {field_name} eq '')"

    @staticmethod
    def _build_s3_reference(doc: Dict[str, Any]) -> str:
        doc_num = doc.get("DocNum") or doc.get("DocEntry")
        return f"S3T{doc_num}"

    async def _is_locally_synced(self, doc_entry: int) -> bool:
        return await self._wms.ais_sap_integration_synced(
            self.name,
            "StockTransfers",
            str(doc_entry),
        )

    async def _mark_locally_synced(
        self,
        doc: Dict[str, Any],
        s3_reference: str,
        sap_mark_error: str | None,
    ) -> None:
        await self._wms.amark_sap_integration_synced(
            self.name,
            "StockTransfers",
            str(doc["DocEntry"]),
            sap_doc_entry=int(doc["DocEntry"]),
            sap_doc_num=int(doc["DocNum"]),
            sap_series=str(doc.get("Series") or ""),
            s3_reference=s3_reference,
            last_error=sap_mark_error,
        )
