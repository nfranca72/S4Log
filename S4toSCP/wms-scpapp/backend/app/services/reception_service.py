from __future__ import annotations
from app.db.connection import db_cursor
from app.models.schemas import (
    PackingListSummary, BoxSummary, BoxDetail, BoxItem,
    WarehouseInfo, LocationInfo, ConfirmBoxRequest, ConfirmBoxResult,
    CancelBoxConfirmationResult, CountingKnownItemSummary, CountingSnapshot
)
from app.services.label_printing import print_volume_label


def _clean_tags(tags: list[str]) -> list[str]:
    clean = []
    seen = set()
    for tag in tags or []:
        value = str(tag or '').strip()
        if value and value not in seen:
            clean.append(value)
            seen.add(value)
    return clean


def _existing_rfid_tags(cursor, tags: list[str]) -> set[str]:
    if not tags:
        return set()

    placeholders = ",".join("?" for _ in tags)
    cursor.execute(
        f"SELECT TAG FROM ItemMasterRFIDTags WHERE TAG IN ({placeholders})",
        tags,
    )
    return {str(row[0]).strip() for row in cursor.fetchall() if row[0]}


def summarize_counting_tags(tags: list[str], tunnel_id: int) -> CountingSnapshot:
    clean_tags = _clean_tags(tags)
    if not clean_tags:
        return CountingSnapshot(tunnel_id=tunnel_id, total_tags=0, known_tags=0, new_tags=0)

    placeholders = ",".join("?" for _ in clean_tags)
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"""
            SELECT
                rt.TAG,
                ISNULL(rt.ItemID, '') AS ItemID,
                ISNULL(im.ItemDesc, '') AS ItemDesc,
                ISNULL(im.ClientRef, '') AS ClientRef,
                ISNULL(im.Barcode, '') AS Barcode
            FROM ItemMasterRFIDTags rt
            LEFT JOIN ItemMaster im ON im.ItemID = rt.ItemID
            WHERE ISNULL(rt.deleted, 0) = 0
              AND rt.TAG IN ({placeholders})
            """,
            clean_tags,
        )
        rows = cursor.fetchall()

    known_by_tag = {}
    items = {}
    for row in rows:
        tag = str(row[0] or "").strip()
        if not tag:
            continue
        known_by_tag[tag] = True
        key = (
            str(row[1] or "").strip(),
            str(row[2] or "").strip(),
            str(row[3] or "").strip(),
            str(row[4] or "").strip(),
        )
        items[key] = items.get(key, 0) + 1

    known_items = [
        CountingKnownItemSummary(
            item_id=item_id,
            item_desc=item_desc,
            client_ref=client_ref,
            barcode=barcode,
            qty_counted=qty_counted,
        )
        for (item_id, item_desc, client_ref, barcode), qty_counted in sorted(
            items.items(),
            key=lambda entry: (-entry[1], entry[0][0], entry[0][2], entry[0][3]),
        )
    ]
    new_tag_list = [tag for tag in clean_tags if tag not in known_by_tag]

    return CountingSnapshot(
        tunnel_id=tunnel_id,
        total_tags=len(clean_tags),
        known_tags=len(clean_tags) - len(new_tag_list),
        new_tags=len(new_tag_list),
        known_items=known_items,
        new_tag_list=new_tag_list,
    )


def get_packing_lists() -> list[PackingListSummary]:
    """Lista packings PKL com totais e estado de conferência."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                o.OrderID,
                o.ClientID,
                o.DeliveryDate,
                o.Obs,
                o.TotalQtyOrd,
                COUNT(v.VolNum)                                    AS TotalBoxes,
                SUM(CASE WHEN v.VolVerified = 1 THEN 1 ELSE 0 END) AS VerifiedBoxes,
                ISNULL(SUM(vi.ItemQty), 0)                         AS TotalQtyReceived
            FROM ClientOrders o
            LEFT JOIN VolMaster v ON v.ParentOrderID = o.OrderID AND v.ParentDocType = 'PSCP'
            LEFT JOIN VolItem vi  ON vi.VolNum = v.VolNum AND vi.VolDocCod = 'CX'
                                  AND v.VolVerified = 1
            WHERE o.DocType = 'PSCP'
            GROUP BY o.OrderID, o.ClientID, o.DeliveryDate, o.Obs, o.TotalQtyOrd
            ORDER BY o.OrderID DESC
        """)
        rows = cursor.fetchall()

    result = []
    for r in rows:
        total_boxes    = r[5] or 0
        verified_boxes = r[6] or 0
        total_qty      = int(r[4] or 0)
        qty_received   = int(r[7] or 0)

        if verified_boxes == 0:
            status = "pendente"
        elif verified_boxes == total_boxes:
            status = "conferido"
        else:
            status = "parcial"

        result.append(PackingListSummary(
            order_id       = r[0],
            client_id      = r[1],
            delivery_date  = str(r[2])[:10] if r[2] else None,
            obs            = r[3],
            total_qty      = total_qty,
            qty_received   = qty_received,
            total_boxes    = total_boxes,
            verified_boxes = verified_boxes,
            status         = status,
        ))
    return result


