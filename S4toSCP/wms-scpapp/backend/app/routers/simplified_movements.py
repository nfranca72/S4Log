from __future__ import annotations

# ── Migration SQL (run once on the database before using this router) ──────────
# ALTER TABLE DocumentConfig ADD IsSimplifiedMovement BIT NOT NULL DEFAULT 0;
# UPDATE DocumentConfig SET IsSimplifiedMovement = 1 WHERE DocType IN (...);
# ──────────────────────────────────────────────────────────────────────────────

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.db.connection import db_cursor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simplified-movements", tags=["Movimentos Simplificados"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class MovementType(BaseModel):
    doc_type: str
    title: str
    doc_desc: Optional[str]
    is_transfer: bool
    allow_business_partner: bool
    partner_type: Optional[str]
    force_orig_doc: bool
    has_components: bool
    has_lots: bool
    use_dims: bool
    with_value: bool
    allow_stock_move: bool

class MovementLine(BaseModel):
    item_id: str
    color_id: str = ''
    size_id: str = ''
    lot_id: str = ''
    vol_num: Optional[int] = None
    qty: float
    unit_value: float = 0.0
    doc_row: Optional[int] = None

class ExecuteMovementRequest(BaseModel):
    doc_type: str
    order_id: Optional[int] = None
    partner_id: Optional[str] = None
    wh_id_orig: int
    location_id_orig: str
    wh_id_dest: Optional[int] = None
    location_id_dest: Optional[str] = None
    obs: str = ''
    lines: list[MovementLine]

class ExecuteMovementResult(BaseModel):
    success: bool
    mov_ids: list[int]
    message: str
    warnings: list[str] = []


# ── 1. Movement types ──────────────────────────────────────────────────────────

@router.get("/types", response_model=list[MovementType])
def list_movement_types():
    try:
        with db_cursor() as (cursor, _):
            cursor.execute("""
                SELECT DocType, Title, DocDesc, DocTypeArea, StockMovType,
                       ISNULL(Transfer, 0)              AS IsTransfer,
                       ISNULL(AllowBusinessPartner, 0)  AS AllowBP,
                       PartnerType,
                       ISNULL(forceOrigDoc, 0)           AS ForceOrig,
                       ISNULL(HasComponents, 0)          AS HasComps,
                       ISNULL(HasLots, 0)                AS HasLots,
                       ISNULL(UseDims, 0)                AS UseDims,
                       ISNULL(WithValue, 0)              AS WithValue,
                       ISNULL(AllowStockMove, 0)         AS AllowStock
                FROM DocumentConfig
                WHERE IsSimplifiedMovement = 1 AND Active = 1
                ORDER BY Title
            """)
            rows = cursor.fetchall()
    except Exception:
        logger.warning(
            "DocumentConfig inacessível ou coluna IsSimplifiedMovement não existe. "
            "Execute: ALTER TABLE DocumentConfig ADD IsSimplifiedMovement BIT NOT NULL DEFAULT 0"
        )
        return []

    return [
        MovementType(
            doc_type=r[0],
            title=r[1] or r[0],
            doc_desc=r[2],
            is_transfer=bool(r[5]),
            allow_business_partner=bool(r[6]),
            partner_type=r[7],
            force_orig_doc=bool(r[8]),
            has_components=bool(r[9]),
            has_lots=bool(r[10]),
            use_dims=bool(r[11]),
            with_value=bool(r[12]),
            allow_stock_move=bool(r[13]),
        )
        for r in rows
    ]


# ── 2. Business partners ───────────────────────────────────────────────────────

