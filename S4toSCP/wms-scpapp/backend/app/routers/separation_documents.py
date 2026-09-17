from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.connection import db_cursor
from app.settings import settings

router = APIRouter(prefix="/separation-documents", tags=["Documentos de Separacao"])

ACTIVE_STATUS_EXCLUSIONS = ("ANULADA", "CANCELADA", "FECHADA")


class SeparationLineAllocation(BaseModel):
    vol_num: str
    barcode: str = ""
    location_id: str = ""
    qty: float = Field(gt=0)


class SeparationCreateLine(BaseModel):
    origin_doc_type: str
    origin_order_id: int
    origin_order_row: int
    origin_part_num: int = 0
    origin_color_id: str = ""
    origin_grid_id: str = ""
    origin_size_id: str = ""
    origin_size_order_num: int = 0
    item_id: str
    substitute_item_id: str = ""
    qty_requested: float = 0
    qty_done: float = 0
    qty_pending: float = 0
    qty_to_separate: float = Field(gt=0)
    allow_without_boxes: bool = False
    allocations: list[SeparationLineAllocation] = Field(default_factory=list)
    # Armazem de origem desta linha. Opcional para compatibilidade - quando omitido,
    # usa-se SeparationCreateRequest.wh_id_orig (caso de um unico armazem selecionado).
    # Quando linhas diferentes trazem armazens diferentes, o /create divide o pedido
    # em varias ordens de separacao (uma por armazem), interligadas por OrderPickingGroup.
    wh_id_orig: int | None = None


class SeparationCreateRequest(BaseModel):
    wh_id_orig: int | None = None
    origin_doc_type: str = Field(min_length=1)
    partner_id: str = Field(min_length=1)
    execution_date: str = Field(min_length=1)
    obs: str = ""
    lines: list[SeparationCreateLine] = Field(default_factory=list)


def _safe_text(value: object) -> str:
    return str(value or "").strip()


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


def _status_filters(cursor) -> tuple[str, tuple]:
    if all(_has_column(cursor, "DocumentStatus", col) for col in ("DocStatusID", "IsInicial", "IsAnulated", "IsFinal")):
        return (
            """
            JOIN DocumentStatus ds
              ON ds.DocType = co.DocType
             AND CAST(ds.DocStatusID AS varchar(50)) = CAST(co.ProductionStatus AS varchar(50))
            WHERE ds.IsInicial = 1
              AND ds.IsAnulated = 0
              AND ds.IsFinal = 0
            """,
            (),
        )

    return (
        """
        WHERE UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)), '')))) NOT IN (?, ?, ?)
        """,
        ACTIVE_STATUS_EXCLUSIONS,
    )


def _pending_qty_expr(cursor, alias: str = "cod") -> tuple[str, str]:
    qty_done_expr = f"ISNULL({alias}.QtyProd, ISNULL({alias}.QtySatisf, 0))"
    if _has_column(cursor, "ClientOrderDetails", "QtyPend"):
        return qty_done_expr, f"ISNULL({alias}.QtyPend, CASE WHEN ISNULL({alias}.QtyOrd, 0) - {qty_done_expr} > 0 THEN ISNULL({alias}.QtyOrd, 0) - {qty_done_expr} ELSE 0 END)"
    return qty_done_expr, f"CASE WHEN ISNULL({alias}.QtyOrd, 0) - {qty_done_expr} > 0 THEN ISNULL({alias}.QtyOrd, 0) - {qty_done_expr} ELSE 0 END"


def _wh_filter(column_expr: str, wh_ids: list[int] | None) -> tuple[str, list[object]]:
    """SQL condition + params filtering `column_expr` to a set of warehouses. An empty/None
    list means no filter (all warehouses) - keeps the previous single-warehouse-or-global
    behaviour when only one (or zero) warehouse is selected."""
    clean = sorted({int(w) for w in (wh_ids or []) if w is not None})
    if not clean:
        return "1=1", []
    placeholders = ",".join("?" for _ in clean)
    return f"{column_expr} IN ({placeholders})", clean


def _reserved_qty_expr(alias: str = "reserved") -> str:
    return f"ISNULL({alias}.QtyReserved, 0)"


def _reserved_qty_join(target_doc_type: str, source_alias: str = "cod", reserved_alias: str = "reserved") -> str:
    safe_doc_type = str(target_doc_type or "").replace("'", "''")
    return f"""
        LEFT JOIN (
            SELECT
                codo.DocTypeOri,
                codo.OrderIDOri,
                codo.OrderRowOri,
                SUM(ISNULL(codo.QtyOrdDest, ISNULL(codo.QtyOrd, 0))) AS QtyReserved
            FROM ClientOrderDetailsOri codo WITH (NOLOCK)
            JOIN ClientOrders co_res WITH (NOLOCK)
              ON co_res.DocType = codo.DocType
             AND co_res.OrderID = codo.OrderID
            WHERE codo.DocType = '{safe_doc_type}'
              AND ISNULL(co_res.ProductionStatus, '') <> 'ANULADO'
            GROUP BY codo.DocTypeOri, codo.OrderIDOri, codo.OrderRowOri
        ) {reserved_alias}
          ON {reserved_alias}.DocTypeOri = {source_alias}.DocType
         AND {reserved_alias}.OrderIDOri = {source_alias}.OrderID
         AND {reserved_alias}.OrderRowOri = {source_alias}.OrderRow
    """


def _next_order_id(cursor, doc_type: str) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        "SELECT ISNULL(MAX(OrderID), ?) FROM ClientOrders WHERE OrderID >= ? AND DocType = ?",
        (base, base, doc_type),
    )
    last = cursor.fetchone()[0]
    return int(last or base) + 1


def _load_item_metadata(cursor, item_ids: list[str]) -> dict[str, dict[str, object]]:
    if not item_ids:
        return {}

    placeholders = ",".join("?" for _ in item_ids)
    cursor.execute(
        f"""
        SELECT
            ItemID,
            ISNULL(StkUnit, 'UN') AS StkUnit,
            ISNULL(Dimensions, 0) AS Dimensions
        FROM ItemMaster
        WHERE ItemID IN ({placeholders})
        """,
        tuple(item_ids),
    )
    return {
        str(row[0] or "").strip(): {
            "unit": str(row[1] or "UN").strip() or "UN",
            "has_dimensions": bool(row[2]),
        }
        for row in cursor.fetchall()
    }


def _effective_size_id(item_meta: dict[str, object] | None, size_id: str) -> str:
    if not item_meta or not bool(item_meta.get("has_dimensions")):
        return ""
    return _safe_text(size_id)


def _load_order_versions(cursor, order_keys: list[tuple[str, int]]) -> dict[tuple[str, int], int]:
    if not order_keys:
        return {}

    clauses = []
    params: list[object] = []
    for doc_type, order_id in order_keys:
        clauses.append("(DocType = ? AND OrderID = ?)")
        params.extend([doc_type, order_id])

    version_expr = "ISNULL([Version], 0)" if _has_column(cursor, "ClientOrders", "Version") else "0"
    cursor.execute(
        f"""
        SELECT DocType, OrderID, {version_expr} AS Version
        FROM ClientOrders
        WHERE {" OR ".join(clauses)}
        """,
        tuple(params),
    )
    return {(str(row[0] or "").strip(), int(row[1] or 0)): int(row[2] or 0) for row in cursor.fetchall()}


def _load_location_meta(cursor, wh_id: int, location_ids: list[str]) -> dict[str, dict[str, object]]:
    clean_locations = [location_id.strip() for location_id in location_ids if location_id and location_id.strip()]
    if not clean_locations:
        return {}

    placeholders = ",".join("?" for _ in clean_locations)
    equip_expr = "ISNULL(EquipID, '')" if _has_column(cursor, "Locations", "EquipID") else "''"
    manual_expr = "ISNULL(IsManual, 0)" if _has_column(cursor, "Locations", "IsManual") else "0"
    cursor.execute(
        f"""
        SELECT CONVERT(varchar(15), LocationID) AS LocationID,
               {equip_expr} AS EquipID,
               {manual_expr} AS IsManual
        FROM Locations
        WHERE WHID = ?
          AND CONVERT(varchar(15), LocationID) IN ({placeholders})
        """,
        (wh_id, *clean_locations),
    )
    return {
        str(row[0] or "").strip(): {
            "equip_id": str(row[1] or "").strip(),
            "is_manual": bool(row[2]),
        }
        for row in cursor.fetchall()
    }


def _load_dimension_rows(cursor, line_keys: list[tuple[str, int, int]]) -> dict[tuple[str, int, int], list[dict[str, object]]]:
    if not line_keys:
        return {}

    clauses = []
    params: list[object] = []
    for doc_type, order_id, order_row in line_keys:
        clauses.append("(DocType = ? AND OrderID = ? AND OrderRow = ?)")
        params.extend([doc_type, order_id, order_row])

    cursor.execute(
        f"""
        SELECT
            DocType,
            OrderID,
            OrderRow,
            ISNULL(ColorID, '') AS ColorID,
            ISNULL(GridID, '') AS GridID,
            ISNULL(SizeID, '') AS SizeID,
            ISNULL(SizeOrderNum, 0) AS SizeOrderNum,
            ISNULL(QtyOrd, 0) AS QtyOrd,
            ISNULL(QtySatisf, 0) AS QtySatisf,
            ISNULL(QtyPend, CASE
                WHEN ISNULL(QtyOrd, 0) - ISNULL(QtySatisf, 0) > 0
                    THEN ISNULL(QtyOrd, 0) - ISNULL(QtySatisf, 0)
                ELSE 0
            END) AS QtyPend
        FROM ClientOrdersDim
        WHERE {" OR ".join(clauses)}
        ORDER BY DocType, OrderID, OrderRow, ISNULL(SizeOrderNum, 0), ColorID, SizeID
        """,
        tuple(params),
    )
    rows = cursor.fetchall()

    result: dict[tuple[str, int, int], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row[0] or "").strip(), int(row[1] or 0), int(row[2] or 0))
        result.setdefault(key, []).append(
            {
                "color_id": str(row[3] or "").strip(),
                "grid_id": str(row[4] or "").strip(),
                "size_id": str(row[5] or "").strip(),
                "size_order_num": int(row[6] or 0),
                "qty_ord": float(row[7] or 0),
                "qty_satisf": float(row[8] or 0),
                "qty_pend": float(row[9] or 0),
            }
        )
    return result


def _load_reserved_dimension_qty(cursor, line_keys: list[tuple[str, int, int]]) -> dict[tuple[str, int, int, str], float]:
    if not line_keys:
        return {}

    clauses = []
    params: list[object] = []
    for doc_type, order_id, order_row in line_keys:
        clauses.append("(DocTypeOri = ? AND OrderIDOri = ? AND OrderRowOri = ?)")
        params.extend([doc_type, order_id, order_row])

    cursor.execute(
        f"""
        SELECT
            codo.DocTypeOri,
            codo.OrderIDOri,
            codo.OrderRowOri,
            ISNULL(cdim.SizeID, '') AS SizeID,
            SUM(ISNULL(cdim.QtyOrd, 0)) AS QtyReserved
        FROM ClientOrderDetailsOri codo WITH (NOLOCK)
        JOIN ClientOrdersDim cdim WITH (NOLOCK)
          ON cdim.DocType = codo.DocType
         AND cdim.OrderID = codo.OrderID
         AND cdim.OrderRow = codo.OrderRow
        JOIN ClientOrders co_res WITH (NOLOCK)
          ON co_res.DocType = codo.DocType
         AND co_res.OrderID = codo.OrderID
        WHERE ({" OR ".join(clauses)})
          AND ISNULL(co_res.ProductionStatus, '') <> 'ANULADO'
        GROUP BY codo.DocTypeOri, codo.OrderIDOri, codo.OrderRowOri, ISNULL(cdim.SizeID, '')
        """,
        tuple(params),
    )
    return {
        (str(row[0] or "").strip(), int(row[1] or 0), int(row[2] or 0), str(row[3] or "").strip()): float(row[4] or 0)
        for row in cursor.fetchall()
    }


