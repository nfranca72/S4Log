from __future__ import annotations

from datetime import date, datetime, timedelta
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
    from_location: str | None,
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
            from_location=from_location,
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
    from_location: str | None,
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
            from_location=from_location,
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
            from_location=from_location,
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
    from_location: str | None,
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
        "ShippedBy": from_location or "",
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
    from_location: str | None,
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
        "ShippedBy": from_location or "",
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


def fetch_separation_orders(
    from_date: str | None,
    to_date: str | None,
    only_open: bool,
    only_executed: bool,
    include_cancelled: bool,
) -> dict[str, Any]:
    if only_open and only_executed:
        raise ValueError("OnlyOpen and OnlyExecuted cannot both be true")

    from_dt = _parse_optional_date(from_date, "FromDate")
    to_dt = _parse_optional_date(to_date, "ToDate")
    if from_dt and to_dt and from_dt > to_dt:
        raise ValueError("FromDate cannot be greater than ToDate")

    wave_column = _client_orders_wave_column_name()
    params: list[Any] = []
    where_parts = ["ISNULL(op.SeparationOrder, 0) = 1"]
    if from_dt is not None:
        where_parts.append("CAST(op.Date AS date) >= ?")
        params.append(from_dt)
    if to_dt is not None:
        where_parts.append("CAST(op.Date AS date) <= ?")
        params.append(to_dt)

    query = f"""
        ;WITH DetailAgg AS (
            SELECT
                opd.OrderID,
                COUNT(*) AS TotalLines,
                SUM(ISNULL(opd.Qty, 0)) AS TotalQuantityToPick,
                SUM(ISNULL(opd.QtyPicked, 0)) AS TotalQuantityPicked
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        ResumeAgg AS (
            SELECT
                opr.ID AS OrderPickingID,
                ISNULL(opr.TotalRows, 0) AS TotalRows,
                ISNULL(opr.CompletedRows, 0) AS CompletedRows
            FROM OrdersPickingResume opr WITH (NOLOCK)
        ),
        ClientAgg AS (
            SELECT
                opd.OrderID,
                MAX(co.ClientID) AS CustomerID,
                MAX(bp.PartnerName) AS CustomerName
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN ClientOrders co WITH (NOLOCK)
              ON co.DocType = opd.DocTypeOri
             AND co.OrderID = opd.OrderIDOri
            LEFT JOIN BusinessPartners bp WITH (NOLOCK)
              ON bp.PartnerType = 'C'
             AND bp.PartnerID = co.ClientID
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        BoxAgg AS (
            SELECT
                opd.OrderID,
                COUNT(DISTINCT CONCAT(ISNULL(CONVERT(varchar(50), vm.VolDocCod), ''), '|', ISNULL(CONVERT(varchar(50), vm.VolNum), ''))) AS TotalBoxes
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN VolMaster vm WITH (NOLOCK)
              ON vm.ParentDocType = opd.DocTypeOri
             AND vm.ParentOrderID = opd.OrderIDOri
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        PklAgg AS (
            SELECT
                co.{wave_column} AS WaveID,
                MAX(co.OrderID) AS PKLOrderID
            FROM ClientOrders co WITH (NOLOCK)
            WHERE co.DocType = 'PKL'
            GROUP BY co.{wave_column}
        )
        SELECT
            op.ID AS OrderPickingID,
            op.OrderPickingGroup AS WaveID,
            op.Date AS CreationDate,
            op.DueDate AS RequestedExecutionDate,
            op.AssignedUser,
            op.UrgencyStatusID,
            ISNULL(op.ProductionStatus, '') AS ProductionStatus,
            ISNULL(op.deleted, 0) AS Deleted,
            ca.CustomerID,
            ca.CustomerName,
            ISNULL(da.TotalLines, 0) AS TotalLines,
            ISNULL(ba.TotalBoxes, 0) AS TotalBoxes,
            ISNULL(da.TotalQuantityToPick, 0) AS TotalQuantityToPick,
            ISNULL(da.TotalQuantityPicked, 0) AS TotalQuantityPicked,
            CASE WHEN ra.OrderPickingID IS NULL THEN 0 ELSE 1 END AS HasResume,
            ra.TotalRows,
            ra.CompletedRows,
            pa.PKLOrderID
        FROM OrdersPicking op WITH (NOLOCK)
        LEFT JOIN DetailAgg da
          ON da.OrderID = op.ID
        LEFT JOIN ResumeAgg ra
          ON ra.OrderPickingID = op.ID
        LEFT JOIN ClientAgg ca
          ON ca.OrderID = op.ID
        LEFT JOIN BoxAgg ba
          ON ba.OrderID = op.ID
        LEFT JOIN PklAgg pa
          ON pa.WaveID = op.OrderPickingGroup
        WHERE {' AND '.join(where_parts)}
        ORDER BY op.Date DESC, op.ID DESC
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    items: list[dict[str, Any]] = []
    for row in rows:
        summary = _build_separation_order_summary(row)
        summary.update(_fetch_separation_order_context(summary["OrderPickingID"]))
        if not include_cancelled and summary["StateCode"] == "cancelled":
            continue
        if only_open and summary["StateCode"] not in {"initial", "in_progress"}:
            continue
        if only_executed and summary["StateCode"] != "completed":
            continue
        items.append(summary)

    return {"Items": items, "Count": len(items)}


def fetch_separation_order_detail(order_picking_id: int) -> dict[str, Any] | None:
    summary_row = _fetch_separation_order_header_row(order_picking_id)
    if summary_row is None:
        return None

    header = _build_separation_order_summary(summary_row)
    header.update(_fetch_separation_order_context(order_picking_id))
    planned_boxes = _fetch_separation_order_boxes(order_picking_id, box_kind="planned")
    picked_boxes = _fetch_separation_order_boxes(order_picking_id, box_kind="picked")

    planned_by_row: dict[int, list[dict[str, Any]]] = {}
    for box in planned_boxes:
        planned_by_row.setdefault(int(box["SourceOrderRow"] or 0), []).append(box)

    picked_by_row: dict[int, list[dict[str, Any]]] = {}
    for box in picked_boxes:
        picked_by_row.setdefault(int(box["SourceOrderRow"] or 0), []).append(box)

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            SELECT
                opd.RowNumber,
                opd.ItemID,
                im.ItemDesc,
                ISNULL(opd.QtyToPick, opd.Qty) AS QuantityToPick,
                ISNULL(opd.QtyPicked, 0) AS QuantityPicked,
                opd.DocTypeOri AS OriginDocType,
                opd.OrderIDOri AS OriginOrderID,
                opd.OrderRowOri AS OriginOrderRow,
                opd.LocationIDOri AS LocationOrigin,
                opd.LocationIDDest AS LocationDest,
                opd.AssignedUser,
                ISNULL(opd.deleted, 0) AS Deleted,
                ISNULL(opd.PickingCompleted, 0) AS PickingCompleted
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            LEFT JOIN ItemMaster im WITH (NOLOCK)
              ON im.ItemID = opd.ItemID
            WHERE opd.OrderID = ?
            ORDER BY opd.RowNumber
            """,
            (order_picking_id,),
        )
        rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    lines: list[dict[str, Any]] = []
    for row in rows:
        quantity_to_pick = _to_float(row.get("QuantityToPick"))
        quantity_picked = _to_float(row.get("QuantityPicked"))
        line_state = _line_state(
            deleted=_to_int(row.get("Deleted")),
            picking_completed=_to_int(row.get("PickingCompleted")),
            quantity_to_pick=quantity_to_pick,
            quantity_picked=quantity_picked,
        )
        origin_row = _to_int(row.get("OriginOrderRow"))
        lines.append(
            {
                "RowNumber": _to_int(row.get("RowNumber")),
                "StateCode": line_state["code"],
                "StateSymbol": line_state["symbol"],
                "StateLabel": line_state["label"],
                "ItemID": row.get("ItemID") or "",
                "ItemDesc": row.get("ItemDesc"),
                "QuantityToPick": quantity_to_pick,
                "QuantityPicked": quantity_picked,
                "OriginDocType": row.get("OriginDocType"),
                "OriginOrderID": _nullable_int(row.get("OriginOrderID")),
                "OriginOrderRow": origin_row if origin_row > 0 else None,
                "LocationOrigin": row.get("LocationOrigin"),
                "LocationDest": row.get("LocationDest"),
                "AssignedUser": row.get("AssignedUser"),
                "PlannedBoxes": planned_by_row.get(origin_row, []),
                "PickedBoxes": picked_by_row.get(origin_row, []),
            }
        )

    return {"Header": header, "Lines": lines}


