from __future__ import annotations
import pandas as pd
import io
from app.models.schemas import (
    OrderRow, OrderPreview, OrderItemCheck
)


def _neg_dot(val: str) -> str:
    v = str(val).strip().lower()
    if 'neg' in v or 'neg' in v:
        return 'NEG'
    return 'DOT'


def _generate_item_id(style_color: str, size: str, neg_dot: str) -> str:
    sc = str(style_color).strip().replace(' ', '')
    sz = str(size).strip().replace(' ', '')
    return f"MESCP{sc}-{sz}-{neg_dot}"


def parse_order_excel(content: bytes) -> OrderPreview:
    df = pd.read_excel(io.BytesIO(content))

    required = ['SO Number', 'NEG / DOT', 'PO Number', 'Style/Color',
                 'Código GIAF', 'Descrição', 'Tamanho', 'Quantidade',
                 'Ship-to Name', 'Nota de Encomenda GIAF']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas em falta no ficheiro: {missing}")

    df = df.dropna(subset=['SO Number', 'Style/Color', 'Tamanho', 'Quantidade'])

    rows = []
    for _, r in df.iterrows():
        nd      = _neg_dot(r['NEG / DOT'])
        item_id = _generate_item_id(r['Style/Color'], r['Tamanho'], nd)
        rows.append(OrderRow(
            so_number    = str(r['SO Number']).strip(),
            neg_dot      = nd,
            po_number    = str(r['PO Number']).strip(),
            style_color  = str(r['Style/Color']).strip(),
            codigo_giaf  = str(r['Código GIAF']).strip(),
            descricao    = str(r['Descrição']).strip(),
            tamanho      = str(r['Tamanho']).strip(),
            quantidade   = int(r['Quantidade']),
            ship_to      = str(r['Ship-to Name']).strip(),
            nota_giaf    = str(r['Nota de Encomenda GIAF']).strip(),
            item_id      = item_id,
            exists_in_db = None,
        ))

    total_qty    = sum(r.quantidade for r in rows)
    unique_items = len({r.item_id for r in rows})
    unique_pos   = list({r.po_number for r in rows})

    # Validação: nenhum ItemID pode ultrapassar 25 caracteres
    oversized = [r.item_id for r in rows if len(r.item_id) > 25]
    if oversized:
        unique_oversized = list(dict.fromkeys(oversized))  # mantém ordem, sem duplicados
        raise ValueError(
            f"Os seguintes códigos de artigo ultrapassam os 25 caracteres permitidos pelo ERP: "
            f"{', '.join(unique_oversized)}"
        )

    return OrderPreview(
        rows         = rows,
        total_lines  = len(rows),
        total_qty    = total_qty,
        unique_items = unique_items,
        po_numbers   = unique_pos,
    )
