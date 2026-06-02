from __future__ import annotations

from html import escape
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.repositories.sales_summary_ma import fetch_sales_summary_ma
from app.services.sales_summary_email import (
    configured_recipients,
    sales_ma_email_config,
    send_html_email,
)
from app.settings import settings


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "email_template_ma.html"
PERIODS = ("Ano total", "Acumulado ate mes corrente", "Mes corrente")
PRODUCTION_TYPES = ("Prod. interna", "Prod. externa")


def send_sales_summary_ma_email(
    company: str,
    preview_only: bool = False,
    reference_date: date | None = None,
    recipients_override: str | None = None,
) -> dict[str, object]:
    data = fetch_sales_summary_ma(company, reference_date=reference_date)
    html = build_sales_summary_ma_html(data)
    subject = _subject(str(data["Company"]), data["ReferenceDate"])
    email_config = sales_ma_email_config()
    recipients = _parse_recipients(recipients_override) or configured_recipients(email_config)

    if not preview_only:
        recipients = send_html_email(
            html_content=html,
            subject=subject,
            recipients=recipients,
            email_config=email_config,
        )

    return {
        "Message": "Preview generated" if preview_only else "Email sent successfully",
        "Company": data["Company"],
        "Subject": subject,
        "Recipients": recipients,
        "PreviewOnly": preview_only,
        "ReferenceDate": data["ReferenceDate"],
        "Data": data,
    }


def preview_sales_summary_ma_email_html(company: str, reference_date: date | None = None) -> str:
    return build_sales_summary_ma_html(fetch_sales_summary_ma(company, reference_date=reference_date))


def build_sales_summary_ma_html(data: dict[str, Any]) -> str:
    company = str(data["Company"])
    reference_date = data.get("ReferenceDate") or date.today()
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("{{ COMPANY }}", escape(company))
    html = html.replace("{{ DATA_EMAIL }}", reference_date.strftime("%d/%m/%Y"))
    html = html.replace("{{ TABLE_ROWS }}", _table_rows_html(data))
    return html


def _table_rows_html(data: dict[str, Any]) -> str:
    rows = _group_html("Total de vendas")
    for index, period in enumerate(PERIODS):
        if index > 0:
            rows += _double_separator_html()
        rows += _period_html(period, data.get("Total", {}).get(period, {}))

    for client in data.get("Clients", []):
        rows += _spacer_html()
        title = str(client.get("PartnerName") or client.get("PartnerId") or "Cliente")
        rows += _group_html(title)
        periods = client.get("Periods", {})
        for index, period in enumerate(PERIODS):
            if index > 0:
                rows += _double_separator_html()
            rows += _period_html(period, periods.get(period, {}))

    return rows


def _group_html(label: str) -> str:
    safe_label = escape(label)
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse; margin-top:2px;">
      <tr>
        <td colspan="6" style="background:#2c2c2a; color:#f1efe8; font-size:13px; font-weight:600;
            padding:11px 8px; letter-spacing:0.02em;">
          {safe_label}
        </td>
      </tr>
    </table>"""


def _period_html(label: str, production_data: dict[str, dict[str, Any]]) -> str:
    internal = _values(production_data.get("Prod. interna"))
    external = _values(production_data.get("Prod. externa"))
    hide_current_year_comparison = label == "Ano total"
    totals = {
        "v2024": internal["v2024"] + external["v2024"],
        "v2025": internal["v2025"] + external["v2025"],
        "v2026": internal["v2026"] + external["v2026"],
    }
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr style="background:#f1efe8; border-top:1px solid #d3d1c7; border-bottom:1px solid #e0dfd8;">
        <td width="31%" style="padding:8px 4px 8px 8px; font-size:12px; font-weight:600; color:#2c2c2a; line-height:1.25;">{label}</td>
        {_value_cells_html(totals, bold=True, hide_current_year_comparison=hide_current_year_comparison)}
      </tr>
      {_sub_row_html("Prod. interna", internal, hide_current_year_comparison=hide_current_year_comparison)}
      {_sub_row_html("Prod. externa", external, last=True, hide_current_year_comparison=hide_current_year_comparison)}
    </table>"""


