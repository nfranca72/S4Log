from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import CSVPreview, ImportResult, PackingCreateRequest
from app.services.csv_parser import parse_csv
from app.services.item_creator import check_items_exist
from app.services.order_service import get_active_escp_client_id
from app.services.packing_creator import create_packing
from app.services.packing_resolver import resolve_item_ids

router = APIRouter(prefix="/packing", tags=["Packing List"])


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

        resolved_rows, errors = resolve_item_ids(escp_order_id, preview.rows)
        preview.rows = [r for r in resolved_rows if r.item_id]
        if errors:
            if not hasattr(preview, "warnings"):
                preview.warnings = []
            preview.warnings = errors

    item_ids = list({r.item_id for r in preview.rows})
    exists_map = check_items_exist(item_ids)

    for row in preview.rows:
        row.exists_in_db = exists_map.get(row.item_id, False)

    unique_exists = sum(1 for iid in item_ids if exists_map.get(iid, False))
    preview.existing_articles = unique_exists
    preview.new_articles = len(item_ids) - unique_exists

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

    resolved_rows, errors = resolve_item_ids(request.escp_order_id, request.csv_rows)
    original_row_count = len(request.csv_rows)
    request.csv_rows = [r for r in resolved_rows if r.item_id]
    import_warnings = errors

    items_created = 0
    items_skipped = original_row_count - len(request.csv_rows)

    packing = create_packing(
        client_id=request.client_id,
        rows=request.csv_rows,
        header=request.header,
        escp_order_id=request.escp_order_id,
    )

    warnings = list(import_warnings)
    if not packing.qty_match:
        warnings.append(
            f"Atencao: quantidade CSV ({request.header.total_qty}) "
            f"difere da quantidade criada no packing ({packing.total_qty})"
        )
    if import_warnings:
        warnings.insert(0, f"{len(import_warnings)} artigo(s) nao encontrados na encomenda foram ignorados.")

    return ImportResult(
        items_created=items_created,
        items_skipped=items_skipped,
        packing=packing,
        warnings=warnings,
    )
