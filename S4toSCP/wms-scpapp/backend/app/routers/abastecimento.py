from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.connection import db_cursor
from app.services.label_printing import get_document_print_configs

router = APIRouter(prefix="/abastecimento", tags=["Abastecimento"])

ACTIVE_STATUS_EXCLUSIONS = ("ANULADA", "CANCELADA", "FECHADA")


class SupplyRequirementsRequest(BaseModel):
    doc_type: str = Field(min_length=1)
    order_ids: list[int] = Field(default_factory=list)
    wh_id_orig: int


def _has_column(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ? AND COLUMN_NAME = ?
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _status_filters(cursor) -> tuple[str, str, tuple]:
    required = ["DocStatusID", "IsFinal", "IsAnulated"]
    if all(_has_column(cursor, "DocumentStatus", col) for col in required):
        block_column = "BlockDoc" if _has_column(cursor, "DocumentStatus", "BlockDoc") else None
        block_filter = f"AND ISNULL(ds.{block_column}, 0) = 0" if block_column else ""
        return (
            """
            LEFT JOIN DocumentStatus ds
              ON CAST(ds.DocStatusID AS varchar(50)) = CAST(co.Status AS varchar(50))
            """,
            f"""
              {block_filter}
              AND ISNULL(ds.IsFinal, 0) = 0
              AND ISNULL(ds.IsAnulated, 0) = 0
            """,
            (),
        )

    return (
        "",
        """
          AND UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)), ''))))
              NOT IN (?, ?, ?)
        """,
        ACTIVE_STATUS_EXCLUSIONS,
    )


def _load_group_metadata(cursor) -> tuple[str, str, str]:
    if _has_column(cursor, "ItemMaster", "ITEMGROUP"):
        join_sql = """
            LEFT JOIN GroupType gt
              ON CAST(gt.GroupTypeID AS varchar(50)) = CAST(im.ITEMGROUP AS varchar(50))
        """
        return (
            "ISNULL(CAST(im.ITEMGROUP AS varchar(50)), '')",
            "ISNULL(gt.GroupTypeDescr, ISNULL(CAST(im.ITEMGROUP AS varchar(50)), 'Sem grupo'))",
            join_sql,
        )

    if _has_column(cursor, "ItemMaster", "GroupType"):
        join_sql = """
            LEFT JOIN GroupType gt
              ON CAST(gt.GroupTypeID AS varchar(50)) = CAST(im.GroupType AS varchar(50))
        """
        return (
            "ISNULL(CAST(im.GroupType AS varchar(50)), '')",
            "ISNULL(gt.GroupTypeDescr, ISNULL(CAST(im.GroupType AS varchar(50)), 'Sem grupo'))",
            join_sql,
        )

    return ("''", "'Sem grupo'", "")


@router.get("/partners")
def list_partners(
    doc_type: str = Query(..., min_length=1),
    search: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT TOP 1 ISNULL(PartnerType, '')
            FROM DocumentConfig
            WHERE DocType = ?
            """,
            (doc_type,),
        )
        config_row = cursor.fetchone()
        if not config_row:
            raise HTTPException(status_code=404, detail="Tipo de documento nao encontrado em DocumentConfig")

        partner_type = _safe_text(config_row[0])
        if not partner_type:
            raise HTTPException(status_code=400, detail="PartnerType nao configurado em DocumentConfig para este documento")

        if search:
            term = f"%{search.strip()}%"
            cursor.execute(
                """
                SELECT TOP 50 PartnerID, PartnerName, PartnerType
                FROM BusinessPartners
                WHERE PartnerType = ?
                  AND (PartnerID LIKE ? OR PartnerName LIKE ?)
                ORDER BY PartnerName, PartnerID
                """,
                (partner_type, term, term),
            )
        else:
            cursor.execute(
                """
                SELECT TOP 100 PartnerID, PartnerName, PartnerType
                FROM BusinessPartners
                WHERE PartnerType = ?
                ORDER BY PartnerName, PartnerID
                """,
                (partner_type,),
            )
        rows = cursor.fetchall()

    return [
        {
            "partner_id": row[0],
            "partner_name": row[1] or "",
            "partner_type": row[2] or "",
        }
        for row in rows
    ]


@router.get("/warehouses")
def list_warehouses():
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT WHID, ISNULL(WHDesc, '')
            FROM Warehouses
            ORDER BY WHDesc, WHID
            """
        )
        rows = cursor.fetchall()

    return [{"wh_id": row[0], "wh_desc": row[1]} for row in rows]


@router.get("/warehouses/{wh_id}/locations")
def list_locations(wh_id: int):
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT LocationID, ISNULL(LocationDesc, LocationID)
            FROM Locations
            WHERE WHID = ?
            ORDER BY LocationID
            """,
            (wh_id,),
        )
        rows = cursor.fetchall()

    return [{"location_id": row[0], "location_desc": row[1]} for row in rows]


@router.get("/document-types")
def list_document_types():
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT
                DocType,
                ISNULL(Title, DocType) AS Title,
                ISNULL(DocDesc, '') AS DocDesc
            FROM DocumentConfig
            WHERE UPPER(ISNULL(DocTypeArea, '')) = 'PLANING'
              AND ISNULL(Active, 1) = 1
            ORDER BY Title, DocType
            """
        )
        rows = cursor.fetchall()

    return [
        {
            "doc_type": row[0],
            "title": row[1] or row[0],
            "doc_desc": row[2] or "",
        }
        for row in rows
    ]