def update_separation_order_maintenance(
    order_picking_id: int,
    assigned_user: str | None,
    urgency_status_id: str | None,
) -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        cache: dict[str, dict[str, str]] = {}
        if not _order_picking_exists(cursor, order_picking_id):
            raise ValueError(f"OrdersPicking ID {order_picking_id} was not found")

        if assigned_user is not None:
            _validate_user_exists(cursor, assigned_user)
        if urgency_status_id is not None:
            _validate_urgency_status_exists(cursor, urgency_status_id)

        now = datetime.now()
        columns = _table_columns(cursor, "OrdersPicking", cache)
        set_parts: list[str] = []
        params: list[Any] = []

        if assigned_user is not None and "assigneduser" in columns:
            set_parts.append(f"{columns['assigneduser']} = ?")
            params.append(assigned_user)
        if urgency_status_id is not None and "urgencystatusid" in columns:
            set_parts.append(f"{columns['urgencystatusid']} = ?")
            params.append(urgency_status_id)
        if "edited_by" in columns:
            set_parts.append(f"{columns['edited_by']} = ?")
            params.append("Ons3")
        if "edited_date" in columns:
            set_parts.append(f"{columns['edited_date']} = ?")
            params.append(now)

        if not set_parts:
            raise ValueError("OrdersPicking does not expose editable maintenance columns")

        params.append(order_picking_id)
        cursor.execute(
            f"""
            UPDATE OrdersPicking
            SET {', '.join(set_parts)}
            WHERE ID = ?
            """,
            tuple(params),
        )

        if assigned_user is not None:
            detail_columns = _table_columns(cursor, "OrdersPickingDetails", cache)
            detail_set_parts: list[str] = []
            detail_params: list[Any] = []
            if "assigneduser" in detail_columns:
                detail_set_parts.append(f"{detail_columns['assigneduser']} = ?")
                detail_params.append(assigned_user)
            if "edited_by" in detail_columns:
                detail_set_parts.append(f"{detail_columns['edited_by']} = ?")
                detail_params.append("Ons3")
            if "edited_date" in detail_columns:
                detail_set_parts.append(f"{detail_columns['edited_date']} = ?")
                detail_params.append(now)
            if detail_set_parts:
                detail_params.append(order_picking_id)
                cursor.execute(
                    f"""
                    UPDATE OrdersPickingDetails
                    SET {', '.join(detail_set_parts)}
                    WHERE OrderID = ?
                      AND ISNULL(deleted, 0) = 0
                    """,
                    tuple(detail_params),
                )

    return {
        "OrderPickingID": order_picking_id,
        "AssignedUser": assigned_user,
        "UrgencyStatusID": urgency_status_id,
        "Message": "Separation order updated successfully",
    }


