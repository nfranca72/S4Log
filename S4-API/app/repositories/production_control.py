from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.db.connection import db_cursor


def fetch_coonsumption_for_itemmaster_and_bpartner(
    item_id: str,
    doc_type_area: str,
    bp_id: str,
) -> list[dict[str, object]]:
    query = """
        WITH Opss AS (
            SELECT DISTINCT
                cod.DocType,
                cod.OrderID,
                cod.OrderRow,
                cod.ItemID,
                imc.CharacteristicValue AS Project
            FROM ClientOrderDetails cod WITH (NOLOCK)
            JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
                ON imc.ItemID = cod.ItemID
               AND imc.Version = cod.Versao
               AND imc.CharacteristicID = 'PROJETO'
            JOIN ClientOrders co WITH (NOLOCK)
                ON co.DocType = cod.DocType
               AND co.OrderID = cod.OrderID
            JOIN DocumentConfig dc WITH (NOLOCK)
                ON dc.DocType = co.DocType
               AND dc.DocTypeArea = ?
            WHERE cod.ItemID = ?
              AND co.SubContratado = ?
        ),
        Abast AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'ABST'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        ),
        Ret AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'RABS'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        ),
        Cons AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'CONS'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        )
        SELECT
            abast.ItemID,
            abast.Project,
            isnull(abast.QtyTot, 0) AS QtyAbastecido,
            isnull(ret.QtyTot, 0) AS QtyRetorno,
            isnull(cons.QtyTot, 0) AS QtyConsumido
        FROM Abast abast
        LEFT JOIN Ret ret
            ON ret.ItemID = abast.ItemID
           AND ret.Project = abast.Project
        LEFT JOIN Cons cons
            ON cons.ItemID = abast.ItemID
           AND cons.Project = abast.Project
        ORDER BY abast.ItemID, abast.Project
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (doc_type_area, item_id, bp_id))
        rows = cursor.fetchall()

    return [
        {
            "ItemID": row[0],
            "Project": row[1],
            "QtyAbastecido": row[2],
            "QtyRetorno": row[3],
            "QtyConsumido": row[4],
        }
        for row in rows
    ]


def fetch_consumption_context(item_id: str, project: str, subcontract_id: str) -> dict[str, Any]:
    del project  # Kept in contract for future filtering parity with legacy code.

    normalized_subcontract_id = subcontract_id.strip()
    if not normalized_subcontract_id:
        raise ValueError("PartnerID is required to resolve subcontractor context")

    subcontract_resolve_query = """
        SELECT TOP 1 bp.PartnerID, bp.GLNCode
        FROM BusinessPartners bp WITH (NOLOCK)
        WHERE bp.PartnerType = 'S'
          AND (
              bp.PartnerID = ?
              OR bp.GLNCode = ?
          )
        ORDER BY CASE WHEN bp.PartnerID = ? THEN 0 ELSE 1 END, bp.PartnerID
    """

    origin_query = """
        SELECT TOP 1 cod.DocType, cod.OrderID, cod.OrderRow
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
           AND co.SubContratado = ?
        WHERE cod.ItemID = ?
        ORDER BY cod.OrderID DESC, cod.OrderRow DESC
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            subcontract_resolve_query,
            (normalized_subcontract_id, normalized_subcontract_id, normalized_subcontract_id),
        )
        subcontract_row = cursor.fetchone()
        if not subcontract_row:
            raise ValueError(
                "No subcontractor was found for the supplied PartnerID "
                "(expected BusinessPartners.PartnerID or BusinessPartners.GLNCode)"
            )

        resolved_subcontract_id = str(subcontract_row[0]).strip()
        resolved_gln_code = str(subcontract_row[1] or "").strip()

        cursor.execute(origin_query, (resolved_subcontract_id, item_id))
        origin_row = cursor.fetchone()

        if not origin_row:
            raise ValueError(
                "No origin OPS document was found for the supplied ItemId and PartnerID"
            )
    if not resolved_gln_code:
        raise ValueError("No consumption location (GLNCode) was found for the supplied PartnerID")

    return {
        "origin_doc_type": str(origin_row[0]),
        "origin_order_id": int(origin_row[1]),
        "origin_order_row": int(origin_row[2]),
        "subcontract_partner_id": resolved_subcontract_id,
        "local_consumo": f"200-{resolved_gln_code}",
    }


