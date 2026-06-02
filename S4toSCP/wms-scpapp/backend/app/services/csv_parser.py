from __future__ import annotations

import io

import pandas as pd

from app.models.schemas import CSVHeader, CSVPreview, CSVRow


def _generate_item_id(style: str, color: str, size: str) -> str:
    return f"MC{style}-{color}-{size}"


def _clean_cell(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_csv_lines(lines: list[str]) -> CSVPreview:
    if len(lines) < 4:
        raise ValueError("Bloco CSV incompleto")

    header_parts = lines[0].split(",")
    doc_num = header_parts[1].strip()
    delivery_date = header_parts[2].strip()
    ref_supplier = header_parts[3].strip()
    client_code = header_parts[4].strip()
    num_boxes = int(header_parts[5].strip())
    total_qty = int(header_parts[6].strip())
    value = float(header_parts[7].strip())

    header2_parts = lines[1].split(",")
    header2_values = [part.strip() for part in header2_parts[1:] if part.strip()]
    if header2_values:
        ref_supplier = ",".join(header2_values)

    header = CSVHeader(
        doc_num=doc_num,
        delivery_date=delivery_date,
        ref_supplier=ref_supplier,
        client_code_csv=client_code,
        num_boxes=num_boxes,
        total_qty=total_qty,
        value=value,
    )

    data_content = "\n".join(lines[3:])
    col_names = [
        "box_barcode", "style_code", "color_code", "size", "ean",
        "country", "qty_box", "qty_total", "season_desc", "extra",
    ]

    df = pd.read_csv(
        io.StringIO(data_content),
        header=None,
        names=col_names,
        dtype=str,
    )
    df = df[df["box_barcode"].notna() & (df["box_barcode"].str.strip() != "")]

    df["qty_box"] = df["qty_box"].str.strip().replace("", "0").fillna("0").astype(float).astype(int)
    df["qty_total"] = df["qty_total"].str.strip().replace("", "0").fillna("0").astype(float).astype(int)
    df["box_barcode"] = df["box_barcode"].str.strip().str.lstrip("0")

    rows: list[CSVRow] = []
    for _, row in df.iterrows():
        box_barcode = _clean_cell(row["box_barcode"])
        style_code = _clean_cell(row["style_code"])
        color_code = _clean_cell(row["color_code"])
        size = _clean_cell(row["size"])
        ean = _clean_cell(row["ean"])
        country = _clean_cell(row["country"])
        season_desc = _clean_cell(row["season_desc"])

        rows.append(CSVRow(
            box_barcode=box_barcode,
            style_code=style_code,
            color_code=color_code,
            size=size,
            ean=ean.lstrip("0"),
            country=country,
            qty_box=int(row["qty_box"]),
            qty_total=int(row["qty_total"]),
            season_desc=season_desc,
            item_id=_generate_item_id(
                style_code,
                color_code,
                size,
            ),
        ))

    unique_items = {row.item_id for row in rows}
    actual_qty = sum(row.qty_box for row in rows)
    unique_boxes = len({row.box_barcode for row in rows})

    oversized = [item_id for item_id in unique_items if len(item_id) > 25]
    if oversized:
        raise ValueError(
            "Os seguintes codigos de artigo ultrapassam os 25 caracteres permitidos pelo ERP: "
            f"{', '.join(oversized)}"
        )

    return CSVPreview(
        header=header,
        rows=rows,
        total_boxes=unique_boxes,
        total_qty=actual_qty,
        total_articles=len(unique_items),
        new_articles=0,
        existing_articles=0,
    )


def _split_packing_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        if line.upper().startswith("HEADER1"):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        blocks.append(current)

    return blocks


def parse_csv(content: bytes) -> CSVPreview:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        lines = content.decode("latin-1").splitlines()

    blocks = _split_packing_blocks(lines)
    if not blocks:
        raise ValueError("CSV sem HEADER1")

    previews = [_parse_csv_lines(block) for block in blocks]
    if len(previews) == 1:
        return previews[0]

    rows = [row for preview in previews for row in preview.rows]
    unique_items = {row.item_id for row in rows}

    return CSVPreview(
        header=previews[0].header,
        rows=rows,
        total_boxes=sum(preview.total_boxes for preview in previews),
        total_qty=sum(preview.total_qty for preview in previews),
        total_articles=len(unique_items),
        new_articles=0,
        existing_articles=0,
        warnings=[],
        packings=previews,
    )
