from __future__ import annotations

from app.models.settings import CreateUpdateUserRequest, CreateUpdateUserResponse
from app.repositories.settings import create_or_update_user


def create_update_new_user(payload: CreateUpdateUserRequest) -> CreateUpdateUserResponse:
    active = 1 if payload.status == "1" else 0

    result = create_or_update_user(
        user_id=payload.user_id,
        name=payload.name,
        active=active,
    )

    return CreateUpdateUserResponse(**result)