def get_boxes(order_id: int) -> list[BoxSummary]:
    """Lista caixas de um packing com estado."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                v.VolNum,
                v.VolNum2N,
                v.VolVerified,
                v.VolStatus,
                COUNT(vi.VolItemNumber)                             AS TotalItems,
                ISNULL(SUM(vi.ItemQtyIni), 0)                      AS QtyExpected,
                ISNULL(SUM(vi.ItemQty), 0)                         AS QtyReceived,
                v.VolReady
            FROM VolMaster v
            LEFT JOIN VolItem vi ON vi.VolNum = v.VolNum AND vi.VolDocCod = 'CX'
            WHERE v.ParentOrderID = ? AND v.ParentDocType = 'PSCP'
            GROUP BY v.VolNum, v.VolNum2N, v.VolVerified, v.VolStatus, v.VolReady
            ORDER BY v.VolNum
        """, (order_id,))
        rows = cursor.fetchall()

    result = []
    for r in rows:
        verified = bool(r[2])
        status   = str(r[3] or '')

        if verified and 'INCIDENCIA' in status.upper():
            box_status = "incidencia"
        elif verified:
            box_status = "conferida"
        elif status == 'INICIAL':
            box_status = "pendente"
        else:
            box_status = "parcial"

        result.append(BoxSummary(
            vol_num      = r[0],
            barcode      = str(r[1]) if r[1] else '',
            status       = box_status,
            total_items  = r[4] or 0,
            qty_expected = int(r[5] or 0),
            qty_received = int(r[6] or 0),
        ))
    return result


def get_box_detail(vol_num: int):
    """Detalhe de uma caixa com artigos."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT v.VolNum, v.VolNum2N, v.VolVerified, v.VolStatus,
                   v.ParentOrderID
            FROM VolMaster v
            WHERE v.VolNum = ? AND v.VolDocCod = 'CX'
        """, (vol_num,))
        row = cursor.fetchone()
        if not row:
            return None

        verified = bool(row[2])

        cursor.execute("""
            SELECT
                vi.VolItemNumber,
                vi.ItemID,
                vi.ItemQty,
                vi.ColorID,
                vi.SizeId,
                vi.VariationCountry,
                im.ItemDesc,
                vi.ItemQtyIni
            FROM VolItem vi
            LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
            WHERE vi.VolNum = ? AND vi.VolDocCod = 'CX'
            ORDER BY vi.VolItemNumber
        """, (vol_num,))
        items = cursor.fetchall()

    box_items = [
        BoxItem(
            vol_item_number = i[0],
            item_id         = i[1],
            item_desc       = i[6] or '',
            qty_expected    = int(i[7] or 0),
            qty_read        = int(i[2] or 0) if verified else 0,
            color_id        = i[3] or '',
            size_id         = i[4] or '',
            country         = i[5] or '',
        )
        for i in items
    ]

    return BoxDetail(
        vol_num    = row[0],
        barcode    = str(row[1]) if row[1] else '',
        verified   = bool(row[2]),
        status     = str(row[3] or ''),
        order_id   = row[4],
        items      = box_items,
    )


def get_warehouses() -> list[WarehouseInfo]:
    with db_cursor() as (cursor, _):
        cursor.execute("SELECT WHID, WHDesc FROM Warehouses ORDER BY WHDesc")
        return [WarehouseInfo(wh_id=r[0], wh_desc=r[1]) for r in cursor.fetchall()]


def get_locations(wh_id: int) -> list[LocationInfo]:
    with db_cursor() as (cursor, _):
        cursor.execute(
            "SELECT LocationID, LocationDesc FROM Locations WHERE WHID = ? ORDER BY LocationID",
            (wh_id,)
        )
        return [LocationInfo(location_id=r[0], location_desc=r[1] or r[0]) for r in cursor.fetchall()]


