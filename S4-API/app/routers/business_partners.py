from fastapi import APIRouter, HTTPException, Query

from app.services.business_partners import (
    get_business_partner,
    list_active_business_partners,
    list_active_subcontractors_for_itemmaster,
    list_business_contact_persons,
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


@router.get(
    "/GetById",
    summary="Get business partner details by partner type and partner ID",
)
def get_business_partner_endpoint(
    partner_type: str = Query(..., alias="PartnerType", min_length=1, max_length=5),
    partner_id: str = Query(..., alias="PartnerID", min_length=1, max_length=50),
) -> dict[str, object]:
    try:
        result = get_business_partner(
            partner_type=partner_type,
            partner_id=partner_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch business partner: {exc}",
        ) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Business partner not found")

    return result


@router.get(
    "/GetBusinessContactPersonList",
    summary="List business partner contact persons",
)
def get_business_contact_person_list(
    partner_type: str = Query(..., alias="PartnerType", min_length=1, max_length=5),
    partner_id: str = Query(..., alias="PartnerID", min_length=1, max_length=50),
    contact_id: str = Query("", alias="ContactID", max_length=100),
) -> list[dict[str, object]]:
    try:
        return list_business_contact_persons(
            partner_type=partner_type,
            partner_id=partner_id,
            contact_id=contact_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch business partner contact persons: {exc}",
        ) from exc
