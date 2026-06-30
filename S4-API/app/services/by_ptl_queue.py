from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import FastAPI

from app.db.connection import db_cursor
from app.models.by_ptl import ByPtlDispatchRequest
from app.repositories.by_ptl import _fill_required_table_defaults
from app.repositories.production_control import _insert_dynamic, _table_columns
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
        pkl_order_id = _ensure_pkl_document(
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            ptl_id=current_ptl,
        )
        _update_event_pkl_fields(event.sync_id, pkl_order_id)
        packing_list_id = f"PKL.{pkl_order_id}"
        return _build_packing_list_payload(
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            ptl_id=current_ptl,
            packing_list_id=packing_list_id,
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


def _update_event_pkl_fields(sync_id: UUID, pkl_order_id: int) -> None:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            UPDATE dbo.SyncQueue
            SET Field02 = N'PKL',
                Field03 = ?
            WHERE SyncID = ?
            """,
            (str(pkl_order_id), sync_id),
        )


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


def _ensure_pkl_document(order_picking_id: int, wave_id: str, ptl_id: str) -> int:
    now = datetime.now()
    cache: dict[str, dict[str, str]] = {}
    with db_cursor() as (cursor, _conn):
        rows = _fetch_order_picking_detail_origins(cursor, order_picking_id)
        if not rows:
            raise ValueError(
                f"No picking details were found for OrdersPicking ID {order_picking_id}"
            )

        pkl_order_id = _get_or_create_pkl_header(
            cursor=cursor,
            cache=cache,
            wave_id=wave_id,
            ptl_id=ptl_id,
            total_qty=sum(_decimal(row[5]) for row in rows),
            requester_id=str(rows[0][6] or "").strip(),
            client_id=str(rows[0][7] or "").strip(),
            now=now,
        )
        _rebuild_pkl_lines(
            cursor=cursor,
            cache=cache,
            pkl_order_id=pkl_order_id,
            rows=rows,
            now=now,
        )
        return pkl_order_id


def _fetch_order_picking_detail_origins(cursor, order_picking_id: int):
    cursor.execute(
        """
        SELECT
            opd.RowNumber,
            opd.ItemID,
            opd.DocTypeOri,
            opd.OrderIDOri,
            opd.OrderRowOri,
            ISNULL(NULLIF(opd.QtyPicked, 0), opd.Qty) AS Qty,
            co.RequesterID,
            co.ClientID
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        LEFT JOIN ClientOrders co WITH (NOLOCK)
          ON co.DocType = opd.DocTypeOri
         AND co.OrderID = opd.OrderIDOri
        WHERE opd.OrderID = ?
          AND ISNULL(opd.deleted, 0) = 0
        ORDER BY opd.RowNumber
        """,
        (order_picking_id,),
    )
    return cursor.fetchall()


def _get_or_create_pkl_header(
    cursor,
    cache: dict[str, dict[str, str]],
    wave_id: str,
    ptl_id: str,
    total_qty: Decimal,
    requester_id: str,
    client_id: str,
    now: datetime,
) -> int:
    wave_column = _client_orders_wave_column(cursor, cache)
    cursor.execute(
        f"""
        SELECT OrderID
        FROM ClientOrders WITH (UPDLOCK, HOLDLOCK)
        WHERE DocType = 'PKL'
          AND {wave_column} = ?
        """,
        (wave_id,),
    )
    row = cursor.fetchone()
    if row is not None:
        pkl_order_id = int(row[0])
        _update_pkl_header(
            cursor=cursor,
            cache=cache,
            pkl_order_id=pkl_order_id,
            wave_id=wave_id,
            ptl_id=ptl_id,
            total_qty=total_qty,
            requester_id=requester_id,
            client_id=client_id,
            now=now,
        )
        return pkl_order_id

    pkl_order_id = _next_pkl_order_id(cursor)
    values: dict[str, Any] = {
        "DocType": "PKL",
        "OrderID": pkl_order_id,
        "PartNum": 0,
        "CreateDateTime": now,
        "OrderDateTime": now,
        "ClientID": client_id or requester_id or "BY-PTL",
        "PartnerID": client_id or requester_id or "BY-PTL",
        "RequesterID": requester_id or client_id or "BY-PTL",
        "RouteID": ptl_id,
        "Status": 1,
        "PepStatus": 0,
        "ProductionStatus": "INICIAL",
        "OrderDatePrev": now,
        "Obs": f"BY-PTL packing list for wave {wave_id}",
        "CreationUser": "BY-PTL",
        "CreationDateTime": now,
        "Currency": "EUR",
        "ExangeRate": 1,
        "ExchangeRate": 1,
        "TotalQtyOrd": total_qty,
        "TotalValue": 0,
        "TotalShipValue": 0,
        "Tipo": 0,
        "PercDsc2": 0,
        "CreditApproved": 0,
        "UrgencyStatusID": 0,
        "ConsignmentDoc": 0,
        "RecuseDoc": 0,
        "PartnerCategory": "C",
        "IDIntegration": wave_id,
        "RefCli": wave_id,
    }
    _fill_required_table_defaults(
        cursor=cursor,
        table_name="ClientOrders",
        values=values,
        now=now,
    )
    _insert_dynamic(
        cursor,
        "ClientOrders",
        values,
        required_columns={"DocType", "OrderID"},
        cache=cache,
    )
    return pkl_order_id


def _update_pkl_header(
    cursor,
    cache: dict[str, dict[str, str]],
    pkl_order_id: int,
    wave_id: str,
    ptl_id: str,
    total_qty: Decimal,
    requester_id: str,
    client_id: str,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "ClientOrders", cache)
    values: dict[str, Any] = {
        "OrderDateTime": now,
        "ClientID": client_id or requester_id or "BY-PTL",
        "PartnerID": client_id or requester_id or "BY-PTL",
        "RequesterID": requester_id or client_id or "BY-PTL",
        "RouteID": ptl_id,
        "Obs": f"BY-PTL packing list for wave {wave_id}",
        "TotalQtyOrd": total_qty,
        "IDIntegration": wave_id,
        "RefCli": wave_id,
        "ModifDateTime": now,
    }
    set_parts: list[str] = []
    params: list[Any] = []
    for column_name, value in values.items():
        normalized = column_name.lower()
        if normalized not in columns:
            continue
        set_parts.append(f"{columns[normalized]} = ?")
        params.append(value)

    if not set_parts:
        return

    params.append(pkl_order_id)
    cursor.execute(
        f"""
        UPDATE ClientOrders
        SET {', '.join(set_parts)}
        WHERE DocType = 'PKL'
          AND OrderID = ?
        """,
        tuple(params),
    )


def _client_orders_wave_column(cursor, cache: dict[str, dict[str, str]]) -> str:
    columns = _table_columns(cursor, "ClientOrders", cache)
    if "refcli" in columns:
        return columns["refcli"]
    if "idintegration" in columns:
        return columns["idintegration"]
    raise ValueError(
        "ClientOrders must have either RefCli or IDIntegration to store the BY-PTL wave"
    )


def _next_pkl_order_id(cursor) -> int:
    base = datetime.now().year * 1000000
    cursor.execute(
        """
        SELECT ISNULL(MAX(OrderID), ?)
        FROM ClientOrders WITH (UPDLOCK, HOLDLOCK)
        WHERE DocType = 'PKL'
          AND OrderID >= ?
        """,
        (base, base),
    )
    return int(cursor.fetchone()[0]) + 1


def _rebuild_pkl_lines(
    cursor,
    cache: dict[str, dict[str, str]],
    pkl_order_id: int,
    rows,
    now: datetime,
) -> None:
    cursor.execute(
        """
        DELETE FROM ClientOrderDetailsOri
        WHERE DocType = 'PKL'
          AND OrderID = ?
        """,
        (pkl_order_id,),
    )
    cursor.execute(
        """
        DELETE FROM ClientOrderDetails
        WHERE DocType = 'PKL'
          AND OrderID = ?
        """,
        (pkl_order_id,),
    )

    for order_row, row in enumerate(rows, start=1):
        item_id = _required_text(row[1], "OrdersPickingDetails.ItemID")
        origin_doc_type = _required_text(row[2], "OrdersPickingDetails.DocTypeOri")
        origin_order_id = _positive_int(
            _required_text(row[3], "OrdersPickingDetails.OrderIDOri"),
            "OrdersPickingDetails.OrderIDOri",
        )
        origin_order_row = _positive_int(
            _required_text(row[4], "OrdersPickingDetails.OrderRowOri"),
            "OrdersPickingDetails.OrderRowOri",
        )
        qty = _decimal(row[5])

        detail_values: dict[str, Any] = {
            "DocType": "PKL",
            "OrderID": pkl_order_id,
            "OrderRow": order_row,
            "PartNum": 0,
            "VolNum": 0,
            "ItemID": item_id,
            "QtyProd": qty,
            "QtyOrdered": qty,
            "QtyOrd": qty,
            "QtySatisf": 0,
            "QtyPicked": 0,
            "QtyVols": 0,
            "Unit": "UN",
            "UnitPrice": 0,
            "ItemValue": 0,
            "TotValue": 0,
            "Status": 1,
            "ProductionStatus": "INICIAL",
            "CreationUser": "BY-PTL",
            "CreationDateTime": now,
            "Currency": "EUR",
            "ExchangeRate": 1,
            "ExangeRate": 1,
            "ColorID": "UN",
            "GridID": "UN",
            "SizeID": "UN",
            "DocTypeOri": origin_doc_type,
            "OrderIDOri": origin_order_id,
            "OrderIdORi": origin_order_id,
            "OrderRowOri": origin_order_row,
            "PartNumOri": 0,
            "IDIntegration": str(row[0]),
            "RefCli": str(row[0]),
        }
        _fill_required_table_defaults(
            cursor=cursor,
            table_name="ClientOrderDetails",
            values=detail_values,
            now=now,
        )
        _insert_dynamic(
            cursor,
            "ClientOrderDetails",
            detail_values,
            required_columns={"DocType", "OrderID", "OrderRow", "ItemID"},
            cache=cache,
        )

        ori_values: dict[str, Any] = {
            "DocType": "PKL",
            "OrderID": pkl_order_id,
            "OrderRow": order_row,
            "PartNum": 0,
            "VolNum": 0,
            "DocTypeOri": origin_doc_type,
            "OrderIDOri": origin_order_id,
            "OrderRowOri": origin_order_row,
            "PartNumOri": 0,
            "VolNumOri": 0,
            "QtyOrd": qty,
            "QtyVols": 0,
            "QtyOrdDest": qty,
        }
        _fill_required_table_defaults(
            cursor=cursor,
            table_name="ClientOrderDetailsOri",
            values=ori_values,
            now=now,
        )
        _insert_dynamic(
            cursor,
            "ClientOrderDetailsOri",
            ori_values,
            required_columns={"DocType", "OrderID", "OrderRow"},
            cache=cache,
        )


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
