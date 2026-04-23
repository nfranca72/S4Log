from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.models.schemas import (
    OrderPreview, EscpOrderSummary, EscpMergeDiff,
    EscpCreateRequest, EscpMergeApplyRequest, OrderRow
)
from app.services.order_parser import parse_order_excel
from app.services.order_service import (
    check_order_items, create_order_items,
    get_escp_orders, get_escp_order_details,
    create_escp_order, merge_escp_order, apply_escp_merge
)

router = APIRouter(prefix="/orders", tags=["Encomendas"])


@router.post("/preview", response_model=OrderPreview)
async def preview_order(file: UploadFile = File(...)):
    """Parse do Excel de encomenda + verificação de artigos na BD."""
    if not file.filename.upper().endswith(('.XLSX', '.XLS')):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser Excel (.xlsx)")

    content = await file.read()
    try:
        preview = parse_order_excel(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Verifica existência dos artigos
    item_ids   = list({r.item_id for r in preview.rows})
    exists_map = check_order_items(item_ids)

    existing = 0
    new      = 0
    for row in preview.rows:
        row.exists_in_db = exists_map.get(row.item_id, False)
        if row.exists_in_db:
            existing += 1
        else:
            new += 1

    unique_exists = sum(1 for iid in item_ids if exists_map.get(iid, False))
    preview.existing_items = unique_exists
    preview.new_items      = len(item_ids) - unique_exists

    return preview


@router.post("/items/create")
async def create_items(rows: list[OrderRow]):
    """Cria artigos em falta no ItemMaster."""
    created, skipped = create_order_items(rows)
    return {"created": created, "skipped": skipped}


@router.get("/escp", response_model=list[EscpOrderSummary])
def list_escp_orders():
    """Lista encomendas ESCP existentes."""
    return [EscpOrderSummary(**o) for o in get_escp_orders()]


@router.post("/escp", response_model=dict)
def create_escp(req: EscpCreateRequest):
    """Cria nova encomenda ESCP."""
    result = create_escp_order(req.client_id, req.rows, req.obs)
    return result


@router.post("/escp/{order_id}/merge-preview", response_model=EscpMergeDiff)
async def merge_preview(order_id: int, file: UploadFile = File(...)):
    """Faz preview do merge sem gravar — mostra diferenças."""
    content = await file.read()
    try:
        preview = parse_order_excel(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    diff = merge_escp_order(order_id, preview.rows)
    return EscpMergeDiff(**diff)


@router.post("/escp/{order_id}/merge-apply")
def merge_apply(order_id: int, req: EscpMergeApplyRequest):
    """Aplica o merge após confirmação do utilizador."""
    apply_escp_merge(order_id, req.rows_to_add, req.rows_to_update)
    return {"success": True}
