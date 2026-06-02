from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Form, HTTPException

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.services.logistic_tables import create_update_volume

router = APIRouter(prefix="/LogisticTables", tags=["LogisticTables"])


@router.post(
    "/Volumes",
    summary="Create or update a volume type",
    response_model=VolumeResponse,
)
def post_volume(
    volume_type: str = Form(..., alias="VolumeType", min_length=1, max_length=10),
    vol_doc_cod: Optional[str] = Form(None, alias="VolDocCod", min_length=1, max_length=10),
    length: Decimal = Form(..., alias="Long"),
    height: Decimal = Form(..., alias="High"),
    width: Decimal = Form(..., alias="Width"),
    net_weight: Optional[Decimal] = Form(None, alias="NetWeight"),
) -> VolumeResponse:
    try:
        payload = VolumeRequest(
            VolumeType=volume_type,
            VolDocCod=vol_doc_cod,
            Long=length,
            High=height,
            Width=width,
            NetWeight=net_weight,
        )
        return create_update_volume(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update volume: {exc}",
        ) from exc