@router.get("/partners")
def list_partners(
    partner_type: str = Query(default="C"),
    search: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        types = [t.strip() for t in partner_type.split(",") if t.strip()]
        if not types:
            types = ["C"]

        placeholders = ",".join("?" for _ in types)
        if search:
            cursor.execute(
                f"""
                SELECT TOP 50 PartnerID, PartnerName, PartnerType
                FROM BusinessPartners
                WHERE PartnerType IN ({placeholders})
                  AND (PartnerName LIKE ? OR PartnerID LIKE ?)
                ORDER BY PartnerName
                """,
                (*types, f"%{search}%", f"%{search}%"),
            )
        else:
            cursor.execute(
                f"""
                SELECT TOP 100 PartnerID, PartnerName, PartnerType
                FROM BusinessPartners
                WHERE PartnerType IN ({placeholders})
                ORDER BY PartnerName
                """,
                types,
            )
        rows = cursor.fetchall()

    return [
        {"partner_id": r[0], "partner_name": r[1], "partner_type": r[2]}
        for r in rows
    ]


# ── 3. Origin documents ────────────────────────────────────────────────────────

@router.get("/documents")
def list_documents(
    doc_type: str = Query(...),
    partner_id: str = Query(default=""),
):
    with db_cursor() as (cursor, _):
        if partner_id:
            cursor.execute("""
                SELECT co.OrderID, co.DocType, co.ClientID,
                       co.OrderDateTime, co.Obs,
                       COUNT(cod.OrderRow) AS total_lines,
                       SUM(CASE WHEN ISNULL(cod.QtyOrd,0) > ISNULL(cod.QtySatisf,0)
                                THEN 1 ELSE 0 END) AS pending_lines
                FROM ClientOrders co
                JOIN ClientOrderDetails cod
                  ON cod.OrderID = co.OrderID AND cod.DocType = co.DocType
                WHERE co.DocType = ? AND co.ClientID = ?
                  AND UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)),''))))
                      NOT IN ('ANULADA','CANCELADA','FECHADA')
                GROUP BY co.OrderID, co.DocType, co.ClientID, co.OrderDateTime, co.Obs
                ORDER BY co.OrderID DESC
            """, (doc_type, partner_id))
        else:
            cursor.execute("""
                SELECT co.OrderID, co.DocType, co.ClientID,
                       co.OrderDateTime, co.Obs,
                       COUNT(cod.OrderRow) AS total_lines,
                       SUM(CASE WHEN ISNULL(cod.QtyOrd,0) > ISNULL(cod.QtySatisf,0)
                                THEN 1 ELSE 0 END) AS pending_lines
                FROM ClientOrders co
                JOIN ClientOrderDetails cod
                  ON cod.OrderID = co.OrderID AND cod.DocType = co.DocType
                WHERE co.DocType = ?
                  AND UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)),''))))
                      NOT IN ('ANULADA','CANCELADA','FECHADA')
                GROUP BY co.OrderID, co.DocType, co.ClientID, co.OrderDateTime, co.Obs
                ORDER BY co.OrderID DESC
            """, (doc_type,))

        rows = cursor.fetchall()

    return [
        {
            "order_id":      r[0],
            "doc_type":      r[1],
            "partner_id":    r[2],
            "order_date":    str(r[3])[:10] if r[3] else None,
            "obs":           r[4] or "",
            "total_lines":   r[5] or 0,
            "pending_lines": r[6] or 0,
        }
        for r in rows
    ]


# ── 4. Document lines / components ────────────────────────────────────────────

@router.get("/documents/{order_id}/lines")
def document_lines(
    order_id: int,
    doc_type: str = Query(...),
    with_components: bool = Query(default=False),
):
    with db_cursor() as (cursor, _):
        if with_components:
            # Components from ClientOrderComp (if HasComponents = 1)
            cursor.execute("""
                SELECT coc.ComponentID,
                       ISNULL(im.ItemDesc, coc.ComponentID) AS item_desc,
                       ISNULL(coc.QtyComp, 0)    AS qty_ord,
                       ISNULL(coc.QtySatisf, 0)  AS qty_satisf,
                       ISNULL(im.Dimensions, 0)  AS has_dims,
                       ISNULL(im.Lots, 0)         AS has_lots,
                       ISNULL(im.VolNums, 0)      AS has_volumes,
                       0                          AS order_row
                FROM ClientOrderComp coc
                LEFT JOIN ItemMaster im ON im.ItemID = coc.ComponentID
                WHERE coc.OrderID = ? AND coc.DocType = ?
                  AND ISNULL(coc.QtyComp, 0) > ISNULL(coc.QtySatisf, 0)
                ORDER BY coc.ComponentID
            """, (order_id, doc_type))
        else:
            cursor.execute("""
                SELECT cod.ItemID,
                       ISNULL(im.ItemDesc, cod.ItemID) AS item_desc,
                       ISNULL(cod.QtyOrd, 0)    AS qty_ord,
                       ISNULL(cod.QtySatisf, 0) AS qty_satisf,
                       ISNULL(im.Dimensions, 0) AS has_dims,
                       ISNULL(im.Lots, 0)        AS has_lots,
                       ISNULL(im.VolNums, 0)     AS has_volumes,
                       cod.OrderRow
                FROM ClientOrderDetails cod
                LEFT JOIN ItemMaster im ON im.ItemID = cod.ItemID
                WHERE cod.OrderID = ? AND cod.DocType = ?
                  AND ISNULL(cod.QtyOrd, 0) > ISNULL(cod.QtySatisf, 0)
                ORDER BY cod.OrderRow
            """, (order_id, doc_type))

        rows = cursor.fetchall()

    return [
        {
            "item_id":     r[0],
            "item_desc":   r[1],
            "qty_ord":     float(r[2]),
            "qty_satisf":  float(r[3]),
            "qty_pending": float(r[2]) - float(r[3]),
            "has_dims":    bool(r[4]),
            "has_lots":    bool(r[5]),
            "has_volumes": bool(r[6]),
            "order_row":   r[7],
        }
        for r in rows
    ]


# ── 5. Item details ────────────────────────────────────────────────────────────

@router.get("/items/{item_id}")
def item_details(item_id: str):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT ItemID, ItemDesc,
                   ISNULL(StkUnit, 'UN')  AS StkUnit,
                   ISNULL(Dimensions, 0)  AS HasDims,
                   ISNULL(Lots, 0)         AS HasLots,
                   ISNULL(VolNums, 0)      AS HasVolumes,
                   ISNULL(ItemValue, 0)    AS ItemValue
            FROM ItemMaster
            WHERE ItemID = ?
        """, (item_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Artigo '{item_id}' não encontrado")

    return {
        "item_id":     row[0],
        "item_desc":   row[1] or "",
        "stk_unit":    row[2],
        "has_dims":    bool(row[3]),
        "has_lots":    bool(row[4]),
        "has_volumes": bool(row[5]),
        "item_value":  float(row[6]),
    }


# ── 6. Item stock by item (no warehouse filter) ─────────────────────────────

@router.get("/items/{item_id}/stock")
def item_stock(item_id: str, wh_id: Optional[int] = Query(default=None)):
    with db_cursor() as (cursor, _):
        if wh_id is not None:
            cursor.execute("""
                SELECT ISNULL(SUM(Qty), 0)
                FROM Inventory
                WHERE ItemID = ? AND WHID = ? AND Qty > 0
            """, (item_id, wh_id))
        else:
            cursor.execute("""
                SELECT ISNULL(SUM(Qty), 0)
                FROM Inventory
                WHERE ItemID = ? AND Qty > 0
            """, (item_id,))
        row = cursor.fetchone()

    return {"item_id": item_id, "qty_stock": float(row[0]) if row else 0.0}


# ── 7. Dimension grid (Color × Size) with stock ────────────────────────────────

@router.get("/items/{item_id}/dim-stock")
def item_dim_stock(item_id: str, wh_id: Optional[int] = Query(default=None)):
    with db_cursor() as (cursor, _):
        if wh_id is not None:
            cursor.execute("""
                SELECT i.ColorID, i.SizeID, SUM(ISNULL(i.Qty, 0)) AS qty_stock
                FROM Inventory i
                WHERE i.ItemID = ? AND i.WHID = ? AND i.Qty > 0
                  AND i.ColorID IS NOT NULL AND i.ColorID <> ''
                  AND i.SizeID  IS NOT NULL AND i.SizeID  <> ''
                GROUP BY i.ColorID, i.SizeID
                ORDER BY i.ColorID, i.SizeID
            """, (item_id, wh_id))
        else:
            cursor.execute("""
                SELECT i.ColorID, i.SizeID, SUM(ISNULL(i.Qty, 0)) AS qty_stock
                FROM Inventory i
                WHERE i.ItemID = ? AND i.Qty > 0
                  AND i.ColorID IS NOT NULL AND i.ColorID <> ''
                  AND i.SizeID  IS NOT NULL AND i.SizeID  <> ''
                GROUP BY i.ColorID, i.SizeID
                ORDER BY i.ColorID, i.SizeID
            """, (item_id,))
        cells = cursor.fetchall()

    colors = list(dict.fromkeys(r[0] for r in cells))
    sizes  = list(dict.fromkeys(r[1] for r in cells))
    cell_map = {(r[0], r[1]): float(r[2]) for r in cells}

    return {
        "item_id": item_id,
        "colors":  colors,
        "sizes":   sizes,
        "cells": [
            {
                "color_id":   r[0],
                "size_id":    r[1],
                "qty_stock":  float(r[2]),
            }
            for r in cells
        ],
    }


# ── 8. Lot stock ───────────────────────────────────────────────────────────────

@router.get("/items/{item_id}/lots")
def item_lots(item_id: str, wh_id: Optional[int] = Query(default=None)):
    with db_cursor() as (cursor, _):
        if wh_id is not None:
            cursor.execute("""
                SELECT i.Lot, i.WHID,
                       ISNULL(w.WHDesc, '') AS wh_desc,
                       i.LocationID,
                       SUM(ISNULL(i.Qty, 0)) AS qty_stock
                FROM Inventory i
                LEFT JOIN Warehouses w ON w.WHID = i.WHID
                WHERE i.ItemID = ? AND i.WHID = ?
                  AND i.Qty > 0
                  AND i.Lot IS NOT NULL AND i.Lot <> ''
                GROUP BY i.Lot, i.WHID, w.WHDesc, i.LocationID
                ORDER BY i.Lot
            """, (item_id, wh_id))
        else:
            cursor.execute("""
                SELECT i.Lot, i.WHID,
                       ISNULL(w.WHDesc, '') AS wh_desc,
                       i.LocationID,
                       SUM(ISNULL(i.Qty, 0)) AS qty_stock
                FROM Inventory i
                LEFT JOIN Warehouses w ON w.WHID = i.WHID
                WHERE i.ItemID = ?
                  AND i.Qty > 0
                  AND i.Lot IS NOT NULL AND i.Lot <> ''
                GROUP BY i.Lot, i.WHID, w.WHDesc, i.LocationID
                ORDER BY i.Lot
            """, (item_id,))
        rows = cursor.fetchall()

    return [
        {
            "lot_id":      r[0],
            "wh_id":       r[1],
            "wh_desc":     r[2],
            "location_id": r[3] or "",
            "qty_stock":   float(r[4]),
        }
        for r in rows
    ]


# ── 9. Volumes with stock ──────────────────────────────────────────────────────

@router.get("/items/{item_id}/volumes")
def item_volumes(item_id: str, wh_id: Optional[int] = Query(default=None)):
    with db_cursor() as (cursor, _):
        if wh_id is not None:
            cursor.execute("""
                SELECT i.VolNum,
                       ISNULL(vm.VolNum2N, '')   AS barcode,
                       i.WHID,
                       ISNULL(w.WHDesc, '')       AS wh_desc,
                       i.LocationID,
                       SUM(ISNULL(i.Qty, 0))      AS qty_stock
                FROM Inventory i
                LEFT JOIN VolMaster vm ON vm.VolNum = TRY_CAST(i.VolNum AS int)
                LEFT JOIN Warehouses w ON w.WHID = i.WHID
                WHERE i.ItemID = ? AND i.WHID = ?
                  AND i.Qty > 0
                  AND i.VolNum IS NOT NULL AND i.VolNum <> ''
                GROUP BY i.VolNum, vm.VolNum2N, i.WHID, w.WHDesc, i.LocationID
                ORDER BY i.VolNum
            """, (item_id, wh_id))
        else:
            cursor.execute("""
                SELECT i.VolNum,
                       ISNULL(vm.VolNum2N, '')   AS barcode,
                       i.WHID,
                       ISNULL(w.WHDesc, '')       AS wh_desc,
                       i.LocationID,
                       SUM(ISNULL(i.Qty, 0))      AS qty_stock
                FROM Inventory i
                LEFT JOIN VolMaster vm ON vm.VolNum = TRY_CAST(i.VolNum AS int)
                LEFT JOIN Warehouses w ON w.WHID = i.WHID
                WHERE i.ItemID = ?
                  AND i.Qty > 0
                  AND i.VolNum IS NOT NULL AND i.VolNum <> ''
                GROUP BY i.VolNum, vm.VolNum2N, i.WHID, w.WHDesc, i.LocationID
                ORDER BY i.VolNum
            """, (item_id,))
        rows = cursor.fetchall()

    return [
        {
            "vol_num":     r[0],
            "barcode":     r[1],
            "wh_id":       r[2],
            "wh_desc":     r[3],
            "location_id": r[4] or "",
            "qty_stock":   float(r[5]),
        }
        for r in rows
    ]


# ── 10. Warehouses allowed for a doc type ─────────────────────────────────────

@router.get("/warehouses")
def list_warehouses(doc_type: str = Query(default="")):
    with db_cursor() as (cursor, _):
        if doc_type:
            # Try DocumentWarehouses first; fall back to all warehouses if table/rows not found
            try:
                cursor.execute("""
                    SELECT dw.WHID, ISNULL(w.WHDesc, '') AS WHDesc,
                           ISNULL(dw.WHRole, '') AS WHRole
                    FROM DocumentWarehouses dw
                    JOIN Warehouses w ON w.WHID = dw.WHID
                    WHERE dw.DocType = ?
                    ORDER BY w.WHDesc
                """, (doc_type,))
                rows = cursor.fetchall()
                if rows:
                    return [
                        {
                            "wh_id":   r[0],
                            "wh_desc": r[1],
                            "wh_role": r[2],
                        }
                        for r in rows
                    ]
            except Exception:
                pass  # table may not exist; fall through

        cursor.execute("SELECT WHID, WHDesc FROM Warehouses ORDER BY WHDesc")
        rows = cursor.fetchall()

    return [
        {"wh_id": r[0], "wh_desc": r[1], "wh_role": ""}
        for r in rows
    ]


@router.get("/warehouses/{wh_id}/locations")
def list_locations(wh_id: int):
    with db_cursor() as (cursor, _):
        cursor.execute(
            "SELECT LocationID, ISNULL(LocationDesc, LocationID) FROM Locations WHERE WHID = ? ORDER BY LocationID",
            (wh_id,),
        )
        rows = cursor.fetchall()
    return [{"location_id": r[0], "location_desc": r[1]} for r in rows]


# ── 11. Search items (free entry / scan) ──────────────────────────────────────

@router.get("/items")
def search_items(search: str = Query(default=""), wh_id: Optional[int] = Query(default=None)):
    if not search or len(search) < 2:
        return []

    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TOP 20 im.ItemID, im.ItemDesc,
                   ISNULL(im.StkUnit, 'UN') AS StkUnit,
                   ISNULL(im.Dimensions, 0) AS HasDims,
                   ISNULL(im.Lots, 0)        AS HasLots,
                   ISNULL(im.VolNums, 0)     AS HasVolumes,
                   ISNULL(im.ItemValue, 0)   AS ItemValue,
                   ISNULL(
                       (SELECT SUM(i.Qty) FROM Inventory i WHERE i.ItemID = im.ItemID AND i.Qty > 0),
                   0) AS QtyStock
            FROM ItemMaster im
            WHERE im.ItemID LIKE ? OR im.ItemDesc LIKE ? OR im.ClientRef LIKE ?
            ORDER BY im.ItemID
        """, (f"%{search}%", f"%{search}%", f"%{search}%"))
        rows = cursor.fetchall()

    return [
        {
            "item_id":     r[0],
            "item_desc":   r[1] or "",
            "stk_unit":    r[2],
            "has_dims":    bool(r[3]),
            "has_lots":    bool(r[4]),
            "has_volumes": bool(r[5]),
            "item_value":  float(r[6]),
            "qty_stock":   float(r[7]),
        }
        for r in rows
    ]


