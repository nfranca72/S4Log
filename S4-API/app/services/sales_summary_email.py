from __future__ import annotations

import smtplib
from datetime import date, datetime
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, NamedTuple

from app.repositories.sales_summary import fetch_sales_summary_sections
from app.settings import settings


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "email_template.html"


class EmailConfig(NamedTuple):
    smtp_server: str | None
    smtp_port: int
    sender: str | None
    password: str | None
    recipients: str | None
    required_prefix: str


def send_sales_summary_email(preview_only: bool = False) -> dict[str, object]:
    sections = fetch_sales_summary_sections()
    html = build_sales_summary_html(sections)
    email_config = sales_email_config()
    recipients = _recipients(email_config) if not preview_only else configured_recipients(email_config)
    subject = _subject()

    if not preview_only:
        _send_email(
            html_content=html,
            subject=subject,
            recipients=recipients,
            email_config=email_config,
        )

    return {
        "Message": "Preview generated" if preview_only else "Email sent successfully",
        "Subject": subject,
        "Recipients": recipients,
        "PreviewOnly": preview_only,
        "Sections": sections,
    }


def preview_sales_summary_email_html() -> str:
    sections = fetch_sales_summary_sections()
    return build_sales_summary_html(sections)


def build_sales_summary_html(sections: list[dict[str, Any]]) -> str:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("{{ DATA_EMAIL }}", date.today().strftime("%d/%m/%Y"))
    html = html.replace("{{ SALES_SECTIONS }}", "\n".join(_section_html(section) for section in sections))
    return html


def _section_html(section: dict[str, Any]) -> str:
    title = str(section.get("Title") or "")
    data = section.get("Rows") or {}
    margin_top = "0" if title == "VENDAS TOTAIS" else "26px"
    rows = "\n".join(
        _summary_row_html(label, data.get(label, {"v2024": 0, "v2025": 0, "v2026": 0}), is_last)
        for label, is_last in [
            ("Ano total", False),
            ("De 01/jan ate hoje", False),
            ("Mes corrente", True),
        ]
    )
    return f"""
              <p style="margin:{margin_top} 0 12px 0; font-size:14px; font-weight:700; letter-spacing:0.04em; color:#2c2c2a; text-transform:uppercase;">{title}</p>
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed; border-collapse:collapse; font-size:13px;">
                <colgroup>
                  <col style="width:24%;">
                  <col style="width:17%;">
                  <col style="width:12%;">
                  <col style="width:17%;">
                  <col style="width:12%;">
                  <col style="width:18%;">
                </colgroup>
                <tr style="border-bottom: 1px solid #e0dfd8;">
                  <th style="text-align:left; padding:8px 8px 8px 0; font-weight:500; color:#888780; font-size:12px;">Periodo</th>
                  <th style="text-align:right; padding:8px 6px; font-weight:500; color:#888780; font-size:12px;">2026</th>
                  <th style="text-align:center; padding:8px 6px; font-weight:500; color:#888780; font-size:12px; white-space:nowrap;">vs 2025</th>
                  <th style="text-align:right; padding:8px 6px; font-weight:500; color:#888780; font-size:12px;">2025</th>
                  <th style="text-align:center; padding:8px 6px; font-weight:500; color:#888780; font-size:12px; white-space:nowrap;">vs 2024</th>
                  <th style="text-align:right; padding:8px 0 8px 6px; font-weight:500; color:#888780; font-size:12px;">2024</th>
                </tr>
{rows}
              </table>"""


def _summary_row_html(label: str, row: dict[str, Any], is_last: bool) -> str:
    border = "" if is_last else "border-bottom: 1px solid #f1efe8;"
    return f"""
                <tr style="{border}">
                  <td style="padding:11px 8px 11px 0; color:#5f5e5a; font-size:13px;">{label}</td>
                  <td style="padding:11px 6px; text-align:right; color:#2c2c2a; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap;">{_fmt_eur(row.get("v2026"))}</td>
                  <td style="padding:11px 6px; text-align:center; white-space:nowrap;">{_badge(row.get("v2026"), row.get("v2025"))}</td>
                  <td style="padding:11px 6px; text-align:right; color:#2c2c2a; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap;">{_fmt_eur(row.get("v2025"))}</td>
                  <td style="padding:11px 6px; text-align:center; white-space:nowrap;">{_badge(row.get("v2025"), row.get("v2024"))}</td>
                  <td style="padding:11px 0 11px 6px; text-align:right; color:#2c2c2a; font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap;">{_fmt_eur(row.get("v2024"))}</td>
                </tr>"""


