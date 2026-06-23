from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import FastAPI

from app.db.connection import db_cursor
from app.models.by_ptl import ByPtlDispatchRequest
from app.services.by_ptl import dispatch_to_wms
from app.settings import settings


LOGGER = logging.getLogger("s4_api.by_ptl.queue")
SUPPORTED_EVENTS = ("PTL_START", "PTL_CHANGE", "PACKING_LIST", "PACKED_BOX")


@dataclass(frozen=True)
class QueueEvent:
    sync_id: UUID
    area: str
    fields: tuple[Optional[str], ...]

    def field(self, number: int, required: bool = False) -> Optional[str]:
        value = self.fields[number - 1]
        normalized = str(value).strip() if value is not None else ""
        if required and not normalized:
            raise ValueError(f"{self.area}: Field{number:02d} is required")
        return normalized or None


def register_by_ptl_queue_worker(app: FastAPI) -> None:
    @app.on_event("startup")
    async def start_by_ptl_queue_worker() -> None:
        if not settings.by_ptl_queue_enabled:
            LOGGER.info("BY-PTL SyncQueue worker is disabled")
            return
        if not settings.by_ptl_wms_url:
            LOGGER.warning(
                "BY-PTL SyncQueue worker was not started because BY_PTL_WMS_URL is empty"
            )
            return
        app.state.by_ptl_queue_task = asyncio.create_task(_queue_loop())

    @app.on_event("shutdown")
    async def stop_by_ptl_queue_worker() -> None:
        task = getattr(app.state, "by_ptl_queue_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _queue_loop() -> None:
    LOGGER.info(
        "BY-PTL SyncQueue worker started; poll interval=%ss",
        settings.by_ptl_queue_poll_seconds,
    )
    while True:
        try:
            processed = await asyncio.to_thread(process_next_event)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Unexpected failure while polling BY-PTL SyncQueue")
            processed = False

        if not processed:
            await asyncio.sleep(settings.by_ptl_queue_poll_seconds)


def process_next_event() -> bool:
    event = _claim_next_event()
    if event is None:
        return False

    try:
        payload = _build_event_payload(event)
        request = ByPtlDispatchRequest.model_validate(
            {"Action": event.area, "Data": payload}
        )
        response = dispatch_to_wms(request)
        response_text = response.model_dump_json(by_alias=True)
        _finish_event(event.sync_id, succeeded=True, response=response_text)
        LOGGER.info("BY-PTL event %s (%s) sent successfully", event.sync_id, event.area)
    except Exception as exc:
        error_text = json.dumps(
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            ensure_ascii=False,
        )
        _finish_event(event.sync_id, succeeded=False, response=error_text)
        LOGGER.exception("BY-PTL event %s (%s) failed", event.sync_id, event.area)

    return True


def _claim_next_event() -> Optional[QueueEvent]:
    placeholders = ", ".join("?" for _ in SUPPORTED_EVENTS)
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            f"""
            ;WITH NextEvent AS (
                SELECT TOP (1) *
                FROM dbo.SyncQueue WITH (UPDLOCK, READPAST, ROWLOCK)
                WHERE SyncStarted = 0
                  AND SyncEnded = 0
                  AND Area IN ({placeholders})
                ORDER BY Priority DESC, RequestDate, SyncID
            )
            UPDATE NextEvent
            SET SyncStarted = 1,
                SyncStartDate = GETDATE(),
                SyncSucceeded = 0,
                SyncError = 0,
                SyncResponse = N''
            OUTPUT
                INSERTED.SyncID,
                INSERTED.Area,
                INSERTED.Field01,
                INSERTED.Field02,
                INSERTED.Field03,
                INSERTED.Field04,
                INSERTED.Field05,
                INSERTED.Field06,
                INSERTED.Field07,
                INSERTED.Field08,
                INSERTED.Field09,
                INSERTED.Field10
            """,
            SUPPORTED_EVENTS,
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return QueueEvent(
        sync_id=row[0],
        area=str(row[1]).strip().upper(),
        fields=tuple(row[index] for index in range(2, 12)),
    )


def _finish_event(sync_id: UUID, succeeded: bool, response: str) -> None:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            UPDATE dbo.SyncQueue
            SET SyncEnded = 1,
                SyncSucceeded = ?,
                SyncError = ?,
                SyncResponse = ?,
                SyncEndDate = GETDATE()
            WHERE SyncID = ?
            """,
            (1 if succeeded else 0, 0 if succeeded else 1, response, sync_id),
        )


def _build_event_payload(event: QueueEvent) -> dict[str, Any]:
    order_picking_id = _positive_int(event.field(1, required=True), "Field01")
    wave_id, current_ptl = _get_wave_context(order_picking_id)

    if event.area == "PTL_START":
        return {"WAVEID": wave_id, "PTLID": current_ptl}
    if event.area == "PTL_CHANGE":
        return {
            "WAVEID": wave_id,
            "PTLID": event.field(2, required=True),
        }
    if event.area == "PACKING_LIST":
        return _build_packing_list_payload(
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            ptl_id=current_ptl,
            packing_list_id=event.field(2, required=True) or "",
        )
    if event.area == "PACKED_BOX":
        return _build_packed_box_payload(
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            ptl_id=current_ptl,
            vol_doc_cod=event.field(2, required=True) or "",
            vol_num=_positive_int(event.field(3, required=True), "Field03"),
        )
    raise ValueError(f"Unsupported BY-PTL queue event: {event.area}")


def _get_wave_context(order_picking_id: int) -> tuple[str, str]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            SELECT
                op.OrderPickingGroup,
                ptl.RouteID
            FROM OrdersPicking op WITH (NOLOCK)
            OUTER APPLY (
                SELECT TOP (1) co.RouteID
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                JOIN ClientOrders co WITH (NOLOCK)
                  ON co.DocType = opd.DocTypeOri
                 AND co.OrderID = opd.OrderIDOri
                WHERE opd.OrderID = op.ID
                  AND ISNULL(opd.deleted, 0) = 0
                  AND NULLIF(LTRIM(RTRIM(co.RouteID)), '') IS NOT NULL
                ORDER BY opd.RowNumber
            ) ptl
            WHERE op.ID = ?
              AND ISNULL(op.deleted, 0) = 0
            """,
            (order_picking_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise ValueError(f"OrdersPicking ID {order_picking_id} was not found")
    wave_id = _required_text(row[0], "OrdersPicking.OrderPickingGroup")
    ptl_id = _required_text(row[1], "ClientOrders.RouteID (PTL)")
    return wave_id, ptl_id


def _build_packing_list_payload(
    order_picking_id: int,
    wave_id: str,
    ptl_id: str,
    packing_list_id: str,
) -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            ;WITH PickingOrders AS (
                SELECT
                    OrderIDOri,
                    DocTypeOri,
                    MIN(NULLIF(LTRIM(RTRIM(LocationIDDest)), '')) AS PTLLight
                FROM OrdersPickingDetails WITH (NOLOCK)
                WHERE OrderID = ?
                  AND ISNULL(deleted, 0) = 0
                GROUP BY OrderIDOri, DocTypeOri
            )
            SELECT
                po.OrderIDOri,
                po.PTLLight,
                vm.VolNum,
                ISNULL(vm.VolWeight, 0),
                vm.VolTypeID,
                vm.CreationUser,
                vi.VolItemNumber,
                vi.ParentOrderRow,
                vi.ItemID,
                ISNULL(vi.ItemQtyIni, vi.ItemQty)
            FROM PickingOrders po
            JOIN VolMaster vm WITH (NOLOCK)
              ON vm.ParentDocType = po.DocTypeOri
             AND vm.ParentOrderID = po.OrderIDOri
            JOIN VolItem vi WITH (NOLOCK)
              ON vi.VolDocCod = vm.VolDocCod
             AND vi.VolNum = vm.VolNum
            ORDER BY po.OrderIDOri, vm.VolNum, vi.VolItemNumber
            """,
            (order_picking_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        raise ValueError(
            f"No volumes were found for OrdersPicking ID {order_picking_id}"
        )

    orders: dict[str, dict[str, Any]] = {}
    volumes: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        order_id = _required_text(row[0], "OrdersPickingDetails.OrderIDOri")
        order = orders.setdefault(
            order_id,
            {
                "ORDERID": order_id,
                "PTLLIGHT": _required_text(row[1], "OrdersPickingDetails.LocationIDDest"),
                "VOLUMES": [],
            },
        )
        volume_id = _required_text(row[2], "VolMaster.VolNum")
        volume_key = (order_id, volume_id)
        volume = volumes.get(volume_key)
        if volume is None:
            volume = {
                "VOLUMEID": volume_id,
                "VOLUMEWEIGHT": _decimal(row[3]),
                "VOLUMETYPE": _required_text(row[4], "VolMaster.VolTypeID"),
                "USERID": _required_text(row[5], "VolMaster.CreationUser"),
                "VOLUMEDETAIL": [],
            }
            volumes[volume_key] = volume
            order["VOLUMES"].append(volume)
        volume["VOLUMEDETAIL"].append(
            {
                "ORDERID": order_id,
                "VOLUMROWID": _required_text(row[6], "VolItem.VolItemNumber"),
                "LINE": _required_text(row[7], "VolItem.ParentOrderRow"),
                "ITEMID": _required_text(row[8], "VolItem.ItemID"),
                "QUANTITY": _decimal(row[9]),
            }
        )

    return {
        "WAVEID": wave_id,
        "PTLID": ptl_id,
        "PACKINGLISTID": packing_list_id,
        "ORDERS": list(orders.values()),
    }


def _build_packed_box_payload(
    order_picking_id: int,
    wave_id: str,
    ptl_id: str,
    vol_doc_cod: str,
    vol_num: int,
) -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            ;WITH PickingOrders AS (
                SELECT
                    OrderIDOri,
                    DocTypeOri,
                    MIN(NULLIF(LTRIM(RTRIM(LocationIDDest)), '')) AS PTLLight
                FROM OrdersPickingDetails WITH (NOLOCK)
                WHERE OrderID = ?
                  AND ISNULL(deleted, 0) = 0
                GROUP BY OrderIDOri, DocTypeOri
            )
            SELECT
                po.OrderIDOri,
                po.PTLLight,
                vm.CreationUser,
                vm.VolNum,
                ISNULL(vm.VolWeight, 0),
                vm.VolTypeID,
                vi.VolItemNumber,
                vi.ParentOrderRow,
                vi.ItemID,
                ISNULL(vi.ItemQty, 0)
            FROM VolMaster vm WITH (NOLOCK)
            JOIN PickingOrders po
              ON po.DocTypeOri = vm.ParentDocType
             AND po.OrderIDOri = vm.ParentOrderID
            JOIN VolItem vi WITH (NOLOCK)
              ON vi.VolDocCod = vm.VolDocCod
             AND vi.VolNum = vm.VolNum
            WHERE vm.VolDocCod = ?
              AND vm.VolNum = ?
            ORDER BY vi.VolItemNumber
            """,
            (order_picking_id, vol_doc_cod, vol_num),
        )
        rows = cursor.fetchall()

    if not rows:
        raise ValueError(
            f"Volume {vol_doc_cod}/{vol_num} was not found in OrdersPicking {order_picking_id}"
        )

    first = rows[0]
    return {
        "WAVEID": wave_id,
        "ORDERID": _required_text(first[0], "OrdersPickingDetails.OrderIDOri"),
        "PTLID": ptl_id,
        "PTLLIGHT": _required_text(first[1], "OrdersPickingDetails.LocationIDDest"),
        "USERID": _required_text(first[2], "VolMaster.CreationUser"),
        "VOLUMEID": _required_text(first[3], "VolMaster.VolNum"),
        "VOLUMEWEIGHT": _decimal(first[4]),
        "VOLUMETYPE": _required_text(first[5], "VolMaster.VolTypeID"),
        "VOLUMEDETAIL": [
            {
                "VOLUMROWID": _required_text(row[6], "VolItem.VolItemNumber"),
                "LINE": _required_text(row[7], "VolItem.ParentOrderRow"),
                "ITEMID": _required_text(row[8], "VolItem.ItemID"),
                "QUANTITY": _decimal(row[9]),
            }
            for row in rows
        ],
    }


def _positive_int(value: Optional[str], field_name: str) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain a numeric ID") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must contain a positive numeric ID")
    return parsed


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"Missing required source value: {field_name}")
    return normalized


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))