# ── 12. Execute movement ───────────────────────────────────────────────────────

@router.post("/execute", response_model=ExecuteMovementResult)
def execute_movement(req: ExecuteMovementRequest):
    if not req.lines:
        raise HTTPException(status_code=400, detail="Nenhuma linha de movimento especificada")

    is_transfer = req.wh_id_dest is not None and req.location_id_dest is not None

    mov_ids: list[int] = []
    warnings: list[str] = []

    with db_cursor() as (cursor, conn):
        # Resolve stk_unit for each item
        item_units: dict[str, str] = {}
        item_ids = list({line.item_id for line in req.lines})
        if item_ids:
            ph = ",".join("?" for _ in item_ids)
            cursor.execute(
                f"SELECT ItemID, ISNULL(StkUnit,'UN') FROM ItemMaster WHERE ItemID IN ({ph})",
                item_ids,
            )
            item_units = {r[0]: r[1] for r in cursor.fetchall()}

        for line in req.lines:
            stk_unit = item_units.get(line.item_id, "UN")
            qty = float(line.qty)
            if qty <= 0:
                continue

            # ── Validate source stock ──────────────────────────────────────────
            cursor.execute("""
                SELECT ISNULL(SUM(Qty), 0)
                FROM Inventory
                WHERE ItemID    = ?
                  AND WHID      = ?
                  AND LocationID = ?
                  AND (? = '' OR Lot = ?)
                  AND (? = '' OR ColorID = ?)
                  AND (? = '' OR SizeID  = ?)
                  AND (? = '' OR VolNum  = ?)
                  AND Qty > 0
            """, (
                line.item_id,
                req.wh_id_orig, req.location_id_orig,
                line.lot_id, line.lot_id,
                line.color_id, line.color_id,
                line.size_id, line.size_id,
                str(line.vol_num) if line.vol_num else '', str(line.vol_num) if line.vol_num else '',
            ))
            available = float(cursor.fetchone()[0] or 0)
            if available < qty:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Stock insuficiente para '{line.item_id}': "
                        f"disponível {available:.0f}, solicitado {qty:.0f}"
                    ),
                )

            vol_num_str = str(line.vol_num) if line.vol_num else ''

            # ── Stock exit StockMov ────────────────────────────────────────────
            cursor.execute("""
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
                    GETDATE(),
                    ?, ?, '', ?, ?,
                    ?, ?, ?,
                    'O', '',
                    'MOVSIMP', GETDATE(),
                    ?, ?, ?, '', '',
                    1, 1, 0, ?,
                    ?, ?, ''
                )
            """, (
                req.wh_id_orig,
                req.wh_id_dest if is_transfer else 0,
                req.location_id_orig,
                req.location_id_dest if is_transfer else '',
                line.item_id,
                line.lot_id, qty, stk_unit,
                req.doc_type,
                str(req.order_id) if req.order_id else '',
                line.doc_row or 0,
                line.unit_value,
                line.unit_value * qty,
                req.obs,
                vol_num_str,
                line.color_id, line.size_id,
            ))
            mov_row = cursor.fetchone()
            mov_id_o = mov_row[0] if mov_row else None
            if mov_id_o:
                mov_ids.append(mov_id_o)

            # ── Decrease source inventory ──────────────────────────────────────
            _adjust_inventory(
                cursor,
                wh_id=req.wh_id_orig,
                location_id=req.location_id_orig,
                item_id=line.item_id,
                lot=line.lot_id,
                color_id=line.color_id,
                size_id=line.size_id,
                vol_num=vol_num_str,
                delta=-qty,
            )

            # ── Transfer: increase destination inventory + entry StockMov ─────
            if is_transfer:
                cursor.execute("""
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
                        GETDATE(),
                        ?, ?, '', ?, ?,
                        ?, ?, ?,
                        'I', '',
                        'MOVSIMP', GETDATE(),
                        ?, ?, ?, '', '',
                        1, 1, 0, ?,
                        ?, ?, ''
                    )
                """, (
                    req.wh_id_orig,
                    req.wh_id_dest,
                    req.location_id_orig,
                    req.location_id_dest,
                    line.item_id,
                    line.lot_id, qty, stk_unit,
                    req.doc_type,
                    str(req.order_id) if req.order_id else '',
                    line.doc_row or 0,
                    line.unit_value,
                    line.unit_value * qty,
                    req.obs,
                    vol_num_str,
                    line.color_id, line.size_id,
                ))
                mov_row_i = cursor.fetchone()
                if mov_row_i and mov_row_i[0]:
                    mov_ids.append(mov_row_i[0])

                _upsert_inventory(
                    cursor,
                    wh_id=req.wh_id_dest,
                    location_id=req.location_id_dest,
                    item_id=line.item_id,
                    lot=line.lot_id,
                    color_id=line.color_id,
                    size_id=line.size_id,
                    vol_num=vol_num_str,
                    qty=qty,
                )

            # ── Update origin document satisfaction ────────────────────────────
            if req.order_id and line.doc_row:
                cursor.execute("""
                    UPDATE ClientOrderDetails
                    SET QtySatisf = ISNULL(QtySatisf, 0) + ?
                    WHERE OrderID = ? AND DocType = ? AND OrderRow = ?
                """, (qty, req.order_id, req.doc_type, line.doc_row))

    n = len(req.lines)
    op = "Transferência" if is_transfer else "Saída de stock"
    return ExecuteMovementResult(
        success=True,
        mov_ids=mov_ids,
        message=f"{op} executada: {n} linha(s), {sum(l.qty for l in req.lines):.0f} unidades.",
        warnings=warnings,
    )