def _send_email(
    html_content: str,
    subject: str,
    recipients: list[str],
    email_config: EmailConfig | None = None,
) -> None:
    email_config = email_config or sales_email_config()
    missing = [
        name
        for name, value in {
            f"{email_config.required_prefix}_SMTP_SERVER": email_config.smtp_server,
            f"{email_config.required_prefix}_SENDER": email_config.sender,
            f"{email_config.required_prefix}_PASSWORD": email_config.password,
            f"{email_config.required_prefix}_RECIPIENTS": email_config.recipients,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError("Email configuration is incomplete. Missing: " + ", ".join(missing))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = str(email_config.sender)
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP(str(email_config.smtp_server), email_config.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(str(email_config.sender), str(email_config.password))
        server.sendmail(str(email_config.sender), recipients, msg.as_string())


def send_html_email(
    html_content: str,
    subject: str,
    recipients: list[str] | None = None,
    email_config: EmailConfig | None = None,
) -> list[str]:
    email_config = email_config or sales_email_config()
    target_recipients = recipients or _recipients(email_config)
    _send_email(
        html_content=html_content,
        subject=subject,
        recipients=target_recipients,
        email_config=email_config,
    )
    return target_recipients


def _recipients(email_config: EmailConfig | None = None) -> list[str]:
    email_config = email_config or sales_email_config()
    recipients = configured_recipients(email_config)
    if not recipients:
        raise ValueError(
            f"Email configuration is incomplete. Missing: {email_config.required_prefix}_RECIPIENTS"
        )
    return recipients


def configured_recipients(email_config: EmailConfig | None = None) -> list[str]:
    email_config = email_config or sales_email_config()
    recipients = [
        recipient.strip()
        for recipient in (email_config.recipients or "").replace(";", ",").split(",")
        if recipient.strip()
    ]
    return recipients


def configured_sales_email_recipients() -> list[str]:
    return configured_recipients(sales_email_config())


def sales_email_config() -> EmailConfig:
    return EmailConfig(
        smtp_server=settings.sales_email_smtp_server,
        smtp_port=settings.sales_email_smtp_port,
        sender=settings.sales_email_sender,
        password=settings.sales_email_password,
        recipients=settings.sales_email_recipients,
        required_prefix="SALES_EMAIL",
    )


def sales_ma_email_config() -> EmailConfig:
    return EmailConfig(
        smtp_server=settings.sales_ma_email_smtp_server,
        smtp_port=settings.sales_ma_email_smtp_port,
        sender=settings.sales_ma_email_sender,
        password=settings.sales_ma_email_password,
        recipients=settings.sales_ma_email_recipients,
        required_prefix="SALES_MA_EMAIL",
    )


def _subject() -> str:
    month_label = datetime.now().strftime("%m/%Y")
    return f"{settings.sales_email_subject_prefix} - {month_label}"


def _fmt_eur(value: Any) -> str:
    if value is None:
        return "-"
    number = _decimal(value)
    formatted = f"{number:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} &euro;"


def _badge(v_new: Any, v_old: Any) -> str:
    new = _decimal(v_new)
    old = _decimal(v_old)
    if old == 0:
        return ""

    pct = ((new - old) / abs(old)) * Decimal("100")
    abs_pct = abs(pct)
    if pct > Decimal("1"):
        return (
            '<span style="display:inline-block; background:#eaf3de; color:#3b6d11; '
            'font-size:11px; font-weight:600; padding:3px 8px; border-radius:999px;">'
            f'&#9650; {abs_pct:.1f}%</span>'
        )
    if pct < Decimal("-1"):
        return (
            '<span style="display:inline-block; background:#fcebeb; color:#a32d2d; '
            'font-size:11px; font-weight:600; padding:3px 8px; border-radius:999px;">'
            f'&#9660; {abs_pct:.1f}%</span>'
        )
    return (
        '<span style="display:inline-block; background:#f1efe8; color:#5f5e5a; '
        'font-size:11px; font-weight:600; padding:3px 8px; border-radius:999px;">'
        f'= {abs_pct:.1f}%</span>'
    )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))