def cancel_separation_order(
    order_picking_id: int,
    cancelled_by: str | None,
    reason: str | None,
) -> dict[str, Any]:
    actor = cancelled_by or "Ons3"
    now = datetime.now()

    with db_cursor() as (cursor, _conn):
        cache: dict[str, dict[str, str]] = {}
        if not _order_picking_exists(cursor, order_picking_id):
            raise ValueError(f"OrdersPicking ID {order_picking_id} was not found")

        origin_rows = _fetch_origin_rows(cursor, order_picking_id)
        wave_id = _fetch_wave_id(cursor, order_picking_id)
        pkl_order_id = _fetch_pkl_order_id_by_wave(cursor, cache, wave_id) if wave_id else None
        related_documents = _fetch_related_target_documents(cursor, order_picking_id, include_pkl=True)
        source_context = _resolve_separation_order_context_from_docs(
            order_picking_id=order_picking_id,
            wave_id=wave_id,
            related_documents=related_documents,
        )

        released_boxes = _release_related_boxes(
            cursor=cursor,
            cache=cache,
            origin_rows=origin_rows,
            pkl_order_id=pkl_order_id,
            related_documents=related_documents,
        )
        released_origin_documents = _release_origin_documents(
            cursor=cursor,
            cache=cache,
            origin_rows=origin_rows,
        )
        cancelled_pkl_documents, cancelled_related_documents = _cancel_related_documents(
            cursor=cursor,
            cache=cache,
            related_documents=related_documents,
            actor=actor,
            now=now,
        )

        _mark_orders_picking_cancelled(
            cursor=cursor,
            cache=cache,
            order_picking_id=order_picking_id,
            actor=actor,
            reason=reason,
            now=now,
        )
        _mark_orders_picking_details_cancelled(
            cursor=cursor,
            cache=cache,
            order_picking_id=order_picking_id,
            now=now,
        )

    return {
        "OrderPickingID": order_picking_id,
        "Source": source_context["Source"],
        "StateCode": "cancelled",
        "ProductionStatus": "ANULADO",
        "Deleted": 1,
        "ReleasedOriginDocuments": released_origin_documents,
        "ReleasedBoxes": released_boxes,
        "CancelledPKLDocuments": cancelled_pkl_documents,
        "CancelledRelatedDocuments": cancelled_related_documents,
        "Message": "Separation order cancelled successfully",
    }


def fetch_separation_order_metadata() -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        users = _fetch_users_metadata(cursor)
        urgency_statuses = _fetch_urgency_status_metadata(cursor)
    return {"Users": users, "UrgencyStatuses": urgency_statuses}


