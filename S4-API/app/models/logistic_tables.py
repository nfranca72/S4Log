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

    @field_validator("length", "height", "width", "net_weight")
    @classmethod
    def validate_decimal_6_2(cls, value: Optional[Decimal]) -> Optional[Decimal]:
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

        if decimal_places > 2:
            raise ValueError("Decimal values support at most 2 decimal places")
        if total_digits > 6:
            raise ValueError("Decimal values support at most 6 total digits")
        if integer_digits > 4:
            raise ValueError("Decimal values support up to 4 integer digits with precision (6,2)")

        return value


class VolumeResponse(BaseModel):
    volume_type: str = Field(..., alias="VolumeType")
    length: Decimal = Field(..., alias="Long")
    height: Decimal = Field(..., alias="High")
    width: Decimal = Field(..., alias="Width")
    net_weight: Optional[Decimal] = Field(default=None, alias="NetWeight")
    volume: Decimal = Field(..., alias="Volume")
    action: str = Field(..., alias="Action")
