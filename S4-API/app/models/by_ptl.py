from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Optional, Type, Union

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator


def _validate_decimal_6_2(value: Decimal) -> Decimal:
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


class ByPtlArticle(BaseModel):
    item_id: str = Field(..., alias="ItemId", min_length=1, max_length=50)
    description: str = Field(..., alias="Description", min_length=1, max_length=250)
    length: Decimal = Field(..., alias="Long")
    height: Decimal = Field(..., alias="High")
    width: Decimal = Field(..., alias="Width")
    net_weight: Decimal = Field(..., alias="NetWeight")
    barcode: str = Field(..., alias="Barcode", min_length=1, max_length=50)

    @field_validator("item_id", "description", "barcode", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("length", "height", "width", "net_weight")
    @classmethod
    def validate_dimensions(cls, value: Decimal) -> Decimal:
        return _validate_decimal_6_2(value)


class ByPtlOrderLine(BaseModel):
    line: str = Field(..., alias="Line", min_length=1, max_length=10)
    item_id: str = Field(..., alias="ItemId", min_length=1, max_length=50)
    quantity: int = Field(..., alias="Quantity", ge=1, le=9999)

    @field_validator("line", "item_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ByPtlOrder(BaseModel):
    order_id: str = Field(..., alias="OrderId", min_length=1, max_length=35)
    order_obs: Optional[str] = Field(default=None, alias="Orderobs", max_length=250)
    customer_id: str = Field(..., alias="CustomerId", min_length=1, max_length=20)
    customer_name: str = Field(..., alias="CustomerName", min_length=1, max_length=40)
    detail_order: list[ByPtlOrderLine] = Field(..., alias="detailOrder", min_length=1)

    @field_validator("order_id", "order_obs", "customer_id", "customer_name", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class ByPtlWaveRequest(BaseModel):
    wave_id: str = Field(..., alias="WaveID", min_length=1, max_length=32)
    wave_obs: Optional[str] = Field(default=None, alias="WaveObs", max_length=250)
    ptl: str = Field(..., alias="PTL", min_length=1, max_length=10)
    articles: list[ByPtlArticle] = Field(..., alias="Articles", min_length=1)
    orders: list[ByPtlOrder] = Field(..., alias="Orders", min_length=1)

    @field_validator("wave_id", "wave_obs", "ptl", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class ByPtlWaveResponse(BaseModel):
    wave_id: str = Field(..., alias="WaveID")
    ptl: str = Field(..., alias="PTL")
    articles_count: int = Field(..., alias="ArticlesCount")
    articles_created: int = Field(..., alias="ArticlesCreated")
    articles_updated: int = Field(..., alias="ArticlesUpdated")
    customers_created: int = Field(..., alias="CustomersCreated")
    customers_updated: int = Field(..., alias="CustomersUpdated")
    orders_count: int = Field(..., alias="OrdersCount")
    orders_created: int = Field(..., alias="OrdersCreated")
    orders_updated: int = Field(..., alias="OrdersUpdated")
    order_lines_count: int = Field(..., alias="OrderLinesCount")
    picking_created: bool = Field(default=False, alias="PickingCreated")
    picking_details_count: int = Field(default=0, alias="PickingDetailsCount")
    message: str = Field(..., alias="Message")


class ByPtlAction(str, Enum):
    PTL_START = "PTL_START"
    PTL_CHANGE = "PTL_CHANGE"
    PICKING_LIST = "PICKING_LIST"


class ByPtlSimpleActionData(BaseModel):
    wave_id: str = Field(..., alias="WAVEID", min_length=1, max_length=50)
    ptl_id: str = Field(..., alias="PTLID", min_length=1, max_length=50)

    @field_validator("wave_id", "ptl_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ByPtlPickingListDetail(BaseModel):
    order_id: str = Field(..., alias="ORDERID", min_length=1, max_length=50)
    volume_row_id: str = Field(..., alias="VOLUMROWID", min_length=1, max_length=50)
    line: str = Field(..., alias="LINE", min_length=1, max_length=50)
    item_id: str = Field(..., alias="ITEMID", min_length=1, max_length=50)
    quantity: Decimal = Field(..., alias="QUANTITY", ge=0)

    @field_validator("order_id", "volume_row_id", "line", "item_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ByPtlPickingListVolume(BaseModel):
    volume_id: str = Field(..., alias="VOLUMEID", min_length=1, max_length=50)
    volume_weight: Decimal = Field(..., alias="VOLUMEWEIGHT", ge=0)
    volume_type: str = Field(..., alias="VOLUMETYPE", min_length=1, max_length=50)
    user_id: str = Field(..., alias="USERID", min_length=1, max_length=50)
    volume_detail: list[ByPtlPickingListDetail] = Field(..., alias="VOLUMEDETAIL", min_length=1)

    @field_validator("volume_id", "volume_type", "user_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ByPtlPickingListOrder(BaseModel):
    order_id: str = Field(..., alias="ORDERID", min_length=1, max_length=50)
    ptl_light: str = Field(..., alias="PTLLIGHT", min_length=1, max_length=50)
    volumes: list[ByPtlPickingListVolume] = Field(..., alias="VOLUMES", min_length=1)

    @field_validator("order_id", "ptl_light", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ByPtlPickingListData(BaseModel):
    wave_id: str = Field(..., alias="WAVEID", min_length=1, max_length=50)
    ptl_id: str = Field(..., alias="PTLID", min_length=1, max_length=50)
    packing_list_id: str = Field(..., alias="PACKINGLISTID", min_length=1, max_length=50)
    orders: list[ByPtlPickingListOrder] = Field(..., alias="ORDERS", min_length=1)

    @field_validator("wave_id", "ptl_id", "packing_list_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


ByPtlValidatedPayload = Union[ByPtlSimpleActionData, ByPtlPickingListData]


class ByPtlDispatchRequest(BaseModel):
    action: str = Field(..., alias="Action", min_length=1, max_length=50)
    data: dict = Field(..., alias="Data")

    _validated_payload: ByPtlValidatedPayload = PrivateAttr()
    _action_to_send: ByPtlAction = PrivateAttr()

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().upper()
        if normalized == "PACKED_BOX":
            return ByPtlAction.PICKING_LIST.value
        return normalized

    @model_validator(mode="after")
    def validate_payload(self) -> "ByPtlDispatchRequest":
        try:
            action = ByPtlAction(self.action)
        except ValueError as exc:
            supported = ", ".join(action.value for action in ByPtlAction)
            raise ValueError(f"Unsupported BY-PTL action '{self.action}'. Supported: {supported}") from exc

        payload_model: Type[BaseModel]
        if action in {ByPtlAction.PTL_START, ByPtlAction.PTL_CHANGE}:
            payload_model = ByPtlSimpleActionData
        else:
            payload_model = ByPtlPickingListData

        self._validated_payload = payload_model.model_validate(self.data)
        self._action_to_send = action
        return self

    @property
    def validated_payload(self) -> ByPtlValidatedPayload:
        return self._validated_payload

    @property
    def action_to_send(self) -> ByPtlAction:
        return self._action_to_send


class ByPtlDispatchResponse(BaseModel):
    action_requested: str = Field(..., alias="ActionRequested")
    action_sent: str = Field(..., alias="ActionSent")
    endpoint: str = Field(..., alias="Endpoint")
    http_status: int = Field(..., alias="HttpStatus")
    request_payload: dict = Field(..., alias="RequestPayload")
    response_body: str = Field(..., alias="ResponseBody")
    message: str = Field(..., alias="Message")
