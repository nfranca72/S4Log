from json import JSONDecodeError

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.services.logistic_tables import create_update_volume

router = APIRouter(prefix="/LogisticTables", tags=["LogisticTables"])


async def _parse_volume_payload(request: Request) -> VolumeRequest:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            raw_payload = await request.json()
        except JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
        return VolumeRequest.model_validate(raw_payload)

    form = await request.form()
    payload_json = form.get("PayloadJson")
    if payload_json:
        return VolumeRequest.model_validate_json(str(payload_json))

    return VolumeRequest.model_validate(
        {
            "VolumeType": form.get("VolumeType"),
            "VolDocCod": form.get("VolDocCod"),
            "Long": form.get("Long"),
            "High": form.get("High"),
            "Width": form.get("Width"),
            "NetWeight": form.get("NetWeight"),
        }
    )


@router.post(
    "/Volumes",
    summary="Create or update a volume type",
    response_model=VolumeResponse,
)
async def post_volume(
    request: Request,
) -> VolumeResponse:
    try:
        payload = await _parse_volume_payload(request)
        return create_update_volume(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update volume: {exc}",
        ) from exc
