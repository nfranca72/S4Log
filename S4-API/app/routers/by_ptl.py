from fastapi import APIRouter, HTTPException

from app.models.by_ptl import ByPtlWaveRequest, ByPtlWaveResponse
from app.services.by_ptl import receive_wave

router = APIRouter(prefix="/BY-PTL", tags=["BY-PTL"])


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
