from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UpdateWorkFlowFaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    doc_type: str = Field(..., alias="DocType", min_length=1, max_length=20)
    order_id: int = Field(..., alias="OrderID", ge=1)
    order_row: int = Field(..., alias="OrderRow", ge=1)
    user_id: str = Field("", alias="UserID", max_length=50)
    fase_id: str = Field(..., alias="FaseID", min_length=1, max_length=50)
    operation: int = Field(..., alias="Operation", ge=0, le=2)
    date_close: Optional[date] = Field(None, alias="DateClose")
    date_prev: Optional[date] = Field(None, alias="DatePrev")
