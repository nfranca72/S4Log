from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

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
) -> dict[str, int]:
    customers_created = 0
    customers_updated = 0
    orders_created = 0
    orders_updated = 0
    lines_created = 0
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

    return {
        "customers_created": customers_created,
        "customers_updated": customers_updated,
        "orders_created": orders_created,
        "orders_updated": orders_updated,
        "lines_created": lines_created,
    }


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
    _insert_dynamic(
        cursor,
        "BusinessPartners",
        values,
        required_columns={"PartnerType", "PartnerID", "PartnerName"},
        cache=cache,
    )
    return "created"


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
    _insert_dynamic(
        cursor,
        "ItemMaster",
        values,
        required_columns={"ItemID", "ItemDesc"},
        cache=cache,
    )


def _to_float(value: Decimal) -> float:
    return float(value)
