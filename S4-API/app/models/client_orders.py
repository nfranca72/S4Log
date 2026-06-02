from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class UpdateCadConsumptionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    doc_type: str = Field(..., alias="DocType", min_length=1, max_length=20)
    order_id: int = Field(..., alias="OrderID", ge=1)
    item_group_id: str = Field(..., alias="ItemGroupID", min_length=1, max_length=50)
    item_sub_group_id: str = Field(..., alias="ItemSubGroupID", min_length=1, max_length=50)
    item_id: str = Field(..., alias="ItemID", min_length=1, max_length=100)
    shrink_in_x: Decimal = Field(Decimal("0"), alias="ShrinkInX")
    shrink_in_y: Decimal = Field(Decimal("0"), alias="ShrinkInY")
    roll_width: Decimal = Field(Decimal("0"), alias="RollWidth")
    qty_by_cad: Decimal = Field(Decimal("0"), alias="QtyByCad")
    obs: str = Field("", alias="Obs", max_length=500)
