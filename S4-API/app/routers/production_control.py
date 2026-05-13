from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.models.production_control import (
    ConsumptionRequest,
    ConsumptionResponse,
    ConsumptionWithOriginRequest,
)
from app.services.production_control import (
    create_consumption_order,
    create_consumption_order_with_origin,
    get_production_entrie_status,
    list_coonsumption_for_itemmaster_and_bpartner,
    list_production_entries_by_dates,
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


@router.get(
    "/GetProductionEntriesByDates",
    summary="List production entries between two dates",
)
def get_production_entries_by_dates(
    from_date: date = Query(..., alias="FromDate"),
    to_date: date = Query(..., alias="ToDate"),
) -> list[dict[str, object]]:
    try:
        return list_production_entries_by_dates(
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch production entries by dates: {exc}",
        ) from exc


@router.get(
    "/GetProductionEntrieStatus",
    summary="Get production entry status",
)
def get_production_entrie_status_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderId"),
) -> list[dict[str, object]]:
    try:
        return get_production_entrie_status(
            doc_type=doc_type,
            order_id=order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch production entrie status: {exc}",
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


@router.post(
    "/ConsumptionWithOrigin",
    summary="Create a subcontractor consumption using an explicit origin document",
    response_model=ConsumptionResponse,
)
def post_consumption_with_origin(payload: ConsumptionWithOriginRequest) -> ConsumptionResponse:
    try:
        return create_consumption_order_with_origin(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create consumption with origin: {exc}",
        ) from exc
