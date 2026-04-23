from __future__ import annotations
import io
import pandas as pd
from app.models.schemas import CSVHeader, CSVRow, CSVPreview


def _generate_item_id(style: str, color: str, size: str) -> str:
    return f"MC{style}-{color}-{size}"


def parse_csv(content: bytes) -> CSVPreview:
    # Lê as 3 linhas de cabeçalho
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        lines = content.decode("latin-1").splitlines()

    header_parts = lines[0].split(",")
    doc_num       = header_parts[1].strip()
    delivery_date = header_parts[2].strip()
    ref_supplier  = header_parts[3].strip()
    client_code   = header_parts[4].strip()
    num_boxes     = int(header_parts[5].strip())
    total_qty     = int(header_parts[6].strip())
    value         = float(header_parts[7].strip())

    # HEADER2 contém referências adicionais (ex: 7601670122,7601687233)
    # Usa o conteúdo da HEADER2 (sem o prefixo HEADER2) como ref_fornecedor
    header2_parts = lines[1].split(",")
    header2_values = [p.strip() for p in header2_parts[1:] if p.strip()]
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

    # Lê as linhas de detalhe (salta os 3 headers)
    data_content = "\n".join(lines[3:])
    col_names = ["box_barcode","style_code","color_code","size","ean",
                 "country","qty_box","qty_total","season_desc","extra"]

    df = pd.read_csv(
        io.StringIO(data_content),
        header=None,
        names=col_names,
        dtype=str,
    )
    df = df[df["box_barcode"].notna() & (df["box_barcode"].str.strip() != "")]

    # Remove zeros à esquerda que o pandas pode introduzir
    df["qty_box"]   = df["qty_box"].str.strip().replace('', '0').fillna('0').astype(float).astype(int)
    df["qty_total"] = df["qty_total"].str.strip().replace('', '0').fillna('0').astype(float).astype(int)
    df["box_barcode"] = df["box_barcode"].str.strip().str.lstrip("0")

    rows: list[CSVRow] = []
    for _, r in df.iterrows():
        rows.append(CSVRow(
            box_barcode  = r["box_barcode"].strip(),
            style_code   = r["style_code"].strip(),
            color_code   = r["color_code"].strip(),
            size         = r["size"].strip(),
            ean          = r["ean"].strip().lstrip("0"),
            country      = r["country"].strip(),
            qty_box      = int(r["qty_box"]),
            qty_total    = int(r["qty_total"]),
            season_desc  = r["season_desc"].strip(),
            item_id      = _generate_item_id(
                               r["style_code"].strip(),
                               r["color_code"].strip(),
                               r["size"].strip()
                           ),
        ))

    unique_items  = {r.item_id for r in rows}
    actual_qty    = sum(r.qty_box for r in rows)
    unique_boxes  = len({r.box_barcode for r in rows})

    # Validação: nenhum ItemID pode ultrapassar 25 caracteres
    oversized = [iid for iid in unique_items if len(iid) > 25]
    if oversized:
        raise ValueError(
            f"Os seguintes códigos de artigo ultrapassam os 25 caracteres permitidos pelo ERP: "
            f"{', '.join(oversized)}"
        )

    return CSVPreview(
        header           = header,
        rows             = rows,
        total_boxes      = unique_boxes,
        total_qty        = actual_qty,
        total_articles   = len(unique_items),
        new_articles     = 0,   # preenchido após verificação na BD
        existing_articles= 0,
    )
