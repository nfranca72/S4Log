from json import JSONDecodeError
from typing import TypeVar, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.models.by_ptl import (
    ByPtlDispatchRequest,
    ByPtlDispatchResponse,
    ByPtlQueuedResponse,
    ByPtlWaveRequest,
    ByPtlWaveResponse,
)
from app.services.by_ptl import queue_or_dispatch_to_wms, receive_wave
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