def _fetch_separation_order_header_row(order_picking_id: int) -> dict[str, Any] | None:
    wave_column = _client_orders_wave_column_name()
    query = f"""
        ;WITH DetailAgg AS (
            SELECT
                opd.OrderID,
                COUNT(*) AS TotalLines,
                SUM(ISNULL(opd.Qty, 0)) AS TotalQuantityToPick,
                SUM(ISNULL(opd.QtyPicked, 0)) AS TotalQuantityPicked
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        ResumeAgg AS (
            SELECT
                opr.ID AS OrderPickingID,
                ISNULL(opr.TotalRows, 0) AS TotalRows,
                ISNULL(opr.CompletedRows, 0) AS CompletedRows
            FROM OrdersPickingResume opr WITH (NOLOCK)
        ),
        ClientAgg AS (
            SELECT
                opd.OrderID,
                MAX(co.ClientID) AS CustomerID,
                MAX(bp.PartnerName) AS CustomerName
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN ClientOrders co WITH (NOLOCK)
              ON co.DocType = opd.DocTypeOri
             AND co.OrderID = opd.OrderIDOri
            LEFT JOIN BusinessPartners bp WITH (NOLOCK)
              ON bp.PartnerType = 'C'
             AND bp.PartnerID = co.ClientID
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        BoxAgg AS (
            SELECT
                opd.OrderID,
                COUNT(DISTINCT CONCAT(ISNULL(CONVERT(varchar(50), vm.VolDocCod), ''), '|', ISNULL(CONVERT(varchar(50), vm.VolNum), ''))) AS TotalBoxes
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN VolMaster vm WITH (NOLOCK)
              ON vm.ParentDocType = opd.DocTypeOri
             AND vm.ParentOrderID = opd.OrderIDOri
            WHERE ISNULL(opd.deleted, 0) = 0
            GROUP BY opd.OrderID
        ),
        PklAgg AS (
            SELECT
                co.{wave_column} AS WaveID,
                MAX(co.OrderID) AS PKLOrderID
            FROM ClientOrders co WITH (NOLOCK)
            WHERE co.DocType = 'PKL'
            GROUP BY co.{wave_column}
        )
        SELECT
            op.ID AS OrderPickingID,
            op.OrderPickingGroup AS WaveID,
            op.Date AS CreationDate,
            op.DueDate AS RequestedExecutionDate,
            op.AssignedUser,
            op.UrgencyStatusID,
            ISNULL(op.ProductionStatus, '') AS ProductionStatus,
            ISNULL(op.deleted, 0) AS Deleted,
            ca.CustomerID,
            ca.CustomerName,
            ISNULL(da.TotalLines, 0) AS TotalLines,
            ISNULL(ba.TotalBoxes, 0) AS TotalBoxes,
            ISNULL(da.TotalQuantityToPick, 0) AS TotalQuantityToPick,
            ISNULL(da.TotalQuantityPicked, 0) AS TotalQuantityPicked,
            CASE WHEN ra.OrderPickingID IS NULL THEN 0 ELSE 1 END AS HasResume,
            ra.TotalRows,
            ra.CompletedRows,
            pa.PKLOrderID
        FROM OrdersPicking op WITH (NOLOCK)
        LEFT JOIN DetailAgg da
          ON da.OrderID = op.ID
        LEFT JOIN ResumeAgg ra
          ON ra.OrderPickingID = op.ID
        LEFT JOIN ClientAgg ca
          ON ca.OrderID = op.ID
        LEFT JOIN BoxAgg ba
          ON ba.OrderID = op.ID
        LEFT JOIN PklAgg pa
          ON pa.WaveID = op.OrderPickingGroup
        WHERE op.ID = ?
    """
    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (order_picking_id,))
        row = cursor.fetchone()
        return None if row is None else _row_to_dict(cursor, row)


def _build_separation_order_summary(row: dict[str, Any]) -> dict[str, Any]:
    deleted = _to_int(row.get("Deleted"))
    production_status = str(row.get("ProductionStatus") or "").strip()
    has_resume = _to_int(row.get("HasResume"))
    total_rows = _to_int(row.get("TotalRows") or row.get("TotalLines"))
    completed_rows = _to_int(row.get("CompletedRows"))
    total_qty = _to_float(row.get("TotalQuantityToPick"))
    picked_qty = _to_float(row.get("TotalQuantityPicked"))
    state = _separation_order_state(
        deleted=deleted,
        production_status=production_status,
        has_resume=has_resume,
        total_rows=total_rows,
        completed_rows=completed_rows,
    )
    progress_percentage = _progress_percentage(
        total_rows=total_rows,
        completed_rows=completed_rows,
        total_qty=total_qty,
        picked_qty=picked_qty,
        state_code=state["code"],
    )

    return {
        "OrderPickingID": _to_int(row.get("OrderPickingID")),
        "WaveID": row.get("WaveID"),
        "StateCode": state["code"],
        "StateSymbol": state["symbol"],
        "StateLabel": state["label"],
        "CreationDate": _iso_value(row.get("CreationDate")),
        "RequestedExecutionDate": _iso_value(row.get("RequestedExecutionDate")),
        "CustomerID": row.get("CustomerID"),
        "CustomerName": row.get("CustomerName"),
        "AssignedUser": row.get("AssignedUser"),
        "UrgencyStatusID": row.get("UrgencyStatusID"),
        "ProductionStatus": production_status or None,
        "TotalLines": _to_int(row.get("TotalLines")),
        "TotalBoxes": _to_int(row.get("TotalBoxes")),
        "TotalQuantityToPick": total_qty,
        "TotalQuantityPicked": picked_qty,
        "CompletedRows": completed_rows,
        "ProgressPercentage": progress_percentage,
    }


