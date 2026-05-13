from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CreateUpdateUserRequest(BaseModel):
    user_id: str = Field(..., alias="UserId", min_length=1, max_length=40)
    name: str = Field(..., alias="name", min_length=1, max_length=40)
    status: str = Field(..., alias="status", min_length=1, max_length=1)

    @field_validator("user_id", "name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in {"0", "1"}:
            raise ValueError("status must be '1' for active or '0' for inactive")
        return normalized


class CreateUpdateUserResponse(BaseModel):
    user_id: str = Field(..., alias="UserId")
    name: str = Field(..., alias="name")
    active: int = Field(..., alias="Active")
    action: str = Field(..., alias="Action")