def fetch_component_metadata(component_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not component_ids:
        return {}

    placeholders = ",".join("?" for _ in component_ids)
    with db_cursor() as (cursor, _conn):
        try:
            cursor.execute(
                f"""
                SELECT ItemID, ISNULL(StkUnit, 'UN') AS StkUnit, ISNULL(ItemValue, 0) AS ItemValue
                FROM ItemMaster WITH (NOLOCK)
                WHERE ItemID IN ({placeholders})
                """,
                tuple(component_ids),
            )
            rows = cursor.fetchall()
        except Exception:
            cursor.execute(
                f"""
                SELECT ItemID, ISNULL(StkUnit, 'UN') AS StkUnit
                FROM ItemMaster WITH (NOLOCK)
                WHERE ItemID IN ({placeholders})
                """,
                tuple(component_ids),
            )
            rows = cursor.fetchall()
            return {
                str(row[0]).upper(): {"StkUnit": str(row[1]), "ItemValue": Decimal("0")}
                for row in rows
            }

    return {
        str(row[0]).upper(): {
            "StkUnit": str(row[1]) if row[1] else "UN",
            "ItemValue": _to_decimal(row[2]),
        }
        for row in rows
    }


def create_local_consumption_document(
    partner_id: str,
    movement_date: date,
    location_code: str,
    origin_doc_type: str,
    origin_order_id: int,
    origin_order_row: int,
    sap_doc_type: str,
    sap_doc_num: int | None,
    lines: list[dict[str, Any]],
    component_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not lines:
        raise ValueError("Cannot create local consumption document without lines")

    with db_cursor() as (cursor, _conn):
        cache: dict[str, dict[str, str]] = {}
        now = datetime.now()
        movement_dt = datetime.combine(movement_date, datetime.min.time())

        order_id = _next_doc_order_id(cursor, "CONS")
        sap_obs = f"{sap_doc_type}.{sap_doc_num}" if sap_doc_num is not None else sap_doc_type

        total_qty = sum(_to_decimal(line["qty_applied"]) for line in lines)
        total_value = Decimal("0")

        header_values = {
            "DocType": "CONS",
            "OrderID": order_id,
            "PartNum": 0,
            "CreateDateTime": now,
            "OrderDateTime": movement_dt,
            "PartnerID": partner_id,
            "ClientID": partner_id,
            "RequesterID": partner_id,
            "RouteID": "",
            "Status": 0,
            "PepStatus": 0,
            "ProductionStatus": "INICIAL",
            "OrderDatePrev": now,
            "Obs": sap_obs,
            "CreationUser": "OnS3",
            "CreationDateTime": now,
            "Currency": "EUR",
            "ExangeRate": 1,
            "ExchangeRate": 1,
            "TotalQtyOrd": float(total_qty),
            "TotalValue": 0,
            "TotalShipValue": 0,
            "Tipo": 0,
            "PercDsc2": 0,
            "CreditApproved": 0,
            "UrgencyStatusID": 0,
            "ConsignmentDoc": 0,
            "RecuseDoc": 0,
            "PartnerCategory": "S",
        }
        _insert_dynamic(
            cursor,
            "ClientOrders",
            header_values,
            required_columns={"DocType", "OrderID"},
            cache=cache,
        )

        cursor.execute(
            """
            SELECT ISNULL(MAX(OrderRow), 0)
            FROM ClientOrderDetails
            WHERE DocType = 'CONS' AND OrderID = ?
            """,
            (order_id,),
        )
        next_order_row = int(cursor.fetchone()[0]) + 1

        persisted_lines: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            order_row = next_order_row + index
            item_id = str(line["component_id"]).upper().strip()
            qty = _quantize_5(_to_decimal(line["qty_applied"]))

            metadata = component_metadata.get(item_id, {})
            stk_unit = str(metadata.get("StkUnit") or "UN")
            item_value = _to_decimal(metadata.get("ItemValue", 0))
            total_line_value = _quantize_5(item_value * qty)
            total_value += total_line_value

            detail_values = {
                "DocType": "CONS",
                "OrderID": order_id,
                "OrderRow": order_row,
                "PartNum": 0,
                "VolNum": 0,
                "ItemID": item_id,
                "QtyProd": float(qty),
                "QtyOrdered": float(qty),
                "QtyOrd": float(qty),
                "Unit": stk_unit,
                "UnitPrice": float(item_value),
                "ItemValue": float(item_value),
                "QtyPicked": 0,
                "QtyPVolume": 0,
                "Location": location_code,
                "Status": 0,
                "ActivePickingId": 0,
                "Descount": 0,
                "PercCstAdic": 0,
                "Currency": "EUR",
                "ExchangeRate": 1,
                "ExangeRate": 1,
                "ColorID": "UN",
                "GRidID": "UN",
                "GridID": "UN",
                "DocTypeOri": origin_doc_type,
                "OrderIdORi": origin_order_id,
                "OrderIDOri": origin_order_id,
                "OrderRowOri": origin_order_row,
                "PartNumOri": 0,
                "Version": 0,
                "Versao": 0,
                "Totvalue": float(total_line_value),
                "TotValue": float(total_line_value),
                "ProductionStatus": "INICIAL",
                "CreationUser": "OnS3",
                "CreationDateTime": now,
                "QtySatisf": 0,
                "QtyVols": 0,
                "IDIntegration": "",
                "RefCli": "",
            }
            _insert_dynamic(
                cursor,
                "ClientOrderDetails",
                detail_values,
                required_columns={"DocType", "OrderID", "OrderRow", "ItemID"},
                cache=cache,
            )

            ori_values = {
                "DocType": "CONS",
                "OrderID": order_id,
                "OrderRow": order_row,
                "PartNum": 0,
                "VolNum": 0,
                "DocTypeOri": origin_doc_type,
                "OrderIDOri": origin_order_id,
                "OrderRowOri": origin_order_row,
                "PartNumOri": 0,
                "VolNumOri": 0,
                "QtyOrd": 0,
                "QtyVols": 0,
                "QtyOrdDest": 0,
            }
            _insert_dynamic(
                cursor,
                "ClientOrderDetailsOri",
                ori_values,
                required_columns={"DocType", "OrderID", "OrderRow"},
                cache=cache,
            )

            mov_id = _insert_stock_movement(
                cursor=cursor,
                cache=cache,
                movement_dt=movement_dt,
                location_code=location_code,
                order_id=order_id,
                order_row=order_row,
                origin_doc_type=origin_doc_type,
                origin_order_id=origin_order_id,
                item_id=item_id,
                qty=qty,
                move_unit=stk_unit,
                unit_value=item_value,
            )

            apply_inventory_output(
                cursor=cursor,
                cache=cache,
                movement_dt=movement_dt,
                item_id=item_id,
                whid=200,
                location_id=location_code,
                qty=qty,
                mov_id=mov_id,
            )

            if mov_id is not None:
                _update_detail_movement_id(cursor, cache, mov_id, order_id, order_row)

            persisted_lines.append(
                {
                    "component_id": item_id,
                    "qty_applied": qty,
                    "order_row": order_row,
                    "mov_id": mov_id,
                }
            )

        if total_value > 0:
            client_orders_columns = _table_columns(cursor, "ClientOrders", cache)
            if "totalvalue" in client_orders_columns:
                cursor.execute(
                    f"""
                    UPDATE ClientOrders
                    SET {client_orders_columns['totalvalue']} = ?
                    WHERE DocType = 'CONS' AND OrderID = ?
                    """,
                    (float(_quantize_5(total_value)), order_id),
                )

    return {
        "doc_type": "CONS",
        "order_id": order_id,
        "lines": persisted_lines,
    }


def _next_doc_order_id(cursor, doc_type: str) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        """
        SELECT ISNULL(MAX(OrderID), ?)
        FROM ClientOrders
        WHERE OrderID >= ? AND DocType = ?
        """,
        (base, base, doc_type),
    )
    return int(cursor.fetchone()[0]) + 1


def _table_columns(
    cursor,
    table_name: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    if table_name in cache:
        return cache[table_name]

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        """,
        (table_name,),
    )
    rows = cursor.fetchall()
    columns = {str(row[0]).lower(): str(row[0]) for row in rows}
    cache[table_name] = columns
    return columns


def _insert_dynamic(
    cursor,
    table_name: str,
    values: dict[str, Any],
    required_columns: set[str],
    cache: dict[str, dict[str, str]],
) -> None:
    columns = _table_columns(cursor, table_name, cache)
    if not columns:
        raise ValueError(f"Table '{table_name}' does not exist or has no visible columns")

    selected_columns: list[str] = []
    params: list[Any] = []
    selected_normalized: set[str] = set()

    for key, value in values.items():
        normalized = key.lower()
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

    if not selected_columns:
        raise ValueError(f"No matching columns found to insert into '{table_name}'")

    placeholders = ", ".join("?" for _ in selected_columns)
    sql = f"INSERT INTO {table_name} ({', '.join(selected_columns)}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(params))


def _insert_stock_movement(
    cursor,
    cache: dict[str, dict[str, str]],
    movement_dt: datetime,
    location_code: str,
    order_id: int,
    order_row: int,
    origin_doc_type: str,
    origin_order_id: int,
    item_id: str,
    qty: Decimal,
    move_unit: str,
    unit_value: Decimal,
) -> int | None:
    columns = _table_columns(cursor, "StockMov", cache)
    if not columns:
        return None

    explicit_mov_id: int | None = None
    if "movid" in columns:
        cursor.execute("SELECT ISNULL(MAX(MovID), 0) + 1 FROM StockMov WITH (UPDLOCK, HOLDLOCK)")
        explicit_mov_id = int(cursor.fetchone()[0])

    values: dict[str, Any] = {
        "MovDateTime": movement_dt,
        "MoveDateTime": movement_dt,
        "ItemID": item_id,
        "MovType": "O",
        "MovDir": "O",
        "MoveDirection": "Output",
        "WHIDOrig": 200,
        "LocOrig": location_code,
        "LocationOrig": location_code,
        "WHIDDest": 0,
        "LocDest": "",
        "LocationDest": "",
        "Qty": float(qty),
        "Quantity": float(qty),
        "Unit": move_unit,
        "MoveUnit": move_unit,
        "MovUnit": move_unit,
        "DocTypeOrig": "CONS",
        "DocOrig": order_id,
        "DocRowOrig": order_row,
        "EquipmentID": 0,
        "UserID": "OnS3",
        "Obs": f"{origin_doc_type}.{origin_order_id}",
        "UnitValue": float(unit_value),
        "TotValue": float(_quantize_5(qty * unit_value)),
        "Lot": "",
        "SerialNum": "",
        "SerialNumber": "",
        "VolNum": 0,
    }
    if explicit_mov_id is not None:
        values["MovID"] = explicit_mov_id

    try:
        _insert_dynamic(cursor, "StockMov", values, required_columns={"ItemID"}, cache=cache)
    except Exception as exc:
        if explicit_mov_id is None or "identity" not in str(exc).lower():
            raise

        # Identity column scenario: retry without explicit MovID.
        values.pop("MovID", None)
        _insert_dynamic(cursor, "StockMov", values, required_columns={"ItemID"}, cache=cache)
        explicit_mov_id = None

    if "movid" not in columns:
        return None

    if explicit_mov_id is not None:
        return explicit_mov_id

    try:
        cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS BIGINT)")
        row = cursor.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        pass

    cursor.execute("SELECT ISNULL(MAX(MovID), 0) FROM StockMov WITH (NOLOCK)")
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _update_detail_movement_id(
    cursor,
    cache: dict[str, dict[str, str]],
    mov_id: int,
    order_id: int,
    order_row: int,
) -> None:
    columns = _table_columns(cursor, "ClientOrderDetails", cache)
    mov_col = columns.get("movid")
    if not mov_col:
        return

    cursor.execute(
        f"""
        UPDATE ClientOrderDetails
        SET {mov_col} = ?
        WHERE DocType = 'CONS' AND OrderID = ? AND OrderRow = ?
        """,
        (mov_id, order_id, order_row),
    )


def apply_inventory_output(
    cursor,
    cache: dict[str, dict[str, str]],
    movement_dt: datetime,
    item_id: str,
    whid: int,
    location_id: str,
    qty: Decimal,
    mov_id: int | None,
) -> None:
    inventory_columns = _table_columns(cursor, "Inventory", cache)
    qty_col = inventory_columns.get("qty")
    last_output_col = inventory_columns.get("lastoutput")
    if not qty_col:
        raise ValueError("Inventory table is missing required Qty column")
    if not last_output_col:
        raise ValueError("Inventory table is missing required LastOutput column")

    set_parts = [
        f"{qty_col} = {qty_col} - ?",
        f"{last_output_col} = ?",
    ]
    params: list[Any] = [float(_quantize_5(qty)), movement_dt]

    last_move_col = inventory_columns.get("lastmoveid")
    if last_move_col and mov_id is not None:
        set_parts.append(f"{last_move_col} = ?")
        params.append(mov_id)

    params.extend([item_id, whid, location_id])
    sql = f"""
        UPDATE Inventory
        SET {', '.join(set_parts)}
        WHERE ItemID = ?
          AND WHID = ?
          AND LocationID = ?
    """
    cursor.execute(sql, tuple(params))
    if cursor.rowcount == 0:
        raise ValueError(
            "No inventory row found for ItemID/WHID/LocationID to apply output "
            f"({item_id}, {whid}, {location_id})"
        )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _quantize_5(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
