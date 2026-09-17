from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import CSVPreview, ImportResult, PackingCreateRequest
from app.services.csv_parser import parse_csv
from app.services.item_creator import check_items_exist
from app.services.order_service import get_active_escp_client_id
from app.services.packing_creator import check_requester_id_duplicate, create_packing
from app.services.packing_resolver import resolve_item_ids

router = APIRouter(prefix="/packing", tags=["Packing List"])


def _apply_item_resolution(preview: CSVPreview, escp_order_id: int | None) -> list[str]:
    warnings: list[str] = []

    if escp_order_id:
        resolved_rows, errors = resolve_item_ids(escp_order_id, preview.rows)
        preview.rows = resolved_rows
        warnings.extend(errors)

    preview.unresolved_rows = sum(1 for row in preview.rows if not row.resolved)

    # Linhas por resolver não têm um código final (falta o sufixo real da encomenda,
    # ex: -DOT, -NEG) — não entram na contagem de artigos novos/existentes nem na
    # verificação de existência, que não fazem sentido para um código incompleto.
    item_ids = list({row.item_id for row in preview.rows if row.resolved})
    exists_map = check_items_exist(item_ids)

    for row in preview.rows:
        row.exists_in_db = exists_map.get(row.item_id, False) if row.resolved else None

    unique_exists = sum(1 for item_id in item_ids if exists_map.get(item_id, False))
    preview.existing_articles = unique_exists
    preview.new_articles = len(item_ids) - unique_exists
    preview.total_articles = len(item_ids)

    if warnings:
        preview.warnings = list(preview.warnings or []) + warnings
    return warnings


@router.post("/preview", response_model=CSVPreview)
async def preview_csv(file: UploadFile = File(...), escp_order_id: int = None):
    """
    Faz o parse do CSV. Se escp_order_id fornecido, resolve os ItemIDs
    a partir da encomenda ESCP e verifica se todos existem.
    """
    if not file.filename.upper().endswith(".CSV"):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser CSV")

    content = await file.read()
    preview = parse_csv(content)

    if escp_order_id:
        if not get_active_escp_client_id(escp_order_id):
            raise HTTPException(status_code=400, detail="Encomenda ESCP inexistente ou fechada/anulada/cancelada")

    if preview.packings:
        warnings: list[str] = []
        for packing_preview in preview.packings:
            warnings.extend(_apply_item_resolution(packing_preview, escp_order_id))
            packing_preview.requester_id_duplicate_orders = check_requester_id_duplicate(
                packing_preview.header.doc_num
            )

        preview.rows = [row for packing_preview in preview.packings for row in packing_preview.rows]
        item_ids = list({row.item_id for row in preview.rows if row.resolved})
        exists_map = check_items_exist(item_ids)
        for row in preview.rows:
            row.exists_in_db = exists_map.get(row.item_id, False) if row.resolved else None
        preview.existing_articles = sum(1 for item_id in item_ids if exists_map.get(item_id, False))
        preview.new_articles = len(item_ids) - preview.existing_articles
        preview.total_articles = len(item_ids)
        preview.total_boxes = sum(packing_preview.total_boxes for packing_preview in preview.packings)
        preview.total_qty = sum(sum(row.qty_box for row in packing_preview.rows) for packing_preview in preview.packings)
        preview.unresolved_rows = sum(packing_preview.unresolved_rows for packing_preview in preview.packings)
        if warnings:
            preview.warnings = warnings
    else:
        _apply_item_resolution(preview, escp_order_id)
        preview.requester_id_duplicate_orders = check_requester_id_duplicate(preview.header.doc_num)

    return preview


@router.post("/import", response_model=ImportResult)
async def import_packing(request: PackingCreateRequest):
    """
    Executa a importacao completa.
    A encomenda ESCP e obrigatoria e tem de estar aberta.
    """
    if not request.escp_order_id:
        raise HTTPException(
            status_code=400,
            detail="Encomenda obrigatoria - seleciona uma encomenda ESCP antes de importar o packing list",
        )

    client_id = get_active_escp_client_id(request.escp_order_id)
    if not client_id:
        raise HTTPException(status_code=400, detail="Encomenda ESCP inexistente ou fechada/anulada/cancelada")
    request.client_id = client_id

    import_requests = request.packings or [request]
    packings = []
    warnings = []
    items_created = 0
    items_skipped = 0

    for index, packing_request in enumerate(import_requests, start=1):
        resolved_rows, errors = resolve_item_ids(request.escp_order_id, packing_request.csv_rows)
        original_row_count = len(packing_request.csv_rows)
        # Só entram na importação as linhas com ligação confirmada à encomenda ESCP
        # (automática ou completada manualmente pelo operador). As restantes ficam de
        # fora — sem código completo não há criação de caixa/artigo para essas linhas.
        rows = [row for row in resolved_rows if row.resolved]
        unresolved_count = original_row_count - len(rows)
        items_skipped += unresolved_count

        doc_label = packing_request.header.doc_num or f"bloco {index}"
        if unresolved_count:
            warnings.append(
                f"{doc_label}: {unresolved_count} linha(s) sem ligação à encomenda ESCP "
                "não foram importadas (código de artigo incompleto — falta completar manualmente)."
            )

        packing = create_packing(
            client_id=request.client_id,
            rows=rows,
            header=packing_request.header,
            escp_order_id=request.escp_order_id,
        )
        packings.append(packing)

        for error in errors:
            warnings.append(f"{doc_label}: {error}")
        if not packing.qty_match:
            warnings.append(
                f"{doc_label}: quantidade CSV ({packing_request.header.total_qty}) "
                f"difere da quantidade criada no packing ({packing.total_qty})"
            )

    return ImportResult(
        items_created=items_created,
        items_skipped=items_skipped,
        packing=packings[0] if packings else None,
        packings=packings,
        total_packings=len(packings),
        warnings=warnings,
    )
