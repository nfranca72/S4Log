from __future__ import annotations
from datetime import datetime
from app.db.connection import db_cursor
from app.models.schemas import CSVRow, CSVHeader, PackingCreated


def _next_order_id(cursor) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        "SELECT ISNULL(MAX(OrderID), ?) FROM ClientOrders WHERE OrderID >= ? AND DocType = 'PSCP'",
        (base, base)
    )
    last = cursor.fetchone()[0]
    return last + 1


def _next_vol_num(cursor) -> int:
    """
    Obtém o próximo número de caixa da tabela DocumentConfig.
    Formato: 9YY00001 onde YY são os dois dígitos do ano.
    Após usar o número, incrementa o DocNumber na tabela.
    """
    year2 = datetime.now().year % 100  # dois dígitos do ano
    prefix = 900000000 + year2 * 1000000  # ex: 926000000 para 2026

    # Lê o próximo número da tabela DocumentConfig
    cursor.execute("""
        SELECT DocNumber FROM DocumentConfig
        WHERE DocType = 'CX'
    """)
    row = cursor.fetchone()

    if row and row[0]:
        vol_num = int(row[0])
        # Atualiza para o próximo
        cursor.execute("""
            UPDATE DocumentConfig SET DocNumber = DocNumber + 1
            WHERE DocType = 'CX'
        """)
    else:
        vol_num = prefix + 1
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM DocumentConfig WHERE DocType = 'CX')
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
                    'PKL', 'CX', ?,
                    '', 0, 0, 0, 0, 0, 0,
                    0, 0, 1, 1, 0, 0, 0,
                    0, '', 0, 0, 0, 0, 0,
                    0, 0, '', 0, 0, 1
                )
            ELSE
                UPDATE DocumentConfig SET DocNumber = ? WHERE DocType = 'CX'
        """, (vol_num + 1, vol_num + 1))

    return vol_num


def create_packing(
    client_id: str,
    rows: list[CSVRow],
    header: CSVHeader,
    escp_order_id: int = None,
) -> PackingCreated:

    with db_cursor() as (cursor, conn):

        # ── 1. Cabeçalho ClientOrder ───────────────────────────────────────────
        order_id = _next_order_id(cursor)
        delivery_date = datetime.strptime(header.delivery_date, "%d/%m/%Y")
        obs = f"Doc: {header.doc_num} | Ref: {header.ref_supplier}"

        cursor.execute("""
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
                'PSCP', ?, 0,
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
                    ItemID, QtyOrd, QtySatisf, QtyPicked,
                    QtyVols, Status, ProductionStatus,
                    CreationUser, CreationDateTime,
                    UnitPrice, TotValue,
                    ColorID, QtyProd,
                    VariationCountry
                ) VALUES (
                    'PSCP', ?, ?, 0, 0,
                    ?, ?, 0, 0,
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
                    'PSCP', ?, ?,
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
                        ItemID, ItemQty, ItemQtyIni,
                        ItemWeight, ItemWidth, ItemHeight, ItemLength, ItemVolume,
                        ParentDocType, ParentOrderID, ParentOrderRow,
                        ColorID, GridID, SizeId, VariationCountry,
                        CreationDate, CreationUser
                    ) VALUES (
                        'CX', ?, ?,
                        ?, ?, ?,
                        0, 0, 0, 0, 0,
                        'PSCP', ?, ?,
                        ?, '', ?, ?,
                        GETDATE(), 'AI'
                    )
                """, (
                    vol_num, vol_item_num,
                    r.item_id, 0, r.qty_box,  # ItemQty=0 (por confirmar), ItemQtyIni=qty prevista
                    order_id, detail_row,
                    r.color_code, r.size, r.country,
                ))
                vol_item_num += 1

            total_boxes += 1

        # ── 4. ClientOrderDetailsOri — liga PSCP à ESCP ──────────────────────
        if escp_order_id:
            # Para cada linha do PSCP, encontra a linha ESCP com menor OrderRow
            # que tem o mesmo ItemID
            cursor.execute("""
                SELECT p.OrderRow, p.ItemID, e.OrderID, e.OrderRow
                FROM ClientOrderDetails p
                JOIN (
                    SELECT ItemID, OrderID, OrderRow,
                           ROW_NUMBER() OVER (PARTITION BY ItemID ORDER BY OrderRow ASC) AS rn
                    FROM ClientOrderDetails
                    WHERE DocType = 'ESCP' AND OrderID = ?
                ) e ON e.ItemID = p.ItemID AND e.rn = 1
                WHERE p.OrderID = ? AND p.DocType = 'PSCP'
            """, (escp_order_id, order_id))
            ori_rows = cursor.fetchall()

            for pscp_row, item_id, escp_oid, escp_row in ori_rows:
                cursor.execute("""
                    IF NOT EXISTS (
                        SELECT 1 FROM ClientOrderDetailsOri
                        WHERE DocType='PSCP' AND OrderID=? AND OrderRow=?
                    )
                    INSERT INTO ClientOrderDetailsOri (
                        DocType, OrderID, OrderRow, PartNum, VolNum,
                        DocTypeOri, OrderIDOri, OrderRowOri, PartNumOri, VolNumOri,
                        QtyOrd, QtyVols, QtyOrdDest
                    ) VALUES (
                        'PSCP', ?, ?, 0, 0,
                        'ESCP', ?, ?, 0, 0,
                        0, 0, 0
                    )
                """, (order_id, pscp_row, order_id, pscp_row, escp_oid, escp_row))

        # ── 5. Validação final ─────────────────────────────────────────────────
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