@router.get("/documents")
def list_documents(
    doc_type: str = Query(..., min_length=1),
    partner_id: str = Query(default=""),
    search: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        term = f"%{search.strip()}%"
        partner_filter = "AND co.SubContratado = ?" if partner_id else ""
        search_filter = """
            AND (
                ? = '%%'
                OR CAST(co.OrderID AS varchar(50)) LIKE ?
                OR ISNULL(cod.ItemID, '') LIKE ?
                OR ISNULL(bp.PartnerName, '') LIKE ?
                OR ISNULL(co.SubContratado, '') LIKE ?
                OR ISNULL(co.ClientID, '') LIKE ?
                OR ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) LIKE ?
            )
        """

        if all(_has_column(cursor, "ClientOrders", col) for col in ("ProductionStatus", "SubContratado")):
            sql = f"""
                SELECT
                    co.OrderID,
                    co.DocType,
                    ISNULL(co.SubContratado, '') AS PartnerID,
                    ISNULL(bp.PartnerName, '') AS PartnerName,
                    co.OrderDateTime,
                    co.OrderDatePrev,
                    ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) AS Obs,
                    COUNT(cod.OrderRow) AS TotalLines,
                    MAX(cod.ItemID) AS ItemID
                FROM ClientOrders co
                JOIN DocumentStatus ds WITH (NOLOCK)
                  ON ds.DocStatusID = co.ProductionStatus
                 AND ds.DocType = co.DocType
                JOIN ClientOrderDetails cod WITH (NOLOCK)
                  ON cod.DocType = co.DocType
                 AND cod.OrderID = co.OrderID
                LEFT JOIN BusinessPartners bp
                  ON bp.PartnerID = co.SubContratado
                 AND bp.PartnerType = ds.DocType
                WHERE co.DocType = ?
                  {partner_filter}
                  AND ISNULL(ds.IsFinal, 0) = 0
                  AND ISNULL(ds.BlockDoc, 0) = 0
                  AND ISNULL(ds.IsAnulated, 0) = 0
                  {search_filter}
                GROUP BY
                    co.OrderID,
                    co.DocType,
                    co.SubContratado,
                    bp.PartnerName,
                    co.OrderDateTime,
                    co.OrderDatePrev,
                    co.ObsInternal,
                    co.Obs
                ORDER BY co.OrderID DESC
            """
        else:
            status_join_sql, status_sql, status_params = _status_filters(cursor)
            sql = f"""
                SELECT
                    co.OrderID,
                    co.DocType,
                    co.ClientID,
                    ISNULL(bp.PartnerName, '') AS PartnerName,
                    co.OrderDateTime,
                    co.OrderDatePrev,
                    ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) AS Obs,
                    COUNT(cod.OrderRow) AS TotalLines,
                    MAX(cod.ItemID) AS ItemID
                FROM ClientOrders co
                JOIN ClientOrderDetails cod
                  ON cod.DocType = co.DocType
                 AND cod.OrderID = co.OrderID
                LEFT JOIN BusinessPartners bp
                  ON bp.PartnerID = co.ClientID
                {status_join_sql}
                WHERE co.DocType = ?
                  {"AND co.ClientID = ?" if partner_id else ""}
                  {search_filter}
                  {status_sql}
                GROUP BY
                    co.OrderID,
                    co.DocType,
                    co.ClientID,
                    bp.PartnerName,
                    co.OrderDateTime,
                    co.OrderDatePrev,
                    co.ObsInternal,
                    co.Obs
                ORDER BY co.OrderID DESC
            """
            partner_filter = ""

        params: list[object] = [doc_type]
        if partner_id:
            params.append(partner_id)
        params.extend([term, term, term, term, term, term, term])
        if 'status_params' in locals():
            params.extend(status_params)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

    return [
        {
            "order_id": row[0],
            "doc_type": row[1],
            "partner_id": row[2] or "",
            "partner_name": row[3] or "",
            "order_date": str(row[4])[:10] if row[4] else None,
            "due_date": str(row[5])[:10] if row[5] else None,
            "obs": row[6] or "",
            "total_lines": int(row[7] or 0),
            "item_id": row[8] or "",
        }
        for row in rows
    ]


@router.post("/requirements")
def load_requirements(req: SupplyRequirementsRequest):
    if not req.order_ids:
        raise HTTPException(status_code=400, detail="Seleciona pelo menos uma ordem de fabrico")

    with db_cursor() as (cursor, _):
        placeholders = ",".join("?" for _ in req.order_ids)
        group_code_expr, group_desc_expr, group_join_sql = _load_group_metadata(cursor)

        cursor.execute(
            f"""
            SELECT
                co.OrderID,
                co.DocType,
                co.ClientID,
                ISNULL(bp.PartnerName, '') AS PartnerName
            FROM ClientOrders co
            LEFT JOIN BusinessPartners bp
              ON bp.PartnerID = co.ClientID
            WHERE co.DocType = ? AND co.OrderID IN ({placeholders})
            ORDER BY co.OrderID
            """,
            [req.doc_type, *req.order_ids],
        )
        order_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT
                coc.OrderID,
                coc.ComponentID,
                ISNULL(im.ItemDesc, coc.ComponentID) AS ItemDesc,
                {group_code_expr} AS GroupCode,
                {group_desc_expr} AS GroupDesc,
                SUM(ISNULL(coc.QtyComp, 0)) AS QtyNeeded,
                SUM(ISNULL(coc.QtySatisf, 0)) AS QtySatisfied
            FROM ClientOrderComp coc
            LEFT JOIN ItemMaster im
              ON im.ItemID = coc.ComponentID
            {group_join_sql}
            WHERE coc.DocType = ?
              AND coc.OrderID IN ({placeholders})
            GROUP BY
                coc.OrderID,
                coc.ComponentID,
                im.ItemDesc,
                {group_code_expr},
                {group_desc_expr}
            ORDER BY {group_desc_expr}, coc.ComponentID, coc.OrderID
            """,
            [req.doc_type, *req.order_ids],
        )
        component_rows = cursor.fetchall()

        item_ids = sorted({_safe_text(row[1]) for row in component_rows if _safe_text(row[1])})
        stock_by_item: dict[str, float] = {}
        if item_ids:
            item_placeholders = ",".join("?" for _ in item_ids)
            cursor.execute(
                f"""
                SELECT ItemID, SUM(ISNULL(Qty, 0)) AS QtyStock
                FROM Inventory
                WHERE WHID = ?
                  AND Qty > 0
                  AND ItemID IN ({item_placeholders})
                GROUP BY ItemID
                """,
                [req.wh_id_orig, *item_ids],
            )
            stock_by_item = {
                _safe_text(row[0]): float(row[1] or 0)
                for row in cursor.fetchall()
            }

        supplied_by_item: dict[str, float] = defaultdict(float)
        if (
            item_ids
            and _has_column(cursor, "StockMov", "ItemID")
            and _has_column(cursor, "StockMov", "Qty")
            and _has_column(cursor, "StockMov", "WarehouseID")
            and _has_column(cursor, "StockMov", "U_SEI_DOCONS3S")
        ):
            refs = [f"{req.doc_type};{order_id}" for order_id in req.order_ids]
            ref_placeholders = ",".join("?" for _ in refs)
            item_placeholders = ",".join("?" for _ in item_ids)
            cursor.execute(
                f"""
                SELECT ItemID, SUM(ABS(ISNULL(Qty, 0))) AS QtySupplied
                FROM StockMov
                WHERE WarehouseID = ?
                  AND Qty < 0
                  AND U_SEI_DOCONS3S IN ({ref_placeholders})
                  AND ItemID IN ({item_placeholders})
                GROUP BY ItemID
                """,
                [req.wh_id_orig, *refs, *item_ids],
            )
            supplied_by_item = defaultdict(
                float,
                {
                    _safe_text(row[0]): float(row[1] or 0)
                    for row in cursor.fetchall()
                },
            )

    orders = [
        {
            "order_id": int(row[0]),
            "doc_type": _safe_text(row[1]),
            "partner_id": _safe_text(row[2]),
            "partner_name": _safe_text(row[3]),
        }
        for row in order_rows
    ]

    grouped: dict[tuple[str, str, str], dict] = {}
    for row in component_rows:
        order_id = int(row[0] or 0)
        item_id = _safe_text(row[1])
        item_desc = _safe_text(row[2])
        group_code = _safe_text(row[3])
        group_desc = _safe_text(row[4]) or "Sem grupo"
        qty_needed = float(row[5] or 0)
        qty_satisfied = float(row[6] or 0)
        qty_open = max(0.0, qty_needed - qty_satisfied)
        if not item_id or qty_open <= 0:
            continue

        key = (group_code, group_desc, item_id)
        current = grouped.get(key)
        if current is None:
            stock = float(stock_by_item.get(item_id, 0.0))
            qty_supplied = float(supplied_by_item.get(item_id, 0.0))
            current = {
                "group_code": group_code,
                "group_desc": group_desc,
                "item_id": item_id,
                "item_desc": item_desc,
                "qty_needed": 0.0,
                "qty_satisfied": 0.0,
                "qty_open": 0.0,
                "qty_stock": stock,
                "qty_supplied": qty_supplied,
                "qty_missing": 0.0,
                "qty_to_ship_max": 0.0,
                "orders": [],
            }
            grouped[key] = current

        current["qty_needed"] += qty_needed
        current["qty_satisfied"] += qty_satisfied
        current["qty_open"] += qty_open
        current["orders"].append(order_id)

    lines = []
    for key in sorted(grouped.keys(), key=lambda value: (value[1], value[2])):
        current = grouped[key]
        current["orders"] = sorted(set(current["orders"]))
        current["qty_missing"] = max(0.0, current["qty_open"] - current["qty_supplied"])
        current["qty_to_ship_max"] = min(current["qty_missing"], current["qty_stock"])
        lines.append(current)

    groups_map: dict[str, dict] = {}
    for line in lines:
        group_key = line["group_code"] or line["group_desc"]
        existing = groups_map.get(group_key)
        if existing is None:
            existing = {
                "group_code": line["group_code"],
                "group_desc": line["group_desc"],
                "qty_needed": 0.0,
                "qty_missing": 0.0,
                "qty_stock": 0.0,
                "qty_to_ship_max": 0.0,
                "lines": [],
            }
            groups_map[group_key] = existing

        existing["qty_needed"] += line["qty_needed"]
        existing["qty_missing"] += line["qty_missing"]
        existing["qty_stock"] += line["qty_stock"]
        existing["qty_to_ship_max"] += line["qty_to_ship_max"]
        existing["lines"].append(line)

    groups = sorted(groups_map.values(), key=lambda row: row["group_desc"])

    return {
        "orders": orders,
        "groups": groups,
        "summary": {
            "orders_count": len(orders),
            "items_count": len(lines),
            "qty_needed": sum(line["qty_needed"] for line in lines),
            "qty_missing": sum(line["qty_missing"] for line in lines),
            "qty_to_ship_max": sum(line["qty_to_ship_max"] for line in lines),
        },
    }


@router.get("/volume-print-configs")
def volume_print_configs(doc_type: str = Query(default="CX")):
    configs = get_document_print_configs("VOLUMES", doc_type)
    return [
        {
            "description": _safe_text(config.get("DocPrintDescr") or config.get("DocPrintFile")),
            "file_name": _safe_text(config.get("DocPrintFile")),
            "printer_name": _safe_text(config.get("PrinterName")),
            "direct_print": bool(config.get("DirectPrint")),
        }
        for config in configs
        if _safe_text(config.get("DocPrintFile"))
    ]