def _fetch_separation_order_boxes(order_picking_id: int, box_kind: str) -> list[dict[str, Any]]:
    if box_kind == "planned":
        query = """
            SELECT DISTINCT
                opd.DocTypeOri AS SourceDocType,
                opd.OrderIDOri AS SourceOrderID,
                opd.OrderRowOri AS SourceOrderRow,
                vm.VolDocCod,
                vm.VolNum,
                vm.VolTypeID,
                vm.CreationUser AS UserID,
                vi.ItemID,
                ISNULL(vi.ItemQtyIni, vi.ItemQty) AS Quantity
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN VolMaster vm WITH (NOLOCK)
              ON vm.ParentDocType = opd.DocTypeOri
             AND vm.ParentOrderID = opd.OrderIDOri
            LEFT JOIN VolItem vi WITH (NOLOCK)
              ON vi.VolDocCod = vm.VolDocCod
             AND vi.VolNum = vm.VolNum
             AND vi.ParentOrderRow = opd.OrderRowOri
             AND vi.ItemID = opd.ItemID
            WHERE opd.OrderID = ?
              AND ISNULL(opd.deleted, 0) = 0
            ORDER BY opd.OrderIDOri, opd.OrderRowOri, vm.VolNum
        """
        params = (order_picking_id,)
    else:
        query = """
            ;WITH TargetMap AS (
                SELECT DISTINCT
                    codo.DocTypeOri AS SourceDocType,
                    codo.OrderIDOri AS SourceOrderID,
                    codo.OrderRowOri AS SourceOrderRow,
                    cod.DocType AS TargetDocType,
                    cod.OrderID AS TargetOrderID,
                    cod.OrderRow AS TargetOrderRow
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                  ON codo.DocTypeOri = opd.DocTypeOri
                 AND codo.OrderIDOri = opd.OrderIDOri
                 AND codo.OrderRowOri = opd.OrderRowOri
                JOIN ClientOrderDetails cod WITH (NOLOCK)
                  ON cod.DocType = codo.DocType
                 AND cod.OrderID = codo.OrderID
                 AND cod.OrderRow = codo.OrderRow
                WHERE opd.OrderID = ?
                  AND ISNULL(opd.deleted, 0) = 0
                  AND cod.DocType <> opd.DocTypeOri
            )
            SELECT DISTINCT
                map.SourceDocType,
                map.SourceOrderID,
                map.SourceOrderRow,
                vm.VolDocCod,
                vm.VolNum,
                vm.VolTypeID,
                vm.CreationUser AS UserID,
                vi.ItemID,
                ISNULL(vi.ItemQtyIni, vi.ItemQty) AS Quantity
            FROM TargetMap map
            JOIN VolMaster vm WITH (NOLOCK)
              ON vm.ParentDocType = map.TargetDocType
             AND vm.ParentOrderID = map.TargetOrderID
            LEFT JOIN VolItem vi WITH (NOLOCK)
              ON vi.VolDocCod = vm.VolDocCod
             AND vi.VolNum = vm.VolNum
             AND vi.ParentOrderRow = map.TargetOrderRow
            ORDER BY map.SourceOrderID, map.SourceOrderRow, vm.VolNum
        """
        params = (order_picking_id,)

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, params)
        rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    return [
        {
            "BoxKind": box_kind,
            "SourceDocType": row.get("SourceDocType"),
            "SourceOrderID": _nullable_int(row.get("SourceOrderID")),
            "SourceOrderRow": _nullable_int(row.get("SourceOrderRow")),
            "VolDocCod": row.get("VolDocCod"),
            "VolNum": None if row.get("VolNum") is None else str(row.get("VolNum")),
            "VolTypeID": row.get("VolTypeID"),
            "UserID": row.get("UserID"),
            "ItemID": row.get("ItemID"),
            "Quantity": _to_float(row.get("Quantity")),
        }
        for row in rows
    ]


def _order_picking_exists(cursor, order_picking_id: int) -> bool:
    cursor.execute("SELECT 1 FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
    return cursor.fetchone() is not None


def _validate_user_exists(cursor, user_id: str) -> None:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'Users'
        """
    )
    columns = {str(row[0]).lower(): str(row[0]) for row in cursor.fetchall()}
    user_id_column = None
    for candidate in ("userid", "userid", "usrid", "user", "login", "code"):
        if candidate in columns:
            user_id_column = columns[candidate]
            break
    if not user_id_column:
        raise ValueError("Could not resolve the user id column in Users")

    cursor.execute(f"SELECT 1 FROM [Users] WITH (NOLOCK) WHERE [{user_id_column}] = ?", (user_id,))
    if cursor.fetchone() is None:
        raise ValueError(f"User '{user_id}' was not found in Users")


def _validate_urgency_status_exists(cursor, urgency_status_id: str) -> None:
    columns = _table_columns(cursor, "UrgencyStatus", {})
    if not columns:
        raise ValueError("UrgencyStatus table was not found")

    id_column = columns.get("urgencystatusid") or columns.get("id") or columns.get("code")
    if not id_column:
        raise ValueError("Could not resolve the UrgencyStatus identifier column")

    cursor.execute(
        f"SELECT 1 FROM UrgencyStatus WITH (NOLOCK) WHERE {id_column} = ?",
        (urgency_status_id,),
    )
    if cursor.fetchone() is None:
        raise ValueError(f"UrgencyStatus '{urgency_status_id}' was not found")


def _fetch_origin_rows(cursor, order_picking_id: int) -> list[tuple[str, int, int]]:
    cursor.execute(
        """
        SELECT DISTINCT
            opd.DocTypeOri,
            opd.OrderIDOri,
            opd.OrderRowOri
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        WHERE opd.OrderID = ?
          AND ISNULL(opd.deleted, 0) = 0
        """,
        (order_picking_id,),
    )
    return [
        (str(row[0]), int(row[1]), int(row[2]))
        for row in cursor.fetchall()
        if row[0] is not None and row[1] is not None and row[2] is not None
    ]


def _fetch_wave_id(cursor, order_picking_id: int) -> str | None:
    cursor.execute(
        "SELECT OrderPickingGroup FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?",
        (order_picking_id,),
    )
    row = cursor.fetchone()
    return None if row is None or row[0] is None else str(row[0]).strip()


def _fetch_wave_id_from_no_lock(order_picking_id: int) -> str:
    with db_cursor() as (cursor, _conn):
        wave_id = _fetch_wave_id(cursor, order_picking_id)
    if not wave_id:
        raise ValueError(f"OrdersPicking ID {order_picking_id} was not found")
    return wave_id


def _fetch_pkl_order_id_by_wave(cursor, cache: dict[str, dict[str, str]], wave_id: str) -> int | None:
    wave_column = _client_orders_wave_column(cursor, cache)
    cursor.execute(
        f"""
        SELECT TOP (1) OrderID
        FROM ClientOrders WITH (NOLOCK)
        WHERE DocType = 'PKL'
          AND {wave_column} = ?
        ORDER BY OrderID DESC
        """,
        (wave_id,),
    )
    row = cursor.fetchone()
    return None if row is None or row[0] is None else int(row[0])


def _fetch_separation_order_context(order_picking_id: int) -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        wave_id = _fetch_wave_id(cursor, order_picking_id)
        related_documents = _fetch_related_target_documents(cursor, order_picking_id, include_pkl=True)
    return _resolve_separation_order_context_from_docs(
        order_picking_id=order_picking_id,
        wave_id=wave_id,
        related_documents=related_documents,
    )


def _fetch_related_target_documents(
    cursor,
    order_picking_id: int,
    include_pkl: bool,
) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT DISTINCT
            cod.DocType AS TargetDocType,
            cod.OrderID AS TargetOrderID
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
          ON codo.DocTypeOri = opd.DocTypeOri
         AND codo.OrderIDOri = opd.OrderIDOri
         AND codo.OrderRowOri = opd.OrderRowOri
        JOIN ClientOrderDetails cod WITH (NOLOCK)
          ON cod.DocType = codo.DocType
         AND cod.OrderID = codo.OrderID
         AND cod.OrderRow = codo.OrderRow
        WHERE opd.OrderID = ?
          AND ISNULL(opd.deleted, 0) = 0
          AND cod.DocType <> opd.DocTypeOri
        ORDER BY cod.DocType, cod.OrderID
        """,
        (order_picking_id,),
    )
    documents = [
        {
            "doc_type": str(row[0] or "").strip(),
            "order_id": int(row[1] or 0),
        }
        for row in cursor.fetchall()
        if row[0] is not None and row[1] is not None
    ]
    if include_pkl:
        return documents
    return [document for document in documents if document["doc_type"].upper() != "PKL"]


