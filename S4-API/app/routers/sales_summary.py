from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.services.sales_summary_email import (
    preview_sales_summary_email_html,
    send_sales_summary_email,
)

router = APIRouter(prefix="/SalesSummary", tags=["SalesSummary"])


@router.get(
    "/SendEmail",
    summary="Send sales summary email",
)
def get_send_sales_summary_email(
    preview_only: bool = Query(False, alias="PreviewOnly"),
) -> dict[str, object]:
    try:
        return send_sales_summary_email(preview_only=preview_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send sales summary email: {exc}",
        ) from exc


@router.get(
    "/Preview",
    summary="Preview sales summary email HTML",
    response_class=HTMLResponse,
)
def get_sales_summary_email_preview() -> HTMLResponse:
    try:
        return HTMLResponse(content=preview_sales_summary_email_html())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview sales summary email: {exc}",
        ) from exc
