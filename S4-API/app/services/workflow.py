from __future__ import annotations

from datetime import date
from typing import Any

from app.models.workflow import UpdateWorkFlowFaseRequest
from app.repositories.workflow import fetch_workflow_list
from app.repositories.workflow import update_workflow_fase


def get_workflow_list(
    by_date: int = 0,
    from_date: date | None = None,
    to_date: date | None = None,
    doc_type: str = "",
    order_id: int = 0,
    order_row: int = 0,
    user_id: str = "",
    page_number: int = 1,
    page_size: int = 50,
    include_lines: bool = False,
) -> dict[str, Any]:
    return fetch_workflow_list(
        by_date=by_date,
        from_date=from_date,
        to_date=to_date,
        doc_type=doc_type.strip(),
        order_id=order_id,
        order_row=order_row,
        user_id=user_id.strip(),
        page_number=page_number,
        page_size=page_size,
        include_lines=include_lines,
    )


def update_workflow_fase_values(payload: UpdateWorkFlowFaseRequest) -> dict[str, Any]:
    return update_workflow_fase(
        doc_type=payload.doc_type.strip(),
        order_id=payload.order_id,
        order_row=payload.order_row,
        fase_id=payload.fase_id.strip(),
        operation=payload.operation,
        date_close=payload.date_close,
        date_prev=payload.date_prev,
        user_id=payload.user_id.strip(),
    )
