from __future__ import annotations
from app.db.connection import db_cursor
from app.models.schemas import CSVRow


def check_items_exist(item_ids: list[str]) -> dict[str, bool]:
    """Verifica quais ItemIDs já existem na tabela ItemMaster."""
    if not item_ids:
        return {}

    placeholders = ",".join(["?" for _ in item_ids])
    query = f"SELECT ItemID FROM ItemMaster WHERE ItemID IN ({placeholders})"

    with db_cursor() as (cursor, _):
        cursor.execute(query, item_ids)
        found = {row[0] for row in cursor.fetchall()}

    return {item_id: item_id in found for item_id in item_ids}


def create_items(rows: list[CSVRow]) -> tuple[int, int]:
    """
    Cria artigos em falta no ItemMaster.
    Retorna (criados, ignorados).
    """
    unique: dict[str, CSVRow] = {}
    for r in rows:
        if r.item_id not in unique:
            unique[r.item_id] = r

    item_ids = list(unique.keys())
    exists_map = check_items_exist(item_ids)

    to_create = [row for item_id, row in unique.items() if not exists_map.get(item_id, False)]
    skipped   = len(unique) - len(to_create)

    if not to_create:
        return 0, skipped

    sql = """
    INSERT INTO ItemMaster (
        ItemID, ItemDesc, BrandID, CategoryID,
        StkUnit, PackUnit, SaleUnit, PackToStkConv, QtyPVolume,
        Barcode, InterStat,
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
        ?, ?, 'NIKE', 'ME',
        'UN', 'UN', 'UN', 1, 1,
        ?, ?,
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

    with db_cursor() as (cursor, conn):
        for row in to_create:
            cursor.execute(sql, (
                row.item_id,
                row.season_desc,
                row.ean,
                row.country,
            ))

    return len(to_create), skipped
