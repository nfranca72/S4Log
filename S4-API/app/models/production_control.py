from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ConsumptionHeader(BaseModel):
    partner_id: str = Field(..., alias="PartnerID", min_length=1, max_length=20)
    project: str = Field(..., alias="Project", min_length=1, max_length=20)
    item_id: str = Field(..., alias="ItemId", min_length=1, max_length=50)
    movement_date: date = Field(..., alias="ConsumptionDate")
    location_code: Optional[str] = Field(default=None, alias="LocationCode", min_length=1, max_length=20)

    @field_validator("location_code", mode="before")
    @classmethod
    def normalize_location_code(cls, value: object) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized or normalized.lower() == "null":
                return None
            return normalized

        return value


class ConsumptionLine(BaseModel):
    component_id: str = Field(..., alias="ComponentId", min_length=1, max_length=50)
    qty_consumir: Decimal = Field(..., alias="QtyConsumir")

    @field_validator("qty_consumir")
    @classmethod
    def validate_decimal_18_5(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("QtyConsumir must be greater than zero")

        normalized = value.normalize()
        sign, digits, exponent = normalized.as_tuple()
        _ = sign

        decimal_places = -exponent if exponent < 0 else 0
        integer_digits = len(digits) - decimal_places
        total_digits = len(digits)

        if decimal_places > 5:
            raise ValueError("QtyConsumir supports at most 5 decimal places")
        if total_digits > 18:
            raise ValueError("QtyConsumir supports at most 18 total digits")
        if integer_digits > 13:
            raise ValueError("QtyConsumir supports up to 13 integer digits with precision (18,5)")

        return value


class ConsumptionRequest(BaseModel):
    header: ConsumptionHeader = Field(..., alias="Header")
    lines: list[ConsumptionLine] = Field(..., alias="Lines", min_length=1)


class ConsumptionWithOriginHeader(ConsumptionHeader):
    origin_doc_type: str = Field(..., alias="OriginDocType", min_length=1, max_length=20)
    origin_order_id: int = Field(..., alias="OriginOrderID")
    origin_order_row: int = Field(..., alias="OriginOrderRow")

    @field_validator("origin_doc_type")
    @classmethod
    def normalize_origin_doc_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("OriginDocType is required")
        return normalized


class ConsumptionWithOriginRequest(BaseModel):
    header: ConsumptionWithOriginHeader = Field(..., alias="Header")
    lines: list[ConsumptionLine] = Field(..., alias="Lines", min_length=1)


class ConsumptionResultLine(BaseModel):
    component_id: str = Field(..., alias="ComponentId")
    qty_requested: Decimal = Field(..., alias="QtyRequested")
    qty_applied: Decimal = Field(..., alias="QtyApplied")
    qty_skipped: Decimal = Field(..., alias="QtySkipped")


class ConsumptionResponse(BaseModel):
    message: str = Field(..., alias="Message")
    sap_doc_entry: Optional[int] = Field(default=None, alias="SapDocEntry")
    sap_doc_num: Optional[int] = Field(default=None, alias="SapDocNum")
    sap_doc_type: str = Field(..., alias="SapDocType")
    warehouse_code: str = Field(..., alias="WarehouseCode")
    location_code: str = Field(..., alias="LocationCode")
    local_doc_type: str = Field(..., alias="LocalDocType")
    local_order_id: int = Field(..., alias="LocalOrderID")
    movement_date: date = Field(..., alias="MovementDate")
    lines: list[ConsumptionResultLine] = Field(..., alias="Lines")
