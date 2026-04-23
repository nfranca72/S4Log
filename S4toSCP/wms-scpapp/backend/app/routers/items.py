from __future__ import annotations
from fastapi import APIRouter
from app.models.schemas import ItemCheckResult, CSVRow
from app.services.item_creator import check_items_exist, create_items

router = APIRouter(prefix="/items", tags=["Artigos"])


@router.post("/check", response_model=list[ItemCheckResult])
def check_items(item_ids: list[str]):
    """Verifica quais artigos já existem no ItemMaster."""
    exists_map = check_items_exist(item_ids)
    return [
        ItemCheckResult(item_id=item_id, exists=exists)
        for item_id, exists in exists_map.items()
    ]


@router.post("/create")
def create_items_endpoint(rows: list[CSVRow]):
    """Cria artigos em falta no ItemMaster a partir das linhas do CSV."""
    created, skipped = create_items(rows)
    return {"created": created, "skipped": skipped}
