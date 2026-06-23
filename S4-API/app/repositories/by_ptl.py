from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.db.connection import db_cursor
from app.repositories.production_control import _insert_dynamic, _table_columns


def create_or_update_articles(articles: list[dict[str, Any]]) -> dict[str, int]:
    created = 0
    updated = 0
    cache: dict[str, dict[str, str]] = {}

    with db_cursor() as (cursor, _conn):
        for article in articles:
            item_id = str(article["item_id"]).strip()
            description = str(article["description"]).strip()
            length = _to_float(article["length"])
            height = _to_float(article["height"])
            width = _to_float(article["width"])
            net_weight = _to_float(article["net_weight"])
            barcode = str(article["barcode"]).strip()
            now = datetime.now()

            cursor.execute("SELECT 1 FROM ItemMaster WITH (NOLOCK) WHERE ItemID = ?", (item_id,))
            exists = cursor.fetchone() is not None

            if exists:
                _update_item_master(
                    cursor=cursor,
                    cache=cache,
                    item_id=item_id,
                    description=description,
                    length=length,
                    height=height,
                    width=width,
                    net_weight=net_weight,
                    barcode=barcode,
                    now=now,
                )
                updated += 1
            else:
                _insert_item_master(
                    cursor=cursor,
                    cache=cache,
                    item_id=item_id,
                    description=description,
                    length=length,
                    height=height,
                    width=width,
                    net_weight=net_weight,
                    barcode=barcode,
                    now=now,
                )
                created += 1

    return {"created": created, "updated": updated}


