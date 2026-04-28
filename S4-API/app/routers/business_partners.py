from fastapi import APIRouter, HTTPException, Query

from app.services.business_partners import (
    list_active_business_partners,
    list_active_subcontractors_for_itemmaster,
)

router = APIRouter(prefix="/BusinessPartners", tags=["BusinessPartners"])


@router.get(
    "/ActiveBusinessPartners",
    summary="List active business partners for a given partner type and document area",
)
def get_active_business_partners(
    bp_type: str = Query(..., alias="BpType", min_length=1, max_length=5),
    doc_type_area: str = Query(..., alias="DocTypeArea", min_length=1, max_length=20),
) -> list[dict[str, str]]:
    try:
        return list_active_business_partners(bp_type=bp_type, doc_type_area=doc_type_area)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active business partners: {exc}",
        ) from exc


@router.get(
    "/AtiveSubcontratorforItemMaster",
    summary="List active subcontractors for a given item and document area",
)
def get_active_subcontractors_for_itemmaster(
    item_id: str = Query(..., alias="ItemId", min_length=1, max_length=100),
    bp_type: str = Query(..., alias="BpType", min_length=1, max_length=1),
    doc_type_area: str = Query(..., alias="DocTypeArea", min_length=1, max_length=20),
) -> list[dict[str, str]]:
    try:
        return list_active_subcontractors_for_itemmaster(
            item_id=item_id,
            bp_type=bp_type,
            doc_type_area=doc_type_area,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active subcontractors for item master: {exc}",
        ) from exc