def confirm_box(
    vol_num: int,
    req: ConfirmBoxRequest,
    station_identifier: str | None = None,
) -> ConfirmBoxResult:
    """
    Confirma uma caixa apos conferencia.
    As TAGs ja existentes em ItemMasterRFIDTags nao contam para nova entrada.
    """
    result_payload: dict[str, object] | None = None
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT vi.VolItemNumber, vi.ItemID, vi.ItemQty, vi.ItemQtyIni,
                   vi.ColorID, vi.SizeId, vi.VariationCountry,
                   v.ParentOrderID, vi.ParentOrderRow,
                   ISNULL(im.StkUnit, 'UN') AS StkUnit,
                   v.VolNum2N,
                   v.VolVerified
            FROM VolItem vi
            JOIN VolMaster v ON v.VolNum = vi.VolNum
            LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
            WHERE vi.VolNum = ? AND vi.VolDocCod = 'CX'
        """, (vol_num,))
        items = cursor.fetchall()

        if not items:
            return ConfirmBoxResult(success=False, message="Caixa nao encontrada")

        if bool(items[0][11]):
            return ConfirmBoxResult(success=False, message="Caixa ja conferida")

        order_id = items[0][7]
        vol_num_reference = str(items[0][10] or '')
        has_incident = False

        item_tags_map = {}
        for item_key, tags in (req.item_tags or {}).items():
            clean_tags = _clean_tags(tags)
            if clean_tags:
                item_tags_map[str(item_key)] = clean_tags
        if not item_tags_map and req.rfid_tags and len(items) == 1:
            item_tags_map[str(items[0][0])] = _clean_tags(req.rfid_tags)

        all_tags = []
        for tags in item_tags_map.values():
            all_tags.extend(tags)
        existing_tags = _existing_rfid_tags(cursor, _clean_tags(all_tags))
        accepted_tags_map = {
            item_id: [tag for tag in tags if tag not in existing_tags]
            for item_id, tags in item_tags_map.items()
        }

        qty_by_line: dict[int, int] = {}
        qty_by_item: dict[str, int] = {}
        mov_id_by_line: dict[int, int | None] = {}
        mov_id_by_item: dict[str, int | None] = {}

        for item in items:
            item_num = item[0]
            item_id = item[1]
            line_key = str(item_num)
            qty_exp = int(item[3] or 0)
            color_id = item[4] or ''
            size_id = item[5] or ''
            country = item[6] or ''
            doc_row = int(item[8] or 0)
            stk_unit = item[9] or 'UN'

            accepted_tags = accepted_tags_map.get(line_key) or accepted_tags_map.get(str(item_id))
            if accepted_tags:
                qty_read = len(accepted_tags)
            else:
                qty_read = int(
                    req.item_quantities.get(line_key, req.item_quantities.get(item_id, 0)) or 0
                )
            qty_by_line[item_num] = qty_read
            qty_by_item[item_id] = qty_by_item.get(item_id, 0) + qty_read

            if qty_read != qty_exp:
                has_incident = True

            cursor.execute("""
                UPDATE VolItem
                SET ItemQty = ?
                WHERE VolNum = ? AND VolItemNumber = ? AND VolDocCod = 'CX'
            """, (qty_read, vol_num, item_num))

            mov_id_by_line[item_num] = None
            mov_id_by_item[item_id] = None
            if qty_read > 0:
                cursor.execute("""
                    SELECT Qty FROM Inventory
                    WHERE WHID = ? AND LocationID = ? AND ItemID = ?
                      AND VolNum = ? AND ColorID = ? AND SizeID = ?
                      AND ISNULL(Country, '') = ''
                """, (req.wh_id, req.location_id, item_id,
                      str(vol_num), '', ''))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute("""
                        UPDATE Inventory
                        SET Qty = Qty + ?, LastInput = GETDATE()
                        WHERE WHID = ? AND LocationID = ? AND ItemID = ?
                          AND VolNum = ? AND ColorID = ? AND SizeID = ?
                          AND ISNULL(Country, '') = ''
                    """, (qty_read, req.wh_id, req.location_id, item_id,
                          str(vol_num), '', ''))
                else:
                    cursor.execute("""
                        INSERT INTO Inventory (
                            WHID, LocationID, ItemID,
                            Lot, SerialNum, Qty,
                            LastInput, Version, VolNum,
                            ColorID, SizeID, Country
                        ) VALUES (
                            ?, ?, ?,
                            '', '', ?,
                            GETDATE(), 0, ?,
                            ?, ?, ?
                        )
                    """, (req.wh_id, req.location_id, item_id,
                          qty_read, str(vol_num), '', '', ''))

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
                        0, ?,
                        '', ?,
                        GETDATE(),
                        ?, '', '', ?, ?,
                        'PSCP', ?, ?,
                        'I', '',
                        'AI', GETDATE(),
                        0, 0, '', '', '',
                        1, 1, 0, ?,
                        ?, ?, ?
                    )
                """, (
                    req.wh_id,
                    req.location_id,
                    item_id,
                    qty_read,
                    stk_unit,
                    str(order_id),
                    doc_row,
                    str(vol_num),
                    color_id,
                    size_id,
                    country,
                ))
                mov_row = cursor.fetchone()
                mov_id = mov_row[0] if mov_row else None
                mov_id_by_line[item_num] = mov_id
                mov_id_by_item[item_id] = mov_id

        if accepted_tags_map:
            item_context = {
                str(item[0]): {
                    "item_id": item[1],
                    "color_id": item[4] or '',
                    "size_id": item[5] or '',
                    "country": item[6] or '',
                    "doc_row": int(item[8] or 0),
                }
                for item in items
            }
            item_context.update({
                item[1]: {
                    "item_id": item[1],
                    "color_id": item[4] or '',
                    "size_id": item[5] or '',
                    "country": item[6] or '',
                    "doc_row": int(item[8] or 0),
                }
                for item in items
            })

            for item_key, tags in accepted_tags_map.items():
                ctx = item_context.get(str(item_key), {})
                item_id = ctx.get("item_id", item_key)
                mov_id = (
                    mov_id_by_line.get(int(item_key))
                    if str(item_key).isdigit()
                    else mov_id_by_item.get(item_id)
                )
                for tag in tags:
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM ItemMasterRFIDTags WHERE TAG = ?)
                        INSERT INTO ItemMasterRFIDTags (
                            ItemID, ColorID, GridID, OrderNum, SizeID,
                            TAG, available, deleted, created_by, created_date
                        ) VALUES (
                            ?, ?, '', ?, ?,
                            ?, 1, 0, 'AI', GETDATE()
                        )
                    """, (
                        tag,
                        item_id,
                        ctx.get("color_id", ''),
                        order_id,
                        ctx.get("size_id", ''),
                        tag,
                    ))

                    cursor.execute("""
                        INSERT INTO ItemRFIDControlRegister (
                            ItemID, Lot, LocationID, WhID,
                            SerialNum, RFIDTAG,
                            Qty, QtyRFID, QtyCruzetas,
                            [Date], MovDir, MovID,
                            deleted, created_by, created_date,
                            VolNum, DocType, OrderID, OrderRow,
                            [Version], ColorID, SizeID, Country
                        ) VALUES (
                            ?, '', ?, ?,
                            '0', ?,
                            1, 1, 0,
                            GETDATE(), 'I', ?,
                            0, 'AI', GETDATE(),
                            ?, 'PSCP', ?, ?,
                            0, ?, ?, ?
                        )
                    """, (
                        item_id,
                        req.location_id,
                        req.wh_id,
                        tag,
                        mov_id,
                        str(vol_num),
                        order_id,
                        ctx.get("doc_row", 0),
                        ctx.get("color_id", ''),
                        ctx.get("size_id", ''),
                        ctx.get("country", ''),
                    ))

        total_qty_read = sum(qty_by_item.values())
        if total_qty_read > 0:
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM InventoryVolNums WHERE VolNum = ?)
                INSERT INTO InventoryVolNums (
                    VolNum, VolNumReference,
                    VolWeight, VolLenght, VolHeight, VolWidht, VolArtWeight,
                    ItemQty,
                    CreationUser, CreationDate
                ) VALUES (
                    ?, ?,
                    0, 0, 0, 0, 0,
                    ?,
                    'IA', GETDATE()
                )
            """, (
                vol_num,
                vol_num,
                vol_num_reference,
                total_qty_read,
            ))

        new_status = 'CAIXA COM INCIDENCIAS' if has_incident else 'CONFERIDA'
        cursor.execute("""
            UPDATE VolMaster
            SET VolVerified = 1, VolVerifiedDate = GETDATE(), VolStatus = ?
            WHERE VolNum = ? AND VolDocCod = 'CX'
        """, (new_status, vol_num))

        for item in items:
            item_id = item[1]
            country = item[6] or ''
            qty_read = qty_by_line.get(item[0], 0)
            cursor.execute("""
                UPDATE ClientOrderDetails
                SET QtySatisf = ISNULL(QtySatisf, 0) + ?
                WHERE OrderID = ? AND ItemID = ? AND VariationCountry = ?
                  AND DocType = 'PSCP'
            """, (qty_read, order_id, item_id, country))

        import logging
        _log = logging.getLogger(__name__)
        _log.info(
            "confirm_box: vol_num=%s order_id=%s escp_order_id=%s items=%s ignored_tags=%s",
            vol_num,
            order_id,
            req.escp_order_id,
            [(i[0], i[1], qty_by_line.get(i[0], 0)) for i in items],
            len(existing_tags),
        )

        cursor.execute("""
            SELECT TOP 1 OrderIDOri
            FROM ClientOrderDetailsOri
            WHERE DocType    = 'PSCP'
              AND OrderID    = ?
              AND DocTypeOri = 'ESCP'
        """, (order_id,))
        ori_row = cursor.fetchone()
        escp_order_id = ori_row[0] if ori_row else req.escp_order_id

        _log.info("ESCP encontrada via ClientOrderDetailsOri: %s", escp_order_id)

        if escp_order_id:
            for item in items:
                item_id = item[1]
                qty_remaining = qty_by_line.get(item[0], 0)
                if qty_remaining <= 0:
                    continue

                cursor.execute("""
                    SELECT OrderRow, QtyOrd, ISNULL(QtySatisf, 0)
                    FROM ClientOrderDetails
                    WHERE OrderID = ? AND ItemID = ? AND DocType = 'ESCP'
                    ORDER BY OrderRow ASC
                """, (escp_order_id, item_id))
                escp_lines = cursor.fetchall()

                _log.info("Artigo %s: qty_remaining=%s escp_lines=%s", item_id, qty_remaining, escp_lines)

                if not escp_lines:
                    continue

                for idx, (order_row, qty_ord, qty_satisf) in enumerate(escp_lines):
                    is_last = (idx == len(escp_lines) - 1)
                    qty_ord = int(qty_ord or 0)
                    qty_satisf = int(qty_satisf or 0)

                    if not is_last:
                        available = max(0, qty_ord - qty_satisf)
                        if available <= 0:
                            continue
                        to_add = min(qty_remaining, available)
                        qty_remaining -= to_add
                    else:
                        to_add = qty_remaining
                        qty_remaining = 0

                    if to_add > 0:
                        _log.info("  -> ESCP OrderRow=%s to_add=%s", order_row, to_add)
                        cursor.execute("""
                            UPDATE ClientOrderDetails
                            SET QtySatisf = ISNULL(QtySatisf, 0) + ?
                            WHERE OrderID = ? AND ItemID = ? AND DocType = 'ESCP'
                              AND OrderRow = ?
                        """, (to_add, escp_order_id, item_id, order_row))

                    if qty_remaining <= 0:
                        break

        result_payload = {
            "success": True,
            "has_incident": has_incident,
            "message": 'CAIXA COM INCIDENCIAS' if has_incident else 'CONFERIDA',
            "order_id": order_id,
        }

    print_result = {
        "attempted": False,
        "printed": False,
        "message": "",
    }
    try:
        print_result = print_volume_label(vol_num, station_identifier=station_identifier)
    except Exception as exc:
        print_result = {
            "attempted": True,
            "printed": False,
            "message": str(exc),
        }

    return ConfirmBoxResult(
        success=bool(result_payload["success"]) if result_payload else False,
        has_incident=bool(result_payload["has_incident"]) if result_payload else False,
        message=str(result_payload["message"]) if result_payload else "Erro a confirmar caixa",
        order_id=int(result_payload["order_id"]) if result_payload and result_payload.get("order_id") is not None else None,
        print_attempted=bool(print_result["attempted"]),
        print_success=bool(print_result["printed"]),
        print_message=str(print_result["message"] or ""),
    )


