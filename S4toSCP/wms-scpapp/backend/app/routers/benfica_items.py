from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import BenficaItemRow, BenficaItemsImportResult, BenficaItemsPreview
from app.services.benfica_items_service import import_benfica_items, parse_benfica_items_excel

router = APIRouter(prefix="/benfica-items", tags=["Import Artigos Benfica"])


@router.post("/preview", response_model=BenficaItemsPreview)
async def preview_benfica_items(file: UploadFile = File(...)):
    if not file.filename.upper().endswith((".XLSX", ".XLS")):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser Excel (.xlsx)")

    content = await file.read()
    try:
        return parse_benfica_items_excel(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import", response_model=BenficaItemsImportResult)
def import_items(rows: list[BenficaItemRow]):
    created, skipped_existing, skipped_duplicates = import_benfica_items(rows)
    return BenficaItemsImportResult(
        created=created,
        skipped_existing=skipped_existing,
        skipped_duplicates=skipped_duplicates,
    )