def _load_dimension_stock(cursor, wh_ids: list[int] | None, stock_keys: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    clean_keys = [(item_id.strip(), size_id.strip()) for item_id, size_id in stock_keys if item_id and item_id.strip()]
    if not clean_keys:
        return {}

    wh_sql, wh_params = _wh_filter("WHID", wh_ids)
    clauses = []
    params: list[object] = list(wh_params)
    for item_id, size_id in clean_keys:
        clauses.append("(ItemID = ? AND ISNULL(SizeID, '') = ?)")
        params.extend([item_id, size_id])

    cursor.execute(
        f"""
        SELECT
            ItemID,
            ISNULL(SizeID, '') AS SizeID,
            SUM(ISNULL(Qty, 0)) AS QtyStock
        FROM Inventory
        WHERE Qty > 0
          AND {wh_sql}
          AND ({' OR '.join(clauses)})
        GROUP BY ItemID, ISNULL(SizeID, '')
        """,
        tuple(params),
    )
    return {
        (str(row[0] or "").strip(), str(row[1] or "").strip()): float(row[2] or 0)
        for row in cursor.fetchall()
    }


def _reserved_stock_by_item(cursor, wh_ids: list[int] | None, item_size_keys: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """Quantity of each (item, size) already committed to OTHER separation orders that are
    still pending or in progress (not yet fully picked). Boxes holding this qty must not be
    offered again as free stock when building a new separation order, even though the
    warehouse's Inventory.Qty itself is only decremented later, by a separate process."""
    clean_keys = [(item_id.strip(), size_id.strip()) for item_id, size_id in item_size_keys if item_id and item_id.strip()]
    if not clean_keys:
        return {}

    wh_sql, wh_params = _wh_filter("ISNULL(opd.WhIDOri, 0)", wh_ids)
    clauses = []
    params: list[object] = list(wh_params)
    for item_id, size_id in clean_keys:
        clauses.append("(opd.ItemID = ? AND ISNULL(opd.SizeID, '') = ?)")
        params.extend([item_id, size_id])

    cursor.execute(
        f"""
        SELECT
            opd.ItemID,
            ISNULL(opd.SizeID, '') AS SizeID,
            SUM(CASE
                WHEN ISNULL(opd.QtyToPick, 0) > ISNULL(opd.QtyPicked, 0)
                THEN ISNULL(opd.QtyToPick, 0) - ISNULL(opd.QtyPicked, 0)
                ELSE 0
            END) AS QtyReserved
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        JOIN OrdersPicking op WITH (NOLOCK) ON op.ID = opd.OrderID
        WHERE ISNULL(opd.deleted, 0) = 0
          AND ISNULL(op.deleted, 0) = 0
          AND ISNULL(opd.PickingCompleted, 0) = 0
          AND {wh_sql}
          AND ({' OR '.join(clauses)})
        GROUP BY opd.ItemID, ISNULL(opd.SizeID, '')
        """,
        tuple(params),
    )
    return {
        (str(row[0] or "").strip(), str(row[1] or "").strip()): float(row[2] or 0)
        for row in cursor.fetchall()
    }


def _split_doc_types(value: object) -> list[str]:
    return [part.strip().upper() for part in str(value or "").split(",") if part.strip()]


def _target_doc_config(cursor) -> dict:
    doc_type = _safe_text(settings.SEPARATION_DOC_TYPE).upper() or "SSCP"
    cursor.execute(
        """
        SELECT TOP 1 DocType, ISNULL(Title, DocType), ISNULL(Active, 1), ISNULL(DocTypeOrig, ''), ISNULL(UseDocOriComps, 0)
        FROM DocumentConfig
        WHERE DocType = ?
        """,
        (doc_type,),
    )
    row = cursor.fetchone()
    return {
        "doc_type": doc_type,
        "title": (row[1] if row else doc_type) or doc_type,
        "exists": bool(row),
        "active": bool(row[2]) if row else False,
        "origin_doc_types": _split_doc_types(row[3] if row else ""),
        # Quando True, os artigos/quantidades a separar não vêm das linhas do documento
        # origem (ClientOrderDetails) mas sim dos componentes da ordem de fabrico
        # (ClientOrderComp) — ex: ordem de fabrico com lista de materiais a picking.
        "use_doc_ori_comps": bool(row[4]) if row else False,
    }


def _build_picking_rows(
    line: SeparationCreateLine,
    wh_id_orig: int,
    unit_id: str,
    version: int,
    location_meta: dict[str, dict[str, object]],
    target_doc_type: str,
    target_order_id: int,
    target_order_row: int,
    effective_size_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    item_id = _safe_text(line.substitute_item_id) or _safe_text(line.item_id)

    for allocation in line.allocations:
        qty = float(allocation.qty or 0)
        if qty <= 0:
            continue
        location_id = _safe_text(allocation.location_id)
        meta = location_meta.get(location_id, {})
        rows.append(
            {
                "item_id": item_id,
                "qty": qty,
                "qty_vols": 1 if _safe_text(allocation.vol_num) else 0,
                "unit_id": unit_id or "UN",
                "location_id_orig": location_id,
                "wh_id_orig": wh_id_orig,
                "equip_id_orig": str(meta.get("equip_id") or "").strip(),
                "is_manual_orig": 1 if meta.get("is_manual") else 0,
                "doc_type_ori": target_doc_type,
                "order_id_ori": target_order_id,
                "order_row_ori": target_order_row,
                "part_num_ori": 0,
                "version": version,
                "vol_num": _safe_text(allocation.vol_num),
                "color_id": _safe_text(line.origin_color_id),
                "size_id": effective_size_id,
            }
        )

    qty_allocated = sum(row["qty"] for row in rows)
    qty_remaining = max(0.0, float(line.qty_to_separate or 0) - qty_allocated)
    if qty_remaining > 0:
        rows.append(
            {
                "item_id": item_id,
                "qty": qty_remaining,
                "qty_vols": 0,
                "unit_id": unit_id or "UN",
                "location_id_orig": "",
                "wh_id_orig": wh_id_orig,
                "equip_id_orig": "",
                "is_manual_orig": 0,
                "doc_type_ori": target_doc_type,
                "order_id_ori": target_order_id,
                "order_row_ori": target_order_row,
                "part_num_ori": 0,
                "version": version,
                "vol_num": "",
                "color_id": _safe_text(line.origin_color_id),
                "size_id": effective_size_id,
            }
        )

    return rows


def _reserved_boxes_join(source_alias: str = "i", reserved_alias: str = "reserved_boxes") -> str:
    return f"""
        LEFT JOIN (
            SELECT
                ISNULL(opd.VolTypeID, 'CX') AS VolTypeID,
                CAST(opd.VolNum AS varchar(50)) AS VolNum,
                ISNULL(opd.ItemID, '') AS ItemID,
                ISNULL(opd.WhIDOri, 0) AS WhIDOri,
                ISNULL(opd.SizeID, '') AS SizeID,
                SUM(CASE
                    WHEN ISNULL(opd.QtyToPick, 0) > 0 THEN ISNULL(opd.QtyToPick, 0)
                    ELSE ISNULL(opd.Qty, 0)
                END) AS ReservedQty
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN OrdersPicking op WITH (NOLOCK)
              ON op.ID = opd.OrderID
            WHERE ISNULL(opd.deleted, 0) = 0
              AND ISNULL(op.deleted, 0) = 0
              AND ISNULL(opd.PickingCompleted, 0) = 0
              AND ISNULL(opd.VolNum, '') <> ''
            GROUP BY
                ISNULL(opd.VolTypeID, 'CX'),
                CAST(opd.VolNum AS varchar(50)),
                ISNULL(opd.ItemID, ''),
                ISNULL(opd.WhIDOri, 0),
                ISNULL(opd.SizeID, '')
        ) {reserved_alias}
          ON {reserved_alias}.VolTypeID = 'CX'
         AND {reserved_alias}.VolNum = CAST({source_alias}.VolNum AS varchar(50))
         AND {reserved_alias}.ItemID = ISNULL({source_alias}.ItemID, '')
         AND {reserved_alias}.WhIDOri = ISNULL({source_alias}.WHID, 0)
         AND {reserved_alias}.SizeID = ISNULL({source_alias}.SizeID, '')
    """


def _ensure_boxes_available(
    cursor,
    wh_id_orig: int,
    item_id: str,
    size_id: str,
    allocations: list[SeparationLineAllocation],
) -> None:
    vol_nums = sorted({
        _safe_text(allocation.vol_num)
        for allocation in allocations
        if float(allocation.qty or 0) > 0 and _safe_text(allocation.vol_num)
    })
    if not vol_nums:
        return

    placeholders = ",".join("?" for _ in vol_nums)
    cursor.execute(
        f"""
        WITH reserved AS (
            SELECT
                CAST(opd.VolNum AS varchar(50)) AS VolNum,
                SUM(CASE
                    WHEN ISNULL(opd.QtyToPick, 0) > 0 THEN ISNULL(opd.QtyToPick, 0)
                    ELSE ISNULL(opd.Qty, 0)
                END) AS ReservedQty
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            JOIN OrdersPicking op WITH (NOLOCK)
              ON op.ID = opd.OrderID
            WHERE ISNULL(opd.deleted, 0) = 0
              AND ISNULL(op.deleted, 0) = 0
              AND ISNULL(opd.PickingCompleted, 0) = 0
              AND ISNULL(opd.VolTypeID, 'CX') = 'CX'
              AND ISNULL(opd.ItemID, '') = ?
              AND ISNULL(opd.WhIDOri, 0) = ?
              AND ISNULL(opd.SizeID, '') = ?
              AND CAST(opd.VolNum AS varchar(50)) IN ({placeholders})
            GROUP BY CAST(opd.VolNum AS varchar(50))
        )
        SELECT
            CAST(i.VolNum AS varchar(50)) AS VolNum,
            SUM(ISNULL(i.Qty, 0)) AS QtyStock,
            ISNULL(r.ReservedQty, 0) AS ReservedQty
        FROM Inventory i
        LEFT JOIN reserved r
          ON r.VolNum = CAST(i.VolNum AS varchar(50))
        WHERE i.ItemID = ?
          AND i.WHID = ?
          AND ISNULL(i.SizeID, '') = ?
          AND i.Qty > 0
          AND CAST(i.VolNum AS varchar(50)) IN ({placeholders})
        GROUP BY CAST(i.VolNum AS varchar(50)), ISNULL(r.ReservedQty, 0)
        """,
        (item_id, wh_id_orig, size_id, *vol_nums, item_id, wh_id_orig, size_id, *vol_nums),
    )

    availability = {
        str(row[0] or "").strip(): max(0.0, float(row[1] or 0) - float(row[2] or 0))
        for row in cursor.fetchall()
        if str(row[0] or "").strip()
    }
    exhausted_boxes = []
    for allocation in allocations:
        vol_num = _safe_text(allocation.vol_num)
        if not vol_num or float(allocation.qty or 0) <= 0:
            continue
        available_qty = availability.get(vol_num, 0.0)
        if float(allocation.qty or 0) > available_qty:
            exhausted_boxes.append(vol_num)

    if exhausted_boxes:
        raise HTTPException(
            status_code=400,
            detail=f"As caixas {', '.join(exhausted_boxes)} nao tem saldo disponivel para esta separacao",
        )


def _box_available_qty(
    cursor,
    wh_id_orig: int,
    item_id: str,
    size_id: str,
    vol_num: str,
    exclude_order_id: int | None = None,
    exclude_row_number: int | None = None,
) -> float:
    """Stock of `item_id` currently sitting in box `vol_num`, minus what other order lines
    are already counting on from that same box - both lines still pending and lines already
    picked, since picking here only marks the demand as fulfilled and does not itself
    decrement Inventory.Qty (that happens later in a separate reconciliation step)."""
    cursor.execute(
        """
        SELECT SUM(ISNULL(Qty, 0))
        FROM Inventory WITH (NOLOCK)
        WHERE ItemID = ? AND WHID = ? AND ISNULL(SizeID, '') = ?
          AND CAST(VolNum AS varchar(50)) = ? AND Qty > 0
        """,
        (item_id, wh_id_orig, size_id, vol_num),
    )
    stock_row = cursor.fetchone()
    stock_qty = float(stock_row[0] or 0) if stock_row and stock_row[0] is not None else 0.0

    reserved_sql = """
        SELECT SUM(CASE
            WHEN ISNULL(opd.PickingCompleted, 0) = 1 THEN ISNULL(opd.QtyPicked, 0)
            WHEN ISNULL(opd.QtyToPick, 0) > 0 THEN ISNULL(opd.QtyToPick, 0)
            ELSE ISNULL(opd.Qty, 0)
        END)
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        JOIN OrdersPicking op WITH (NOLOCK) ON op.ID = opd.OrderID
        WHERE ISNULL(opd.deleted, 0) = 0
          AND ISNULL(op.deleted, 0) = 0
          AND ISNULL(opd.ItemID, '') = ?
          AND ISNULL(opd.WhIDOri, 0) = ?
          AND ISNULL(opd.SizeID, '') = ?
          AND CAST(opd.VolNum AS varchar(50)) = ?
    """
    params: list[object] = [item_id, wh_id_orig, size_id, vol_num]
    if exclude_order_id is not None and exclude_row_number is not None:
        reserved_sql += " AND NOT (opd.OrderID = ? AND opd.RowNumber = ?)"
        params.extend([exclude_order_id, exclude_row_number])

    cursor.execute(reserved_sql, params)
    reserved_row = cursor.fetchone()
    reserved_qty = float(reserved_row[0] or 0) if reserved_row and reserved_row[0] is not None else 0.0

    return max(0.0, stock_qty - reserved_qty)


@router.get("/config")
def get_config():
    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
    return target


@router.get("/document-types")
def list_document_types():
    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
        allowed_doc_types = target["origin_doc_types"]
        if not allowed_doc_types:
            return []

        placeholders = ",".join("?" for _ in allowed_doc_types)
        cursor.execute(
            f"""
            SELECT DocType, ISNULL(Title, DocType) AS Title, ISNULL(DocDesc, '') AS DocDesc
            FROM DocumentConfig
            WHERE ISNULL(Active, 1) = 1
              AND ISNULL(PartnerType, '') <> ''
              AND DocType IN ({placeholders})
            ORDER BY Title, DocType
            """,
            tuple(allowed_doc_types),
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


@router.get("/partners")
def list_partners(
    doc_type: str = Query(..., min_length=1),
    search: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
        if doc_type.strip().upper() not in target["origin_doc_types"]:
            raise HTTPException(status_code=400, detail="Tipo de documento origem nao permitido para este SPA")

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
            raise HTTPException(status_code=400, detail="PartnerType nao configurado para este documento")

        result_limit = 50
        if search:
            term = search.strip()
            like_term = f"%{term}%"
            prefix_term = f"{term}%"
            cursor.execute(
                f"""
                SELECT TOP {result_limit}
                    PartnerID, PartnerName, PartnerType, ISNULL(PartnerAbrev, ''),
                    ISNULL(City, ''), ISNULL(VATNo, '')
                FROM BusinessPartners
                WHERE PartnerType = ?
                  AND (
                        PartnerID LIKE ?
                     OR PartnerName LIKE ?
                     OR PartnerAbrev LIKE ?
                     OR VATNo LIKE ?
                  )
                ORDER BY
                    CASE
                        WHEN PartnerID = ? THEN 0
                        WHEN PartnerName LIKE ? OR PartnerAbrev LIKE ? THEN 1
                        ELSE 2
                    END,
                    PartnerName, PartnerID
                """,
                (
                    partner_type,
                    like_term, like_term, like_term, like_term,
                    term, prefix_term, prefix_term,
                ),
            )
        else:
            cursor.execute(
                f"""
                SELECT TOP {result_limit}
                    PartnerID, PartnerName, PartnerType, ISNULL(PartnerAbrev, ''),
                    ISNULL(City, ''), ISNULL(VATNo, '')
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
            "partner_abrev": row[3] or "",
            "city": row[4] or "",
            "vat_no": row[5] or "",
        }
        for row in rows
    ]


@router.get("/warehouses")
def list_warehouses():
    """Armazens que este SPA pode usar. Quando DocumentWarehouses tem linhas configuradas
    para o DocType (ex: 'SSCP'), a lista fica restrita a essas - e as marcadas
    DefaultWhAndLocation=1 vem identificadas para o frontend pre-selecionar sem o operador
    ter de escolher sempre os mesmos armazens. Sem configuracao, mostra todos (comportamento
    anterior)."""
    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
        cursor.execute(
            """
            SELECT dw.WHID, ISNULL(w.WHDesc, ''), ISNULL(dw.DefaultWhAndLocation, 0)
            FROM DocumentWarehouses dw
            JOIN Warehouses w ON w.WHID = dw.WHID
            WHERE dw.DocType = ?
            ORDER BY w.WHDesc, dw.WHID
            """,
            (target["doc_type"],),
        )
        rows = cursor.fetchall()
        if rows:
            return [{"wh_id": row[0], "wh_desc": row[1], "is_default": bool(row[2])} for row in rows]

        cursor.execute(
            """
            SELECT WHID, ISNULL(WHDesc, '')
            FROM Warehouses
            ORDER BY WHDesc, WHID
            """
        )
        rows = cursor.fetchall()
    return [{"wh_id": row[0], "wh_desc": row[1], "is_default": False} for row in rows]


def _list_documents_from_comps(cursor, target: dict, doc_type: str, partner_id: str, search: str) -> list[dict]:
    """Equivalente a list_documents, mas para SPAs com UseDocOriComps=1: a elegibilidade de
    cada OF/OFT depende do saldo pendente em ClientOrderComp (TotQty - QtySatisf - reservado
    por outras separacoes), nao das linhas em ClientOrderDetails - caso contrario aparecem
    aqui documentos que ja nao tem nada por separar, so se descobrindo isso depois de
    seleccionados (o /lines volta vazio)."""
    status_sql, status_params = _status_filters(cursor)
    row_key_expr = "(coc.OrderRow * 100000 + coc.Sequence)"

    search_text = search.strip()
    search_sql = ""
    params: list[object] = [target["doc_type"], doc_type]

    if partner_id:
        search_sql += " AND bp.PartnerID = ?"
        params.append(partner_id)

    if search_text:
        term = f"%{search_text}%"
        search_sql += """
            AND (
                CAST(co.OrderID AS varchar(50)) LIKE ?
                OR ISNULL(coc.ComponentID, '') LIKE ?
                OR ISNULL(bp.PartnerName, '') LIKE ?
                OR ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) LIKE ?
            )
        """
        params.extend([term, term, term, term])

    params.extend(status_params)
    cursor.execute(
        f"""
        WITH document_lines AS (
            SELECT
                co.OrderID,
                co.DocType,
                ISNULL(bp.PartnerID, ISNULL(co.ClientID, '')) AS PartnerID,
                ISNULL(bp.PartnerName, '') AS PartnerName,
                CAST(co.OrderDateTime AS date) AS OrderDate,
                CAST(co.OrderDatePrev AS date) AS DueDate,
                ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) AS Obs,
                coc.ComponentID AS ItemID,
                CASE
                    WHEN (ISNULL(coc.TotQty, 0) - ISNULL(coc.QtySatisf, 0)) - ISNULL(reserved.QtyReserved, 0) > 0
                        THEN (ISNULL(coc.TotQty, 0) - ISNULL(coc.QtySatisf, 0)) - ISNULL(reserved.QtyReserved, 0)
                    ELSE 0
                END AS QtyAvailable
            FROM ClientOrders co
            JOIN DocumentConfig dc
              ON dc.DocType = co.DocType
            JOIN ClientOrderComp coc
              ON coc.DocType = co.DocType
             AND coc.OrderID = co.OrderID
            LEFT JOIN (
                SELECT
                    codo.DocTypeOri,
                    codo.OrderIDOri,
                    codo.OrderRowOri,
                    SUM(ISNULL(codo.QtyOrdDest, ISNULL(codo.QtyOrd, 0))) AS QtyReserved
                FROM ClientOrderDetailsOri codo WITH (NOLOCK)
                JOIN ClientOrders co_res WITH (NOLOCK)
                  ON co_res.DocType = codo.DocType
                 AND co_res.OrderID = codo.OrderID
                WHERE codo.DocType = ?
                  AND ISNULL(co_res.ProductionStatus, '') <> 'ANULADO'
                GROUP BY codo.DocTypeOri, codo.OrderIDOri, codo.OrderRowOri
            ) reserved
              ON reserved.DocTypeOri = coc.DocType
             AND reserved.OrderIDOri = coc.OrderID
             AND reserved.OrderRowOri = {row_key_expr}
            LEFT JOIN BusinessPartners bp
              ON bp.PartnerType = dc.PartnerType
             AND bp.PartnerID = co.ClientID
            {status_sql}
              AND co.DocType = ?
              {search_sql}
        ),
        eligible_lines AS (
            SELECT *
            FROM document_lines
            WHERE QtyAvailable > 0
        )
        SELECT
            OrderID,
            DocType,
            PartnerID,
            PartnerName,
            OrderDate,
            DueDate,
            Obs,
            SUM(QtyAvailable) AS TotalQty,
            COUNT(*) AS TotalLines,
            MAX(ItemID) AS ItemID
        FROM eligible_lines
        GROUP BY OrderID, DocType, PartnerID, PartnerName, OrderDate, DueDate, Obs
        ORDER BY OrderID DESC
        """,
        tuple(params),
    )
    rows = cursor.fetchall()
    return [
        {
            "order_id": row[0],
            "doc_type": row[1],
            "partner_id": row[2] or "",
            "partner_name": row[3] or "",
            "order_date": str(row[4]) if row[4] else None,
            "due_date": str(row[5]) if row[5] else None,
            "obs": row[6] or "",
            "total_qty": float(row[7] or 0),
            "total_lines": int(row[8] or 0),
            "item_id": row[9] or "",
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
        target = _target_doc_config(cursor)
        if doc_type.strip().upper() not in target["origin_doc_types"]:
            raise HTTPException(status_code=400, detail="Tipo de documento origem nao permitido para este SPA")

        if target["use_doc_ori_comps"]:
            return _list_documents_from_comps(cursor, target, doc_type, partner_id, search)

        status_sql, status_params = _status_filters(cursor)
        qty_done_expr, qty_pending_expr = _pending_qty_expr(cursor)
        qty_reserved_expr = _reserved_qty_expr()
        reserved_join_sql = _reserved_qty_join(target["doc_type"])
        qty_available_expr = f"""
            CASE
                WHEN ({qty_pending_expr}) - ({qty_reserved_expr}) > 0
                    THEN ({qty_pending_expr}) - ({qty_reserved_expr})
                ELSE 0
            END
        """
        search_text = search.strip()
        search_sql = ""
        params: list[object] = [doc_type]

        if partner_id:
            search_sql += " AND bp.PartnerID = ?"
            params.append(partner_id)

        if search_text:
            term = f"%{search_text}%"
            search_sql += """
                AND (
                    CAST(co.OrderID AS varchar(50)) LIKE ?
                    OR ISNULL(cod.ItemID, '') LIKE ?
                    OR ISNULL(bp.PartnerName, '') LIKE ?
                    OR ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) LIKE ?
                )
            """
            params.extend([term, term, term, term])

        params.extend(status_params)
        cursor.execute(
            f"""
            WITH document_lines AS (
                SELECT
                    co.OrderID,
                    co.DocType,
                    ISNULL(bp.PartnerID, ISNULL(co.ClientID, '')) AS PartnerID,
                    ISNULL(bp.PartnerName, '') AS PartnerName,
                    CAST(co.OrderDateTime AS date) AS OrderDate,
                    CAST(co.OrderDatePrev AS date) AS DueDate,
                    ISNULL(co.ObsInternal, ISNULL(co.Obs, '')) AS Obs,
                    cod.ItemID,
                    {qty_available_expr} AS QtyAvailable
                FROM ClientOrders co
                JOIN DocumentConfig dc
                  ON dc.DocType = co.DocType
                JOIN ClientOrderDetails cod
                  ON cod.DocType = co.DocType
                 AND cod.OrderID = co.OrderID
                {reserved_join_sql}
                LEFT JOIN BusinessPartners bp
                  ON bp.PartnerType = dc.PartnerType
                 AND bp.PartnerID = co.ClientID
                {status_sql}
                  AND co.DocType = ?
                  {search_sql}
            ),
            eligible_lines AS (
                SELECT *
                FROM document_lines
                WHERE QtyAvailable > 0
            )
            SELECT
                OrderID,
                DocType,
                PartnerID,
                PartnerName,
                OrderDate,
                DueDate,
                Obs,
                SUM(QtyAvailable) AS TotalQty,
                COUNT(*) AS TotalLines,
                MAX(ItemID) AS ItemID
            FROM eligible_lines
            GROUP BY OrderID, DocType, PartnerID, PartnerName, OrderDate, DueDate, Obs
            ORDER BY OrderID DESC
            """,
            tuple(params),
        )
        rows = cursor.fetchall()

    return [
        {
            "order_id": row[0],
            "doc_type": row[1],
            "partner_id": row[2] or "",
            "partner_name": row[3] or "",
            "order_date": str(row[4]) if row[4] else None,
            "due_date": str(row[5]) if row[5] else None,
            "obs": row[6] or "",
            "total_qty": float(row[7] or 0),
            "total_lines": int(row[8] or 0),
            "item_id": row[9] or "",
        }
        for row in rows
    ]


def _load_document_lines_from_comps(
    cursor,
    target: dict,
    doc_type: str,
    order_ids: list,
    wh_ids: list[int] | None,
    placeholders: str,
) -> dict:
    """
    Quando DocumentConfig.UseDocOriComps = 1 para o SPA (ex: 'SSCP'), os artigos e
    quantidades a separar não vêm das linhas do documento origem (ClientOrderDetails)
    mas sim dos componentes da ordem de fabrico, em ClientOrderComp — ex:
    SELECT ComponentID, TotQty FROM ClientOrderComp WHERE DocType='OF' AND OrderID=...

    ClientOrderComp não tem OrderRow único por componente — várias linhas de
    componentes diferentes partilham o mesmo OrderRow (a chave real é
    OrderRow+Sequence, ou o próprio ComponentID). Como o resto do fluxo de separação
    (ClientOrderDetailsOri.OrderRowOri, SeparationCreateLine.origin_order_row) assume
    um único inteiro por linha de origem, sintetiza-se uma chave única e estável
    (OrderRow * 100000 + Sequence — Sequence nunca observado acima de poucas centenas)
    para identificar cada componente sem alterar o esquema da base de dados.
    """
    row_key_expr = "(coc.OrderRow * 100000 + coc.Sequence)"
    stock_wh_sql, stock_wh_params = _wh_filter("i.WHID", wh_ids)
    cursor.execute(
        f"""
        SELECT
            coc.DocType,
            coc.OrderID,
            {row_key_expr} AS OrderRowKey,
            coc.ComponentID,
            ISNULL(im.ItemDesc, coc.ComponentID) AS ItemDesc,
            ISNULL(coc.TotQty, 0) AS QtyOrd,
            ISNULL(coc.QtySatisf, 0) AS QtyDone,
            ISNULL(reserved.QtyReserved, 0) AS QtyReserved,
            ISNULL(coc.Obs, '') AS ObsLine,
            CAST(co.OrderDateTime AS date) AS OrderDate,
            CAST(co.OrderDatePrev AS date) AS DueDate,
            ISNULL((
                SELECT SUM(i.Qty)
                FROM Inventory i
                WHERE i.ItemID = coc.ComponentID
                  AND i.Qty > 0
                  AND {stock_wh_sql}
            ), 0) AS QtyStock
        FROM ClientOrderComp coc WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
          ON co.DocType = coc.DocType
         AND co.OrderID = coc.OrderID
        LEFT JOIN (
            SELECT
                codo.DocTypeOri,
                codo.OrderIDOri,
                codo.OrderRowOri,
                SUM(ISNULL(codo.QtyOrdDest, ISNULL(codo.QtyOrd, 0))) AS QtyReserved
            FROM ClientOrderDetailsOri codo WITH (NOLOCK)
            JOIN ClientOrders co_res WITH (NOLOCK)
              ON co_res.DocType = codo.DocType
             AND co_res.OrderID = codo.OrderID
            WHERE codo.DocType = ?
              AND ISNULL(co_res.ProductionStatus, '') <> 'ANULADO'
            GROUP BY codo.DocTypeOri, codo.OrderIDOri, codo.OrderRowOri
        ) reserved
          ON reserved.DocTypeOri = coc.DocType
         AND reserved.OrderIDOri = coc.OrderID
         AND reserved.OrderRowOri = {row_key_expr}
        LEFT JOIN ItemMaster im WITH (NOLOCK)
          ON im.ItemID = coc.ComponentID
        WHERE coc.DocType = ?
          AND coc.OrderID IN ({placeholders})
        ORDER BY coc.OrderID, coc.OrderRow, coc.Sequence
        """,
        (*stock_wh_params, target["doc_type"], doc_type, *order_ids),
    )
    rows = cursor.fetchall()

    reserved_stock = _reserved_stock_by_item(cursor, wh_ids, [(str(row[3] or "").strip(), "") for row in rows])

    lines = []
    for row in rows:
        doc_type_key = str(row[0] or "").strip()
        order_id_key = int(row[1] or 0)
        order_row_key = int(row[2] or 0)
        item_id = row[3] or ""
        item_desc = row[4] or row[3] or ""
        qty_requested = float(row[5] or 0)
        qty_done = float(row[6] or 0)
        qty_reserved = max(0.0, float(row[7] or 0))
        qty_pending = max(0.0, (qty_requested - qty_done) - qty_reserved)
        if qty_pending <= 0:
            continue
        qty_stock = max(0.0, float(row[11] or 0) - reserved_stock.get((str(item_id).strip(), ""), 0.0))
        lines.append(
            {
                "origin_doc_type": doc_type_key,
                "origin_order_id": order_id_key,
                "origin_order_row": order_row_key,
                "item_id": item_id,
                "item_desc": item_desc,
                "qty_requested": qty_requested,
                "qty_done": qty_done,
                "qty_in_separation": qty_reserved,
                "qty_pending": qty_pending,
                "obs": row[8] or "",
                "order_date": str(row[9]) if row[9] else None,
                "due_date": str(row[10]) if row[10] else None,
                "qty_stock": qty_stock,
                "origin_color_id": "",
                "origin_grid_id": "",
                "origin_size_id": "",
                "origin_size_order_num": 0,
                "has_dimensions": False,
            }
        )

    return {
        "lines": lines,
        "summary": {
            "documents_count": len(set((line["origin_doc_type"], line["origin_order_id"]) for line in lines)),
            "lines_count": len(lines),
            "qty_pending": sum(line["qty_pending"] for line in lines),
        },
    }


@router.post("/lines")
def load_document_lines(payload: dict):
    doc_type = _safe_text(payload.get("doc_type")).upper()
    order_ids = payload.get("order_ids") or []
    # Aceita tanto o formato antigo (um unico wh_id_orig) como uma lista wh_ids, para
    # permitir obter stock/produtos a separar considerando mais do que um armazem.
    raw_wh_ids = payload.get("wh_ids")
    if raw_wh_ids:
        wh_ids = [int(w) for w in raw_wh_ids if w is not None]
    elif payload.get("wh_id_orig") is not None:
        wh_ids = [int(payload["wh_id_orig"])]
    else:
        wh_ids = []

    if not doc_type or not order_ids:
        raise HTTPException(status_code=400, detail="Seleciona o tipo de documento e pelo menos um documento origem")

    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
        if doc_type not in target["origin_doc_types"]:
            raise HTTPException(status_code=400, detail="Tipo de documento origem nao permitido para este SPA")

        placeholders = ",".join("?" for _ in order_ids)

        if target["use_doc_ori_comps"]:
            return _load_document_lines_from_comps(cursor, target, doc_type, order_ids, wh_ids, placeholders)

        qty_done_expr, qty_pending_expr = _pending_qty_expr(cursor)
        qty_reserved_expr = _reserved_qty_expr()
        reserved_join_sql = _reserved_qty_join(target["doc_type"])
        stock_wh_sql, stock_wh_params = _wh_filter("i.WHID", wh_ids)
        cursor.execute(
            f"""
            SELECT
                cod.DocType,
                cod.OrderID,
                cod.OrderRow,
                cod.ItemID,
                ISNULL(im.ItemDesc, cod.ItemID) AS ItemDesc,
                ISNULL(cod.QtyOrd, 0) AS QtyOrd,
                {qty_done_expr} AS QtyDone,
                {qty_pending_expr} AS QtyPendingBase,
                {qty_reserved_expr} AS QtyReserved,
                ISNULL(cod.ObsInternal, ISNULL(cod.Obs, '')) AS ObsLine,
                CAST(co.OrderDateTime AS date) AS OrderDate,
                CAST(co.OrderDatePrev AS date) AS DueDate,
                ISNULL(cod.ColorID, '') AS ColorID,
                ISNULL(cod.GridID, '') AS GridID,
                ISNULL(im.Dimensions, 0) AS HasDimensions,
                ISNULL((
                    SELECT SUM(i.Qty)
                    FROM Inventory i
                    WHERE i.ItemID = cod.ItemID
                      AND i.Qty > 0
                      AND {stock_wh_sql}
                ), 0) AS QtyStock
            FROM ClientOrderDetails cod WITH (NOLOCK)
            JOIN ClientOrders co WITH (NOLOCK)
              ON co.DocType = cod.DocType
             AND co.OrderID = cod.OrderID
            {reserved_join_sql}
            LEFT JOIN ItemMaster im WITH (NOLOCK)
              ON im.ItemID = cod.ItemID
            WHERE cod.DocType = ?
              AND cod.OrderID IN ({placeholders})
            ORDER BY cod.OrderID, cod.OrderRow
            """,
            (*stock_wh_params, doc_type, *order_ids),
        )
        rows = cursor.fetchall()

        dimension_keys = [
            (str(row[0] or "").strip(), int(row[1] or 0), int(row[2] or 0))
            for row in rows
            if bool(row[14])
        ]
        dimension_rows_by_key = _load_dimension_rows(cursor, dimension_keys)
        reserved_dimension_qty = _load_reserved_dimension_qty(cursor, dimension_keys)
        dimension_stock_keys = [
            (str(row[3] or "").strip(), dim_row["size_id"])
            for row in rows
            for dim_row in dimension_rows_by_key.get((str(row[0] or "").strip(), int(row[1] or 0), int(row[2] or 0)), [])
        ]
        dimension_stock = _load_dimension_stock(cursor, wh_ids, dimension_stock_keys)
        reserved_stock_by_dim = _reserved_stock_by_item(cursor, wh_ids, dimension_stock_keys)
        reserved_stock_flat = _reserved_stock_by_item(
            cursor, wh_ids, [(str(row[3] or "").strip(), "") for row in rows if not bool(row[14])]
        )

    lines = []
    for row in rows:
        doc_type_key = str(row[0] or "").strip()
        order_id_key = int(row[1] or 0)
        order_row_key = int(row[2] or 0)
        item_id = row[3] or ""
        item_desc = row[4] or row[3] or ""
        order_key = (doc_type_key, order_id_key, order_row_key)

        if bool(row[14]) and dimension_rows_by_key.get(order_key):
            for dim_row in dimension_rows_by_key[order_key]:
                size_id = str(dim_row["size_id"] or "").strip()
                qty_pending_base = max(0.0, float(dim_row["qty_pend"] or 0))
                qty_reserved = max(0.0, reserved_dimension_qty.get((doc_type_key, order_id_key, order_row_key, size_id), 0.0))
                qty_pending = max(0.0, qty_pending_base - qty_reserved)
                if qty_pending <= 0:
                    continue
                lines.append(
                    {
                        "origin_doc_type": doc_type_key,
                        "origin_order_id": order_id_key,
                        "origin_order_row": order_row_key,
                        "item_id": item_id,
                        "item_desc": item_desc,
                        "qty_requested": float(dim_row["qty_ord"] or 0),
                        "qty_done": float(dim_row["qty_satisf"] or 0),
                        "qty_in_separation": qty_reserved,
                        "qty_pending": qty_pending,
                        "obs": row[9] or "",
                        "order_date": str(row[10]) if row[10] else None,
                        "due_date": str(row[11]) if row[11] else None,
                        "qty_stock": max(0.0, dimension_stock.get((str(item_id).strip(), size_id), 0.0) - reserved_stock_by_dim.get((str(item_id).strip(), size_id), 0.0)),
                        "origin_color_id": str(dim_row["color_id"] or "").strip(),
                        "origin_grid_id": str(dim_row["grid_id"] or "").strip(),
                        "origin_size_id": size_id,
                        "origin_size_order_num": int(dim_row["size_order_num"] or 0),
                        "has_dimensions": True,
                    }
                )
            continue

        qty_pending_base = max(0.0, float(row[7] or 0))
        qty_reserved = max(0.0, float(row[8] or 0))
        qty_pending = max(0.0, qty_pending_base - qty_reserved)
        if qty_pending <= 0:
            continue
        lines.append(
            {
                "origin_doc_type": doc_type_key,
                "origin_order_id": order_id_key,
                "origin_order_row": order_row_key,
                "item_id": item_id,
                "item_desc": item_desc,
                "qty_requested": float(row[5] or 0),
                "qty_done": float(row[6] or 0),
                "qty_in_separation": qty_reserved,
                "qty_pending": qty_pending,
                "obs": row[9] or "",
                "order_date": str(row[10]) if row[10] else None,
                "due_date": str(row[11]) if row[11] else None,
                "qty_stock": max(0.0, float(row[15] or 0) - reserved_stock_flat.get((str(item_id).strip(), ""), 0.0)),
                "origin_color_id": str(row[12] or "").strip(),
                "origin_grid_id": str(row[13] or "").strip(),
                "origin_size_id": "",
                "origin_size_order_num": 0,
                "has_dimensions": False,
            }
        )

    return {
        "lines": lines,
        "summary": {
            "documents_count": len(set((line["origin_doc_type"], line["origin_order_id"]) for line in lines)),
            "lines_count": len(lines),
            "qty_pending": sum(line["qty_pending"] for line in lines),
        },
    }


@router.get("/items")
def search_items(
    wh_id: int = Query(...),
    search: str = Query(..., min_length=2),
):
    term = f"%{search.strip()}%"
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT TOP 30
                im.ItemID,
                ISNULL(im.ItemDesc, '') AS ItemDesc,
                SUM(ISNULL(i.Qty, 0)) AS QtyStock
            FROM Inventory i
            JOIN ItemMaster im
              ON im.ItemID = i.ItemID
            WHERE i.WHID = ?
              AND i.Qty > 0
              AND (im.ItemID LIKE ? OR im.ItemDesc LIKE ?)
            GROUP BY im.ItemID, im.ItemDesc
            ORDER BY im.ItemID
            """,
            (wh_id, term, term),
        )
        rows = cursor.fetchall()

    return [
        {
            "item_id": row[0],
            "item_desc": row[1] or "",
            "qty_stock": float(row[2] or 0),
        }
        for row in rows
    ]


@router.get("/items/{item_id}/boxes")
def item_boxes(
    item_id: str,
    wh_id: list[int] = Query(...),
    size_id: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        item_meta = _load_item_metadata(cursor, [_safe_text(item_id)]).get(_safe_text(item_id), {})
        effective_size_id = _effective_size_id(item_meta, size_id)
        reserved_boxes_join = _reserved_boxes_join()
        wh_sql, wh_params = _wh_filter("i.WHID", wh_id)
        cursor.execute(
            f"""
            SELECT
                CAST(i.VolNum AS varchar(50)) AS VolNum,
                ISNULL(vm.VolNum2N, '') AS Barcode,
                ISNULL(i.LocationID, '') AS LocationID,
                i.WHID AS WhId,
                SUM(ISNULL(i.Qty, 0)) - ISNULL(MAX(reserved_boxes.ReservedQty), 0) AS QtyStock
            FROM Inventory i
            LEFT JOIN VolMaster vm
              ON vm.VolNum = TRY_CAST(i.VolNum AS int)
            {reserved_boxes_join}
            WHERE i.ItemID = ?
              AND {wh_sql}
              AND i.Qty > 0
              AND (? = '' OR ISNULL(i.SizeID, '') = ?)
              AND i.VolNum IS NOT NULL
              AND CAST(i.VolNum AS varchar(50)) <> ''
            GROUP BY i.VolNum, vm.VolNum2N, i.LocationID, i.WHID
            HAVING SUM(ISNULL(i.Qty, 0)) - ISNULL(MAX(reserved_boxes.ReservedQty), 0) > 0
            ORDER BY i.WHID, i.VolNum
            """,
            (item_id, *wh_params, effective_size_id, effective_size_id),
        )
        rows = cursor.fetchall()

    return [
        {
            "vol_num": row[0] or "",
            "barcode": row[1] or "",
            "location_id": row[2] or "",
            "wh_id": int(row[3] or 0),
            "qty_stock": float(row[4] or 0),
        }
        for row in rows
    ]


def _create_one_separation_order(
    cursor,
    target: dict,
    req: "SeparationCreateRequest",
    group_lines: list["SeparationCreateLine"],
    wh_id: int,
    order_picking_group: str,
    item_metadata: dict[str, dict[str, object]],
    execution_date: datetime,
) -> dict[str, object]:
    """Creates one ClientOrders/OrdersPicking pair (one separation document) for the
    lines belonging to a single origin warehouse. When a /create request spans more than
    one warehouse, the caller invokes this once per warehouse and tags every resulting
    order with the same `order_picking_group`, so they show up linked in the UI."""
    order_id = _next_order_id(cursor, target["doc_type"])
    group_total_qty = sum(float(line.qty_to_separate or 0) for line in group_lines)
    location_ids = list({
        _safe_text(allocation.location_id)
        for line in group_lines
        for allocation in line.allocations
        if _safe_text(allocation.location_id)
    })
    location_meta = _load_location_meta(cursor, wh_id, location_ids)

    cursor.execute(
        """
        INSERT INTO ClientOrders (
            DocType, OrderID, PartNum,
            OrderDateTime, RequesterID, ClientID,
            Status, CreationUser, CreationDateTime,
            Obs, Currency, ExangeRate,
            TotalQtyOrd, DeliveryDate,
            Tipo, PercDsc2, TotalValue, TotalShipValue,
            CreditApproved, UrgencyStatusID,
            ConsignmentDoc, RecuseDoc,
            PartnerCategory
        ) VALUES (
            ?, ?, 0,
            GETDATE(), ?, ?,
            1, 'AI', GETDATE(),
            ?, 'EUR', 1,
            ?, ?,
            0, 0, 0, 0,
            0, 0,
            0, 0,
            'C'
        )
        """,
        (
            target["doc_type"],
            order_id,
            req.origin_doc_type,
            req.partner_id,
            req.obs.strip(),
            group_total_qty,
            execution_date,
        ),
    )

    cursor.execute(
        """
        INSERT INTO OrdersPicking (
            SeparationOrder, SeqNumber, [Date], DueDate, Obs,
            AssignedUser, WhIDDest, LocationIDDest,
            deleted, created_by, created_date,
            edited_by, RouteID, ShippingCompanyID,
            Shipped, Sync, PKLCreated,
            WhIDOri, StatusID, UrgencyStatusID,
            PendingOrderPickingID, AllowPickMoreQty, TotalShipValue,
            PickingByCart, PickingCartID, OrderPickingGroup, Required
        )
        OUTPUT INSERTED.ID
        VALUES (
            1, 1, GETDATE(), ?, ?,
            '', 0, '0',
            0, 'AI', GETDATE(),
            '', '', '',
            0, 0, 0,
            ?, 0, 0,
            0, 0, 0,
            0, 0, ?, 0
        )
        """,
        (
            execution_date,
            req.obs.strip(),
            wh_id,
            order_picking_group,
        ),
    )
    picking_order_id = int(cursor.fetchone()[0] or 0)
    if picking_order_id <= 0:
        raise HTTPException(status_code=500, detail="Nao foi possivel obter o ID da ordem de picking criada")

    created_rows = 0
    total_boxes = 0
    total_allocated = 0.0
    picking_row_number = 1

    for index, line in enumerate(group_lines, start=1):
        allocations = [allocation for allocation in line.allocations if float(allocation.qty or 0) > 0]
        qty_allocated = sum(float(allocation.qty or 0) for allocation in allocations)
        if qty_allocated > float(line.qty_to_separate or 0):
            raise HTTPException(
                status_code=400,
                detail=f"A linha {line.origin_order_id}/{line.origin_order_row} tem mais quantidade em caixas do que a quantidade a separar",
            )
        if not allocations and not line.allow_without_boxes:
            raise HTTPException(
                status_code=400,
                detail=f"A linha {line.origin_order_id}/{line.origin_order_row} precisa de caixas selecionadas ou validacao sem caixas",
            )

        item_id = _safe_text(line.substitute_item_id) or _safe_text(line.item_id)
        item_meta = item_metadata.get(item_id) or {}
        effective_size_id = _effective_size_id(item_meta, line.origin_size_id)
        _ensure_boxes_available(
            cursor,
            wh_id,
            item_id,
            effective_size_id,
            allocations,
        )
        cursor.execute(
            """
            INSERT INTO ClientOrderDetails (
                DocType, OrderID, OrderRow, PartNum, VolNum,
                ItemID, QtyOrd, QtySatisf, QtyPicked,
                QtyVols, Status, ProductionStatus,
                CreationUser, CreationDateTime,
                UnitPrice, TotValue,
                ColorID, QtyProd,
                VariationCountry
            ) VALUES (
                ?, ?, ?, 0, 0,
                ?, ?, 0, ?,
                ?, 1, 'INICIAL',
                'AI', GETDATE(),
                0, 0,
                '', 0,
                ''
            )
            """,
            (
                target["doc_type"],
                order_id,
                index,
                item_id,
                float(line.qty_to_separate or 0),
                qty_allocated,
                len(allocations),
            ),
        )

        item_has_dimensions = bool(item_meta.get("has_dimensions"))
        if item_has_dimensions and _safe_text(line.origin_size_id):
            dim_params = (
                target["doc_type"],
                order_id,
                index,
                _safe_text(line.origin_color_id),
                _safe_text(line.origin_grid_id),
                _safe_text(line.origin_size_id),
                int(line.origin_size_order_num or 0),
            )
            cursor.execute(
                """
                UPDATE ClientOrdersDim
                SET QtyOrd = ?,
                    QtySatisf = 0,
                    QtyPicked = ?,
                    QtyVols = ?,
                    QtyPVol = ?,
                    Status = 1,
                    ActivePickingID = 0
                WHERE DocType = ?
                  AND OrderID = ?
                  AND OrderRow = ?
                  AND PartNum = 0
                  AND ISNULL(ColorID, '') = ?
                  AND ISNULL(GridID, '') = ?
                  AND ISNULL(SizeId, '') = ?
                  AND ISNULL(SizeOrderNum, 0) = ?
                """,
                (
                    float(line.qty_to_separate or 0),
                    qty_allocated,
                    len(allocations),
                    qty_allocated,
                    *dim_params,
                ),
            )
            if max(cursor.rowcount or 0, 0) == 0:
                cursor.execute(
                    """
                    INSERT INTO ClientOrdersDim (
                        DocType, OrderID, OrderRow, PartNum,
                        ColorID, GridID, SizeId, SizeOrderNum,
                        QtyOrd, QtySatisf, QtyPicked,
                        Location, Status, ActivePickingID,
                        CreationUser, CreationDateTime,
                        QtyVols, QtyPVol
                    ) VALUES (
                        ?, ?, ?, 0,
                        ?, ?, ?, ?,
                        ?, 0, ?,
                        '', 1, 0,
                        'AI', GETDATE(),
                        ?, ?
                    )
                    """,
                    (
                        *dim_params,
                        float(line.qty_to_separate or 0),
                        qty_allocated,
                        len(allocations),
                        qty_allocated,
                    ),
                )

        cursor.execute(
            """
            INSERT INTO ClientOrderDetailsOri (
                DocType, OrderID, OrderRow, PartNum, VolNum,
                DocTypeOri, OrderIDOri, OrderRowOri, PartNumOri, VolNumOri,
                QtyOrd, QtyVols, QtyOrdDest
            ) VALUES (
                ?, ?, ?, 0, 0,
                ?, ?, ?, ?, 0,
                ?, ?, ?
            )
            """,
            (
                target["doc_type"],
                order_id,
                index,
                line.origin_doc_type,
                line.origin_order_id,
                line.origin_order_row,
                line.origin_part_num,
                float(line.qty_to_separate or 0),
                len(allocations),
                float(line.qty_to_separate or 0),
            ),
        )

        created_rows += 1
        total_boxes += len(allocations)
        total_allocated += qty_allocated

        unit_id = str(item_meta.get("unit") or "UN")
        version = 0
        picking_rows = _build_picking_rows(
            line,
            wh_id,
            unit_id,
            version,
            location_meta,
            target["doc_type"],
            order_id,
            index,
            effective_size_id,
        )

        for picking_row in picking_rows:
            cursor.execute(
                """
                INSERT INTO OrdersPickingDetails (
                    OrderID, RowNumber, PriorityExec,
                    ItemID, Qty, QtyToPick, QtyPicked, ReservedQty,
                    VolTypeID, QtyVols, QtyVolsPicked, QtyPVolume,
                    UnitID, Lot, LocationIDOri, WhIDOri,
                    EquipIDOri, IsManualOri, LocationIDDest, WhIDDest,
                    EquipIDDest, IsManualDest, AssignedUser,
                    PickingCompleted, DocTypeOri, OrderIDOri, OrderRowOri, PartNumOri,
                    deleted, created_by, created_date, edited_by,
                    DetailObs, Version, SerialNum, VolNum, ColorID, SizeID, Country
                ) VALUES (
                    ?, ?, 0,
                    ?, ?, ?, 0, 0,
                    'CX', ?, 0, 0,
                    ?, '', ?, ?,
                    ?, ?, '', 0,
                    '', 0, '',
                    0, ?, ?, ?, ?,
                    0, 'AI', GETDATE(), '',
                    '', ?, '', ?, ?, ?, ''
                )
                """,
                (
                    picking_order_id,
                    picking_row_number,
                    picking_row["item_id"],
                    picking_row["qty"],
                    picking_row["qty"],
                    picking_row["qty_vols"],
                    picking_row["unit_id"],
                    picking_row["location_id_orig"],
                    picking_row["wh_id_orig"],
                    picking_row["equip_id_orig"],
                    picking_row["is_manual_orig"],
                    picking_row["doc_type_ori"],
                    picking_row["order_id_ori"],
                    picking_row["order_row_ori"],
                    picking_row["part_num_ori"],
                    picking_row["version"],
                    picking_row["vol_num"],
                    picking_row["color_id"],
                    picking_row["size_id"],
                ),
            )
            picking_row_number += 1

    client_order_columns = _table_columns(cursor, "ClientOrders")
    client_order_set: list[str] = []
    if client_order_columns.get("productionstatus"):
        client_order_set.append(f"{client_order_columns['productionstatus']} = 'INICIAL'")
    if client_order_columns.get("pendingorderpickingid"):
        client_order_set.append(f"{client_order_columns['pendingorderpickingid']} = ?")
    if client_order_set:
        params: list[object] = []
        if client_order_columns.get("pendingorderpickingid"):
            params.append(picking_order_id)
        params.extend([target["doc_type"], order_id])
        cursor.execute(
            f"UPDATE ClientOrders SET {', '.join(client_order_set)} WHERE DocType = ? AND OrderID = ?",
            tuple(params),
        )

    header_columns = _table_columns(cursor, "OrdersPicking")
    if header_columns.get("productionstatus"):
        cursor.execute(
            f"UPDATE OrdersPicking SET {header_columns['productionstatus']} = 'INICIAL' WHERE ID = ?",
            (picking_order_id,),
        )
    _touch_separation_order(cursor, picking_order_id)

    return {
        "order_id": order_id,
        "doc_type": target["doc_type"],
        "picking_order_id": picking_order_id,
        "title": target["title"],
        "wh_id_orig": wh_id,
        "total_lines": created_rows,
        "total_qty": group_total_qty,
        "total_boxes": total_boxes,
        "total_allocated_qty": total_allocated,
        "order_picking_group": order_picking_group,
    }


@router.post("/create")
def create_separation_document(req: SeparationCreateRequest):
    if not req.lines:
        raise HTTPException(status_code=400, detail="Seleciona pelo menos uma linha para separar")

    try:
        execution_date = datetime.strptime(req.execution_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data de execucao invalida") from exc

    valid_lines = [line for line in req.lines if float(line.qty_to_separate or 0) > 0]
    if not valid_lines:
        raise HTTPException(status_code=400, detail="Nenhuma linha com quantidade para separar")

    # Cada linha pode trazer o seu proprio armazem de origem (wh_id_orig); quando omitido,
    # cai no armazem unico do pedido (compatibilidade com o formato anterior).
    resolved_wh_by_line: list[tuple["SeparationCreateLine", int]] = []
    for line in valid_lines:
        wh_id = line.wh_id_orig if line.wh_id_orig is not None else req.wh_id_orig
        if wh_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"A linha {line.origin_order_id}/{line.origin_order_row} nao tem armazem de origem definido",
            )
        resolved_wh_by_line.append((line, int(wh_id)))

    groups: dict[int, list["SeparationCreateLine"]] = {}
    for line, wh_id in resolved_wh_by_line:
        groups.setdefault(wh_id, []).append(line)
    is_linked = len(groups) > 1

    with db_cursor() as (cursor, _):
        target = _target_doc_config(cursor)
        if not target["exists"]:
            raise HTTPException(
                status_code=400,
                detail=f"DocType '{target['doc_type']}' nao existe em DocumentConfig. Configure SEPARATION_DOC_TYPE ou crie o documento na base.",
            )
        if not target["active"]:
            raise HTTPException(status_code=400, detail=f"DocType '{target['doc_type']}' esta inativo em DocumentConfig")
        if req.origin_doc_type.strip().upper() not in target["origin_doc_types"]:
            raise HTTPException(status_code=400, detail="Tipo de documento origem nao permitido para este SPA")

        item_ids = list({
            (_safe_text(line.substitute_item_id) or _safe_text(line.item_id))
            for line in valid_lines
            if (_safe_text(line.substitute_item_id) or _safe_text(line.item_id))
        })
        item_metadata = _load_item_metadata(cursor, item_ids)

        separations: list[dict[str, object]] = []
        order_picking_group = ""
        for wh_id, group_lines in groups.items():
            result = _create_one_separation_order(
                cursor,
                target,
                req,
                group_lines,
                wh_id,
                order_picking_group,
                item_metadata,
                execution_date,
            )
            separations.append(result)
            if is_linked and not order_picking_group:
                # A primeira ordem criada da o nome ao grupo; as seguintes ja nascem com ele.
                order_picking_group = f"WHSPLIT-{result['order_id']}"
                result["order_picking_group"] = order_picking_group
                cursor.execute(
                    "UPDATE OrdersPicking SET OrderPickingGroup = ? WHERE ID = ?",
                    (order_picking_group, result["picking_order_id"]),
                )

    return {
        "linked": is_linked,
        "order_picking_group": order_picking_group,
        "separations": separations,
        "execution_date": req.execution_date,
    }


class SeparationOrderUpdateRequest(BaseModel):
    assigned_user: str | None = None
    urgency_status_id: str | None = None


class SeparationOrderCancelRequest(BaseModel):
    cancelled_by: str | None = None
    reason: str | None = None


class CreateDestinationVolumeRequest(BaseModel):
    vol_type_id: str = "CX_STNDRD"


class PickExecutionLineRequest(BaseModel):
    location_origin: str = ""
    vol_num: str = ""
    lot: str = ""
    qty_picked: float = Field(gt=0)
    vol_type_id_dest: str
    vol_num_dest: str


class CheckExecutionBoxRequest(BaseModel):
    vol_num: str


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_to_dict(cursor, row) -> dict:
    names = [column[0] for column in cursor.description]
    return {name: _json_value(value) for name, value in zip(names, row)}


def _table_columns(cursor, table_name: str) -> dict[str, str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        """,
        (table_name,),
    )
    return {str(row[0]).lower(): str(row[0]) for row in cursor.fetchall()}


def _column_expr(columns: dict[str, str], column_name: str, alias: str, fallback_sql: str = "NULL") -> str:
    real_name = columns.get(column_name.lower())
    if not real_name:
        return fallback_sql
    return f"{alias}.[{real_name}]"


def _normalize_status(value: object) -> str:
    return _safe_text(value).upper().replace("Ã", "A").replace("Ç", "C")


STATUS_META = {
    "INICIAL": {"code": "initial", "symbol": ".", "label": "Inicial"},
    "EM SEPARACAO": {"code": "in_progress", "symbol": "~", "label": "Em separacao"},
    "SEPARADA": {"code": "separated", "symbol": "+", "label": "Separada"},
    "CONFERIDA": {"code": "conferenced", "symbol": "#", "label": "Conferida"},
    "ANULADO": {"code": "cancelled", "symbol": "x", "label": "Anulado"},
}


def _status_meta(value: object) -> dict[str, str] | None:
    normalized = _normalize_status(value)
    return STATUS_META.get(normalized)


def _touch_separation_order(cursor, order_picking_id: int) -> None:
    header_columns = _table_columns(cursor, "OrdersPicking")
    header_set: list[str] = []
    if header_columns.get("edited_by"):
        header_set.append(f"{header_columns['edited_by']} = 'AI'")
    if header_columns.get("edited_date"):
        header_set.append(f"{header_columns['edited_date']} = GETDATE()")
    if header_set:
        cursor.execute(
            f"UPDATE OrdersPicking SET {', '.join(header_set)} WHERE ID = ?",
            (order_picking_id,),
        )

    detail_columns = _table_columns(cursor, "OrdersPickingDetails")
    detail_set: list[str] = []
    if detail_columns.get("edited_by"):
        detail_set.append(f"{detail_columns['edited_by']} = 'AI'")
    if detail_columns.get("edited_date"):
        detail_set.append(f"{detail_columns['edited_date']} = GETDATE()")
    if detail_set:
        cursor.execute(
            f"UPDATE OrdersPickingDetails SET {', '.join(detail_set)} WHERE OrderID = ?",
            (order_picking_id,),
        )


def _sync_production_status(cursor, order_picking_id: int) -> str:
    cursor.execute(
        """
        SELECT
            SUM(CASE WHEN ISNULL(opd.deleted, 0) = 0 THEN 1 ELSE 0 END) AS TotalLines,
            SUM(CASE
                WHEN ISNULL(opd.deleted, 0) = 0
                 AND (
                    ISNULL(opd.PickingCompleted, 0) = 1
                    OR ISNULL(opd.QtyPicked, 0) >= CASE
                        WHEN ISNULL(opd.QtyToPick, 0) > 0 THEN ISNULL(opd.QtyToPick, 0)
                        ELSE ISNULL(opd.Qty, 0)
                    END
                 )
                THEN 1 ELSE 0
            END) AS CompletedLines,
            SUM(CASE
                WHEN ISNULL(opd.deleted, 0) = 0
                 AND ISNULL(opd.QtyPicked, 0) > 0
                THEN 1 ELSE 0
            END) AS StartedLines
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        WHERE opd.OrderID = ?
        """,
        (order_picking_id,),
    )
    row = cursor.fetchone()
    total_lines = int((row[0] if row and row[0] is not None else 0) or 0)
    completed_lines = int((row[1] if row and row[1] is not None else 0) or 0)
    started_lines = int((row[2] if row and row[2] is not None else 0) or 0)

    if total_lines > 0 and completed_lines >= total_lines:
        new_status = "SEPARADA"
    elif started_lines > 0:
        new_status = "EM SEPARACAO"
    else:
        new_status = "INICIAL"

    header_columns = _table_columns(cursor, "OrdersPicking")
    production_column = header_columns.get("productionstatus")
    if production_column:
        cursor.execute(
            f"UPDATE OrdersPicking SET {production_column} = ? WHERE ID = ?",
            (new_status, order_picking_id),
        )

    cursor.execute(
        """
        SELECT DISTINCT ISNULL(opd.DocTypeOri, ''), ISNULL(opd.OrderIDOri, 0)
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        WHERE opd.OrderID = ?
          AND ISNULL(opd.deleted, 0) = 0
          AND ISNULL(opd.DocTypeOri, '') <> ''
          AND ISNULL(opd.OrderIDOri, 0) > 0
        """,
        (order_picking_id,),
    )
    origin_orders = [(str(doc_type).strip(), int(order_id)) for doc_type, order_id in cursor.fetchall()]
    client_columns = _table_columns(cursor, "ClientOrders")
    client_production_column = client_columns.get("productionstatus")
    if client_production_column:
        for doc_type, order_id in origin_orders:
            cursor.execute(
                f"UPDATE ClientOrders SET {client_production_column} = ? WHERE DocType = ? AND OrderID = ?",
                (new_status, doc_type, order_id),
            )

    return new_status


def _parse_optional_date(value: str | None, field_name: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} deve estar no formato YYYY-MM-DD") from exc


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _to_int(value: object) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _nullable_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _progress_percentage(total_rows: int, completed_rows: int, total_qty: float, picked_qty: float, state_code: str) -> float:
    if state_code == "cancelled":
        return 0.0
    if total_rows > 0:
        return round(min(max((completed_rows / total_rows) * 100, 0), 100), 2)
    if total_qty > 0:
        return round(min(max((picked_qty / total_qty) * 100, 0), 100), 2)
    return 100.0 if state_code == "completed" else 0.0


def _header_state(
    deleted: int,
    production_status: str,
    has_resume: int,
    total_rows: int,
    completed_rows: int,
    total_qty: float,
    picked_qty: float,
) -> dict[str, str]:
    normalized = _normalize_status(production_status)
    mapped = _status_meta(normalized)
    if deleted == 1 or normalized == "ANULADO":
        return STATUS_META["ANULADO"]
    if mapped:
        return mapped
    if has_resume == 0:
        return STATUS_META["INICIAL"]
    if completed_rows <= 0 and picked_qty <= 0:
        return STATUS_META["INICIAL"]
    if total_rows > 0 and completed_rows >= total_rows:
        return STATUS_META["SEPARADA"]
    if total_qty > 0 and picked_qty >= total_qty:
        return STATUS_META["SEPARADA"]
    if completed_rows < total_rows:
        return STATUS_META["EM SEPARACAO"]
    return STATUS_META["INICIAL"]


def _line_state(deleted: int, picking_completed: int, qty_to_pick: float, qty_picked: float) -> dict[str, str]:
    if deleted == 1:
        return STATUS_META["ANULADO"]
    if picking_completed == 1 or qty_to_pick <= 0 or qty_picked >= qty_to_pick:
        return STATUS_META["SEPARADA"]
    if qty_picked > 0:
        return STATUS_META["EM SEPARACAO"]
    return STATUS_META["INICIAL"]


def _fetch_related_documents(cursor, order_picking_id: int) -> list[dict[str, object]]:
    cursor.execute(
        """
        SELECT DISTINCT
            opd.DocTypeOri AS SeparationDocType,
            opd.OrderIDOri AS SeparationOrderID,
            codo.DocTypeOri AS SourceDocType,
            codo.OrderIDOri AS SourceOrderID
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
          ON codo.DocType = opd.DocTypeOri
         AND codo.OrderID = opd.OrderIDOri
         AND codo.OrderRow = opd.OrderRowOri
        WHERE opd.OrderID = ?
        ORDER BY codo.DocTypeOri, codo.OrderIDOri
        """,
        (order_picking_id,),
    )
    return [
        {
            "separation_doc_type": str(row[0] or "").strip(),
            "separation_order_id": int(row[1] or 0),
            "source_doc_type": str(row[2] or "").strip(),
            "source_order_id": int(row[3] or 0),
        }
        for row in cursor.fetchall()
        if row[0] is not None and row[1] is not None
    ]


def _resolve_context(cursor, order_picking_id: int) -> dict[str, object]:
    cursor.execute("SELECT OrderPickingGroup FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
    wave_row = cursor.fetchone()
    wave_id = str(wave_row[0] or "").strip() if wave_row and wave_row[0] is not None else ""
    related = _fetch_related_documents(cursor, order_picking_id)
    manual_docs = [doc for doc in related if doc["separation_doc_type"].upper() != "PKL"]
    if manual_docs:
        primary = manual_docs[0]
        return {
            "Source": "MANUAL_SSCP",
            "SourceLabel": "Manual SEP/SSCP",
            "RelatedDocType": primary["separation_doc_type"],
            "RelatedOrderID": primary["separation_order_id"],
            "WaveID": wave_id or None,
        }
    pkl = next((doc for doc in related if doc["separation_doc_type"].upper() == "PKL"), None)
    if wave_id or pkl:
        return {
            "Source": "BY_PTL",
            "SourceLabel": "Integracao BY-PTL",
            "RelatedDocType": pkl["separation_doc_type"] if pkl else None,
            "RelatedOrderID": pkl["separation_order_id"] if pkl else None,
            "WaveID": wave_id or None,
        }
    return {
        "Source": "UNKNOWN",
        "SourceLabel": "Origem desconhecida",
        "RelatedDocType": None,
        "RelatedOrderID": None,
        "WaveID": None,
    }


def _summary_from_row(cursor, row_dict: dict[str, object]) -> dict[str, object]:
    total_qty = _to_float(row_dict.get("TotalQuantityToPick"))
    picked_qty = _to_float(row_dict.get("TotalQuantityPicked"))
    state = _header_state(
        deleted=_to_int(row_dict.get("Deleted")),
        production_status=str(row_dict.get("ProductionStatus") or ""),
        has_resume=_to_int(row_dict.get("HasResume")),
        total_rows=_to_int(row_dict.get("TotalRows") or row_dict.get("TotalLines")),
        completed_rows=_to_int(row_dict.get("CompletedRows")),
        total_qty=total_qty,
        picked_qty=picked_qty,
    )
    total_rows = _to_int(row_dict.get("TotalRows") or row_dict.get("TotalLines"))
    completed_rows = _to_int(row_dict.get("CompletedRows"))
    context = _resolve_context(cursor, _to_int(row_dict.get("OrderPickingID")))
    return {
        "OrderPickingID": _to_int(row_dict.get("OrderPickingID")),
        "WaveID": context["WaveID"],
        "Source": context["Source"],
        "SourceLabel": context["SourceLabel"],
        "RelatedDocType": context["RelatedDocType"],
        "RelatedOrderID": context["RelatedOrderID"],
        "StateCode": state["code"],
        "StateSymbol": state["symbol"],
        "StateLabel": state["label"],
        "CreationDate": row_dict.get("CreationDate"),
        "RequestedExecutionDate": row_dict.get("RequestedExecutionDate"),
        "CustomerID": row_dict.get("CustomerID"),
        "CustomerName": row_dict.get("CustomerName"),
        "AssignedUser": row_dict.get("AssignedUser"),
        "UrgencyStatusID": row_dict.get("UrgencyStatusID"),
        "ProductionStatus": row_dict.get("ProductionStatus"),
        "TotalLines": _to_int(row_dict.get("TotalLines")),
        "TotalBoxes": _to_int(row_dict.get("TotalBoxes")),
        "TotalQuantityToPick": total_qty,
        "TotalQuantityPicked": picked_qty,
        "CompletedRows": completed_rows,
        "ProgressPercentage": _progress_percentage(total_rows, completed_rows, total_qty, picked_qty, state["code"]),
    }


@router.get("/execution/document-types")
def execution_document_types():
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT DocType, ISNULL(Title, DocType) AS Title
            FROM DocumentConfig WITH (NOLOCK)
            WHERE DocTypeArea = 'PICKING'
            ORDER BY ISNULL(Title, DocType), DocType
            """
        )
        return [
            {"doc_type": str(row[0] or "").strip(), "title": str((row[1] or row[0] or "")).strip()}
            for row in cursor.fetchall()
            if row[0] is not None
        ]


@router.get("/execution/orders")
def list_separation_execution_orders(doc_types: list[str] | None = Query(default=None, alias="doc_type")):
    clean_doc_types = [doc_type.strip().upper() for doc_type in (doc_types or []) if doc_type and doc_type.strip()]

    with db_cursor() as (cursor, _):
        order_columns = _table_columns(cursor, "OrdersPicking")
        urgency_columns = _table_columns(cursor, "UrgencyStatus")
        production_status_expr = _column_expr(order_columns, "ProductionStatus", "op", "''")
        edited_date_expr = _column_expr(order_columns, "Edited_Date", "op", "op.[Date]")
        urgency_id_col = urgency_columns.get("urgencystatusid") or urgency_columns.get("id") or urgency_columns.get("code")
        urgency_order_col = urgency_columns.get("orderindex") or urgency_columns.get("sortorder") or urgency_columns.get("displayorder")
        urgency_join = ""
        urgency_order_expr = "0"
        if urgency_id_col:
            urgency_join = f"""
            LEFT JOIN UrgencyStatus us WITH (NOLOCK)
              ON CAST(us.[{urgency_id_col}] AS varchar(50)) = CAST(op.UrgencyStatusID AS varchar(50))
            """
            if urgency_order_col:
                urgency_order_expr = f"ISNULL(us.[{urgency_order_col}], 0)"

        params: list[object] = []
        doc_type_filter = ""
        if clean_doc_types:
            placeholders = ",".join("?" for _ in clean_doc_types)
            doc_type_filter = f"""
              AND EXISTS (
                  SELECT 1
                  FROM OrdersPickingDetails opd_filter WITH (NOLOCK)
                  WHERE opd_filter.OrderID = op.ID
                    AND ISNULL(opd_filter.deleted, 0) = 0
                    AND opd_filter.DocTypeOri IN ({placeholders})
              )
            """
            params.extend(clean_doc_types)

        cursor.execute(
            f"""
            ;WITH DetailAgg AS (
                SELECT
                    opd.OrderID,
                    COUNT(*) AS TotalLines,
                    SUM(CASE
                        WHEN ISNULL(opd.PickingCompleted, 0) = 1
                          OR ISNULL(opd.QtyPicked, 0) >= CASE
                              WHEN ISNULL(opd.QtyToPick, 0) > 0 THEN ISNULL(opd.QtyToPick, 0)
                              ELSE ISNULL(opd.Qty, 0)
                          END
                        THEN 1 ELSE 0
                    END) AS CompletedLines,
                    SUM(ISNULL(opd.Qty, 0)) AS TotalQuantityToPick,
                    SUM(ISNULL(opd.QtyPicked, 0)) AS TotalQuantityPicked
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                WHERE ISNULL(opd.deleted, 0) = 0
                GROUP BY opd.OrderID
            ),
            DocTypeAgg AS (
                SELECT
                    opd.OrderID,
                    MAX(ISNULL(opd.DocTypeOri, '')) AS SeparationDocType,
                    MAX(dtc.IsPicking) AS HasPickingDocType,
                    MAX(1 - dtc.IsPicking) AS HasNonPickingDocType
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                CROSS APPLY (
                    SELECT CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM DocumentConfig dc_pick WITH (NOLOCK)
                            WHERE dc_pick.DocType = opd.DocTypeOri
                              AND dc_pick.DocTypeArea = 'PICKING'
                        ) THEN 1 ELSE 0
                    END AS IsPicking
                ) dtc
                WHERE ISNULL(opd.deleted, 0) = 0
                GROUP BY opd.OrderID
            ),
            ClientAgg AS (
                SELECT
                    opd.OrderID,
                    MAX(co.ClientID) AS CustomerID,
                    MAX(ISNULL(bp.PartnerAbrev, bp.PartnerName)) AS CustomerName,
                    MAX(co.OrderDatePrev) AS PlannedDate
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                JOIN ClientOrders co WITH (NOLOCK)
                  ON co.DocType = opd.DocTypeOri
                 AND co.OrderID = opd.OrderIDOri
                JOIN DocumentConfig dc WITH (NOLOCK)
                  ON dc.DocType = co.DocType
                LEFT JOIN BusinessPartners bp WITH (NOLOCK)
                  ON bp.PartnerType = dc.PartnerType
                 AND bp.PartnerID = co.ClientID
                WHERE ISNULL(opd.deleted, 0) = 0
                GROUP BY opd.OrderID
            )
            SELECT
                op.ID AS OrderPickingID,
                op.Date AS CreationDate,
                op.DueDate AS RequestedExecutionDate,
                op.AssignedUser,
                op.UrgencyStatusID,
                ISNULL(op.Obs, '') AS Observation,
                ISNULL({production_status_expr}, '') AS ProductionStatus,
                ISNULL(op.deleted, 0) AS Deleted,
                ISNULL(ca.CustomerID, '') AS CustomerID,
                ISNULL(ca.CustomerName, '') AS CustomerName,
                ISNULL(ca.PlannedDate, op.DueDate) AS PlannedDate,
                ISNULL(da.TotalLines, 0) AS TotalLines,
                ISNULL(da.CompletedLines, 0) AS CompletedLines,
                ISNULL(da.TotalQuantityToPick, 0) AS TotalQuantityToPick,
                ISNULL(da.TotalQuantityPicked, 0) AS TotalQuantityPicked,
                ISNULL(dta.SeparationDocType, '') AS SeparationDocType,
                {urgency_order_expr} AS UrgencyOrder,
                {edited_date_expr} AS EditedDate
            FROM OrdersPicking op WITH (NOLOCK)
            JOIN DetailAgg da ON da.OrderID = op.ID
            LEFT JOIN DocTypeAgg dta ON dta.OrderID = op.ID
            LEFT JOIN ClientAgg ca ON ca.OrderID = op.ID
            {urgency_join}
            WHERE ISNULL(op.SeparationOrder, 0) = 1
              AND ISNULL(op.deleted, 0) = 0
              AND ISNULL(dta.HasPickingDocType, 0) = 1
              AND ISNULL(dta.HasNonPickingDocType, 0) = 0
              {doc_type_filter}
            ORDER BY op.ID DESC
            """,
            tuple(params),
        )
        rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    items: list[dict[str, object]] = []
    today_value = date.today().isoformat()
    for row in rows:
        state = _header_state(
            deleted=_to_int(row.get("Deleted")),
            production_status=row.get("ProductionStatus"),
            has_resume=1,
            total_rows=_to_int(row.get("TotalLines")),
            completed_rows=_to_int(row.get("CompletedLines")),
            total_qty=_to_float(row.get("TotalQuantityToPick")),
            picked_qty=_to_float(row.get("TotalQuantityPicked")),
        )
        if state["code"] not in {"initial", "in_progress", "separated", "conferenced"}:
            continue
        edited_date = str(row.get("EditedDate") or "")[:10]
        if state["code"] == "conferenced" and edited_date != today_value:
            continue
        context = {}
        with db_cursor() as (cursor, _):
            context = _resolve_context(cursor, _to_int(row.get("OrderPickingID")))
        state_priority = {
            "in_progress": 0,
            "initial": 1,
            "separated": 2,
            "conferenced": 3,
        }.get(state["code"], 9)
        items.append(
            {
                "OrderPickingID": _to_int(row.get("OrderPickingID")),
                "RelatedDocType": context.get("RelatedDocType"),
                "RelatedOrderID": context.get("RelatedOrderID"),
                "SourceLabel": context.get("SourceLabel"),
                "LinkGroup": context.get("WaveID"),
                "StateCode": state["code"],
                "StateSymbol": state["symbol"],
                "StateLabel": state["label"],
                "ProductionStatus": row.get("ProductionStatus"),
                "Observation": row.get("Observation"),
                "CreationDate": row.get("CreationDate"),
                "RequestedExecutionDate": row.get("RequestedExecutionDate"),
                "PlannedDate": row.get("PlannedDate"),
                "CustomerID": row.get("CustomerID"),
                "CustomerIDShort": str(row.get("CustomerID") or "")[:5],
                "CustomerName": row.get("CustomerName"),
                "AssignedUser": row.get("AssignedUser"),
                "UrgencyStatusID": row.get("UrgencyStatusID"),
                "UrgencyOrder": _to_int(row.get("UrgencyOrder")),
                "TotalLines": _to_int(row.get("TotalLines")),
                "CompletedLines": _to_int(row.get("CompletedLines")),
                "TotalQuantityToPick": _to_float(row.get("TotalQuantityToPick")),
                "TotalQuantityPicked": _to_float(row.get("TotalQuantityPicked")),
                "CanSeparate": state["code"] in {"initial", "in_progress"},
                "CanCheck": state["code"] == "separated",
                "StatePriority": state_priority,
            }
        )

    items.sort(
        key=lambda row: (
            row["StatePriority"],
            -_to_int(row.get("UrgencyOrder")),
            str(row.get("PlannedDate") or ""),
            -_to_int(row.get("RelatedOrderID")),
            -_to_int(row.get("OrderPickingID")),
        )
    )
    for row in items:
        row.pop("StatePriority", None)

    return {"items": items, "count": len(items)}


@router.get("/execution/parameters")
def execution_parameters():
    param_ids = [
        "ALLOW_TO_PICK_MORE_QTY_THAN_REQUESTED",
        "BOX_AUTO_CREATION",
        "LOCAL_CONFIRM",
        "LOT_CONFIRM",
        "PICKGCONFIRM",
        "PREVENT_PICK_NOTPICK_LOC",
    ]
    defaults = {
        "ALLOW_TO_PICK_MORE_QTY_THAN_REQUESTED": "0",
        "BOX_AUTO_CREATION": "0",
        "LOCAL_CONFIRM": "0",
        "LOT_CONFIRM": "0",
        "PICKGCONFIRM": "NONE",
        "PREVENT_PICK_NOTPICK_LOC": "0",
    }
    values = dict(defaults)

    with db_cursor() as (cursor, _):
        if _has_column(cursor, "ParamValue", "ParamID") and _has_column(cursor, "ParamValue", "ParamValue"):
            placeholders = ",".join("?" for _ in param_ids)
            cursor.execute(
                f"SELECT ParamID, ParamValue FROM ParamValue WITH (NOLOCK) WHERE ParamID IN ({placeholders})",
                tuple(param_ids),
            )
            for row in cursor.fetchall():
                param_id = _safe_text(row[0]).upper()
                if param_id in values:
                    values[param_id] = _safe_text(row[1])

    def _as_bool(value: str) -> bool:
        return value.strip().upper() in ("1", "TRUE", "SIM", "S")

    return {
        "allow_pick_more_qty_than_requested": _as_bool(values["ALLOW_TO_PICK_MORE_QTY_THAN_REQUESTED"]),
        "box_auto_creation": _as_bool(values["BOX_AUTO_CREATION"]),
        "local_confirm": _as_bool(values["LOCAL_CONFIRM"]),
        "lot_confirm": _as_bool(values["LOT_CONFIRM"]),
        "picking_confirm_mode": (values["PICKGCONFIRM"] or "NONE").strip().upper() or "NONE",
        "prevent_pick_notpick_loc": _as_bool(values["PREVENT_PICK_NOTPICK_LOC"]),
    }


def _next_vol_num_for_doc(cursor, vol_doc_cod: str) -> int:
    """Gera o proximo numero de volume/caixa a partir do contador partilhado
    DocumentConfig.DocNumber - o mesmo mecanismo usado na recepcao/packing
    (app/services/packing_creator.py:_next_vol_num), aqui parametrizado pelo
    VolDocCod do tipo de volume escolhido em vez de fixo em 'CX'."""
    year2 = datetime.now().year % 100
    prefix = 900000000 + year2 * 1000000

    cursor.execute("SELECT DocNumber FROM DocumentConfig WHERE DocType = ?", (vol_doc_cod,))
    row = cursor.fetchone()
    if row and row[0]:
        vol_num = int(row[0])
        cursor.execute("UPDATE DocumentConfig SET DocNumber = DocNumber + 1 WHERE DocType = ?", (vol_doc_cod,))
    else:
        vol_num = prefix + 1
        cursor.execute(
            """
            IF NOT EXISTS (SELECT 1 FROM DocumentConfig WHERE DocType = ?)
                INSERT INTO DocumentConfig (
                    DocTypeArea, DocType, DocNumber,
                    SuppliedGroups, SupplyLots, LinkItemidAsComponent,
                    HasComponents, HasOperations, HasLots, HasCutParts,
                    hasRoutes, IsDevolution, ShowOnDocument, ShowOnPosEnc,
                    ShowPosEncByHeaders, SatisfyDocOri, AllowStockMove,
                    AllowCompletedDocOriTransformation, QualityCode,
                    AllowChangeProvider, UsedOnCreditValue, ControlsVies,
                    OnlyAllowApprovedPrices, CanChangePartner,
                    DontAllowToCreateNewDocs, BusinessPartnerRequired,
                    DefaultBusinessPartnerID, TransformationStockMove,
                    UseItemComponentsForTransformation, Active
                ) VALUES (
                    'VOLS', ?, ?,
                    '', 0, 0, 0, 0, 0, 0,
                    0, 0, 1, 1, 0, 0, 0,
                    0, '', 0, 0, 0, 0, 0,
                    0, 0, '', 0, 0, 1
                )
            ELSE
                UPDATE DocumentConfig SET DocNumber = ? WHERE DocType = ?
            """,
            (vol_doc_cod, vol_doc_cod, vol_num + 1, vol_num + 1, vol_doc_cod),
        )
    return vol_num


def _compute_drainable_boxes(cursor, order_picking_id: int, vol_nums: list[str]) -> dict[str, bool]:
    """For each source box (VolNum) referenced by this order's lines, determine whether picking
    everything this order requests from that box would empty it completely - i.e. every item
    currently stocked in the box has enough of this order's own picking quantity to cover it."""
    clean_vol_nums = sorted({str(vol_num).strip() for vol_num in vol_nums if str(vol_num or "").strip()})
    if not clean_vol_nums:
        return {}

    placeholders = ",".join("?" for _ in clean_vol_nums)

    cursor.execute(
        f"""
        SELECT CAST(VolNum AS varchar(50)) AS VolNum, ItemID, SUM(ISNULL(Qty, 0)) AS QtyStock
        FROM Inventory WITH (NOLOCK)
        WHERE ISNULL(Qty, 0) > 0
          AND CAST(VolNum AS varchar(50)) IN ({placeholders})
        GROUP BY CAST(VolNum AS varchar(50)), ItemID
        """,
        tuple(clean_vol_nums),
    )
    box_contents: dict[str, dict[str, float]] = {}
    for vol_num, item_id, qty_stock in cursor.fetchall():
        box_contents.setdefault(str(vol_num).strip(), {})[str(item_id or "").strip()] = float(qty_stock or 0)

    cursor.execute(
        f"""
        SELECT CAST(opd.VolNum AS varchar(50)) AS VolNum, opd.ItemID, SUM(ISNULL(opd.QtyToPick, opd.Qty)) AS QtyToPick
        FROM OrdersPickingDetails opd WITH (NOLOCK)
        WHERE opd.OrderID = ?
          AND ISNULL(opd.deleted, 0) = 0
          AND CAST(opd.VolNum AS varchar(50)) IN ({placeholders})
        GROUP BY CAST(opd.VolNum AS varchar(50)), opd.ItemID
        """,
        (order_picking_id, *clean_vol_nums),
    )
    order_picks: dict[str, dict[str, float]] = {}
    for vol_num, item_id, qty_to_pick in cursor.fetchall():
        order_picks.setdefault(str(vol_num).strip(), {})[str(item_id or "").strip()] = float(qty_to_pick or 0)

    result: dict[str, bool] = {}
    for vol_num in clean_vol_nums:
        contents = box_contents.get(vol_num)
        if not contents:
            result[vol_num] = False
            continue
        picks = order_picks.get(vol_num, {})
        result[vol_num] = all(picks.get(item_id, 0.0) >= qty_stock - 1e-6 for item_id, qty_stock in contents.items())

    return result


@router.get("/execution/{order_picking_id}/detail")
def get_separation_execution_detail(order_picking_id: int):
    with db_cursor() as (cursor, _):
        cursor.execute("SELECT ID FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")

        context = _resolve_context(cursor, order_picking_id)

        wsrl_columns = _table_columns(cursor, "WHSubRoutesLocations")
        wsrl_whid_col = wsrl_columns.get("whid")
        wsrl_loc_col = wsrl_columns.get("locationid")
        wsrl_order_col = wsrl_columns.get("whsubroutelocorder")
        has_wsrl = bool(wsrl_whid_col and wsrl_loc_col and wsrl_order_col)

        wsrl_join = ""
        order_expr = "opd.RowNumber"
        if has_wsrl:
            wsrl_join = f"""
            LEFT JOIN WHSubRoutesLocations wsrl WITH (NOLOCK)
              ON wsrl.[{wsrl_whid_col}] = opd.WhIDOri
             AND wsrl.[{wsrl_loc_col}] = opd.LocationIDOri
            """
            order_expr = f"""
                CASE WHEN EXISTS (
                    SELECT 1 FROM WHSubRoutesLocations wx WITH (NOLOCK) WHERE wx.[{wsrl_whid_col}] = opd.WhIDOri
                ) THEN ISNULL(wsrl.[{wsrl_order_col}], 999999) ELSE opd.RowNumber END,
                opd.RowNumber
            """

        opd_columns = _table_columns(cursor, "OrdersPickingDetails")
        lot_expr = _column_expr(opd_columns, "Lot", "opd", "''")

        loc_columns = _table_columns(cursor, "Locations")
        loc_status_col = loc_columns.get("statusid")
        status_expr = f"loc.[{loc_status_col}]" if loc_status_col else "1"

        cursor.execute(
            f"""
            SELECT
                opd.RowNumber,
                opd.ItemID,
                ISNULL(im.ItemDesc, opd.ItemID) AS ItemDesc,
                ISNULL(im.Lots, 0) AS HasLots,
                ISNULL(im.VolNums, 0) AS HasVolumes,
                ISNULL(opd.LocationIDOri, '') AS LocationOrigin,
                ISNULL(opd.WhIDOri, 0) AS WhIDOri,
                ISNULL(opd.VolTypeID, '') AS VolTypeID,
                CAST(opd.VolNum AS varchar(50)) AS VolNum,
                ISNULL(opd.QtyToPick, opd.Qty) AS QtyToPick,
                ISNULL(opd.QtyPicked, 0) AS QtyPicked,
                ISNULL(opd.EquipIDOri, '') AS EquipIDOri,
                ISNULL(opd.deleted, 0) AS Deleted,
                ISNULL(opd.PickingCompleted, 0) AS PickingCompleted,
                ISNULL({lot_expr}, '') AS Lot,
                ISNULL(opd.VolTypeIdDest, '') AS VolTypeIdDest,
                ISNULL(CAST(opd.VolNumDest AS varchar(50)), '') AS VolNumDest,
                ISNULL({status_expr}, 1) AS LocationStatusID,
                (
                    SELECT TOP 1 inv.LocationID
                    FROM Inventory inv WITH (NOLOCK)
                    WHERE inv.ItemID = opd.ItemID
                      AND inv.WHID = opd.WhIDOri
                      AND ISNULL(inv.Qty, 0) > 0
                    ORDER BY inv.LocationID
                ) AS SuggestedLocation
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            LEFT JOIN ItemMaster im WITH (NOLOCK)
              ON im.ItemID = opd.ItemID
            LEFT JOIN Locations loc WITH (NOLOCK)
              ON loc.WHID = opd.WhIDOri
             AND CONVERT(varchar(15), loc.LocationID) = CONVERT(varchar(15), opd.LocationIDOri)
            {wsrl_join}
            WHERE opd.OrderID = ?
              AND ISNULL(opd.deleted, 0) = 0
            ORDER BY {order_expr}
            """,
            (order_picking_id,),
        )
        rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

        drainable_boxes = _compute_drainable_boxes(cursor, order_picking_id, [row.get("VolNum") for row in rows])

        voltype_columns = _table_columns(cursor, "VolType")
        voltype_id_col = voltype_columns.get("voltypeid")
        voltype_doc_col = voltype_columns.get("voldoccod")
        vol_type_options: list[dict[str, str]] = []
        if voltype_id_col and voltype_doc_col:
            cursor.execute(
                f"SELECT [{voltype_id_col}], [{voltype_doc_col}] FROM VolType WITH (NOLOCK) ORDER BY [{voltype_doc_col}]"
            )
            vol_type_options = [
                {"vol_type_id": _safe_text(row[0]), "vol_doc_cod": _safe_text(row[1])}
                for row in cursor.fetchall()
                if row[0] is not None
            ]

        cursor.execute(
            """
            SELECT CAST(VolNum AS varchar(50)) AS VolNum, VolTypeID, VolDocCod
            FROM VolMaster WITH (NOLOCK)
            WHERE ParentDocType = 'SSCP' AND ParentOrderID = ?
            ORDER BY VolNum
            """,
            (order_picking_id,),
        )
        destination_volumes = [
            {
                "vol_num": _safe_text(row[0]),
                "vol_type_id": _safe_text(row[1]),
                "vol_doc_cod": _safe_text(row[2]),
                "label": _safe_text(row[0]),
            }
            for row in cursor.fetchall()
        ]

    default_vol_type_id = (_safe_text(rows[0].get("VolTypeID")) if rows else "") or "CX_STNDRD"

    lines: list[dict[str, object]] = []
    for row in rows:
        location_origin = _safe_text(row.get("LocationOrigin"))
        location_is_suggested = False
        if not location_origin:
            suggested = row.get("SuggestedLocation")
            if suggested:
                location_origin = _safe_text(suggested)
                location_is_suggested = True
        location_status_id = _to_int(row.get("LocationStatusID"))
        vol_num = _safe_text(row.get("VolNum"))
        lines.append({
            "row_number": _to_int(row.get("RowNumber")),
            "item_id": row.get("ItemID") or "",
            "item_desc": row.get("ItemDesc") or "",
            "has_lots": bool(_to_int(row.get("HasLots"))),
            "has_volumes": bool(_to_int(row.get("HasVolumes"))),
            "location_origin": location_origin,
            "location_is_suggested": location_is_suggested,
            "location_status_id": location_status_id,
            "location_blocked": location_status_id != 1,
            "wh_id_origin": _to_int(row.get("WhIDOri")),
            "vol_type_id": _safe_text(row.get("VolTypeID")) or default_vol_type_id,
            "vol_num": row.get("VolNum") or "",
            "qty_to_pick": _to_float(row.get("QtyToPick")),
            "qty_picked": _to_float(row.get("QtyPicked")),
            "equip_id_origin": row.get("EquipIDOri") or "",
            "picking_completed": bool(_to_int(row.get("PickingCompleted"))),
            "lot": row.get("Lot") or "",
            "vol_type_id_dest": row.get("VolTypeIdDest") or "",
            "vol_num_dest": row.get("VolNumDest") or "",
            "box_fully_drainable": bool(vol_num) and drainable_boxes.get(vol_num, False),
        })

    return {
        "order_picking_id": order_picking_id,
        "related_doc_type": context.get("RelatedDocType"),
        "related_order_id": context.get("RelatedOrderID"),
        "source_label": context.get("SourceLabel"),
        "vol_type_options": vol_type_options,
        "default_vol_type_id": default_vol_type_id,
        "destination_volumes": destination_volumes,
        "lines": lines,
    }


@router.post("/execution/{order_picking_id}/volumes")
def create_execution_destination_volume(order_picking_id: int, payload: CreateDestinationVolumeRequest):
    with db_cursor() as (cursor, _):
        cursor.execute("SELECT ID FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")

        vol_type_id = _safe_text(payload.vol_type_id) or "CX_STNDRD"
        cursor.execute("SELECT VolDocCod FROM VolType WITH (NOLOCK) WHERE VolTypeID = ?", (vol_type_id,))
        vol_type_row = cursor.fetchone()
        vol_doc_cod = _safe_text(vol_type_row[0]) if vol_type_row and vol_type_row[0] else "CX"

        vol_num = _next_vol_num_for_doc(cursor, vol_doc_cod)

        cursor.execute(
            """
            INSERT INTO VolMaster (
                VolDocCod, VolNum, VolTypeID,
                VolWeight, VolLenght, VolHeight, VolWidht,
                VolArtWeight, NumVolOrder, NumVolOrderLine, VolVolume,
                ParentDocType, ParentOrderID, ParentOrderRow,
                VolStatus, CreationDate, VolReady, VolVerified, CreationUser
            ) VALUES (
                ?, ?, ?,
                0, 0, 0, 0,
                0, 0, 0, 0,
                'SSCP', ?, 0,
                'INICIAL', GETDATE(), 1, 0, 'AI'
            )
            """,
            (vol_doc_cod, vol_num, vol_type_id, order_picking_id),
        )

    return {
        "vol_num": str(vol_num),
        "vol_type_id": vol_type_id,
        "vol_doc_cod": vol_doc_cod,
        "label": str(vol_num),
    }


@router.post("/execution/{order_picking_id}/lines/{row_number}/check-box")
def check_execution_box(order_picking_id: int, row_number: int, payload: CheckExecutionBoxRequest):
    vol_num = _safe_text(payload.vol_num)
    if not vol_num:
        raise HTTPException(status_code=400, detail="Numero de caixa obrigatorio")

    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT ItemID, ISNULL(SizeID, ''), ISNULL(WhIDOri, 0), ISNULL(QtyToPick, Qty), ISNULL(QtyPicked, 0)
            FROM OrdersPickingDetails WITH (NOLOCK)
            WHERE OrderID = ? AND RowNumber = ? AND ISNULL(deleted, 0) = 0
            """,
            (order_picking_id, row_number),
        )
        line_row = cursor.fetchone()
        if line_row is None:
            raise HTTPException(status_code=404, detail="Linha de separacao nao encontrada")
        item_id, size_id, wh_id, qty_to_pick, qty_picked = line_row
        remaining_qty = max(0.0, float(qty_to_pick or 0) - float(qty_picked or 0))

        available_qty = _box_available_qty(
            cursor, int(wh_id or 0), item_id, size_id, vol_num,
            exclude_order_id=order_picking_id, exclude_row_number=row_number,
        )

    if available_qty <= 0:
        return {
            "valid": False,
            "available_qty": 0.0,
            "remaining_qty": remaining_qty,
            "message": f"A caixa {vol_num} nao tem stock deste artigo",
        }
    return {
        "valid": True,
        "available_qty": available_qty,
        "remaining_qty": remaining_qty,
        "message": None,
    }


@router.post("/execution/{order_picking_id}/lines/{row_number}/pick")
def pick_execution_line(order_picking_id: int, row_number: int, payload: PickExecutionLineRequest):
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT ItemID, ColorID, SizeID, Country, ISNULL(QtyToPick, Qty), ISNULL(QtyPicked, 0), ISNULL(WhIDOri, 0)
            FROM OrdersPickingDetails WITH (NOLOCK)
            WHERE OrderID = ? AND RowNumber = ? AND ISNULL(deleted, 0) = 0
            """,
            (order_picking_id, row_number),
        )
        line_row = cursor.fetchone()
        if line_row is None:
            raise HTTPException(status_code=404, detail="Linha de separacao nao encontrada")
        item_id, color_id, size_id, country, qty_to_pick, qty_picked_before, wh_id_orig = line_row
        qty_to_pick = float(qty_to_pick or 0)
        qty_picked_before = float(qty_picked_before or 0)

        vol_num_dest = _safe_text(payload.vol_num_dest)
        vol_type_id_dest = _safe_text(payload.vol_type_id_dest)
        if not vol_num_dest or not vol_type_id_dest:
            raise HTTPException(status_code=400, detail="Volume destino obrigatorio para separar a linha")

        origin_vol_num = _safe_text(payload.vol_num)
        if origin_vol_num:
            available_qty = _box_available_qty(
                cursor, int(wh_id_orig or 0), item_id, size_id, origin_vol_num,
                exclude_order_id=order_picking_id, exclude_row_number=row_number,
            )
            if available_qty <= 0:
                raise HTTPException(status_code=400, detail=f"A caixa {origin_vol_num} nao tem stock deste artigo")
            if payload.qty_picked > available_qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"A caixa {origin_vol_num} so tem {available_qty:g} unidades disponiveis deste artigo",
                )

        qty_picked_total = qty_picked_before + payload.qty_picked
        picking_completed = qty_picked_total >= qty_to_pick

        cursor.execute("SELECT VolDocCod FROM VolMaster WITH (NOLOCK) WHERE VolNum = ?", (vol_num_dest,))
        vol_row = cursor.fetchone()
        vol_doc_cod = _safe_text(vol_row[0]) if vol_row and vol_row[0] else "CX"

        cursor.execute(
            """
            UPDATE OrdersPickingDetails
            SET QtyPicked = ?,
                PickingCompleted = ?,
                LocationIDOri = CASE WHEN ? <> '' THEN ? ELSE LocationIDOri END,
                VolNum = CASE WHEN ? <> '' THEN ? ELSE VolNum END,
                Lot = CASE WHEN ? <> '' THEN ? ELSE Lot END,
                VolTypeIdDest = ?,
                VolNumDest = ?,
                PickingStartDate = ISNULL(PickingStartDate, GETDATE()),
                PickingCompletedDate = CASE WHEN ? = 1 THEN GETDATE() ELSE PickingCompletedDate END,
                edited_by = 'AI',
                edited_date = GETDATE()
            WHERE OrderID = ? AND RowNumber = ?
            """,
            (
                qty_picked_total,
                1 if picking_completed else 0,
                payload.location_origin, payload.location_origin,
                payload.vol_num, payload.vol_num,
                payload.lot, payload.lot,
                vol_type_id_dest,
                vol_num_dest,
                1 if picking_completed else 0,
                order_picking_id, row_number,
            ),
        )

        cursor.execute(
            """
            SELECT VolItemNumber FROM VolItem WITH (NOLOCK)
            WHERE VolDocCod = ? AND VolNum = ? AND ParentDocType = 'SSCP'
              AND ParentOrderID = ? AND ParentOrderRow = ?
            """,
            (vol_doc_cod, vol_num_dest, order_picking_id, row_number),
        )
        existing_item = cursor.fetchone()
        if existing_item:
            cursor.execute(
                """
                UPDATE VolItem
                SET ItemQty = ItemQty + ?, ItemQtyIni = ItemQtyIni + ?, Lot = ?
                WHERE VolDocCod = ? AND VolNum = ? AND VolItemNumber = ?
                """,
                (payload.qty_picked, payload.qty_picked, payload.lot, vol_doc_cod, vol_num_dest, existing_item[0]),
            )
        else:
            cursor.execute(
                "SELECT ISNULL(MAX(VolItemNumber), 0) FROM VolItem WITH (NOLOCK) WHERE VolDocCod = ? AND VolNum = ?",
                (vol_doc_cod, vol_num_dest),
            )
            next_item_number = int(cursor.fetchone()[0] or 0) + 1
            cursor.execute(
                """
                INSERT INTO VolItem (
                    VolDocCod, VolNum, VolItemNumber,
                    ItemID, ItemQty, ItemQtyIni,
                    ItemWeight, ItemWidth, ItemHeight, ItemLength, ItemVolume,
                    ParentDocType, ParentOrderID, ParentOrderRow,
                    ColorID, GridID, SizeId, VariationCountry, Lot,
                    CreationDate, CreationUser
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    0, 0, 0, 0, 0,
                    'SSCP', ?, ?,
                    ?, '', ?, ?, ?,
                    GETDATE(), 'AI'
                )
                """,
                (
                    vol_doc_cod, vol_num_dest, next_item_number,
                    item_id, payload.qty_picked, payload.qty_picked,
                    order_picking_id, row_number,
                    color_id or "", size_id or "", country or "", payload.lot or "",
                ),
            )

        _sync_production_status(cursor, order_picking_id)

    return {
        "row_number": row_number,
        "qty_picked": payload.qty_picked,
        "qty_picked_total": qty_picked_total,
        "remaining_qty": max(0.0, qty_to_pick - qty_picked_total),
        "picking_completed": picking_completed,
        "vol_num_dest": vol_num_dest,
        "vol_type_id_dest": vol_type_id_dest,
    }


@router.post("/execution/{order_picking_id}/lines/{row_number}/unpick")
def unpick_execution_line(order_picking_id: int, row_number: int):
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT VolNumDest FROM OrdersPickingDetails WITH (NOLOCK)
            WHERE OrderID = ? AND RowNumber = ? AND ISNULL(deleted, 0) = 0
            """,
            (order_picking_id, row_number),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Linha de separacao nao encontrada")
        vol_num_dest = _safe_text(row[0])

        if vol_num_dest:
            cursor.execute("SELECT VolDocCod FROM VolMaster WITH (NOLOCK) WHERE VolNum = ?", (vol_num_dest,))
            vol_row = cursor.fetchone()
            vol_doc_cod = _safe_text(vol_row[0]) if vol_row and vol_row[0] else None
            if vol_doc_cod:
                cursor.execute(
                    """
                    DELETE FROM VolItem
                    WHERE VolDocCod = ? AND VolNum = ? AND ParentDocType = 'SSCP'
                      AND ParentOrderID = ? AND ParentOrderRow = ?
                    """,
                    (vol_doc_cod, vol_num_dest, order_picking_id, row_number),
                )

        cursor.execute(
            """
            UPDATE OrdersPickingDetails
            SET QtyPicked = 0,
                PickingCompleted = 0,
                VolTypeIdDest = NULL,
                VolNumDest = NULL,
                PickingStartDate = NULL,
                PickingCompletedDate = NULL,
                edited_by = 'AI',
                edited_date = GETDATE()
            WHERE OrderID = ? AND RowNumber = ?
            """,
            (order_picking_id, row_number),
        )

        _sync_production_status(cursor, order_picking_id)

    return {"row_number": row_number, "reset": True}


@router.get("/orders-picking")
def list_separation_orders(
    from_date: str | None = Query(default=None, alias="from_date"),
    to_date: str | None = Query(default=None, alias="to_date"),
    only_open: bool = Query(default=False, alias="only_open"),
    only_executed: bool = Query(default=False, alias="only_executed"),
    include_cancelled: bool = Query(default=False, alias="include_cancelled"),
):
    if only_open and only_executed:
        raise HTTPException(status_code=400, detail="only_open e only_executed nao podem ser verdade ao mesmo tempo")

    from_dt = _parse_optional_date(from_date, "from_date")
    to_dt = _parse_optional_date(to_date, "to_date")
    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(status_code=400, detail="from_date nao pode ser superior a to_date")

    params: list[object] = []
    where_parts = ["ISNULL(op.SeparationOrder, 0) = 1"]
    if from_dt is not None:
        where_parts.append("CAST(op.Date AS date) >= ?")
        params.append(from_dt)
    if to_dt is not None:
        where_parts.append("CAST(op.Date AS date) <= ?")
        params.append(to_dt)

    with db_cursor() as (cursor, _):
        order_columns = _table_columns(cursor, "OrdersPicking")
        production_status_expr = _column_expr(order_columns, "ProductionStatus", "op", "''")
        cursor.execute(
            f"""
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
                    COUNT(DISTINCT CAST(opd.VolNumDest AS varchar(50))) AS TotalBoxes
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                WHERE ISNULL(opd.deleted, 0) = 0
                  AND ISNULL(opd.VolNumDest, '') <> ''
                GROUP BY opd.OrderID
            )
            SELECT
                op.ID AS OrderPickingID,
                op.Date AS CreationDate,
                op.DueDate AS RequestedExecutionDate,
                op.AssignedUser,
                op.UrgencyStatusID,
                ISNULL({production_status_expr}, '') AS ProductionStatus,
                ISNULL(op.deleted, 0) AS Deleted,
                ca.CustomerID,
                ca.CustomerName,
                ISNULL(da.TotalLines, 0) AS TotalLines,
                ISNULL(ba.TotalBoxes, 0) AS TotalBoxes,
                ISNULL(da.TotalQuantityToPick, 0) AS TotalQuantityToPick,
                ISNULL(da.TotalQuantityPicked, 0) AS TotalQuantityPicked,
                CASE WHEN ra.OrderPickingID IS NULL THEN 0 ELSE 1 END AS HasResume,
                ISNULL(ra.TotalRows, 0) AS TotalRows,
                ISNULL(ra.CompletedRows, 0) AS CompletedRows
            FROM OrdersPicking op WITH (NOLOCK)
            LEFT JOIN DetailAgg da ON da.OrderID = op.ID
            LEFT JOIN ResumeAgg ra ON ra.OrderPickingID = op.ID
            LEFT JOIN ClientAgg ca ON ca.OrderID = op.ID
            LEFT JOIN BoxAgg ba ON ba.OrderID = op.ID
            WHERE {' AND '.join(where_parts)}
            ORDER BY op.Date DESC, op.ID DESC
            """,
            tuple(params),
        )
        # Materializa todas as linhas em dicionarios ANTES de chamar _summary_from_row: essa
        # funcao corre queries adicionais (via _resolve_context) no mesmo cursor, o que
        # sobrescreve cursor.description a meio - se _row_to_dict fosse chamado linha a
        # linha na mesma comprehension, a partir da 2a linha ficava a decifrar a tupla com
        # os nomes de coluna da ultima query aninhada em vez da SELECT original.
        raw_rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]
        rows = [_summary_from_row(cursor, row_dict) for row_dict in raw_rows]

    filtered: list[dict[str, object]] = []
    for row in rows:
        if not include_cancelled and row["StateCode"] == "cancelled":
            continue
        if only_open and row["StateCode"] not in {"initial", "in_progress"}:
            continue
        if only_executed and row["StateCode"] not in {"separated", "conferenced"}:
            continue
        filtered.append(row)

    return {"items": filtered, "count": len(filtered)}


@router.get("/orders-picking/metadata")
def separation_orders_metadata():
    with db_cursor() as (cursor, _):
        user_columns = _table_columns(cursor, "Users")
        urgency_columns = _table_columns(cursor, "UrgencyStatus")

        users = []
        user_id_col = next((user_columns.get(name) for name in ("userid", "usrid", "user", "login", "code") if user_columns.get(name)), None)
        user_name_col = user_columns.get("username") or user_columns.get("name") or user_id_col
        if user_id_col and user_name_col:
            active_col = user_columns.get("active")
            where_sql = f"WHERE u.[{active_col}] = 1" if active_col else ""
            cursor.execute(
                f"""
                SELECT u.[{user_id_col}] AS UserValue, u.[{user_name_col}] AS UserLabel
                FROM [Users] u WITH (NOLOCK)
                {where_sql}
                ORDER BY u.[{user_name_col}]
                """
            )
            users = [{"value": str(row[0]).strip(), "label": str((row[1] or row[0])).strip()} for row in cursor.fetchall() if row[0] is not None]

        urgency_statuses = []
        urgency_id_col = urgency_columns.get("urgencystatusid") or urgency_columns.get("id") or urgency_columns.get("code")
        urgency_label_col = urgency_columns.get("urgencystatusdesc") or urgency_columns.get("urgencystatusname") or urgency_columns.get("description") or urgency_columns.get("name") or urgency_id_col
        if urgency_id_col and urgency_label_col:
            order_by_sql = f"us.[{urgency_label_col}]" if urgency_label_col != urgency_id_col else f"us.[{urgency_id_col}]"
            cursor.execute(
                f"""
                SELECT us.[{urgency_id_col}] AS UrgencyValue, us.[{urgency_label_col}] AS UrgencyLabel
                FROM UrgencyStatus us WITH (NOLOCK)
                ORDER BY {order_by_sql}
                """
            )
            urgency_statuses = [{"value": str(row[0]).strip(), "label": str((row[1] or row[0])).strip()} for row in cursor.fetchall() if row[0] is not None]

    return {"users": users, "urgency_statuses": urgency_statuses}


@router.get("/orders-picking/{order_picking_id}")
def get_separation_order_detail(order_picking_id: int):
    with db_cursor() as (cursor, _):
        order_columns = _table_columns(cursor, "OrdersPicking")
        production_status_expr = _column_expr(order_columns, "ProductionStatus", "op", "''")
        cursor.execute(
            f"""
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
                    COUNT(DISTINCT CAST(opd.VolNumDest AS varchar(50))) AS TotalBoxes
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                WHERE ISNULL(opd.deleted, 0) = 0
                  AND ISNULL(opd.VolNumDest, '') <> ''
                GROUP BY opd.OrderID
            )
            SELECT
                op.ID AS OrderPickingID,
                op.Date AS CreationDate,
                op.DueDate AS RequestedExecutionDate,
                op.AssignedUser,
                op.UrgencyStatusID,
                ISNULL({production_status_expr}, '') AS ProductionStatus,
                ISNULL(op.deleted, 0) AS Deleted,
                ca.CustomerID,
                ca.CustomerName,
                ISNULL(da.TotalLines, 0) AS TotalLines,
                ISNULL(ba.TotalBoxes, 0) AS TotalBoxes,
                ISNULL(da.TotalQuantityToPick, 0) AS TotalQuantityToPick,
                ISNULL(da.TotalQuantityPicked, 0) AS TotalQuantityPicked,
                CASE WHEN ra.OrderPickingID IS NULL THEN 0 ELSE 1 END AS HasResume,
                ISNULL(ra.TotalRows, 0) AS TotalRows,
                ISNULL(ra.CompletedRows, 0) AS CompletedRows
            FROM OrdersPicking op WITH (NOLOCK)
            LEFT JOIN DetailAgg da ON da.OrderID = op.ID
            LEFT JOIN ResumeAgg ra ON ra.OrderPickingID = op.ID
            LEFT JOIN ClientAgg ca ON ca.OrderID = op.ID
            LEFT JOIN BoxAgg ba ON ba.OrderID = op.ID
            WHERE op.ID = ?
            """,
            (order_picking_id,),
        )
        header_row = cursor.fetchone()
        if header_row is None:
            raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")
        header = _summary_from_row(cursor, _row_to_dict(cursor, header_row))

        cursor.execute(
            """
            SELECT
                opd.RowNumber,
                opd.ItemID,
                ISNULL(im.ItemDesc, opd.ItemID) AS ItemDesc,
                ISNULL(opd.QtyToPick, opd.Qty) AS QuantityToPick,
                ISNULL(opd.QtyPicked, 0) AS QuantityPicked,
                codo.DocTypeOri AS OriginDocType,
                codo.OrderIDOri AS OriginOrderID,
                codo.OrderRowOri AS OriginOrderRow,
                opd.DocTypeOri AS SeparationDocType,
                opd.OrderIDOri AS SeparationOrderID,
                opd.OrderRowOri AS SeparationOrderRow,
                ISNULL(opd.SizeID, '') AS SizeID,
                ISNULL(opd.LocationIDOri, '') AS LocationOrigin,
                ISNULL(opd.LocationIDDest, '') AS LocationDest,
                ISNULL(opd.AssignedUser, '') AS AssignedUser,
                ISNULL(opd.deleted, 0) AS Deleted,
                ISNULL(opd.PickingCompleted, 0) AS PickingCompleted
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            LEFT JOIN ItemMaster im WITH (NOLOCK)
              ON im.ItemID = opd.ItemID
            LEFT JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
              ON codo.DocType = opd.DocTypeOri
             AND codo.OrderID = opd.OrderIDOri
             AND codo.OrderRow = opd.OrderRowOri
            WHERE opd.OrderID = ?
            ORDER BY opd.RowNumber
            """,
            (order_picking_id,),
        )
        detail_rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT DISTINCT
                opd.OrderRowOri AS SeparationOrderRow,
                opd.DocTypeOri AS SeparationDocType,
                opd.OrderIDOri AS SeparationOrderID,
                ISNULL(opd.SizeID, '') AS SizeID,
                vm.VolDocCod,
                CAST(opd.VolNum AS varchar(50)) AS VolNum,
                ISNULL(vm.VolTypeID, 'CX') AS VolTypeID,
                vm.CreationUser AS UserID,
                opd.ItemID,
                ISNULL(vi.ItemQtyIni, ISNULL(vi.ItemQty, opd.Qty)) AS Quantity
            FROM OrdersPickingDetails opd WITH (NOLOCK)
            LEFT JOIN VolMaster vm WITH (NOLOCK)
              ON vm.VolNum = TRY_CAST(opd.VolNum AS int)
            LEFT JOIN VolItem vi WITH (NOLOCK)
              ON vi.VolDocCod = vm.VolDocCod
             AND vi.VolNum = TRY_CAST(opd.VolNum AS int)
             AND vi.ParentOrderRow = opd.OrderRowOri
             AND vi.ItemID = opd.ItemID
            WHERE opd.OrderID = ?
              AND ISNULL(opd.deleted, 0) = 0
              AND ISNULL(opd.VolNum, '') <> ''
            ORDER BY opd.OrderRowOri, ISNULL(opd.SizeID, ''), CAST(opd.VolNum AS varchar(50))
            """,
            (order_picking_id,),
        )
        planned_boxes_rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

        cursor.execute(
            """
            ;WITH TargetMap AS (
                SELECT DISTINCT
                    opd.OrderRowOri AS SeparationOrderRow,
                    opd.DocTypeOri AS SeparationDocType,
                    opd.OrderIDOri AS SeparationOrderID,
                    ISNULL(opd.SizeID, '') AS SizeID,
                    codo.DocTypeOri AS SourceDocType,
                    codo.OrderIDOri AS SourceOrderID,
                    codo.OrderRowOri AS SourceOrderRow,
                    cod.DocType AS TargetDocType,
                    cod.OrderID AS TargetOrderID,
                    cod.OrderRow AS TargetOrderRow
                FROM OrdersPickingDetails opd WITH (NOLOCK)
                JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                  ON codo.DocType = opd.DocTypeOri
                 AND codo.OrderID = opd.OrderIDOri
                 AND codo.OrderRow = opd.OrderRowOri
                JOIN ClientOrderDetails cod WITH (NOLOCK)
                  ON cod.DocType = codo.DocType
                 AND cod.OrderID = codo.OrderID
                 AND cod.OrderRow = codo.OrderRow
                WHERE opd.OrderID = ?
                  AND ISNULL(opd.deleted, 0) = 0
                  AND cod.DocType <> opd.DocTypeOri
            )
            SELECT DISTINCT
                map.SeparationOrderRow,
                map.SeparationDocType,
                map.SeparationOrderID,
                map.SizeID,
                map.SourceOrderRow,
                map.SourceDocType,
                map.SourceOrderID,
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
             AND vi.ItemID = (
                SELECT TOP 1 ItemID
                FROM OrdersPickingDetails opd2 WITH (NOLOCK)
                WHERE opd2.OrderID = ?
                  AND opd2.OrderRowOri = map.SeparationOrderRow
                  AND ISNULL(opd2.SizeID, '') = map.SizeID
                  AND ISNULL(opd2.deleted, 0) = 0
            )
            ORDER BY map.SeparationOrderRow, map.SizeID, vm.VolNum
            """,
            (order_picking_id, order_picking_id),
        )
        picked_boxes_rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    planned_by_row: dict[tuple[int, str, str], list[dict[str, object]]] = {}
    for row in planned_boxes_rows:
        key = (
            _to_int(row.get("SeparationOrderRow")),
            str(row.get("ItemID") or "").strip(),
            str(row.get("SizeID") or "").strip(),
        )
        planned_by_row.setdefault(key, []).append({
            "box_kind": "planned",
            "source_doc_type": row.get("SeparationDocType"),
            "source_order_id": _nullable_int(row.get("SeparationOrderID")),
            "source_order_row": _nullable_int(row.get("SeparationOrderRow")),
            "vol_doc_cod": row.get("VolDocCod"),
            "vol_num": None if row.get("VolNum") is None else str(row.get("VolNum")),
            "vol_type_id": row.get("VolTypeID"),
            "user_id": row.get("UserID"),
            "item_id": row.get("ItemID"),
            "quantity": _to_float(row.get("Quantity")),
        })

    picked_by_row: dict[tuple[int, str, str], list[dict[str, object]]] = {}
    for row in picked_boxes_rows:
        key = (
            _to_int(row.get("SeparationOrderRow")),
            str(row.get("ItemID") or "").strip(),
            str(row.get("SizeID") or "").strip(),
        )
        picked_by_row.setdefault(key, []).append({
            "box_kind": "picked",
            "source_doc_type": row.get("SourceDocType"),
            "source_order_id": _nullable_int(row.get("SourceOrderID")),
            "source_order_row": _nullable_int(row.get("SourceOrderRow")),
            "vol_doc_cod": row.get("VolDocCod"),
            "vol_num": None if row.get("VolNum") is None else str(row.get("VolNum")),
            "vol_type_id": row.get("VolTypeID"),
            "user_id": row.get("UserID"),
            "item_id": row.get("ItemID"),
            "quantity": _to_float(row.get("Quantity")),
        })

    lines: list[dict[str, object]] = []
    for row in detail_rows:
        qty_to_pick = _to_float(row.get("QuantityToPick"))
        qty_picked = _to_float(row.get("QuantityPicked"))
        state = _line_state(_to_int(row.get("Deleted")), _to_int(row.get("PickingCompleted")), qty_to_pick, qty_picked)
        origin_row = _to_int(row.get("OriginOrderRow"))
        separation_row = _to_int(row.get("SeparationOrderRow"))
        line_key = (
            separation_row,
            str(row.get("ItemID") or "").strip(),
            str(row.get("SizeID") or "").strip(),
        )
        lines.append({
            "row_number": _to_int(row.get("RowNumber")),
            "state_code": state["code"],
            "state_symbol": state["symbol"],
            "state_label": state["label"],
            "item_id": row.get("ItemID") or "",
            "item_desc": row.get("ItemDesc") or "",
            "quantity_to_pick": qty_to_pick,
            "quantity_picked": qty_picked,
            "origin_doc_type": row.get("OriginDocType"),
            "origin_order_id": _nullable_int(row.get("OriginOrderID")),
            "origin_order_row": origin_row if origin_row > 0 else None,
            "location_origin": row.get("LocationOrigin"),
            "location_dest": row.get("LocationDest"),
            "assigned_user": row.get("AssignedUser"),
            "planned_boxes": planned_by_row.get(line_key, []),
            "picked_boxes": picked_by_row.get(line_key, []),
        })

    return {"header": header, "lines": lines}


