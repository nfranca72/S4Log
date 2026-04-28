from __future__ import annotations
import csv
import io
import logging
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from app.db.connection import db_cursor

router = APIRouter(tags=["Consulta"])
logger = logging.getLogger(__name__)


def _packing_status(total: int, confirmed: int) -> str:
    if confirmed == 0:
        return "INICIAL"
    elif confirmed < total:
        return "EMCONFERENCIA"
    else:
        return "FECHADO"


@router.get("/consulting/packings")
def list_packings(
    doc_type: str = Query(default="PSCP"),
    status:   str = Query(default="TODOS"),
):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                co.OrderID,
                co.DocType,
                co.ClientID,
                co.OrderDateTime,
                co.Obs,
                ISNULL(co.RequesterID, '') AS requester_id,
                COUNT(vm.VolNum)                                    AS total_boxes,
                SUM(CASE WHEN vm.VolVerified=1 THEN 1 ELSE 0 END)  AS confirmed_boxes,
                SUM(ISNULL(vi_ini.ItemQtyIni, 0))                  AS qty_initial,
                SUM(ISNULL(vi_conf.ItemQty,   0))                  AS qty_confirmed,
                ISNULL(stock.qty_stock, 0)                        AS qty_stock
            FROM ClientOrders co
            LEFT JOIN VolMaster vm
                ON vm.ParentOrderID = co.OrderID AND vm.VolDocCod = 'CX'
            LEFT JOIN (
                SELECT VolNum, SUM(ItemQtyIni) AS ItemQtyIni
                FROM VolItem GROUP BY VolNum
            ) vi_ini ON vi_ini.VolNum = vm.VolNum
            LEFT JOIN (
                SELECT VolNum, SUM(ItemQty) AS ItemQty
                FROM VolItem WHERE ItemQty > 0 GROUP BY VolNum
            ) vi_conf ON vi_conf.VolNum = vm.VolNum
            OUTER APPLY (
                SELECT SUM(i.Qty) AS qty_stock
                FROM Inventory i
                WHERE EXISTS (
                    SELECT 1
                    FROM ClientOrderDetails cod
                    WHERE cod.OrderID = co.OrderID
                      AND cod.DocType = co.DocType
                      AND cod.ItemID = i.ItemID
                )
            ) stock
            WHERE co.DocType = ?
            GROUP BY co.OrderID, co.DocType, co.ClientID, co.OrderDateTime, co.Obs, co.RequesterID, stock.qty_stock
            ORDER BY co.OrderID DESC
        """, (doc_type,))
        rows = cursor.fetchall()

    result = []
    for r in rows:
        order_id, dtype, client_id, order_date, obs, requester_id, \
            total, confirmed, qty_ini, qty_conf, qty_stock = r
        st = _packing_status(total or 0, confirmed or 0)
        if status != "TODOS" and st != status:
            continue

        result.append({
            "order_id":        order_id,
            "doc_type":        dtype,
            "client_id":       client_id,
            "order_date":      str(order_date)[:10] if order_date else None,
            "obs":             obs or "",
            "requester_id":    requester_id or "",
            "status":          st,
            "total_boxes":     total or 0,
            "confirmed_boxes": confirmed or 0,
            "qty_initial":     float(qty_ini or 0),
            "qty_confirmed":   float(qty_conf or 0),
            "qty_stock":       float(qty_stock),
        })
    return result


@router.get("/consulting/packings/{order_id}/lines")
def packing_lines(order_id: int, doc_type: str = "PSCP"):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                cod.OrderRow,
                cod.ItemID,
                ISNULL(im.ItemDesc, '')   AS item_desc,
                ISNULL(im.ClientRef, '')  AS client_ref,
                ISNULL(cod.QtyOrd, 0)    AS qty_ord,
                ISNULL(cod.QtySatisf, 0) AS qty_satisf,
                ISNULL(
                    (SELECT SUM(i.Qty) FROM Inventory i WHERE i.ItemID = cod.ItemID),
                0) AS qty_stock
            FROM ClientOrderDetails cod
            JOIN ClientOrders co ON co.OrderID = cod.OrderID AND co.DocType = cod.DocType
            LEFT JOIN ItemMaster im ON im.ItemID = cod.ItemID
            WHERE cod.DocType = ? AND cod.OrderID = ?
            ORDER BY cod.OrderRow
        """, (doc_type, order_id,))
        rows = cursor.fetchall()

    return [{
        "order_row":     r[0],
        "item_id":       r[1],
        "item_desc":     r[2],
        "client_ref":    r[3],
        "qty_initial":   float(r[4]),
        "qty_confirmed": float(r[5]),
        "qty_stock":     float(r[6]),
    } for r in rows]


