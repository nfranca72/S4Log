from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

import pandas as pd

from app.db.connection import db_cursor
from app.models.schemas import BenficaItemRow, BenficaItemsPreview


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _normalize_barcode(value: object) -> str:
    raw = _clean_cell(value)
    if not raw:
        return ""
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.replace(" ", "")


def _normalize_price(value: object) -> str:
    raw = _clean_cell(value).replace("EUR", "").replace("€", "").strip()
    if not raw:
        return ""
    if "," in raw and "." in raw:
        normalized = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        normalized = raw.replace(",", ".")
    else:
        normalized = raw
    try:
        return f"{Decimal(normalized):.2f}"
    except (InvalidOperation, ValueError):
        return raw


def _extract_size_id(item_desc: str) -> str:
    desc = str(item_desc or "").strip()
    if " - " not in desc:
        return ""
    return desc.rsplit(" - ", 1)[-1].strip()


def _generated_item_id(barcode: str) -> str:
    return f"PS.EJ.{barcode}"


def _barcode_exists_map(barcodes: list[str]) -> dict[str, str]:
    if not barcodes:
        return {}

    placeholders = ",".join(["?" for _ in barcodes])
    query = f"""
        SELECT Barcode, ItemID
        FROM ItemMaster WITH (NOLOCK)
        WHERE Barcode IN ({placeholders})
    """

    with db_cursor() as (cursor, _):
        cursor.execute(query, barcodes)
        return {str(row[0]).strip(): str(row[1]).strip() for row in cursor.fetchall() if row[0]}


def parse_benfica_items_excel(content: bytes) -> BenficaItemsPreview:
    df = pd.read_excel(io.BytesIO(content), dtype=str)
    if df.shape[1] < 6:
        raise ValueError("O ficheiro deve conter pelo menos as colunas A a F.")

    rows: list[BenficaItemRow] = []
    barcode_counts: dict[str, int] = {}

    for _, row in df.iterrows():
        client_ref = _clean_cell(row.iloc[0])
        item_desc = _clean_cell(row.iloc[2])
        barcode = _normalize_barcode(row.iloc[3])
        price_socio = _normalize_price(row.iloc[4])
        price_pvp = _normalize_price(row.iloc[5])

        if not any([client_ref, item_desc, barcode, price_socio, price_pvp]):
            continue

        # Ignora a linha de cabeçalho quando o ficheiro vem com títulos.
        if barcode.lower() in {"barcode", "ean", "codigo de barras", "código de barras"}:
            continue

        if not barcode:
            continue

        barcode_counts[barcode] = barcode_counts.get(barcode, 0) + 1
        rows.append(
            BenficaItemRow(
                client_ref=client_ref,
                item_desc=item_desc,
                barcode=barcode,
                price_socio=price_socio,
                price_pvp=price_pvp,
                size_id=_extract_size_id(item_desc),
                item_id=_generated_item_id(barcode),
            )
        )

    if not rows:
        raise ValueError("Nao foram encontradas linhas validas no ficheiro.")

    exists_map = _barcode_exists_map(list(barcode_counts.keys()))
    new_items = 0
    existing_items = len(exists_map)
    duplicate_rows = 0

    for barcode, count in barcode_counts.items():
        if count == 1 and barcode not in exists_map:
            new_items += 1

    for row in rows:
        row.duplicate_in_file = barcode_counts.get(row.barcode, 0) > 1
        row.existing_item_id = exists_map.get(row.barcode)
        row.exists_in_db = row.barcode in exists_map
        if row.duplicate_in_file:
            duplicate_rows += 1

    return BenficaItemsPreview(
        rows=rows,
        total_lines=len(rows),
        unique_barcodes=len(barcode_counts),
        new_items=new_items,
        existing_items=existing_items,
        duplicate_rows=duplicate_rows,
    )


def import_benfica_items(rows: list[BenficaItemRow]) -> tuple[int, int, int]:
    unique_rows: dict[str, BenficaItemRow] = {}
    duplicate_barcodes: set[str] = set()

    for row in rows:
        if row.barcode in unique_rows:
            duplicate_barcodes.add(row.barcode)
            continue
        unique_rows[row.barcode] = row

    exists_map = _barcode_exists_map(list(unique_rows.keys()))
    to_create = [row for barcode, row in unique_rows.items() if barcode not in exists_map]
    skipped_existing = len(unique_rows) - len(to_create)
    skipped_duplicates = len(duplicate_barcodes)

    if not to_create:
        return 0, skipped_existing, skipped_duplicates

    item_master_sql = """
    INSERT INTO ItemMaster (
        ItemID, ItemDesc, ClientRef, Barcode, Modelo,
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
        ?, ?, ?, ?, ?,
        'SLB', 'ME',
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

    item_characteristic_sql = """
    INSERT INTO ItemMasterCharacteristics (
        ItemID, Version, CharacteristicID, CharacteristicValue
    ) VALUES (?, 0, ?, ?)
    """

    with db_cursor() as (cursor, _):
        for row in to_create:
            cursor.execute(
                item_master_sql,
                (
                    row.item_id,
                    row.item_desc,
                    row.client_ref,
                    row.barcode,
                    row.size_id,
                ),
            )

            characteristics = [
                ("PRECOSOCIO", row.price_socio),
                ("PRECOPVP", row.price_pvp),
                ("SizeId", row.size_id),
            ]
            for characteristic_id, characteristic_value in characteristics:
                cursor.execute(
                    item_characteristic_sql,
                    (row.item_id, characteristic_id, characteristic_value),
                )

    return len(to_create), skipped_existing, skipped_duplicates
