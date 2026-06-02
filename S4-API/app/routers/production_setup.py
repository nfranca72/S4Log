from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.production_setup import get_production_type

router = APIRouter(prefix="/ProductionSetup", tags=["ProductionSetup"])


@router.get(
    "/ProductionTypeGetAll",
    summary="Get a production type setup",
)
def get_production_type_get_all(
    production_type: Optional[str] = Query(None, alias="ProductionType", max_length=50),
    indentification_code: Optional[str] = Query(None, alias="IndentificationCode", max_length=50),
) -> list[dict[str, object]]:
    try:
        result = get_production_type(
            production_type=production_type or "",
            indentification_code=indentification_code or "",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch production type setup: {exc}",
        ) from exc

    return result
