from __future__ import annotations
from datetime import datetime
from app.db.connection import db_cursor
from app.models.schemas import OrderRow, OrderPreview, OrderItemCheck


def check_order_items(item_ids: list[str]) -> dict[str, bool]:
    if not item_ids:
        return {}
    placeholders = ','.join(['?' for _ in item_ids])
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"SELECT ItemID FROM ItemMaster WHERE ItemID IN ({placeholders})",
            item_ids
        )
        found = {r[0] for r in cursor.fetchall()}
    return {iid: iid in found for iid in item_ids}


def create_order_items(rows: list[OrderRow]) -> tuple[int, int]:
    unique: dict[str, OrderRow] = {}
    for r in rows:
        if r.item_id not in unique:
            unique[r.item_id] = r

    exists_map = check_order_items(list(unique.keys()))
    to_create  = [row for iid, row in unique.items() if not exists_map.get(iid, False)]
    skipped    = len(unique) - len(to_create)

    if not to_create:
        return 0, skipped

    sql = """
    INSERT INTO ItemMaster (
        ItemID, ItemDesc, ClientRef, Modelo,
        BrandID, CategoryID,
        StkUnit, PackUnit, SaleUnit, PackToStkConv, QtyPVolume,
        Status, Blocked, Flag, WMSManaged, MovStock,
        ItemTpValue, ItemValue, stkMin, MinSaleQty, SaleMultiplierQty,
        Lots, SerialNum, ExpirationDate, LotDefaultStatus,
        IsComposed, CanBeComponent, IsNeeded, FragilityLevel,
        StorageWH, Dimensions, Versao,
        ItemWeight, ItemHeight, ItemWidth, ItemLength,
        PackWeight, PackHeight, PackWidth, PackLength,
        MinTemp, MaxTemp, VolNums,
        CreationUser, CreationDateTime, ModifDateTime
    ) VALUES (
        ?, ?, ?, ?,
        'NIKE', 'ME',
        'UN', 'UN', 'UN', 1, 1,
        1, 0, 1, 1, 1,
        1, 0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 1,
        'AI', GETDATE(), GETDATE()
    )
    """
    with db_cursor() as (cursor, _):
        for row in to_create:
            modelo = f"{row.style_color}-{row.tamanho}"
            cursor.execute(sql, (
                row.item_id,
                row.descricao,
                row.codigo_giaf,
                modelo,
            ))
    return len(to_create), skipped


def _next_escp_order_id(cursor) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        "SELECT ISNULL(MAX(OrderID), ?) FROM ClientOrders WHERE OrderID >= ? AND DocType = 'ESCP'",
        (base, base)
    )
    return cursor.fetchone()[0] + 1