# ── Inventory helpers ──────────────────────────────────────────────────────────

def _adjust_inventory(cursor, wh_id, location_id, item_id, lot, color_id, size_id, vol_num, delta):
    cursor.execute("""
        UPDATE Inventory
        SET Qty = Qty + ?, LastInput = GETDATE()
        WHERE WHID = ? AND LocationID = ? AND ItemID = ?
          AND Lot     = ? AND ColorID = ? AND SizeID = ? AND VolNum = ?
    """, (delta, wh_id, location_id, item_id, lot, color_id, size_id, vol_num))


def _upsert_inventory(cursor, wh_id, location_id, item_id, lot, color_id, size_id, vol_num, qty):
    cursor.execute("""
        SELECT Qty FROM Inventory
        WHERE WHID = ? AND LocationID = ? AND ItemID = ?
          AND Lot = ? AND ColorID = ? AND SizeID = ? AND VolNum = ?
    """, (wh_id, location_id, item_id, lot, color_id, size_id, vol_num))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE Inventory
            SET Qty = Qty + ?, LastInput = GETDATE()
            WHERE WHID = ? AND LocationID = ? AND ItemID = ?
              AND Lot = ? AND ColorID = ? AND SizeID = ? AND VolNum = ?
        """, (qty, wh_id, location_id, item_id, lot, color_id, size_id, vol_num))
    else:
        cursor.execute("""
            INSERT INTO Inventory (
                WHID, LocationID, ItemID,
                Lot, SerialNum, Qty,
                LastInput, Version, VolNum,
                ColorID, SizeID, Country
            ) VALUES (
                ?, ?, ?,
                ?, '', ?,
                GETDATE(), 0, ?,
                ?, ?, ''
            )
        """, (wh_id, location_id, item_id, lot, qty, vol_num, color_id, size_id))