def cancel_box_confirmation(vol_num: int, expected_order_id: int | None = None) -> CancelBoxConfirmationResult:
    """
    Reverte a entrada de stock de uma caixa ja conferida.
    Volta a caixa a INICIAL, limpa quantidades confirmadas, remove stock do volume
    e grava StockMov com quantidade negativa.
    """
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT VolNum, ParentOrderID, VolVerified, VolStatus, VolNum2N
            FROM VolMaster
            WHERE VolNum = ? AND VolDocCod = 'CX'
        """, (vol_num,))
        box = cursor.fetchone()
        if not box:
            return CancelBoxConfirmationResult(success=False, message="Caixa nao encontrada")
        if not bool(box[2]):
            return CancelBoxConfirmationResult(success=False, message="Caixa ainda nao esta conferida")

        order_id = box[1]
        if expected_order_id is not None and int(order_id) != int(expected_order_id):
            return CancelBoxConfirmationResult(success=False, message="Caixa nao pertence ao packing indicado")

        cursor.execute("""
            SELECT
                vi.VolItemNumber,
                vi.ItemID,
                ISNULL(vi.ItemQty, 0) AS ItemQty,
                ISNULL(vi.ColorID, '') AS ColorID,
                ISNULL(vi.SizeId, '') AS SizeID,
                ISNULL(vi.VariationCountry, '') AS Country,
                ISNULL(vi.ParentOrderRow, 0) AS ParentOrderRow,
                ISNULL(im.StkUnit, 'UN') AS StkUnit
            FROM VolItem vi
            LEFT JOIN ItemMaster im ON im.ItemID = vi.ItemID
            WHERE vi.VolNum = ? AND vi.VolDocCod = 'CX'
            ORDER BY vi.VolItemNumber
        """, (vol_num,))
        items = cursor.fetchall()

        if not items:
            return CancelBoxConfirmationResult(success=False, message="Caixa sem linhas para anular")

        cursor.execute("""
            SELECT WHID, LocationID, ItemID, ISNULL(Qty, 0)
            FROM Inventory
            WHERE VolNum = ?
        """, (str(vol_num),))
        inventory_rows = cursor.fetchall()
        inventory_qty_by_item: dict[str, int] = {}
        for row in inventory_rows:
            item_id = str(row[2])
            inventory_qty_by_item[item_id] = inventory_qty_by_item.get(item_id, 0) + int(row[3] or 0)

        insufficient = []
        for item in items:
            item_id = str(item[1])
            qty_read = int(item[2] or 0)
            if qty_read <= 0:
                continue

            qty_stock = inventory_qty_by_item.get(item_id, 0)
            if qty_stock < qty_read:
                insufficient.append(f"{item_id}: stock {qty_stock}, necessario {qty_read}")

        if insufficient:
            return CancelBoxConfirmationResult(
                success=False,
                message="Stock insuficiente para anular a entrada da caixa. " + "; ".join(insufficient),
            )

        location_by_item = {
            str(row[2]): {"wh_id": row[0], "location_id": row[1]}
            for row in inventory_rows
        }

        for item in items:
            item_id = item[1]
            qty_read = int(item[2] or 0)
            if qty_read <= 0:
                continue

            location = location_by_item.get(str(item_id), {})
            wh_id = location.get("wh_id", 0)
            location_id = location.get("location_id", "")

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
                ) VALUES (
                    ?, 0,
                    ?, '',
                    GETDATE(),
                    ?, '', '', ?, ?,
                    'PSCP', ?, ?,
                    'O', '',
                    'AI', GETDATE(),
                    0, 0, 'Anulacao entrada caixa', '', '',
                    1, 1, 0, ?,
                    ?, ?, ?
                )
            """, (
                wh_id,
                location_id,
                item_id,
                -qty_read,
                item[7],
                str(order_id),
                int(item[6] or 0),
                str(vol_num),
                item[3],
                item[4],
                item[5],
            ))

            cursor.execute("""
                UPDATE ClientOrderDetails
                SET QtySatisf = CASE
                    WHEN ISNULL(QtySatisf, 0) >= ? THEN ISNULL(QtySatisf, 0) - ?
                    ELSE 0
                END
                WHERE OrderID = ? AND ItemID = ? AND VariationCountry = ?
                  AND DocType = 'PSCP'
            """, (qty_read, qty_read, order_id, item_id, item[5]))

            _reverse_escp_satisfaction(cursor, order_id, int(item[6] or 0), item_id, qty_read)

        cursor.execute("""
            DELETE tags
            FROM ItemMasterRFIDTags tags
            JOIN ItemRFIDControlRegister reg ON reg.RFIDTAG = tags.TAG
            WHERE reg.VolNum = ?
              AND reg.DocType = 'PSCP'
              AND reg.OrderID = ?
        """, (str(vol_num), order_id))
        cursor.execute("""
            DELETE FROM ItemRFIDControlRegister
            WHERE VolNum = ? AND DocType = 'PSCP' AND OrderID = ?
        """, (str(vol_num), order_id))

        cursor.execute("DELETE FROM Inventory WHERE VolNum = ?", (str(vol_num),))
        cursor.execute("DELETE FROM InventoryVolNums WHERE VolNum = ?", (vol_num,))

        cursor.execute("""
            UPDATE VolItem
            SET ItemQty = 0
            WHERE VolNum = ? AND VolDocCod = 'CX'
        """, (vol_num,))

        cursor.execute("""
            UPDATE VolMaster
            SET VolVerified = 0,
                VolVerifiedDate = NULL,
                VolStatus = 'INICIAL'
            WHERE VolNum = ? AND VolDocCod = 'CX'
        """, (vol_num,))

        return CancelBoxConfirmationResult(
            success=True,
            message="Entrada da caixa anulada com sucesso",
            order_id=order_id,
        )


