from datetime import date
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query

from app.models.workflow import UpdateWorkFlowFaseRequest
from app.services.workflow import get_workflow_list
from app.services.workflow import update_workflow_fase_values

router = APIRouter(prefix="/WorkFlow", tags=["WorkFlow"])


@router.get(
    "/GetWorkFlowList",
    summary="Get workflow list",
)
def get_workflow_list_endpoint(
    by_date: int = Query(0, alias="ByDate", ge=0, le=1),
    from_date: Optional[date] = Query(None, alias="FromDate"),
    to_date: Optional[date] = Query(None, alias="ToDate"),
    doc_type: str = Query("", alias="DocType", max_length=20),
    order_id: int = Query(0, alias="OrderID", ge=0),
    order_row: int = Query(0, alias="OrderRow", ge=0),
    user_id: str = Query("", alias="UserID", max_length=50),
    page_number: int = Query(1, alias="PageNumber", ge=1),
    page_size: int = Query(50, alias="PageSize", ge=1, le=500),
    include_lines: bool = Query(False, alias="IncludeLines"),
) -> dict[str, object]:
    try:
        if by_date and (from_date is None or to_date is None):
            raise ValueError("FromDate and ToDate are required when ByDate=1")

        return get_workflow_list(
            by_date=by_date,
            from_date=from_date,
            to_date=to_date,
            doc_type=doc_type,
            order_id=order_id,
            order_row=order_row,
            user_id=user_id,
            page_number=page_number,
            page_size=page_size,
            include_lines=include_lines,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch workflow list: {exc}",
        ) from exc


@router.post(
    "/UpdateWorkFlowFase",
    summary="Update workflow fase",
)
def post_update_workflow_fase(
    doc_type: str = Form(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Form(..., alias="OrderID", ge=1),
    order_row: int = Form(..., alias="OrderRow", ge=1),
    user_id: str = Form("", alias="UserID", max_length=50),
    fase_id: str = Form(..., alias="FaseID", min_length=1, max_length=50),
    operation: int = Form(..., alias="Operation", ge=0, le=2),
    date_close: Optional[date] = Form(None, alias="DateClose"),
    date_prev: Optional[date] = Form(None, alias="DatePrev"),
) -> dict[str, object]:
    try:
        payload = UpdateWorkFlowFaseRequest(
            DocType=doc_type,
            OrderID=order_id,
            OrderRow=order_row,
            UserID=user_id,
            FaseID=fase_id,
            Operation=operation,
            DateClose=date_close,
            DatePrev=date_prev,
        )
        return update_workflow_fase_values(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update workflow fase: {exc}",
        ) from exc