def _resolve_separation_order_context_from_docs(
    order_picking_id: int,
    wave_id: str | None,
    related_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    non_pkl_docs = [doc for doc in related_documents if doc["doc_type"].upper() != "PKL"]
    if non_pkl_docs:
        primary_doc = non_pkl_docs[0]
        return {
            "Source": "MANUAL_SSCP",
            "SourceLabel": "Manual SEP/SSCP",
            "RelatedDocType": primary_doc["doc_type"],
            "RelatedOrderID": primary_doc["order_id"],
        }
    if wave_id:
        pkl_doc = next((doc for doc in related_documents if doc["doc_type"].upper() == "PKL"), None)
        return {
            "Source": "BY_PTL",
            "SourceLabel": "Integracao BY-PTL",
            "RelatedDocType": pkl_doc["doc_type"] if pkl_doc else None,
            "RelatedOrderID": pkl_doc["order_id"] if pkl_doc else None,
        }
    return {
        "Source": "UNKNOWN",
        "SourceLabel": "Origem desconhecida",
        "RelatedDocType": None,
        "RelatedOrderID": None,
    }


def _release_related_boxes(
    cursor,
    cache: dict[str, dict[str, str]],
    origin_rows: list[tuple[str, int, int]],
    pkl_order_id: int | None,
    related_documents: list[dict[str, Any]],
) -> int:
    vol_master_columns = _table_columns(cursor, "VolMaster", cache)
    if not vol_master_columns:
        return 0

    set_parts: list[str] = []
    params: list[Any] = []
    for candidate, value in (
        ("PendingOrderPickingID", ""),
        ("OrderPickingID", 0),
        ("ActivePickingID", 0),
        ("Blocked", 0),
        ("Reserved", 0),
    ):
        normalized = candidate.lower()
        if normalized in vol_master_columns:
            set_parts.append(f"{vol_master_columns[normalized]} = ?")
            params.append(value)

    if not set_parts:
        return 0

    released = 0
    for doc_type, order_id, _order_row in origin_rows:
        local_params = list(params)
        local_params.extend([doc_type, order_id])
        cursor.execute(
            f"""
            UPDATE VolMaster
            SET {', '.join(set_parts)}
            WHERE ParentDocType = ?
              AND ParentOrderID = ?
            """,
            tuple(local_params),
        )
        released += max(cursor.rowcount or 0, 0)

    has_related_pkl = any(document["doc_type"].upper() == "PKL" for document in related_documents)
    if pkl_order_id is not None and not has_related_pkl:
        local_params = list(params)
        local_params.extend(["PKL", pkl_order_id])
        cursor.execute(
            f"""
            UPDATE VolMaster
            SET {', '.join(set_parts)}
            WHERE ParentDocType = ?
              AND ParentOrderID = ?
            """,
            tuple(local_params),
        )
        released += max(cursor.rowcount or 0, 0)

    for document in related_documents:
        local_params = list(params)
        local_params.extend([document["doc_type"], document["order_id"]])
        cursor.execute(
            f"""
            UPDATE VolMaster
            SET {', '.join(set_parts)}
            WHERE ParentDocType = ?
              AND ParentOrderID = ?
            """,
            tuple(local_params),
        )
        released += max(cursor.rowcount or 0, 0)

    return released


def _release_origin_documents(
    cursor,
    cache: dict[str, dict[str, str]],
    origin_rows: list[tuple[str, int, int]],
) -> int:
    header_columns = _table_columns(cursor, "ClientOrders", cache)
    detail_columns = _table_columns(cursor, "ClientOrderDetails", cache)
    released: set[tuple[str, int]] = set()

    for doc_type, order_id, order_row in origin_rows:
        if detail_columns:
            detail_set_parts: list[str] = []
            detail_params: list[Any] = []
            for candidate, value in (
                ("ActivePickingID", 0),
                ("PendingOrderPickingID", 0),
                ("ProductionStatus", "INICIAL"),
            ):
                normalized = candidate.lower()
                if normalized in detail_columns:
                    detail_set_parts.append(f"{detail_columns[normalized]} = ?")
                    detail_params.append(value)
            if detail_set_parts:
                detail_params.extend([doc_type, order_id, order_row])
                cursor.execute(
                    f"""
                    UPDATE ClientOrderDetails
                    SET {', '.join(detail_set_parts)}
                    WHERE DocType = ?
                      AND OrderID = ?
                      AND OrderRow = ?
                    """,
                    tuple(detail_params),
                )

        if (doc_type, order_id) not in released and header_columns:
            header_set_parts: list[str] = []
            header_params: list[Any] = []
            for candidate, value in (
                ("PendingOrderPickingID", ""),
                ("ProductionStatus", "INICIAL"),
            ):
                normalized = candidate.lower()
                if normalized in header_columns:
                    header_set_parts.append(f"{header_columns[normalized]} = ?")
                    header_params.append(value)
            if header_set_parts:
                header_params.extend([doc_type, order_id])
                cursor.execute(
                    f"""
                    UPDATE ClientOrders
                    SET {', '.join(header_set_parts)}
                    WHERE DocType = ?
                      AND OrderID = ?
                    """,
                    tuple(header_params),
                )
            released.add((doc_type, order_id))

    return len(released)


def _cancel_related_documents(
    cursor,
    cache: dict[str, dict[str, str]],
    related_documents: list[dict[str, Any]],
    actor: str,
    now: datetime,
) -> tuple[int, int]:
    if not related_documents:
        return 0, 0

    header_columns = _table_columns(cursor, "ClientOrders", cache)
    detail_columns = _table_columns(cursor, "ClientOrderDetails", cache)
    cancelled_pkl_documents = 0
    cancelled_related_documents = 0

    for document in related_documents:
        doc_type = document["doc_type"]
        order_id = document["order_id"]

        header_set_parts: list[str] = []
        header_params: list[Any] = []
        for candidate, value in (
            ("ProductionStatus", "ANULADO"),
            ("ModifDateTime", now),
            ("ModifUser", actor),
        ):
            normalized = candidate.lower()
            if normalized in header_columns:
                header_set_parts.append(f"{header_columns[normalized]} = ?")
                header_params.append(value)
        if header_set_parts:
            header_params.extend([doc_type, order_id])
            cursor.execute(
                f"""
                UPDATE ClientOrders
                SET {', '.join(header_set_parts)}
                WHERE DocType = ?
                  AND OrderID = ?
                """,
                tuple(header_params),
            )

        detail_set_parts: list[str] = []
        detail_params: list[Any] = []
        if "productionstatus" in detail_columns:
            detail_set_parts.append(f"{detail_columns['productionstatus']} = ?")
            detail_params.append("ANULADO")
        if detail_set_parts:
            detail_params.extend([doc_type, order_id])
            cursor.execute(
                f"""
                UPDATE ClientOrderDetails
                SET {', '.join(detail_set_parts)}
                WHERE DocType = ?
                  AND OrderID = ?
                """,
                tuple(detail_params),
            )

        if doc_type.upper() == "PKL":
            cancelled_pkl_documents += 1
        else:
            cancelled_related_documents += 1

    return cancelled_pkl_documents, cancelled_related_documents


def _mark_orders_picking_cancelled(
    cursor,
    cache: dict[str, dict[str, str]],
    order_picking_id: int,
    actor: str,
    reason: str | None,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "OrdersPicking", cache)
    set_parts: list[str] = []
    params: list[Any] = []
    for candidate, value in (
        ("ProductionStatus", "ANULADO"),
        ("deleted", 1),
        ("deleted_by", actor),
        ("deleted_date", now),
        ("edited_by", actor),
        ("edited_date", now),
    ):
        normalized = candidate.lower()
        if normalized in columns:
            set_parts.append(f"{columns[normalized]} = ?")
            params.append(value)
    if reason and "obs" in columns:
        set_parts.append(f"{columns['obs']} = ?")
        params.append(reason)
    params.append(order_picking_id)
    cursor.execute(
        f"""
        UPDATE OrdersPicking
        SET {', '.join(set_parts)}
        WHERE ID = ?
        """,
        tuple(params),
    )


def _mark_orders_picking_details_cancelled(
    cursor,
    cache: dict[str, dict[str, str]],
    order_picking_id: int,
    now: datetime,
) -> None:
    columns = _table_columns(cursor, "OrdersPickingDetails", cache)
    set_parts: list[str] = []
    params: list[Any] = []
    for candidate, value in (
        ("deleted", 1),
        ("PickingCompleted", 0),
        ("PickingCompletedDate", None),
    ):
        normalized = candidate.lower()
        if normalized in columns:
            set_parts.append(f"{columns[normalized]} = ?")
            params.append(value)
    if "edited_date" in columns:
        set_parts.append(f"{columns['edited_date']} = ?")
        params.append(now)
    if set_parts:
        params.append(order_picking_id)
        cursor.execute(
            f"""
            UPDATE OrdersPickingDetails
            SET {', '.join(set_parts)}
            WHERE OrderID = ?
            """,
            tuple(params),
        )


def _fetch_users_metadata(cursor) -> list[dict[str, str]]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'Users'
        """
    )
    columns = {str(row[0]).lower(): str(row[0]) for row in cursor.fetchall()}
    if not columns:
        return []

    id_column = None
    for candidate in ("userid", "usrid", "user", "login", "code"):
        if candidate in columns:
            id_column = columns[candidate]
            break
    name_column = columns.get("username") or columns.get("name") or id_column
    active_column = columns.get("active")
    if not id_column or not name_column:
        return []

    where_clause = ""
    if active_column:
        where_clause = f"WHERE [{active_column}] = 1"
    cursor.execute(
        f"""
        SELECT [{id_column}] AS Value, [{name_column}] AS Label
        FROM [Users] WITH (NOLOCK)
        {where_clause}
        ORDER BY [{name_column}]
        """
    )
    return [
        {"Value": str(row[0]).strip(), "Label": str((row[1] or row[0])).strip()}
        for row in cursor.fetchall()
        if row[0] is not None
    ]


def _fetch_urgency_status_metadata(cursor) -> list[dict[str, str]]:
    columns = _table_columns(cursor, "UrgencyStatus", {})
    if not columns:
        return []

    id_column = columns.get("urgencystatusid") or columns.get("id") or columns.get("code")
    label_column = (
        columns.get("urgencystatusdesc")
        or columns.get("description")
        or columns.get("name")
        or id_column
    )
    if not id_column or not label_column:
        return []

    cursor.execute(
        f"""
        SELECT {id_column} AS Value, {label_column} AS Label
        FROM UrgencyStatus WITH (NOLOCK)
        ORDER BY {label_column}
        """
    )
    return [
        {"Value": str(row[0]).strip(), "Label": str((row[1] or row[0])).strip()}
        for row in cursor.fetchall()
        if row[0] is not None
    ]


def _client_orders_wave_column_name() -> str:
    with db_cursor() as (cursor, _conn):
        return _client_orders_wave_column(cursor, {})


def _separation_order_state(
    deleted: int,
    production_status: str,
    has_resume: int,
    total_rows: int,
    completed_rows: int,
) -> dict[str, str]:
    normalized_status = production_status.strip().upper()
    if deleted == 1 or normalized_status == "ANULADO":
        return {"code": "cancelled", "symbol": "x", "label": "Anulado"}
    if has_resume == 0:
        return {"code": "initial", "symbol": ".", "label": "Inicial"}
    if completed_rows < total_rows:
        return {"code": "in_progress", "symbol": "~", "label": "Em curso"}
    return {"code": "completed", "symbol": "+", "label": "Executado"}


def _line_state(
    deleted: int,
    picking_completed: int,
    quantity_to_pick: float,
    quantity_picked: float,
) -> dict[str, str]:
    if deleted == 1:
        return {"code": "cancelled", "symbol": "x", "label": "Anulado"}
    if picking_completed == 1 or quantity_to_pick <= 0 or quantity_picked >= quantity_to_pick:
        return {"code": "completed", "symbol": "+", "label": "Executado"}
    if quantity_picked > 0:
        return {"code": "in_progress", "symbol": "~", "label": "Em curso"}
    return {"code": "initial", "symbol": ".", "label": "Inicial"}


def _progress_percentage(
    total_rows: int,
    completed_rows: int,
    total_qty: float,
    picked_qty: float,
    state_code: str,
) -> float:
    if state_code == "cancelled":
        return 0.0
    if total_rows > 0:
        return round(min(max((completed_rows / total_rows) * 100, 0), 100), 2)
    if total_qty > 0:
        return round(min(max((picked_qty / total_qty) * 100, 0), 100), 2)
    if state_code == "completed":
        return 100.0
    return 0.0


def _row_to_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: _json_value(value) for name, value in zip(names, row)}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _parse_optional_date(value: str | None, field_name: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format") from exc


def _iso_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    return int(value)


def _nullable_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _fit_text(value: str, column: dict[str, Any]) -> str:
    max_length = int(column.get("max_length") or 0)
    if max_length <= 0:
        return value

    if str(column.get("data_type", "")).lower() in {"nchar", "nvarchar", "ntext"}:
        max_length = max_length // 2

    return value[:max_length]


def _to_float(value: Decimal) -> float:
    return float(value)
