from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class VolumeRequest(BaseModel):
    volume_type: str = Field(..., alias="VolumeType", min_length=1, max_length=10)
    vol_doc_cod: Optional[str] = Field(default=None, alias="VolDocCod", min_length=1, max_length=10)
    length: Decimal = Field(..., alias="Long")
    height: Decimal = Field(..., alias="High")
    width: Decimal = Field(..., alias="Width")
    net_weight: Optional[Decimal] = Field(default=None, alias="NetWeight")

    @field_validator("volume_type", "vol_doc_cod", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().upper()
            return normalized or None
        return value

    @field_validator("length", "height", "width", "net_weight", mode="before")
    @classmethod
    def normalize_decimal(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            return normalized.replace(",", ".")
        return value

    @field_validator("length", "height", "width", "net_weight")
    @classmethod
    def validate_decimal(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is None:
            return None
        if value < 0:
            raise ValueError("Decimal values must be greater than or equal to zero")

        normalized = value.normalize()
        sign, digits, exponent = normalized.as_tuple()
        _ = sign

        decimal_places = -exponent if exponent < 0 else 0
        integer_digits = len(digits) - decimal_places
        total_digits = len(digits)

        if decimal_places > 3:
            raise ValueError("Volume decimal values support at most 3 decimal places")
        if total_digits > 12:
            raise ValueError("Volume decimal values support at most 12 total digits")
        if integer_digits > 9:
            raise ValueError("Volume decimal values support up to 9 integer digits")

        return value


class VolumeResponse(BaseModel):
    volume_type: str = Field(..., alias="VolumeType")
    length: Decimal = Field(..., alias="Long")
    height: Decimal = Field(..., alias="High")
    width: Decimal = Field(..., alias="Width")
    net_weight: Optional[Decimal] = Field(default=None, alias="NetWeight")
    volume: Decimal = Field(..., alias="Volume")
    action: str = Field(..., alias="Action")