def _reverse_escp_satisfaction(cursor, pscp_order_id: int, pscp_order_row: int, item_id: str, qty_to_reverse: int) -> None:
    qty_remaining = int(qty_to_reverse or 0)
    if qty_remaining <= 0:
        return

    cursor.execute("""
        SELECT codo.OrderIDOri, codo.OrderRowOri, ISNULL(codo.QtyOrdDest, codo.QtyOrd)
        FROM ClientOrderDetailsOri codo
        JOIN ClientOrderDetails cod
          ON cod.DocType = codo.DocTypeOri
         AND cod.OrderID = codo.OrderIDOri
         AND cod.OrderRow = codo.OrderRowOri
        WHERE codo.DocType = 'PSCP'
          AND codo.OrderID = ?
          AND codo.OrderRow = ?
          AND codo.DocTypeOri = 'ESCP'
          AND cod.ItemID = ?
        ORDER BY codo.OrderRowOri DESC
    """, (pscp_order_id, pscp_order_row, item_id))
    origins = cursor.fetchall()

    for escp_order_id, escp_order_row, qty_linked in origins:
        if qty_remaining <= 0:
            break

        to_subtract = min(qty_remaining, int(qty_linked or 0))
        if to_subtract <= 0:
            continue

        cursor.execute("""
            UPDATE ClientOrderDetails
            SET QtySatisf = CASE
                WHEN ISNULL(QtySatisf, 0) >= ? THEN ISNULL(QtySatisf, 0) - ?
                ELSE 0
            END
            WHERE DocType = 'ESCP'
              AND OrderID = ?
              AND OrderRow = ?
              AND ItemID = ?
        """, (to_subtract, to_subtract, escp_order_id, escp_order_row, item_id))
        qty_remaining -= to_subtract


def find_packing_by_barcode(barcode: str):
    """Encontra o packing list a partir do código de barras de uma caixa."""
    with db_cursor() as (cursor, _):
        # Pesquisa por VolNum interno (número sequencial nosso)
        # ou por VolNum2N (código de barras do cliente)
        # Aceita com ou sem zeros à esquerda
        stripped = barcode.lstrip('0') or barcode
        vol_num_int = None
        try:
            vol_num_int = int(barcode)
        except ValueError:
            pass

        cursor.execute("""
            SELECT TOP 1
                v.VolNum,
                v.ParentOrderID,
                o.ClientID,
                o.DeliveryDate,
                o.Obs,
                o.TotalQtyOrd
            FROM VolMaster v
            JOIN ClientOrders o ON o.OrderID = v.ParentOrderID AND o.DocType = 'PSCP'
            WHERE v.VolDocCod = 'CX'
              AND (
                  v.VolNum2N = ?
               OR v.VolNum2N = ?
               OR CAST(v.VolNum AS varchar) = ?
               OR (? IS NOT NULL AND v.VolNum = ?)
              )
        """, (barcode, stripped, barcode, vol_num_int, vol_num_int))
        row = cursor.fetchone()
    return row