def _sub_row_html(
    label: str,
    values: dict[str, Decimal],
    last: bool = False,
    hide_current_year_comparison: bool = False,
) -> str:
    border = "" if last else "border-bottom:1px solid #f1efe8;"
    return f"""
      <tr style="{border}">
        <td style="padding:5px 4px 5px 18px; font-size:11px; color:#888780; line-height:1.25;">{label}</td>
        {_value_cells_html(values, hide_current_year_comparison=hide_current_year_comparison)}
      </tr>"""


def _value_cells_html(
    values: dict[str, Decimal],
    bold: bool = False,
    hide_current_year_comparison: bool = False,
) -> str:
    font_weight = "600" if bold else "400"
    font_size = "12px" if bold else "11px"
    current_year_badge = (
        "&nbsp;" if hide_current_year_comparison else _badge(values["v2026"], values["v2025"])
    )
    return f"""
        <td width="14%" align="right" style="padding:5px 3px; font-size:{font_size}; font-weight:{font_weight}; color:#5f5e5a; font-variant-numeric:tabular-nums; white-space:nowrap;">{_fmt_eur(values["v2026"])}</td>
        <td width="10%" align="center" style="padding:5px 3px; white-space:nowrap;">{current_year_badge}</td>
        <td width="14%" align="right" style="padding:5px 3px; font-size:{font_size}; font-weight:{font_weight}; color:#5f5e5a; font-variant-numeric:tabular-nums; border-left:1px solid #e0dfd8; white-space:nowrap;">{_fmt_eur(values["v2025"])}</td>
        <td width="10%" align="center" style="padding:5px 3px; white-space:nowrap;">{_badge(values["v2025"], values["v2024"])}</td>
        <td width="21%" align="right" style="padding:5px 0 5px 3px; font-size:{font_size}; font-weight:{font_weight}; color:#5f5e5a; font-variant-numeric:tabular-nums; border-left:1px solid #e0dfd8; white-space:nowrap;">{_fmt_eur(values["v2024"])}</td>"""


def _spacer_html() -> str:
    return '<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="height:12px; background:#f5f5f3;"></td></tr></table>'


def _double_separator_html() -> str:
    return '<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="height:0; border-top:1px solid #d3d1c7; border-bottom:3px solid #d3d1c7; padding:0;"></td></tr></table>'


def _subject(company: str, reference_date: date) -> str:
    return f"{settings.sales_ma_email_subject_prefix} - {company} - {reference_date.strftime('%m/%Y')}"


def _parse_recipients(value: str | None) -> list[str]:
    return [
        recipient.strip()
        for recipient in (value or "").replace(";", ",").split(",")
        if recipient.strip()
    ]


def _values(values: dict[str, Any] | None) -> dict[str, Decimal]:
    values = values or {}
    return {
        "v2024": _decimal(values.get("v2024")),
        "v2025": _decimal(values.get("v2025")),
        "v2026": _decimal(values.get("v2026")),
    }


def _fmt_eur(value: Decimal) -> str:
    if value == 0:
        return "-"
    formatted = f"{abs(value):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} &euro;"


def _badge(v_new: Decimal, v_old: Decimal) -> str:
    if v_old == 0:
        return ""

    pct = ((v_new - v_old) / abs(v_old)) * Decimal("100")
    abs_pct = abs(pct)
    if pct > Decimal("1"):
        background, color, arrow = "#eaf3de", "#3b6d11", "&#9650;"
    elif pct < Decimal("-1"):
        background, color, arrow = "#fcebeb", "#a32d2d", "&#9660;"
    else:
        background, color, arrow = "#f1efe8", "#5f5e5a", "="

    return (
        f'<span style="display:inline-block;background:{background};color:{color};'
        f'font-size:9px;font-weight:600;padding:2px 5px;border-radius:999px;">'
        f'{arrow} {abs_pct:.1f}%</span>'
    )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))
