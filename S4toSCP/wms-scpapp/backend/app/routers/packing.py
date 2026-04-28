from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.models.schemas import CSVPreview, PackingCreateRequest, ImportResult
from app.services.csv_parser import parse_csv
from app.services.item_creator import check_items_exist
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
        # Resolve ItemIDs — não bloqueia, importa o que consegue e avisa o resto
        resolved_rows, errors = resolve_item_ids(escp_order_id, preview.rows)
        preview.rows = [r for r in resolved_rows if r.item_id]
        if errors:
            if not hasattr(preview, 'warnings'):
                preview.warnings = []
            preview.warnings = errors

    # Verifica existência de artigos na BD
    item_ids   = list({r.item_id for r in preview.rows})
    exists_map = check_items_exist(item_ids)

    existing = 0
    new      = 0
    for row in preview.rows:
        row.exists_in_db = exists_map.get(row.item_id, False)
        if row.exists_in_db:
            existing += 1
        else:
            new += 1

    unique_exists         = sum(1 for iid in item_ids if exists_map.get(iid, False))
    preview.existing_articles = unique_exists
    preview.new_articles      = len(item_ids) - unique_exists

    return preview


@router.post("/import", response_model=ImportResult)
async def import_packing(request: PackingCreateRequest):
    """
    Executa a importação completa.
    Se escp_order_id presente, valida e resolve ItemIDs antes de importar.
    """
    if not request.escp_order_id:
        raise HTTPException(status_code=400, detail="Encomenda obrigatória — seleciona uma encomenda ESCP antes de importar o packing list")

    # Se não vier client_id, vai buscar à encomenda ESCP
    if not request.client_id:
        with __import__('app.db.connection', fromlist=['db_cursor']).db_cursor() as (cursor, _):
            cursor.execute("SELECT ClientID FROM ClientOrders WHERE OrderID = ? AND DocType = 'ESCP'", (request.escp_order_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Encomenda ESCP não encontrada")
            request.client_id = row[0]

    resolved_rows, errors = resolve_item_ids(request.escp_order_id, request.csv_rows)
    original_row_count = len(request.csv_rows)
    # Filtra só linhas resolvidas — importa o que consegue, avisa o resto
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
            f"Atenção: quantidade CSV ({request.header.total_qty}) "
            f"difere da quantidade criada no packing ({packing.total_qty})"
        )
    if import_warnings:
        warnings.insert(0, f"{len(import_warnings)} artigo(s) não encontrados na encomenda foram ignorados.")

    return ImportResult(
        items_created=items_created,
        items_skipped=items_skipped,
        packing=packing,
        warnings=warnings,
    )
