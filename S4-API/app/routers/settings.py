from fastapi import APIRouter, Form, HTTPException

from app.models.settings import CreateUpdateUserRequest, CreateUpdateUserResponse
from app.services.settings import create_update_new_user

router = APIRouter(prefix="/Settings", tags=["Settings"])


@router.post(
    "/CreateUpdateNewUser",
    summary="Create or update a user",
    response_model=CreateUpdateUserResponse,
)
def post_create_update_new_user(
    user_id: str = Form(..., alias="UserId", min_length=1, max_length=40),
    name: str = Form(..., alias="name", min_length=1, max_length=40),
    status: str = Form(..., alias="status", min_length=1, max_length=1),
) -> CreateUpdateUserResponse:
    try:
        payload = CreateUpdateUserRequest(
            UserId=user_id,
            name=name,
            status=status,
        )
        return create_update_new_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create or update user: {exc}",
        ) from exc