@router.get("/consulting/items/{item_id}/stock")
def item_stock(item_id: str):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                i.WHID,
                ISNULL(w.WHDesc, '')       AS wh_desc,
                i.LocationID,
                ISNULL(l.LocationDesc, '') AS loc_desc,
                i.Qty
            FROM Inventory i
            LEFT JOIN Warehouses w ON w.WHID = i.WHID
            LEFT JOIN Locations  l ON l.LocationID = i.LocationID
            WHERE i.ItemID = ? AND i.Qty > 0
            ORDER BY i.WHID, i.LocationID
        """, (item_id,))
        rows = cursor.fetchall()

    return [{
        "wh_id":   r[0],
        "wh_desc": r[1],
        "loc_id":  r[2],
        "loc_desc":r[3],
        "qty":     float(r[4]),
    } for r in rows]


@router.get("/consulting/packings/{order_id}/boxes/{vol_num}/movements")
def box_movements(order_id: int, vol_num: int):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                sm.MovDateTime,
                sm.ItemID,
                ISNULL(im.ItemDesc, '') AS item_desc,
                sm.MovType,
                sm.WHIDOrig,
                sm.LocOrig,
                sm.WHIDDest,
                sm.LocDest,
                sm.Qty
            FROM StockMov sm
            LEFT JOIN ItemMaster im ON im.ItemID = sm.ItemID
            WHERE sm.VolNum = ?
            ORDER BY sm.MovDateTime DESC
        """, (str(vol_num),))
        rows = cursor.fetchall()

    return [{
        "mov_date":  str(r[0])[:19] if r[0] else None,
        "item_id":   r[1],
        "item_desc": r[2],
        "mov_type":  r[3],
        "wh_orig":   r[4],
        "loc_orig":  r[5],
        "wh_dest":   r[6],
        "loc_dest":  r[7],
        "qty":       float(r[8] or 0),
    } for r in rows]


