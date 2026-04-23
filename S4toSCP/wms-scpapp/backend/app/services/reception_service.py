from __future__ import annotations
from app.db.connection import db_cursor
from app.models.schemas import (
    PackingListSummary, BoxSummary, BoxDetail, BoxItem,
    WarehouseInfo, LocationInfo, ConfirmBoxRequest, ConfirmBoxResult
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
                ISNULL(SUM(vi.ItemQty), 0)                         AS QtyExpected,
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

        # Se a caixa já está verificada, ItemQty = qty_read
        # qty_expected vem do ClientOrderDetails
        verified = bool(row[2])

        # Busca qtd esperada do packing (VolItem antes de conferência)
        # e qtd lida (ItemQty após confirmação quando VolVerified=1)
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
            qty_expected    = int(i[7] or i[2] or 0),  # ItemQtyIni se verificada, senão ItemQty
            qty_read        = int(i[2] or 0) if verified else 0,   # ItemQty = qtd lida após confirmação
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


def confirm_box(vol_num: int, req: ConfirmBoxRequest) -> ConfirmBoxResult:
    """
    Confirma uma caixa após conferência:
    1. Atualiza VolMaster
    2. Atualiza VolItem com qtd recebida
    3. Dá entrada em Inventory por artigo
    """
    with db_cursor() as (cursor, conn):

        # Busca items da caixa
        cursor.execute("""
            SELECT vi.VolItemNumber, vi.ItemID, vi.ItemQty,
                   vi.ColorID, vi.SizeId, vi.VariationCountry,
                   v.ParentOrderID
            FROM VolItem vi
            JOIN VolMaster v ON v.VolNum = vi.VolNum
            WHERE vi.VolNum = ? AND vi.VolDocCod = 'CX'
        """, (vol_num,))
        items = cursor.fetchall()

        if not items:
            return ConfirmBoxResult(success=False, message="Caixa não encontrada")

        order_id     = items[0][6]
        has_incident = False

        for item in items:
            item_num  = item[0]
            item_id   = item[1]
            qty_exp   = int(item[2] or 0)
            color_id  = item[3] or ''
            size_id   = item[4] or ''
            country   = item[5] or ''

            # Qty lida para este artigo
            qty_read = req.item_quantities.get(item_id, 0)
            if qty_read < qty_exp:
                has_incident = True

            # Guarda qtd original em ItemQtyIni e qtd lida em ItemQtyIni
            cursor.execute("""
                UPDATE VolItem
                SET ItemQtyIni = ItemQty,
                    ItemQty    = ?
                WHERE VolNum = ? AND VolItemNumber = ? AND VolDocCod = 'CX'
            """, (qty_read, vol_num, item_num))

            # Entrada de stock em Inventory
            # Verifica se já existe registo para este artigo + caixa + localização
            cursor.execute("""
                SELECT Qty FROM Inventory
                WHERE WHID = ? AND LocationID = ? AND ItemID = ?
                  AND VolNum = ? AND ColorID = ? AND SizeID = ?
            """, (req.wh_id, req.location_id, item_id,
                  str(vol_num), color_id, size_id))
            existing = cursor.fetchone()

            if existing:
                cursor.execute("""
                    UPDATE Inventory
                    SET Qty = Qty + ?, LastInput = GETDATE()
                    WHERE WHID = ? AND LocationID = ? AND ItemID = ?
                      AND VolNum = ? AND ColorID = ? AND SizeID = ?
                """, (qty_read, req.wh_id, req.location_id, item_id,
                      str(vol_num), color_id, size_id))
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
                        '', '', ''
                    )
                """, (req.wh_id, req.location_id, item_id,
                      qty_read, str(vol_num)))

        # Guarda TAGs RFID na tabela ItemMasterRFIDTags
        if req.rfid_tags:
            for item in items:
                item_id = item[1]
                for tag in req.rfid_tags:
                    # Verifica se a tag já existe
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM ItemMasterRFIDTags WHERE TAG = ?)
                        INSERT INTO ItemMasterRFIDTags (
                            ItemID, ColorID, GridID, OrderNum, SizeID,
                            TAG, available, deleted, created_by, created_date
                        ) VALUES (
                            ?, '', '', ?, '',
                            ?, 1, 0, 'AI', GETDATE()
                        )
                    """, (tag, item_id, order_id, tag))

        # Atualiza VolMaster
        new_status = 'CAIXA COM INCIDENCIAS' if has_incident else 'CONFERIDA'
        cursor.execute("""
            UPDATE VolMaster
            SET VolVerified = 1, VolVerifiedDate = GETDATE(), VolStatus = ?
            WHERE VolNum = ? AND VolDocCod = 'CX'
        """, (new_status, vol_num))

        # Atualiza ClientOrderDetails PSCP com qtd recebida por artigo
        for item in items:
            item_id  = item[1]
            country  = item[5] or ''
            qty_read = req.item_quantities.get(item_id, 0)
            cursor.execute("""
                UPDATE ClientOrderDetails
                SET QtySatisf = ISNULL(QtySatisf, 0) + ?
                WHERE OrderID = ? AND ItemID = ? AND VariationCountry = ?
                  AND DocType = 'PSCP'
            """, (qty_read, order_id, item_id, country))

        # Log para diagnóstico
        import logging
        _log = logging.getLogger(__name__)
        _log.info(f"confirm_box: vol_num={vol_num} order_id={order_id} escp_order_id={req.escp_order_id} items={[(i[1], req.item_quantities.get(i[1],0)) for i in items]}")

        # Atualiza QtySatisf na encomenda ESCP linha a linha por ordem de OrderRow
        # Obtém o OrderID da ESCP via ClientOrderDetailsOri
        cursor.execute("""
            SELECT TOP 1 OrderIDOri
            FROM ClientOrderDetailsOri
            WHERE DocType    = 'PSCP'
              AND OrderID    = ?
              AND DocTypeOri = 'ESCP'
        """, (order_id,))
        ori_row = cursor.fetchone()
        escp_order_id = ori_row[0] if ori_row else req.escp_order_id

        _log.info(f"ESCP encontrada via ClientOrderDetailsOri: {escp_order_id}")

        if escp_order_id:
            for item in items:
                item_id       = item[1]
                qty_remaining = req.item_quantities.get(item_id, 0)
                if qty_remaining <= 0:
                    continue

                # Busca linhas do artigo na ESCP por ordem de OrderRow
                cursor.execute("""
                    SELECT OrderRow, QtyOrd, ISNULL(QtySatisf, 0)
                    FROM ClientOrderDetails
                    WHERE OrderID = ? AND ItemID = ? AND DocType = 'ESCP'
                    ORDER BY OrderRow ASC
                """, (escp_order_id, item_id))
                escp_lines = cursor.fetchall()

                _log.info(f"Artigo {item_id}: qty_remaining={qty_remaining} escp_lines={escp_lines}")

                if not escp_lines:
                    continue

                for idx, (order_row, qty_ord, qty_satisf) in enumerate(escp_lines):
                    is_last    = (idx == len(escp_lines) - 1)
                    qty_ord    = int(qty_ord    or 0)
                    qty_satisf = int(qty_satisf or 0)

                    if not is_last:
                        available = max(0, qty_ord - qty_satisf)
                        if available <= 0:
                            continue
                        to_add        = min(qty_remaining, available)
                        qty_remaining -= to_add
                    else:
                        to_add        = qty_remaining
                        qty_remaining = 0

                    if to_add > 0:
                        _log.info(f"  → ESCP OrderRow={order_row} to_add={to_add}")
                        cursor.execute("""
                            UPDATE ClientOrderDetails
                            SET QtySatisf = ISNULL(QtySatisf, 0) + ?
                            WHERE OrderID = ? AND ItemID = ? AND DocType = 'ESCP'
                              AND OrderRow = ?
                        """, (to_add, escp_order_id, item_id, order_row))

                    if qty_remaining <= 0:
                        break

        return ConfirmBoxResult(
            success      = True,
            has_incident = has_incident,
            message      = 'CAIXA COM INCIDENCIAS' if has_incident else 'CONFERIDA',
            order_id     = order_id,
        )


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
