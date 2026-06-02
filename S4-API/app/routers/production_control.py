from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request

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


async def _request_json_payload(request: Request, root_key: Optional[str] = None):
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        return None

    payload = await request.json()
    if root_key and isinstance(payload, dict) and root_key in payload:
        return payload[root_key]
    return payload


def _consumption_payload_from_form(
    partner_id: Optional[str],
    project: Optional[str],
    item_id: Optional[str],
    consumption_date: Optional[date],
    location_code: Optional[str],
    component_ids: Optional[list[str]],
    qtys_consumir: Optional[list[Decimal]],
) -> ConsumptionRequest:
    missing = []
    if not partner_id:
        missing.append("PartnerID")
    if not project:
        missing.append("Project")
    if not item_id:
        missing.append("ItemId")
    if not consumption_date:
        missing.append("ConsumptionDate")
    if not component_ids:
        missing.append("ComponentId")
    if not qtys_consumir:
        missing.append("QtyConsumir")
    if missing:
        raise ValueError(f"Missing required form field(s): {', '.join(missing)}")

    if len(component_ids or []) != len(qtys_consumir or []):
        raise ValueError("ComponentId and QtyConsumir must have the same number of values")

    return ConsumptionRequest(
        Header={
            "PartnerID": partner_id,
            "Project": project,
            "ItemId": item_id,
            "ConsumptionDate": consumption_date,
            "LocationCode": location_code,
        },
        Lines=[
            {"ComponentId": component_id, "QtyConsumir": qty}
            for component_id, qty in zip(component_ids or [], qtys_consumir or [])
        ],
    )


def _consumption_with_origin_payload_from_form(
    partner_id: Optional[str],
    project: Optional[str],
    item_id: Optional[str],
    consumption_date: Optional[date],
    location_code: Optional[str],
    origin_doc_type: Optional[str],
    origin_order_id: Optional[int],
    origin_order_row: Optional[int],
    component_ids: Optional[list[str]],
    qtys_consumir: Optional[list[Decimal]],
) -> ConsumptionWithOriginRequest:
    missing = []
    if not origin_doc_type:
        missing.append("OriginDocType")
    if origin_order_id is None:
        missing.append("OriginOrderID")
    if origin_order_row is None:
        missing.append("OriginOrderRow")
    if missing:
        raise ValueError(f"Missing required form field(s): {', '.join(missing)}")

    base_payload = _consumption_payload_from_form(
        partner_id=partner_id,
        project=project,
        item_id=item_id,
        consumption_date=consumption_date,
        location_code=location_code,
        component_ids=component_ids,
        qtys_consumir=qtys_consumir,
    )

    return ConsumptionWithOriginRequest(
        Header={
            "PartnerID": base_payload.header.partner_id,
            "Project": base_payload.header.project,
            "ItemId": base_payload.header.item_id,
            "ConsumptionDate": base_payload.header.movement_date,
            "LocationCode": base_payload.header.location_code,
            "OriginDocType": origin_doc_type,
            "OriginOrderID": origin_order_id,
            "OriginOrderRow": origin_order_row,
        },
        Lines=[
            {"ComponentId": line.component_id, "QtyConsumir": line.qty_consumir}
            for line in base_payload.lines
        ],
    )


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
async def post_consumption(
    request: Request,
    payload_json: Optional[str] = Form(default=None, alias="PayloadJson"),
    partner_id: Optional[str] = Form(default=None, alias="PartnerID", min_length=1, max_length=20),
    project: Optional[str] = Form(default=None, alias="Project", min_length=1, max_length=20),
    item_id: Optional[str] = Form(default=None, alias="ItemId", min_length=1, max_length=50),
    consumption_date: Optional[date] = Form(default=None, alias="ConsumptionDate"),
    location_code: Optional[str] = Form(default=None, alias="LocationCode", min_length=1, max_length=20),
    component_ids: Optional[list[str]] = Form(default=None, alias="ComponentId"),
    qtys_consumir: Optional[list[Decimal]] = Form(default=None, alias="QtyConsumir"),
) -> ConsumptionResponse:
    try:
        if payload_json:
            payload = ConsumptionRequest.model_validate_json(payload_json)
        elif json_payload := await _request_json_payload(request, "Consumption"):
            payload = ConsumptionRequest.model_validate(json_payload)
        else:
            payload = _consumption_payload_from_form(
                partner_id=partner_id,
                project=project,
                item_id=item_id,
                consumption_date=consumption_date,
                location_code=location_code,
                component_ids=component_ids,
                qtys_consumir=qtys_consumir,
            )
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
async def post_consumption_with_origin(
    request: Request,
    payload_json: Optional[str] = Form(default=None, alias="PayloadJson"),
    partner_id: Optional[str] = Form(default=None, alias="PartnerID", min_length=1, max_length=20),
    project: Optional[str] = Form(default=None, alias="Project", min_length=1, max_length=20),
    item_id: Optional[str] = Form(default=None, alias="ItemId", min_length=1, max_length=50),
    consumption_date: Optional[date] = Form(default=None, alias="ConsumptionDate"),
    location_code: Optional[str] = Form(default=None, alias="LocationCode", min_length=1, max_length=20),
    origin_doc_type: Optional[str] = Form(default=None, alias="OriginDocType", min_length=1, max_length=20),
    origin_order_id: Optional[int] = Form(default=None, alias="OriginOrderID"),
    origin_order_row: Optional[int] = Form(default=None, alias="OriginOrderRow"),
    component_ids: Optional[list[str]] = Form(default=None, alias="ComponentId"),
    qtys_consumir: Optional[list[Decimal]] = Form(default=None, alias="QtyConsumir"),
) -> ConsumptionResponse:
    try:
        if payload_json:
            payload = ConsumptionWithOriginRequest.model_validate_json(payload_json)
        elif json_payload := await _request_json_payload(request, "Consumption"):
            payload = ConsumptionWithOriginRequest.model_validate(json_payload)
        else:
            payload = _consumption_with_origin_payload_from_form(
                partner_id=partner_id,
                project=project,
                item_id=item_id,
                consumption_date=consumption_date,
                location_code=location_code,
                origin_doc_type=origin_doc_type,
                origin_order_id=origin_order_id,
                origin_order_row=origin_order_row,
                component_ids=component_ids,
                qtys_consumir=qtys_consumir,
            )
        return create_consumption_order_with_origin(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create consumption with origin: {exc}",
        ) from exc
