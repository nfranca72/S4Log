from json import JSONDecodeError

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.models.settings import CreateUpdateUserRequest, CreateUpdateUserResponse
from app.services.settings import create_update_new_user

router = APIRouter(prefix="/Settings", tags=["Settings"])


@router.post(
    "/CreateUpdateNewUser",
    summary="Create or update a user",
    response_model=CreateUpdateUserResponse,
)
async def post_create_update_new_user(
    request: Request,
) -> CreateUpdateUserResponse:
    try:
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                raw_payload = await request.json()
            except JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
        else:
            form = await request.form()
            raw_payload = dict(form)

        payload = CreateUpdateUserRequest.model_validate(raw_payload)
        return create_update_new_user(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update user: {exc}",
        ) from exc