@router.get("/consulting/packings/{order_id}/export")
def export_packing(order_id: int, doc_type: str = "PSCP"):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT OrderID, Obs, ISNULL(RequesterID,'') FROM ClientOrders WHERE OrderID = ? AND DocType = ?
        """, (order_id, doc_type))
        header = cursor.fetchone()
        if not header:
            raise HTTPException(404, "Packing não encontrado")
        doc_num, obs, requester_id = header

        # Export por caixa: VolNum, VolNum2N, ItemID, ClientRef, QtyIni, QtyConf
        cursor.execute("""
            SELECT
                vm.VolNum AS VolDocNum,
                ISNULL(vm.VolNum2N, '')   AS barcode,
                vi.ItemID,
                ISNULL(im.ClientRef, '')  AS client_ref,
                ISNULL(vi.ItemQtyIni, 0)  AS qty_initial,
                ISNULL(vi.ItemQty, 0)     AS qty_confirmed
            FROM VolMaster vm
            JOIN VolItem vi ON vi.VolNum = vm.VolNum
            LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
            WHERE vm.ParentDocType = ? AND vm.ParentOrderID = ? AND vm.VolDocCod = 'CX'
            ORDER BY vm.VolNum, vi.ItemID
        """, (doc_type, order_id))
        lines = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["NrCaixa", "NrCaixaOriginal", "ItemID", "RefCliente", "QtyPrevista", "QtyConfirmada"])
    for line in lines:
        vol_doc_num, barcode, item_id, client_ref, qty_ini, qty_conf = line
        writer.writerow([vol_doc_num, barcode, item_id, client_ref,
                         f"{float(qty_ini):.0f}", f"{float(qty_conf):.0f}"])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename=Packing-{doc_num}-{requester_id}.csv'}
    )

@router.get("/consulting/packings/{order_id}/boxes")
def packing_boxes(order_id: int, doc_type: str = "PSCP"):
    """Lista caixas do packing com artigos, qty inicial, confirmada e stock."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                vm.VolNum,
                ISNULL(vm.VolNum2N, '')     AS barcode,
                vm.VolVerified,
                ISNULL(vm.VolStatus, '')    AS vol_status
            FROM VolMaster vm
            WHERE vm.ParentDocType = ? AND vm.ParentOrderID = ? AND vm.VolDocCod = 'CX'
            ORDER BY vm.VolNum
        """, (doc_type, order_id,))
        boxes = cursor.fetchall()

    result = []
    for box in boxes:
        vol_num, barcode, verified, vol_status = box

        with db_cursor() as (c2, _):
            c2.execute("""
                SELECT
                    vi.ItemID,
                    ISNULL(im.ItemDesc, '')  AS item_desc,
                    ISNULL(im.ClientRef, '') AS client_ref,
                    ISNULL(vi.ItemQtyIni, 0) AS qty_initial,
                    ISNULL(vi.ItemQty, 0)    AS qty_confirmed,
                    ISNULL(
                        (SELECT SUM(i.Qty) FROM Inventory i WHERE i.ItemID = vi.ItemID),
                    0) AS qty_stock
                FROM VolItem vi
                LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
                WHERE vi.VolNum = ?
                ORDER BY vi.ItemID
            """, (vol_num,))
            items = c2.fetchall()

        result.append({
            "vol_num":    vol_num,
            "barcode":    barcode,
            "verified":   bool(verified),
            "vol_status": vol_status,
            "items": [{
                "item_id":       r[0],
                "item_desc":     r[1],
                "client_ref":    r[2],
                "qty_initial":   float(r[3]),
                "qty_confirmed": float(r[4]),
                "qty_stock":     float(r[5]),
            } for r in items],
        })
    return result


@router.get("/consulting/packings/{order_id}/boxes/{vol_num}/items/{item_id}/movements")
def item_box_movements(order_id: int, vol_num: int, item_id: str):
    """Movimentos StockMov para um artigo numa caixa específica."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                sm.MovDateTime,
                sm.ItemID,
                ISNULL(im.ItemDesc, '') AS item_desc,
                sm.MovType,
                sm.WHIDOrig,
                sm.LocOrig,
                sm.WHIDDest,
                sm.LocDest,
                sm.Qty
            FROM StockMov sm
            LEFT JOIN ItemMaster im ON im.ItemID = sm.ItemID
            WHERE sm.VolNum = ? AND sm.ItemID = ?
            ORDER BY sm.MovDateTime DESC
        """, (str(vol_num), item_id))
        rows = cursor.fetchall()

    return [{
        "mov_date":  str(r[0])[:19] if r[0] else None,
        "item_id":   r[1],
        "item_desc": r[2],
        "mov_type":  r[3],
        "wh_orig":   r[4],
        "loc_orig":  r[5],
        "wh_dest":   r[6],
        "loc_dest":  r[7],
        "qty":       float(r[8] or 0),
    } for r in rows]

@router.get("/consulting/packings/{order_id}/export-totals")
def export_packing_totals(order_id: int, doc_type: str = "PSCP"):
    """Exporta totais por artigo de um packing list."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT OrderID, ISNULL(RequesterID,'') FROM ClientOrders WHERE OrderID = ? AND DocType = ?
        """, (order_id, doc_type))
        header = cursor.fetchone()
        if not header:
            raise HTTPException(404, "Packing não encontrado")
        doc_num, requester_id = header

        cursor.execute("""
            SELECT
                vi.ItemID,
                ISNULL(im.ClientRef, '')   AS client_ref,
                SUM(ISNULL(vi.ItemQtyIni, 0)) AS qty_initial,
                SUM(ISNULL(vi.ItemQty, 0))    AS qty_confirmed
            FROM VolMaster vm
            JOIN VolItem vi ON vi.VolNum = vm.VolNum
            LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
            WHERE vm.ParentDocType = ? AND vm.ParentOrderID = ? AND vm.VolDocCod = 'CX'
            GROUP BY vi.ItemID, im.ClientRef
            ORDER BY vi.ItemID
        """, (doc_type, order_id))
        lines = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["ItemID", "RefCliente", "QtyPrevista", "QtyConfirmada"])
    for line in lines:
        item_id, client_ref, qty_ini, qty_conf = line
        writer.writerow([item_id, client_ref,
                         f"{float(qty_ini):.0f}", f"{float(qty_conf):.0f}"])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename=Packing-{doc_num}-{requester_id}-totais.csv'}
    )
