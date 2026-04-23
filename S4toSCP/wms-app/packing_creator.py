from datetime import datetime
from app.db.connection import db_cursor
from app.models.schemas import CSVRow, CSVHeader, PackingCreated


def _next_order_id(cursor) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        "SELECT ISNULL(MAX(OrderID), ?) FROM ClientOrder WHERE OrderID >= ? AND DocType = 'PKL'",
        (base, base)
    )
    last = cursor.fetchone()[0]
    return last + 1


def _next_vol_num(cursor) -> int:
    cursor.execute("SELECT ISNULL(MAX(VolNum), 0) + 1 FROM VolMaster")
    return cursor.fetchone()[0]


def create_packing(
    client_id: str,
    rows: list[CSVRow],
    header: CSVHeader,
) -> PackingCreated:

    with db_cursor() as (cursor, conn):

        # ── 1. Cabeçalho ClientOrder ───────────────────────────────────────────
        order_id = _next_order_id(cursor)
        delivery_date = datetime.strptime(header.delivery_date, "%d/%m/%Y")
        obs = f"Doc: {header.doc_num} | Ref: {header.ref_supplier}"

        cursor.execute("""
            INSERT INTO ClientOrder (
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
                'PKL', ?, 0,
                GETDATE(), ?, ?,
                1, 'AI', GETDATE(),
                ?, 'EUR', 1,
                ?, ?,
                0, 0, 0, 0,
                0, 0,
                0, 0,
                'C'
            )
        """, (
            order_id,
            header.doc_num,
            client_id,
            obs,
            header.total_qty,
            delivery_date,
        ))

        # ── 2. Linhas ClientOrderDetails (por ItemID + país) ──────────────────
        detail_map: dict[tuple, dict] = {}
        for r in rows:
            key = (r.item_id, r.country)
            if key not in detail_map:
                detail_map[key] = {
                    "qty": 0,
                    "num_boxes": 0,
                    "color_id": r.color_code,
                    "size": r.size,
                }
            detail_map[key]["qty"]       += r.qty_box
            detail_map[key]["num_boxes"] += 1

        order_row = 1
        row_map: dict[tuple, int] = {}

        for (item_id, country), info in detail_map.items():
            cursor.execute("""
                INSERT INTO ClientOrderDetails (
                    DocType, OrderID, OrderRow, PartNum, VolNum,
                    ItemID, QtyOrd, QtySatisf, QtyPend, QtyPicked,
                    QtyVols, Status, ProductionStatus,
                    CreationUser, CreationDateTime,
                    UnitPrice, TotValue,
                    ColorID, QtyProd,
                    VariationCountry
                ) VALUES (
                    'PKL', ?, ?, 0, 0,
                    ?, ?, 0, 0, 0,
                    ?, 1, 'INICIAL',
                    'AI', GETDATE(),
                    0, 0,
                    ?, 0,
                    ?
                )
            """, (
                order_id, order_row,
                item_id, info["qty"],
                info["num_boxes"],
                info["color_id"],
                country,
            ))
            row_map[(item_id, country)] = order_row
            order_row += 1

        # ── 3. Caixas VolMaster + VolItem ─────────────────────────────────────
        box_map: dict[str, list[CSVRow]] = {}
        for r in rows:
            box_map.setdefault(r.box_barcode, []).append(r)

        total_boxes = 0
        for barcode, box_rows in box_map.items():
            vol_num = _next_vol_num(cursor)

            if len(box_rows) == 1:
                r0 = box_rows[0]
                parent_row = row_map.get((r0.item_id, r0.country), 0)
            else:
                parent_row = 0

            cursor.execute("""
                INSERT INTO VolMaster (
                    VolDocCod, VolNum, VolTypeID,
                    VolWeight, VolLenght, VolHeight, VolWidht,
                    VolArtWeight, NumVolOrder, NumVolOrderLine, VolVolume,
                    ParentDocType, ParentOrderID, ParentOrderRow,
                    VolStatus, VolNum2N,
                    CreationDate, VolReady, VolVerified,
                    CreationUser
                ) VALUES (
                    'CX', ?, 'CXSCP',
                    0, 0, 0, 0,
                    0, 0, 0, 0,
                    'PKL', ?, ?,
                    'INICIAL', ?,
                    GETDATE(), 1, 0,
                    'AI'
                )
            """, (vol_num, order_id, parent_row, barcode))

            vol_item_num = 1
            for r in box_rows:
                detail_row = row_map.get((r.item_id, r.country), 0)
                cursor.execute("""
                    INSERT INTO VolItem (
                        VolDocCod, VolNum, VolItemNumber,
                        ItemID, ItemQty,
                        ItemWeight, ItemWidth, ItemHeight, ItemLength, ItemVolume,
                        ParentDocType, ParentOrderID, ParentOrderRow,
                        ColorID, SizeId, VariationCountry,
                        CreationDate, CreationUser
                    ) VALUES (
                        'CX', ?, ?,
                        ?, ?,
                        0, 0, 0, 0, 0,
                        'PKL', ?, ?,
                        ?, ?, ?,
                        GETDATE(), 'AI'
                    )
                """, (
                    vol_num, vol_item_num,
                    r.item_id, r.qty_box,
                    order_id, detail_row,
                    r.color_code, r.size, r.country,
                ))
                vol_item_num += 1

            total_boxes += 1

        # ── 4. Validação final ─────────────────────────────────────────────────
        created_qty = sum(info["qty"] for info in detail_map.values())
        qty_match = (created_qty == header.total_qty)

        return PackingCreated(
            order_id    = order_id,
            client_id   = client_id,
            total_qty   = created_qty,
            total_boxes = total_boxes,
            total_lines = len(detail_map),
            qty_match   = qty_match,
        )
