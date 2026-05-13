from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.repositories.sales_summary_ma import fetch_sales_summary_ma_companies
from app.services.sales_summary_ma_email import (
    preview_sales_summary_ma_email_html,
    send_sales_summary_ma_email,
)

router = APIRouter(prefix="/SalesSummaryMA", tags=["SalesSummaryMA"])


@router.get(
    "/Companies",
    summary="List MA sales summary companies",
)
def get_sales_summary_ma_companies() -> list[str]:
    try:
        return fetch_sales_summary_ma_companies()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch MA sales summary companies: {exc}",
        ) from exc


@router.get(
    "/SendEmail",
    summary="Send MA sales summary email",
)
def get_send_sales_summary_ma_email(
    company: str = Query(..., alias="Company", min_length=1, max_length=100),
    preview_only: bool = Query(False, alias="PreviewOnly"),
) -> dict[str, object]:
    try:
        return send_sales_summary_ma_email(
            company=company,
            preview_only=preview_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send MA sales summary email: {exc}",
        ) from exc


@router.get(
    "/Preview",
    summary="Preview MA sales summary email HTML",
    response_class=HTMLResponse,
)
def get_sales_summary_ma_email_preview(
    company: str = Query(..., alias="Company", min_length=1, max_length=100),
) -> HTMLResponse:
    try:
        return HTMLResponse(content=preview_sales_summary_ma_email_html(company=company))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview MA sales summary email: {exc}",
        ) from exc