def get_escp_orders() -> list[dict]:
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT o.OrderID, o.ClientID, o.OrderDateTime, o.Obs,
                   o.TotalQtyOrd,
                   COUNT(d.OrderRow) AS TotalLines
            FROM ClientOrders o
            LEFT JOIN ClientOrderDetails d
                ON d.OrderID = o.OrderID AND d.DocType = 'ESCP'
            WHERE o.DocType = 'ESCP'
            GROUP BY o.OrderID, o.ClientID, o.OrderDateTime, o.Obs, o.TotalQtyOrd
            ORDER BY o.OrderID DESC
        """)
        rows = cursor.fetchall()
    return [
        {
            'order_id':    r[0],
            'client_id':   r[1],
            'order_date':  str(r[2])[:10] if r[2] else None,
            'obs':         r[3],
            'total_qty':   int(r[4] or 0),
            'total_lines': r[5],
        }
        for r in rows
    ]


def get_escp_order_details(order_id: int) -> list[dict]:
    """Retorna linhas existentes de uma encomenda ESCP para merge."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT ItemID, QtyOrd, IDIntegration, RefCli, SizeId, ColorID
            FROM ClientOrderDetails
            WHERE OrderID = ? AND DocType = 'ESCP'
        """, (order_id,))
        rows = cursor.fetchall()
    return [
        {
            'item_id':        r[0],
            'qty_ord':        int(r[1] or 0),
            'id_integration': r[2],
            'ref_cli':        r[3],
            'size_id':        r[4],
            'color_id':       r[5],
        }
        for r in rows
    ]


def create_escp_order(client_id: str, rows: list[OrderRow], obs: str = '') -> dict:
    with db_cursor() as (cursor, _):
        order_id  = _next_escp_order_id(cursor)
        total_qty = sum(r.quantidade for r in rows)

        cursor.execute("""
            INSERT INTO ClientOrders (
                DocType, OrderID, PartNum,
                OrderDateTime, ClientID,
                Status, CreationUser, CreationDateTime,
                Obs, Currency, ExangeRate,
                TotalQtyOrd,
                Tipo, PercDsc2, TotalValue, TotalShipValue,
                CreditApproved, UrgencyStatusID,
                ConsignmentDoc, RecuseDoc, PartnerCategory
            ) VALUES (
                'ESCP', ?, 0,
                GETDATE(), ?,
                1, 'AI', GETDATE(),
                ?, 'EUR', 1,
                ?,
                0, 0, 0, 0,
                0, 0, 0, 0, 'C'
            )
        """, (order_id, client_id, obs, total_qty))

        _insert_order_lines(cursor, order_id, rows, start_row=1)

        return {'order_id': order_id, 'total_lines': len(rows), 'total_qty': total_qty}


def merge_escp_order(order_id: int, new_rows: list[OrderRow]) -> dict:
    """
    Compara novas linhas com existentes.
    Retorna diff sem gravar — o utilizador confirma antes.
    """
    existing = get_escp_order_details(order_id)
    existing_map = {r['id_integration']: r for r in existing}

    added    = []
    changed  = []
    unchanged = []

    for row in new_rows:
        key = row.so_number
        if key not in existing_map:
            added.append(row)
        else:
            ex = existing_map[key]
            if int(ex['qty_ord']) != row.quantidade:
                changed.append({
                    'row':      row,
                    'old_qty':  int(ex['qty_ord']),
                    'new_qty':  row.quantidade,
                })
            else:
                unchanged.append(row)

    return {
        'order_id':  order_id,
        'added':     [r.dict() for r in added],
        'changed':   changed,
        'unchanged': len(unchanged),
    }


def apply_escp_merge(order_id: int, rows_to_add: list[OrderRow], rows_to_update: list[dict]):
    """Aplica o merge após confirmação do utilizador."""
    with db_cursor() as (cursor, _):
        # Determina próxima OrderRow
        cursor.execute(
            "SELECT ISNULL(MAX(OrderRow), 0) FROM ClientOrderDetails WHERE OrderID = ? AND DocType = 'ESCP'",
            (order_id,)
        )
        next_row = cursor.fetchone()[0] + 1

        # Insere linhas novas
        add_objs = [OrderRow(**r) if isinstance(r, dict) else r for r in rows_to_add]
        _insert_order_lines(cursor, order_id, add_objs, start_row=next_row)

        # Atualiza quantidades alteradas
        for item in rows_to_update:
            cursor.execute("""
                UPDATE ClientOrderDetails
                SET QtyOrd = ?
                WHERE OrderID = ? AND DocType = 'ESCP' AND IDIntegration = ?
            """, (item['new_qty'], order_id, item['so_number']))

        # Atualiza total no cabeçalho
        cursor.execute("""
            UPDATE ClientOrders
            SET TotalQtyOrd = (
                SELECT ISNULL(SUM(QtyOrd), 0)
                FROM ClientOrderDetails
                WHERE OrderID = ? AND DocType = 'ESCP'
            )
            WHERE OrderID = ? AND DocType = 'ESCP'
        """, (order_id, order_id))


def _insert_order_lines(cursor, order_id: int, rows: list[OrderRow], start_row: int):
    for i, row in enumerate(rows):
        # Extrai color_id da parte depois do '-' em Style/Color
        parts    = row.style_color.split('-')
        color_id = parts[-1] if len(parts) > 1 else ''

        cursor.execute("""
            INSERT INTO ClientOrderDetails (
                DocType, OrderID, OrderRow, PartNum, VolNum,
                ItemID, QtyOrd, QtySatisf, QtyPicked,
                QtyVols, Status, ProductionStatus,
                CreationUser, CreationDateTime,
                UnitPrice, TotValue,
                ColorID, GridID,
                IDIntegration, RefCli, QtyProd
            ) VALUES (
                'ESCP', ?, ?, 0, 0,
                ?, ?, 0, 0,
                0, 1, 'INICIAL',
                'AI', GETDATE(),
                0, 0,
                ?, '',
                ?, ?, 0
            )
        """, (
            order_id, start_row + i,
            row.item_id, row.quantidade,
            color_id,
            row.so_number, row.po_number,
        ))
