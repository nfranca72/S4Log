from fastapi import APIRouter, HTTPException

from app.models.by_ptl import (
    ByPtlDispatchRequest,
    ByPtlDispatchResponse,
    ByPtlWaveRequest,
    ByPtlWaveResponse,
)
from app.services.by_ptl import dispatch_to_wms, receive_wave

router = APIRouter(prefix="/BY-PTL", tags=["BY-PTL"])


@router.post(
    "/BYPTL",
    summary="Send a BY-PTL action to the external WMS",
    response_model=ByPtlDispatchResponse,
)
def post_byptl(payload: ByPtlDispatchRequest) -> ByPtlDispatchResponse:
    try:
        return dispatch_to_wms(payload)
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
def post_wave(payload: ByPtlWaveRequest) -> ByPtlWaveResponse:
    try:
        return receive_wave(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to receive BY-PTL wave: {exc}",
        ) from exc
