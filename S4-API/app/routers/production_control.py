from fastapi import APIRouter, HTTPException, Query

from app.models.production_control import ConsumptionRequest, ConsumptionResponse
from app.services.production_control import (
    create_consumption_order,
    list_coonsumption_for_itemmaster_and_bpartner,
)

router = APIRouter(prefix="/ProductionControl", tags=["ProductionControl"])


@router.get(
    "/CoonsumptionforItemMasterandBPartner",
    summary="List consumption and returns for an item master and business partner",
)
def get_coonsumption_for_itemmaster_and_bpartner(
    item_id: str = Query(..., alias="ItemId", min_length=1, max_length=100),
    doc_type_area: str = Query(..., alias="DocTypeArea", min_length=1, max_length=20),
    bp_id: str = Query(..., alias="BpId", min_length=1, max_length=10),
) -> list[dict[str, object]]:
    try:
        return list_coonsumption_for_itemmaster_and_bpartner(
            item_id=item_id,
            doc_type_area=doc_type_area,
            bp_id=bp_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch consumption for item master and business partner: {exc}",
        ) from exc


@router.post(
    "/Consumption",
    summary="Create a subcontractor consumption with SAP B1 stock issue and local mirror movement",
    response_model=ConsumptionResponse,
)
def post_consumption(payload: ConsumptionRequest) -> ConsumptionResponse:
    try:
        return create_consumption_order(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create consumption: {exc}",
        ) from exc