@router.patch("/orders-picking/{order_picking_id}")
def update_separation_order(order_picking_id: int, payload: SeparationOrderUpdateRequest):
    if payload.assigned_user is None and payload.urgency_status_id is None:
        raise HTTPException(status_code=400, detail="Indica AssignedUser ou UrgencyStatusID")

    with db_cursor() as (cursor, _):
        cursor.execute("SELECT 1 FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")

        columns = _table_columns(cursor, "OrdersPicking")
        set_parts: list[str] = []
        params: list[object] = []
        if payload.assigned_user is not None and columns.get("assigneduser"):
            set_parts.append(f"{columns['assigneduser']} = ?")
            params.append(_safe_text(payload.assigned_user))
        if payload.urgency_status_id is not None and columns.get("urgencystatusid"):
            set_parts.append(f"{columns['urgencystatusid']} = ?")
            params.append(_safe_text(payload.urgency_status_id))
        if columns.get("edited_by"):
            set_parts.append(f"{columns['edited_by']} = ?")
            params.append("AI")
        if columns.get("edited_date"):
            set_parts.append(f"{columns['edited_date']} = GETDATE()")
        if not set_parts:
            raise HTTPException(status_code=400, detail="Nao foi possivel atualizar a ordem")

        params.append(order_picking_id)
        cursor.execute(
            f"UPDATE OrdersPicking SET {', '.join(set_parts)} WHERE ID = ?",
            tuple(params),
        )

        detail_columns = _table_columns(cursor, "OrdersPickingDetails")
        if payload.assigned_user is not None and detail_columns.get("assigneduser"):
            cursor.execute(
                f"""
                UPDATE OrdersPickingDetails
                SET {detail_columns['assigneduser']} = ?
                WHERE OrderID = ?
                  AND ISNULL(deleted, 0) = 0
                """,
                (_safe_text(payload.assigned_user), order_picking_id),
            )
        _touch_separation_order(cursor, order_picking_id)
        _sync_production_status(cursor, order_picking_id)

    return {
        "order_picking_id": order_picking_id,
        "assigned_user": payload.assigned_user,
        "urgency_status_id": payload.urgency_status_id,
        "message": "Ordem de separacao atualizada com sucesso",
    }


