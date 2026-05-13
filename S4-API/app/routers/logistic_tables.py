from fastapi import APIRouter, HTTPException

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.services.logistic_tables import create_update_volume

router = APIRouter(prefix="/LogisticTables", tags=["LogisticTables"])


@router.post(
    "/Volumes",
    summary="Create or update a volume type",
    response_model=VolumeResponse,
)
def post_volume(payload: VolumeRequest) -> VolumeResponse:
    try:
        return create_update_volume(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update volume: {exc}",
        ) from exc