def create_or_update_customers_and_orders(
    wave_id: str,
    wave_obs: str | None,
    ptl: str,
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    customers_created = 0
    customers_updated = 0
    orders_created = 0
    orders_updated = 0
    lines_created = 0
    enc_orders: list[dict[str, Any]] = []
    cache: dict[str, dict[str, str]] = {}

    with db_cursor() as (cursor, _conn):
        for order in orders:
            customer_result = _create_or_update_customer(
                cursor=cursor,
                cache=cache,
                customer_id=str(order["customer_id"]).strip(),
                customer_name=str(order["customer_name"]).strip(),
            )
            if customer_result == "created":
                customers_created += 1
            else:
                customers_updated += 1

            order_result = _create_or_update_enc_order(
                cursor=cursor,
                cache=cache,
                wave_id=wave_id,
                wave_obs=wave_obs,
                ptl=ptl,
                order=order,
            )
            if order_result["action"] == "created":
                orders_created += 1
            else:
                orders_updated += 1
            lines_created += int(order_result["lines"])
            enc_orders.append(
                {
                    "order_id": int(order_result["order_id"]),
                    "lines": order["detail_order"],
                }
            )

        picking_result = _create_or_update_order_picking(
            cursor=cursor,
            cache=cache,
            wave_id=wave_id,
            wave_obs=wave_obs,
            ptl=ptl,
            enc_orders=enc_orders,
        )

    return {
        "customers_created": customers_created,
        "customers_updated": customers_updated,
        "orders_created": orders_created,
        "orders_updated": orders_updated,
        "lines_created": lines_created,
        "picking_created": picking_result["created"],
        "picking_details_count": picking_result["details_count"],
    }


def enqueue_ptl_change(wave_id: str, ptl: str) -> dict[str, Any]:
    now = datetime.now()
    normalized_wave_id = str(wave_id).strip()
    normalized_ptl = str(ptl).strip()
    cache: dict[str, dict[str, str]] = {}

    with db_cursor() as (cursor, _conn):
        wh_id_dest, location_id_dest = _get_ptl_destination(cursor, normalized_ptl)
        order_picking_id = _get_order_picking_id_by_wave(cursor, normalized_wave_id)

        _update_wave_ptl(
            cursor=cursor,
            cache=cache,
            order_picking_id=order_picking_id,
            ptl=normalized_ptl,
            wh_id_dest=wh_id_dest,
            location_id_dest=location_id_dest,
            now=now,
        )

        sync_id = str(uuid4())
        values: dict[str, Any] = {
            "SyncID": sync_id,
            "Area": "PTL_CHANGE",
            "RequestDate": now,
            "SyncStarted": 0,
            "SyncEnded": 0,
            "SyncSucceeded": 0,
            "SyncError": 0,
            "SyncResponse": "",
            "Priority": 0,
            "Async": 1,
            "Field01": str(order_picking_id),
            "Field02": normalized_ptl,
            "CreationUser": "BY-PTL",
            "CreationDateTime": now,
            "created_by": "BY-PTL",
            "created_date": now,
        }
        _fill_required_table_defaults(
            cursor=cursor,
            table_name="SyncQueue",
            values=values,
            now=now,
        )
        _insert_dynamic(
            cursor,
            "SyncQueue",
            values,
            required_columns={"Area", "Field01", "Field02"},
            cache=cache,
        )

    return {
        "sync_id": sync_id,
        "order_picking_id": order_picking_id,
        "wave_id": normalized_wave_id,
        "ptl_id": normalized_ptl,
    }


def _get_order_picking_id_by_wave(cursor, wave_id: str) -> int:
    cursor.execute(
        """
        SELECT TOP (1) ID
        FROM OrdersPicking WITH (UPDLOCK, HOLDLOCK)
        WHERE OrderPickingGroup = ?
          AND ISNULL(deleted, 0) = 0
        ORDER BY ID DESC
        """,
        (wave_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Wave '{wave_id}' was not found in OrdersPicking")
    return int(row[0])


def _update_wave_ptl(
    cursor,
    cache: dict[str, dict[str, str]],
    order_picking_id: int,
    ptl: str,
    wh_id_dest: Any,
    location_id_dest: Any,
    now: datetime,
) -> None:
    order_columns = _table_columns(cursor, "ClientOrders", cache)
    client_order_set_parts: list[str] = []
    client_order_params: list[Any] = []

    if "routeid" in order_columns:
        client_order_set_parts.append(f"co.{order_columns['routeid']} = ?")
        client_order_params.append(ptl)
    if "modifdatetime" in order_columns:
        client_order_set_parts.append(f"co.{order_columns['modifdatetime']} = ?")
        client_order_params.append(now)

    if client_order_set_parts:
        client_order_params.append(order_picking_id)
        cursor.execute(
            f"""
            UPDATE co
            SET {', '.join(client_order_set_parts)}
            FROM ClientOrders co
            WHERE EXISTS (
                SELECT 1
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                WHERE opd.OrderID = ?
                  AND ISNULL(opd.deleted, 0) = 0
                  AND co.DocType = opd.DocTypeOri
                  AND co.OrderID = opd.OrderIDOri
            )
            """,
            tuple(client_order_params),
        )

    picking_columns = _table_columns(cursor, "OrdersPicking", cache)
    picking_values: dict[str, Any] = {
        "WhIDDest": wh_id_dest,
        "LocationIDDest": location_id_dest,
        "edited_by": "BY-PTL",
        "edited_date": now,
    }
    picking_set_parts: list[str] = []
    picking_params: list[Any] = []
    for column_name, value in picking_values.items():
        normalized = column_name.lower()
        if normalized not in picking_columns:
            continue
        picking_set_parts.append(f"{picking_columns[normalized]} = ?")
        picking_params.append(value)

    if picking_set_parts:
        picking_params.append(order_picking_id)
        cursor.execute(
            f"""
            UPDATE OrdersPicking
            SET {', '.join(picking_set_parts)}
            WHERE ID = ?
            """,
            tuple(picking_params),
        )


def _create_or_update_customer(
    cursor,
    cache: dict[str, dict[str, str]],
    customer_id: str,
    customer_name: str,
) -> str:
    now = datetime.now()
    cursor.execute(
        """
        SELECT 1
        FROM BusinessPartners WITH (NOLOCK)
        WHERE PartnerType = 'C'
          AND PartnerID = ?
        """,
        (customer_id,),
    )
    exists = cursor.fetchone() is not None

    if exists:
        columns = _table_columns(cursor, "BusinessPartners", cache)
        values = {
            "PartnerName": customer_name,
            "GLNCode": customer_id,
            "Active": 1,
            "Status": 1,
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

        if set_parts:
            params.append(customer_id)
            cursor.execute(
                f"""
                UPDATE BusinessPartners
                SET {', '.join(set_parts)}
                WHERE PartnerType = 'C'
                  AND PartnerID = ?
                """,
                tuple(params),
            )
        return "updated"

    values = {
        "PartnerType": "C",
        "PartnerID": customer_id,
        "PartnerName": customer_name,
        "GLNCode": customer_id,
        "Active": 1,
        "Status": 1,
        "CreationUser": "BY-PTL",
        "CreationDateTime": now,
        "ModifDateTime": now,
    }
    _fill_required_business_partner_defaults(
        cursor=cursor,
        values=values,
        customer_id=customer_id,
        customer_name=customer_name,
        now=now,
    )
    _insert_dynamic(
        cursor,
        "BusinessPartners",
        values,
        required_columns={"PartnerType", "PartnerID", "PartnerName"},
        cache=cache,
    )
    return "created"


def _fill_required_business_partner_defaults(
    cursor,
    values: dict[str, Any],
    customer_id: str,
    customer_name: str,
    now: datetime,
) -> None:
    current_columns = {column.lower() for column in values}
    for column in _required_insert_columns(cursor, "BusinessPartners"):
        normalized = column["name"].lower()
        if normalized in current_columns:
            continue

        values[column["name"]] = _standard_business_partner_value(
            column=column,
            customer_id=customer_id,
            customer_name=customer_name,
            now=now,
        )
        current_columns.add(normalized)


def _standard_business_partner_value(
    column: dict[str, Any],
    customer_id: str,
    customer_name: str,
    now: datetime,
) -> Any:
    normalized = str(column["name"]).lower()
    data_type = str(column["data_type"]).lower()

    if data_type in {"char", "nchar", "varchar", "nvarchar", "text", "ntext"}:
        if normalized == "partnertype":
            return _fit_text("C", column)
        if normalized in {"partnerid", "clientid", "customerid", "glncode"}:
            return _fit_text(customer_id, column)
        if normalized in {"partnername", "clientname", "customername", "name"}:
            return _fit_text(customer_name, column)
        if "user" in normalized:
            return _fit_text("BY-PTL", column)
        if "currency" in normalized:
            return _fit_text("EUR", column)
        if "country" in normalized:
            return _fit_text("PT", column)
        if "status" in normalized:
            return _fit_text("ACTIVE", column)
        return _fit_text("", column)

    if data_type in {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"}:
        return now

    if data_type == "bit":
        return 1 if normalized in {"active", "status", "flag"} else 0

    if data_type in {
        "tinyint",
        "smallint",
        "int",
        "bigint",
        "decimal",
        "numeric",
        "money",
        "smallmoney",
        "float",
        "real",
    }:
        return 1 if normalized in {"active", "status", "flag"} else 0

    if data_type == "uniqueidentifier":
        return "00000000-0000-0000-0000-000000000000"

    if data_type in {"binary", "varbinary", "image"}:
        return b""

    return ""


def _create_or_update_enc_order(
    cursor,
    cache: dict[str, dict[str, str]],
    wave_id: str,
    wave_obs: str | None,
    ptl: str,
    order: dict[str, Any],
) -> dict[str, object]:
    now = datetime.now()
    external_order_id = str(order["order_id"]).strip()
    order_id = _parse_order_id(external_order_id)
    customer_id = str(order["customer_id"]).strip()
    order_obs = str(order.get("order_obs") or wave_obs or "")
    detail_order = order["detail_order"]
    total_qty = sum(int(line["quantity"]) for line in detail_order)

    cursor.execute(
        """
        SELECT 1
        FROM ClientOrders WITH (NOLOCK)
        WHERE DocType = 'ENC'
          AND OrderID = ?
        """,
        (order_id,),
    )
    row = cursor.fetchone()
    if row:
        _update_enc_order_header(
            cursor=cursor,
            cache=cache,
            order_id=order_id,
            customer_id=customer_id,
            order_obs=order_obs,
            total_qty=total_qty,
            wave_id=wave_id,
            ptl=ptl,
            now=now,
        )
        cursor.execute(
            """
            DELETE FROM ClientOrderDetails
            WHERE DocType = 'ENC'
              AND OrderID = ?
            """,
            (order_id,),
        )
        action = "updated"
    else:
        _insert_enc_order_header(
            cursor=cursor,
            cache=cache,
            order_id=order_id,
            customer_id=customer_id,
            order_obs=order_obs,
            total_qty=total_qty,
            external_order_id=external_order_id,
            wave_id=wave_id,
            ptl=ptl,
            now=now,
        )
        action = "created"

    _insert_enc_order_lines(
        cursor=cursor,
        cache=cache,
        order_id=order_id,
        lines=detail_order,
        now=now,
    )

    return {"action": action, "order_id": order_id, "lines": len(detail_order)}


def _parse_order_id(order_id: str) -> int:
    try:
        return int(order_id)
    except ValueError as exc:
        raise ValueError(
            f"OrderId '{order_id}' must be numeric because it is stored in ClientOrders.OrderID"
        ) from exc


def _create_or_update_order_picking(
    cursor,
    cache: dict[str, dict[str, str]],
    wave_id: str,
    wave_obs: str | None,
    ptl: str,
    enc_orders: list[dict[str, Any]],
) -> dict[str, object]:
    now = datetime.now()
    wh_id_dest, location_id_dest = _get_ptl_destination(cursor, ptl)
    cursor.execute(
        """
        SELECT ID
        FROM OrdersPicking WITH (UPDLOCK, HOLDLOCK)
        WHERE OrderPickingGroup = ?
          AND ISNULL(deleted, 0) = 0
        """,
        (wave_id,),
    )
    row = cursor.fetchone()

    if row:
        order_picking_id = int(row[0])
        _update_order_picking_header(
            cursor=cursor,
            cache=cache,
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            wave_obs=wave_obs,
            wh_id_dest=wh_id_dest,
            location_id_dest=location_id_dest,
            now=now,
        )
        cursor.execute(
            """
            DELETE FROM OrdersPickingDetails
            WHERE OrderID = ?
            """,
            (order_picking_id,),
        )
        created = False
    else:
        seq_number = _next_int_value(cursor, "OrdersPicking", "SeqNumber")
        order_picking_id = _insert_order_picking_header(
            cursor=cursor,
            cache=cache,
            seq_number=seq_number,
            wave_id=wave_id,
            wave_obs=wave_obs,
            wh_id_dest=wh_id_dest,
            location_id_dest=location_id_dest,
            now=now,
        )
        created = True

    details_count = _insert_order_picking_details(
        cursor=cursor,
        cache=cache,
        order_picking_id=order_picking_id,
        enc_orders=enc_orders,
        now=now,
    )
    _complete_order_picking_resume(
        cursor=cursor,
        order_picking_id=order_picking_id,
    )

    return {
        "created": created,
        "order_picking_id": order_picking_id,
        "details_count": details_count,
    }


def _update_order_picking_header(
    cursor,
    cache: dict[str, dict[str, str]],
    order_picking_id: int,
    wave_id: str,
    wave_obs: str | None,
    wh_id_dest: Any,
    location_id_dest: Any,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "OrdersPicking", cache)
    values: dict[str, Any] = {
        "SeparationOrder": 1,
        "Date": now,
        "DueDate": now + timedelta(days=1),
        "Obs": wave_obs or "",
        "AssignedUser": "Ons3",
        "WhIDDest": wh_id_dest,
        "LocationIDDest": location_id_dest,
        "deleted": 0,
        "edited_by": None,
        "edited_date": now,
        "Shipped": 0,
        "Sync": 0,
        "StatusID": 0,
        "AllowPickMoreQty": 1,
        "TotalShipValue": 0,
        "PickingByCart": 0,
        "OrderPickingGroup": wave_id,
        "Required": 1,
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

    params.append(order_picking_id)
    cursor.execute(
        f"""
        UPDATE OrdersPicking
        SET {', '.join(set_parts)}
        WHERE ID = ?
        """,
        tuple(params),
    )
    if "shippingclosingtime" in columns and "created_date" in columns:
        cursor.execute(
            f"""
            UPDATE OrdersPicking
            SET {columns['shippingclosingtime']} = {columns['created_date']}
            WHERE ID = ?
            """,
            (order_picking_id,),
        )


def _insert_order_picking_header(
    cursor,
    cache: dict[str, dict[str, str]],
    seq_number: int,
    wave_id: str,
    wave_obs: str | None,
    wh_id_dest: Any,
    location_id_dest: Any,
    now: datetime,
) -> int:
    values: dict[str, Any] = {
        "SeparationOrder": 1,
        "SeqNumber": seq_number,
        "Date": now,
        "DueDate": now + timedelta(days=1),
        "Obs": wave_obs or "",
        "AssignedUser": "Ons3",
        "WhIDDest": wh_id_dest,
        "LocationIDDest": location_id_dest,
        "deleted": 0,
        "deleted_by": "",
        "deleted_date": None,
        "created_by": "Ons3",
        "created_date": now,
        "edited_by": None,
        "edited_date": now,
        "RouteID": "",
        "ShippingCompanyID": "",
        "ClosingTimeID": "",
        "ShippingClosingTime": now,
        "Shipped": 0,
        "ShippedDate": None,
        "ShippedBy": "",
        "Sync": 0,
        "PKLCreated": "",
        "WhIDOri": "",
        "StatusID": 0,
        "UrgencyStatusID": "",
        "PendingOrderPickingID": "",
        "AllowPickMoreQty": 1,
        "TotalShipValue": 0,
        "PickingByCart": 0,
        "PickingCartID": "",
        "OrderPickingGroup": wave_id,
        "Required": 1,
    }
    _fill_required_table_defaults(
        cursor=cursor,
        table_name="OrdersPicking",
        values=values,
        now=now,
    )
    return _insert_dynamic_output(
        cursor,
        "OrdersPicking",
        values,
        required_columns=set(),
        cache=cache,
        output_column="ID",
    )


def _insert_order_picking_details(
    cursor,
    cache: dict[str, dict[str, str]],
    order_picking_id: int,
    enc_orders: list[dict[str, Any]],
    now: datetime,
) -> int:
    row_number = 0
    for enc_order in enc_orders:
        enc_order_id = int(enc_order["order_id"])
        for line in enc_order["lines"]:
            row_number += 1
            qty = int(line["quantity"])
            order_row = _parse_order_row(str(line["line"]).strip())
            values: dict[str, Any] = {
                "OrderID": order_picking_id,
                "RowNumber": row_number,
                "PriorityExec": 0,
                "ItemID": str(line["item_id"]).strip(),
                "Qty": qty,
                "QtyToPick": qty,
                "QtyPicked": qty,
                "ReservedQty": 0,
                "VolTypeID": "",
                "QtyVols": 0,
                "QtyVolsPicked": 0,
                "QtyPVolume": 1,
                "UnitID": "UN",
                "Lot": "",
                "LocationIDOri": "2A0111",
                "WhIDOri": "2",
                "EquipIDOri": "MAN",
                "IsManualOri": 1,
                "LocationIDDest": "2A0111",
                "WhIDDest": "2",
                "EquipIDDest": 0,
                "IsManualDest": 0,
                "AssignedUser": "ONS3",
                "PickingStartDate": None,
                "PickingEndDate": None,
                "PickingCompleted": 0,
                "PickingCompletedDate": None,
                "DocTypeOri": "ENC",
                "OrderIDOri": enc_order_id,
                "OrderRowOri": order_row,
                "PartNumOri": 0,
                "deleted": 0,
            }
            _fill_required_table_defaults(
                cursor=cursor,
                table_name="OrdersPickingDetails",
                values=values,
                now=now,
            )
            _insert_dynamic(
                cursor,
                "OrdersPickingDetails",
                values,
                required_columns={"OrderID", "RowNumber", "ItemID"},
                cache=cache,
            )

    return row_number


def _complete_order_picking_resume(cursor, order_picking_id: int) -> None:
    cursor.execute(
        """
        UPDATE OrdersPickingResume
        SET CompletedRows = TotalRows,
            CompletedRowsGrouped = TotalRowsGrouped,
            PickingCompletedDate = GETDATE()
        WHERE ID = ?
        """,
        (order_picking_id,),
    )


def _get_ptl_destination(cursor, ptl: str) -> tuple[Any, Any]:
    cursor.execute(
        """
        SELECT WhidDest, LocationidDest
        FROM dbo.PTLDefinitions WITH (NOLOCK)
        WHERE PickToLightID = ?
        """,
        (ptl,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(
            f"PTL '{ptl}' does not have a destination configured in PTLDefinitions"
        )
    return row[0], row[1]


def _next_int_value(cursor, table_name: str, column_name: str) -> int:
    cursor.execute(f"SELECT ISNULL(MAX({column_name}), 0) + 1 FROM {table_name} WITH (UPDLOCK, HOLDLOCK)")
    return int(cursor.fetchone()[0])


def _insert_dynamic_output(
    cursor,
    table_name: str,
    values: dict[str, Any],
    required_columns: set[str],
    cache: dict[str, dict[str, str]],
    output_column: str,
) -> int:
    columns = _table_columns(cursor, table_name, cache)
    if not columns:
        raise ValueError(f"Table '{table_name}' does not exist or has no visible columns")

    selected_columns: list[str] = []
    params: list[Any] = []
    selected_normalized: set[str] = set()

    output_normalized = output_column.lower()
    if output_normalized not in columns:
        raise ValueError(f"Cannot insert into '{table_name}'. Missing output column: {output_column}")

    for key, value in values.items():
        normalized = key.lower()
        if normalized == output_normalized:
            continue
        if normalized not in columns:
            continue
        if normalized in selected_normalized:
            continue
        selected_columns.append(columns[normalized])
        params.append(value)
        selected_normalized.add(normalized)

    missing_required = [
        col for col in required_columns if col.lower() not in {c.lower() for c in selected_columns}
    ]
    if missing_required:
        raise ValueError(
            f"Cannot insert into '{table_name}'. Missing required columns in DB: "
            + ", ".join(sorted(missing_required))
        )

    placeholders = ", ".join("?" for _ in selected_columns)
    sql = (
        f"INSERT INTO {table_name} ({', '.join(selected_columns)}) "
        f"OUTPUT INSERTED.{columns[output_normalized]} "
        f"VALUES ({placeholders})"
    )
    cursor.execute(sql, tuple(params))
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Insert into '{table_name}' did not return {output_column}")
    return int(row[0])


def _update_enc_order_header(
    cursor,
    cache: dict[str, dict[str, str]],
    order_id: int,
    customer_id: str,
    order_obs: str,
    total_qty: int,
    wave_id: str,
    ptl: str,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "ClientOrders", cache)
    values = {
        "OrderDateTime": now,
        "ClientID": customer_id,
        "PartnerID": customer_id,
        "RequesterID": customer_id,
        "Obs": order_obs,
        "TotalQtyOrd": total_qty,
        "RouteID": ptl,
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

    params.append(order_id)
    cursor.execute(
        f"""
        UPDATE ClientOrders
        SET {', '.join(set_parts)}
        WHERE DocType = 'ENC'
          AND OrderID = ?
        """,
        tuple(params),
    )


def _insert_enc_order_header(
    cursor,
    cache: dict[str, dict[str, str]],
    order_id: int,
    customer_id: str,
    order_obs: str,
    total_qty: int,
    external_order_id: str,
    wave_id: str,
    ptl: str,
    now: datetime,
) -> None:
    values: dict[str, Any] = {
        "DocType": "ENC",
        "OrderID": order_id,
        "PartNum": 0,
        "CreateDateTime": now,
        "OrderDateTime": now,
        "ClientID": customer_id,
        "PartnerID": customer_id,
        "RequesterID": customer_id,
        "RouteID": ptl,
        "Status": 1,
        "PepStatus": 0,
        "ProductionStatus": "INICIAL",
        "OrderDatePrev": now,
        "Obs": order_obs,
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
        "IDIntegration": external_order_id,
        "RefCli": wave_id,
    }
    _insert_dynamic(
        cursor,
        "ClientOrders",
        values,
        required_columns={"DocType", "OrderID"},
        cache=cache,
    )


def _insert_enc_order_lines(
    cursor,
    cache: dict[str, dict[str, str]],
    order_id: int,
    lines: list[dict[str, Any]],
    now: datetime,
) -> None:
    for line in lines:
        qty = int(line["quantity"])
        original_price = Decimal(line.get("original_price") or 0)
        discount = Decimal(line.get("discount") or 0)
        supplied_final_price = line.get("final_price")
        final_price = (
            Decimal(supplied_final_price)
            if supplied_final_price is not None
            else original_price * (Decimal("1") - discount / Decimal("100"))
        )
        total_gross_price = original_price * qty
        total_net_price = final_price * qty
        total_discount_value = total_gross_price - total_net_price
        order_row = _parse_order_row(str(line["line"]).strip())
        values: dict[str, Any] = {
            "DocType": "ENC",
            "OrderID": order_id,
            "OrderRow": order_row,
            "PartNum": 0,
            "VolNum": 0,
            "ItemID": str(line["item_id"]).strip(),
            "QtyProd": qty,
            "QtyOrdered": qty,
            "QtyOrd": qty,
            "QtySatisf": 0,
            "QtyPicked": 0,
            "QtyVols": 0,
            "Unit": "UN",
            "UnitPrice": original_price,
            "ItemValue": final_price,
            "TotValue": total_net_price,
            "Descount": discount,
            "PercDescp": discount,
            "TotalGrossPrice": total_gross_price,
            "TotalDiscountValue": total_discount_value,
            "TotalNetPrice": total_net_price,
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
            "IDIntegration": str(line["line"]).strip(),
            "RefCli": str(line["line"]).strip(),
        }
        _insert_dynamic(
            cursor,
            "ClientOrderDetails",
            values,
            required_columns={"DocType", "OrderID", "OrderRow", "ItemID"},
            cache=cache,
        )


def _parse_order_row(order_row: str) -> int:
    try:
        return int(order_row)
    except ValueError as exc:
        raise ValueError(
            f"Line '{order_row}' must be numeric because it is stored in ClientOrderDetails.OrderRow"
        ) from exc


def _update_item_master(
    cursor,
    cache: dict[str, dict[str, str]],
    item_id: str,
    description: str,
    length: float,
    height: float,
    width: float,
    net_weight: float,
    barcode: str,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "ItemMaster", cache)
    values = {
        "ItemDesc": description,
        "Barcode": barcode,
        "ItemWeight": net_weight,
        "ItemHeight": height,
        "ItemWidth": width,
        "ItemLength": length,
        "PackWeight": net_weight,
        "PackHeight": height,
        "PackWidth": width,
        "PackLength": length,
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

    params.append(item_id)
    cursor.execute(
        f"""
        UPDATE ItemMaster
        SET {', '.join(set_parts)}
        WHERE ItemID = ?
        """,
        tuple(params),
    )


def _insert_item_master(
    cursor,
    cache: dict[str, dict[str, str]],
    item_id: str,
    description: str,
    length: float,
    height: float,
    width: float,
    net_weight: float,
    barcode: str,
    now: datetime,
) -> None:
    values: dict[str, Any] = {
        "ItemID": item_id,
        "ItemDesc": description,
        "BrandID": "BY",
        "CategoryID": "PTL",
        "StkUnit": "UN",
        "PackUnit": "UN",
        "SaleUnit": "UN",
        "PackToStkConv": 1,
        "QtyPVolume": 1,
        "Barcode": barcode,
        "InterStat": "",
        "Status": 1,
        "Blocked": 0,
        "Flag": 1,
        "WMSManaged": 1,
        "MovStock": 1,
        "ItemTpValue": 1,
        "ItemValue": 0,
        "stkMin": 0,
        "MinSaleQty": 0,
        "SaleMultiplierQty": 0,
        "Lots": 0,
        "SerialNum": 0,
        "ExpirationDate": 0,
        "LotDefaultStatus": 0,
        "IsComposed": 0,
        "CanBeComponent": 0,
        "IsNeeded": 0,
        "FragilityLevel": 0,
        "StorageWH": 0,
        "Dimensions": 0,
        "Versao": 0,
        "ItemWeight": net_weight,
        "ItemHeight": height,
        "ItemWidth": width,
        "ItemLength": length,
        "PackWeight": net_weight,
        "PackHeight": height,
        "PackWidth": width,
        "PackLength": length,
        "MinTemp": 0,
        "MaxTemp": 0,
        "VolNums": 1,
        "CreationUser": "BY-PTL",
        "CreationDateTime": now,
        "ModifDateTime": now,
    }
    _fill_required_item_master_defaults(
        cursor=cursor,
        values=values,
        item_id=item_id,
        description=description,
        barcode=barcode,
        now=now,
    )
    _insert_dynamic(
        cursor,
        "ItemMaster",
        values,
        required_columns={"ItemID", "ItemDesc"},
        cache=cache,
    )


def _fill_required_item_master_defaults(
    cursor,
    values: dict[str, Any],
    item_id: str,
    description: str,
    barcode: str,
    now: datetime,
) -> None:
    current_columns = {column.lower() for column in values}
    for column in _required_insert_columns(cursor, "ItemMaster"):
        normalized = column["name"].lower()
        if normalized in current_columns:
            continue

        values[column["name"]] = _standard_item_master_value(
            column=column,
            item_id=item_id,
            description=description,
            barcode=barcode,
            now=now,
        )
        current_columns.add(normalized)


def _required_insert_columns(cursor, table_name: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            c.name,
            t.name AS data_type,
            c.max_length,
            c.is_nullable,
            c.is_identity,
            c.is_computed,
            c.default_object_id
        FROM sys.columns c
        JOIN sys.types t
          ON c.user_type_id = t.user_type_id
        WHERE c.object_id = OBJECT_ID(?)
          AND c.is_nullable = 0
          AND c.is_identity = 0
          AND c.is_computed = 0
          AND c.default_object_id = 0
        """,
        (table_name,),
    )
    return [
        {
            "name": str(row[0]),
            "data_type": str(row[1]).lower(),
            "max_length": int(row[2] or 0),
            "is_nullable": bool(row[3]),
        }
        for row in cursor.fetchall()
    ]


def _fill_required_table_defaults(
    cursor,
    table_name: str,
    values: dict[str, Any],
    now: datetime,
) -> None:
    current_columns = {column.lower() for column in values}
    for column in _required_insert_columns(cursor, table_name):
        normalized = column["name"].lower()
        if normalized == "id":
            continue
        if normalized in current_columns:
            continue

        values[column["name"]] = _standard_table_value(column=column, now=now)
        current_columns.add(normalized)


def _standard_table_value(column: dict[str, Any], now: datetime) -> Any:
    normalized = str(column["name"]).lower()
    data_type = str(column["data_type"]).lower()

    if data_type in {"char", "nchar", "varchar", "nvarchar", "text", "ntext"}:
        if "user" in normalized or normalized.endswith("_by"):
            return _fit_text("Ons3", column)
        if "status" in normalized:
            return _fit_text("1", column)
        if "unit" in normalized:
            return _fit_text("UN", column)
        if "whid" in normalized:
            return _fit_text("2", column)
        if "location" in normalized:
            return _fit_text("2A0111", column)
        return _fit_text("", column)

    if data_type in {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"}:
        return now

    if data_type == "bit":
        return 1 if normalized in {"required", "allowpickmoreqty"} else 0

    if data_type in {
        "tinyint",
        "smallint",
        "int",
        "bigint",
        "decimal",
        "numeric",
        "money",
        "smallmoney",
        "float",
        "real",
    }:
        return 1 if normalized in {"required", "allowpickmoreqty", "separationorder", "statusid"} else 0

    if data_type == "uniqueidentifier":
        return "00000000-0000-0000-0000-000000000000"

    if data_type in {"binary", "varbinary", "image"}:
        return b""

    return ""


def _standard_item_master_value(
    column: dict[str, Any],
    item_id: str,
    description: str,
    barcode: str,
    now: datetime,
) -> Any:
    name = str(column["name"])
    normalized = name.lower()
    data_type = str(column["data_type"]).lower()

    if data_type in {"char", "nchar", "varchar", "nvarchar", "text", "ntext"}:
        if normalized == "itemid":
            return _fit_text(item_id, column)
        if normalized in {"itemdesc", "description", "descr"}:
            return _fit_text(description, column)
        if "barcode" in normalized or normalized in {"ean", "gtin"}:
            return _fit_text(barcode, column)
        if normalized.endswith("unit") or "unit" in normalized:
            return _fit_text("UN", column)
        if "user" in normalized:
            return _fit_text("BY-PTL", column)
        if "brand" in normalized:
            return _fit_text("BY", column)
        if "category" in normalized or "family" in normalized or "group" in normalized:
            return _fit_text("PTL", column)
        if "currency" in normalized:
            return _fit_text("EUR", column)
        if "status" in normalized:
            return _fit_text("INICIAL", column)
        return _fit_text("", column)

    if data_type in {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"}:
        return now

    if data_type == "bit":
        return 1 if normalized in {"active", "status", "wmsmanaged", "movstock", "flag"} else 0

    if data_type in {
        "tinyint",
        "smallint",
        "int",
        "bigint",
        "decimal",
        "numeric",
        "money",
        "smallmoney",
        "float",
        "real",
    }:
        return 1 if normalized in {"status", "active", "flag", "wmsmanaged", "movstock"} else 0

    if data_type == "uniqueidentifier":
        return "00000000-0000-0000-0000-000000000000"

    if data_type in {"binary", "varbinary", "image"}:
        return b""

    return ""


def _fit_text(value: str, column: dict[str, Any]) -> str:
    max_length = int(column.get("max_length") or 0)
    if max_length <= 0:
        return value

    if str(column.get("data_type", "")).lower() in {"nchar", "nvarchar", "ntext"}:
        max_length = max_length // 2

    return value[:max_length]


def _to_float(value: Decimal) -> float:
    return float(value)