def _order_has_picking_progress(cursor, order_picking_id: int) -> bool:
    """True if any non-deleted line of this order already has boxes/qty picked - i.e. the
    order is not entirely untouched anymore."""
    cursor.execute(
        """
        SELECT TOP 1 1
        FROM OrdersPickingDetails WITH (NOLOCK)
        WHERE OrderID = ?
          AND ISNULL(deleted, 0) = 0
          AND (ISNULL(QtyPicked, 0) > 0 OR ISNULL(PickingCompleted, 0) = 1)
        """,
        (order_picking_id,),
    )
    return cursor.fetchone() is not None


def _cancel_separation_order_body(cursor, order_picking_id: int, actor: str, reason: str) -> dict:
    cursor.execute("SELECT 1 FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")

    related_documents = _fetch_related_documents(cursor, order_picking_id)

    cursor.execute(
        """
        SELECT DISTINCT DocTypeOri, OrderIDOri, OrderRowOri
        FROM OrdersPickingDetails WITH (NOLOCK)
        WHERE OrderID = ?
        """,
        (order_picking_id,),
    )
    origin_rows = [(str(row[0]), int(row[1]), int(row[2])) for row in cursor.fetchall() if row[0] is not None]

    header_columns = _table_columns(cursor, "OrdersPicking")
    detail_columns = _table_columns(cursor, "OrdersPickingDetails")
    client_order_columns = _table_columns(cursor, "ClientOrders")
    client_detail_columns = _table_columns(cursor, "ClientOrderDetails")
    vol_master_columns = _table_columns(cursor, "VolMaster")

    op_parts: list[str] = []
    op_params: list[object] = []
    for candidate, value in (
        ("productionstatus", "ANULADO"),
        ("deleted", 1),
        ("deleted_by", actor),
        ("edited_by", actor),
    ):
        if header_columns.get(candidate):
            op_parts.append(f"{header_columns[candidate]} = ?")
            op_params.append(value)
    if header_columns.get("deleted_date"):
        op_parts.append(f"{header_columns['deleted_date']} = GETDATE()")
    if header_columns.get("edited_date"):
        op_parts.append(f"{header_columns['edited_date']} = GETDATE()")
    if reason and header_columns.get("obs"):
        op_parts.append(f"{header_columns['obs']} = ?")
        op_params.append(reason)
    op_params.append(order_picking_id)
    cursor.execute(f"UPDATE OrdersPicking SET {', '.join(op_parts)} WHERE ID = ?", tuple(op_params))

    if detail_columns.get("deleted"):
        detail_set = [f"{detail_columns['deleted']} = 1"]
        if detail_columns.get("pickingcompleted"):
            detail_set.append(f"{detail_columns['pickingcompleted']} = 0")
        if detail_columns.get("pickingcompleteddate"):
            detail_set.append(f"{detail_columns['pickingcompleteddate']} = NULL")
        cursor.execute(
            f"UPDATE OrdersPickingDetails SET {', '.join(detail_set)} WHERE OrderID = ?",
            (order_picking_id,),
        )

    released_origin_documents: set[tuple[str, int]] = set()
    for doc_type, order_id, order_row in origin_rows:
        if client_detail_columns:
            detail_parts = []
            detail_vals: list[object] = []
            for candidate, value in (("activepickingid", 0), ("pendingorderpickingid", 0), ("productionstatus", "INICIAL")):
                if client_detail_columns.get(candidate):
                    detail_parts.append(f"{client_detail_columns[candidate]} = ?")
                    detail_vals.append(value)
            if detail_parts:
                detail_vals.extend([doc_type, order_id, order_row])
                cursor.execute(
                    f"UPDATE ClientOrderDetails SET {', '.join(detail_parts)} WHERE DocType = ? AND OrderID = ? AND OrderRow = ?",
                    tuple(detail_vals),
                )
        if (doc_type, order_id) not in released_origin_documents:
            header_parts = []
            header_vals: list[object] = []
            for candidate, value in (("pendingorderpickingid", ""), ("productionstatus", "INICIAL")):
                if client_order_columns.get(candidate):
                    header_parts.append(f"{client_order_columns[candidate]} = ?")
                    header_vals.append(value)
            if header_parts:
                header_vals.extend([doc_type, order_id])
                cursor.execute(
                    f"UPDATE ClientOrders SET {', '.join(header_parts)} WHERE DocType = ? AND OrderID = ?",
                    tuple(header_vals),
                )
            released_origin_documents.add((doc_type, order_id))

    released_boxes = 0
    if vol_master_columns:
        box_parts = []
        box_vals: list[object] = []
        for candidate, value in (("pendingorderpickingid", ""), ("orderpickingid", 0), ("activepickingid", 0), ("blocked", 0), ("reserved", 0)):
            if vol_master_columns.get(candidate):
                box_parts.append(f"{vol_master_columns[candidate]} = ?")
                box_vals.append(value)
        if box_parts:
            parents = {(doc_type, order_id) for doc_type, order_id, _ in origin_rows}
            parents.update((doc["separation_doc_type"], doc["separation_order_id"]) for doc in related_documents)
            for doc_type, order_id in parents:
                values = list(box_vals) + [doc_type, order_id]
                cursor.execute(
                    f"UPDATE VolMaster SET {', '.join(box_parts)} WHERE ParentDocType = ? AND ParentOrderID = ?",
                    tuple(values),
                )
                released_boxes += max(cursor.rowcount or 0, 0)

    cancelled_pkl_documents = 0
    cancelled_related_documents = 0
    for document in related_documents:
        doc_type = document["separation_doc_type"]
        order_id = document["separation_order_id"]
        header_parts = []
        header_vals: list[object] = []
        for candidate, value in (("productionstatus", "ANULADO"), ("modifuser", actor)):
            if client_order_columns.get(candidate):
                header_parts.append(f"{client_order_columns[candidate]} = ?")
                header_vals.append(value)
        if client_order_columns.get("modifdatetime"):
            header_parts.append(f"{client_order_columns['modifdatetime']} = GETDATE()")
        if header_parts:
            header_vals.extend([doc_type, order_id])
            cursor.execute(
                f"UPDATE ClientOrders SET {', '.join(header_parts)} WHERE DocType = ? AND OrderID = ?",
                tuple(header_vals),
            )
        if client_detail_columns.get("productionstatus"):
            cursor.execute(
                f"UPDATE ClientOrderDetails SET {client_detail_columns['productionstatus']} = ? WHERE DocType = ? AND OrderID = ?",
                ("ANULADO", doc_type, order_id),
            )
        if doc_type.upper() == "PKL":
            cancelled_pkl_documents += 1
        else:
            cancelled_related_documents += 1

    _touch_separation_order(cursor, order_picking_id)

    source = _resolve_context(cursor, order_picking_id)["Source"]

    return {
        "order_picking_id": order_picking_id,
        "source": source,
        "state_code": "cancelled",
        "production_status": "ANULADO",
        "deleted": 1,
        "released_origin_documents": len(released_origin_documents),
        "released_boxes": released_boxes,
        "cancelled_pkl_documents": cancelled_pkl_documents,
        "cancelled_related_documents": cancelled_related_documents,
        "message": "Ordem de separacao anulada com sucesso",
    }


