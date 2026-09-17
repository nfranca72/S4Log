from json import JSONDecodeError
from typing import Optional, TypeVar, Union

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.models.by_ptl import (
    ByPtlDispatchRequest,
    ByPtlDispatchResponse,
    ByPtlQueuedResponse,
    SeparationOrderCancelRequest,
    SeparationOrderCancelResponse,
    SeparationOrderDetailResponse,
    SeparationOrderListResponse,
    SeparationOrderMaintenanceRequest,
    SeparationOrderMaintenanceResponse,
    SeparationOrderMetadataResponse,
    ByPtlWaveRequest,
    ByPtlWaveResponse,
)
from app.services.by_ptl import (
    get_separation_order_detail,
    get_separation_order_metadata,
    get_separation_orders,
    patch_separation_order_maintenance,
    post_cancel_separation_order,
    queue_or_dispatch_to_wms,
    receive_wave,
)
from app.services.logistic_tables import create_update_volume

router = APIRouter(prefix="/BY-PTL", tags=["BY-PTL"])

RequestModel = TypeVar("RequestModel", bound=BaseModel)


async def _parse_payload(request: Request, model: type[RequestModel]) -> RequestModel:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            raw_payload = await request.json()
        except JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
        return model.model_validate(raw_payload)

    form = await request.form()
    payload_json = form.get("PayloadJson")
    if not payload_json:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "missing",
                    "loc": ["body", "PayloadJson"],
                    "msg": "Field required",
                    "input": None,
                }
            ],
        )
    return model.model_validate_json(str(payload_json))


@router.post(
    "/BYPTL",
    summary="Send a BY-PTL action to the external WMS",
    response_model=Union[ByPtlDispatchResponse, ByPtlQueuedResponse],
)
async def post_byptl(
    request: Request,
) -> Union[ByPtlDispatchResponse, ByPtlQueuedResponse]:
    try:
        payload = await _parse_payload(request, ByPtlDispatchRequest)
        return queue_or_dispatch_to_wms(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send BY-PTL message to WMS: {exc}",
        ) from exc


@router.post(
    "/Wave",
    summary="Receive a BY-PTL wave",
    response_model=ByPtlWaveResponse,
)
async def post_wave(
    request: Request,
) -> ByPtlWaveResponse:
    try:
        payload = await _parse_payload(request, ByPtlWaveRequest)
        return receive_wave(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to receive BY-PTL wave: {exc}",
        ) from exc


@router.post(
    "/Volumes",
    summary="Receive a BY-PTL volume type",
    response_model=VolumeResponse,
)
async def post_volume(
    request: Request,
) -> VolumeResponse:
    try:
        payload = await _parse_payload(request, VolumeRequest)
        return create_update_volume(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to receive BY-PTL volume type: {exc}",
        ) from exc


@router.get(
    "/OrdersPicking",
    summary="List separation orders with header metrics",
    response_model=SeparationOrderListResponse,
)
def get_orders_picking(
    from_date: Optional[str] = Query(None, alias="FromDate"),
    to_date: Optional[str] = Query(None, alias="ToDate"),
    only_open: bool = Query(False, alias="OnlyOpen"),
    only_executed: bool = Query(False, alias="OnlyExecuted"),
    include_cancelled: bool = Query(False, alias="IncludeCancelled"),
) -> SeparationOrderListResponse:
    try:
        return get_separation_orders(
            from_date=from_date,
            to_date=to_date,
            only_open=only_open,
            only_executed=only_executed,
            include_cancelled=include_cancelled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch separation orders: {exc}",
        ) from exc


@router.get(
    "/OrdersPicking/Metadata",
    summary="Get maintenance metadata for separation orders",
    response_model=SeparationOrderMetadataResponse,
)
def get_orders_picking_metadata() -> SeparationOrderMetadataResponse:
    try:
        return get_separation_order_metadata()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch separation order metadata: {exc}",
        ) from exc


@router.get(
    "/OrdersPicking/{order_picking_id}",
    summary="Get separation order detail with lines and boxes",
    response_model=SeparationOrderDetailResponse,
)
def get_order_picking_detail(order_picking_id: int) -> SeparationOrderDetailResponse:
    try:
        return get_separation_order_detail(order_picking_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch separation order detail: {exc}",
        ) from exc


@router.patch(
    "/OrdersPicking/{order_picking_id}",
    summary="Update assigned user and urgency for a separation order",
    response_model=SeparationOrderMaintenanceResponse,
)
async def patch_order_picking(
    order_picking_id: int,
    request: Request,
) -> SeparationOrderMaintenanceResponse:
    try:
        payload = await _parse_payload(request, SeparationOrderMaintenanceRequest)
        return patch_separation_order_maintenance(order_picking_id, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update separation order: {exc}",
        ) from exc


@router.post(
    "/OrdersPicking/{order_picking_id}/Cancel",
    summary="Cancel a separation order and release related documents",
    response_model=SeparationOrderCancelResponse,
)
async def post_order_picking_cancel(
    order_picking_id: int,
    request: Request,
) -> SeparationOrderCancelResponse:
    try:
        payload = await _parse_payload(request, SeparationOrderCancelRequest)
        return post_cancel_separation_order(order_picking_id, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel separation order: {exc}",
        ) from exc
