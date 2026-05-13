from fastapi import APIRouter, HTTPException

from app.models.settings import CreateUpdateUserRequest, CreateUpdateUserResponse
from app.services.settings import create_update_new_user

router = APIRouter(prefix="/Settings", tags=["Settings"])


@router.post(
    "/CreateUpdateNewUser",
    summary="Create or update a user",
    response_model=CreateUpdateUserResponse,
)
def post_create_update_new_user(
    payload: CreateUpdateUserRequest,
) -> CreateUpdateUserResponse:
    try:
        return create_update_new_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update user: {exc}",
        ) from exc