@router.post("/orders-picking/{order_picking_id}/cancel")
def cancel_separation_order(order_picking_id: int, payload: SeparationOrderCancelRequest):
    actor = _safe_text(payload.cancelled_by) or "AI"
    reason = _safe_text(payload.reason)
    with db_cursor() as (cursor, _):
        return _cancel_separation_order_body(cursor, order_picking_id, actor, reason)


@router.post("/orders-picking/{order_picking_id}/delete")
def delete_separation_order(order_picking_id: int, payload: SeparationOrderCancelRequest):
    """Eliminar so e permitido enquanto a ordem estiver totalmente por executar - assim
    que qualquer linha tiver caixa/quantidade indicada, o operador tem de desfazer essa
    separacao na execucao (unpick) antes de poder eliminar a ordem toda."""
    actor = _safe_text(payload.cancelled_by) or "AI"
    reason = _safe_text(payload.reason)
    with db_cursor() as (cursor, _):
        cursor.execute("SELECT 1 FROM OrdersPicking WITH (NOLOCK) WHERE ID = ?", (order_picking_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Ordem de separacao nao encontrada")
        if _order_has_picking_progress(cursor, order_picking_id):
            raise HTTPException(
                status_code=400,
                detail="Esta ordem ja tem linhas separadas (caixas indicadas). Remove essas linhas na execucao antes de eliminar a ordem.",
            )
        result = _cancel_separation_order_body(cursor, order_picking_id, actor, reason)
        result["message"] = "Ordem de separacao eliminada com sucesso"
        return result
