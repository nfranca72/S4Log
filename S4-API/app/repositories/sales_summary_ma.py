from __future__ import annotations

from datetime import date
from typing import Any

from app.repositories.sales_summary import sales_db_cursor


YEARS = (2024, 2025, 2026)
SALES_MA_TABLE = "[dbo].[DocMovsAcum]"


SALES_MA_COMPANIES_SQL = """
SELECT DISTINCT [COMPANY]
FROM [dbo].[DocMovsAcum] WITH (NOLOCK)
WHERE [COMPANY] IS NOT NULL
ORDER BY [COMPANY]
"""


SALES_MA_TOTAL_SQL = """
SELECT
    Periodo,
    TipoProd,
    SUM(CASE WHEN Ano = 2024 THEN Valor ELSE 0 END) AS v2024,
    SUM(CASE WHEN Ano = 2025 THEN Valor ELSE 0 END) AS v2025,
    SUM(CASE WHEN Ano = 2026 THEN Valor ELSE 0 END) AS v2026
FROM (
    SELECT
        'Ano total' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
    GROUP BY m.[YEAR], m.[ProdType]

    UNION ALL

    SELECT
        'Mes corrente' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
      AND m.[MONTH] = ?
    GROUP BY m.[YEAR], m.[ProdType]

    UNION ALL

    SELECT
        'Acumulado ate mes corrente' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
      AND m.[MONTH] <= ?
    GROUP BY m.[YEAR], m.[ProdType]
) x
GROUP BY Periodo, TipoProd
"""


SALES_MA_CLIENTS_SQL = """
SELECT
    x.PartnerId,
    x.PartnerName,
    x.Periodo,
    x.TipoProd,
    SUM(CASE WHEN x.Ano = 2024 THEN x.Valor ELSE 0 END) AS v2024,
    SUM(CASE WHEN x.Ano = 2025 THEN x.Valor ELSE 0 END) AS v2025,
    SUM(CASE WHEN x.Ano = 2026 THEN x.Valor ELSE 0 END) AS v2026
FROM (
    SELECT
        CAST(m.[PARTNERID] AS varchar(50)) AS PartnerId,
        m.[PARTNERNAME] AS PartnerName,
        'Ano total' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
      AND ISNULL(CAST(m.[PARTNERID] AS varchar(50)), '') <> '0'
    GROUP BY m.[PARTNERID], m.[PARTNERNAME], m.[YEAR], m.[ProdType]

    UNION ALL

    SELECT
        CAST(m.[PARTNERID] AS varchar(50)) AS PartnerId,
        m.[PARTNERNAME] AS PartnerName,
        'Mes corrente' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
      AND m.[MONTH] = ?
      AND ISNULL(CAST(m.[PARTNERID] AS varchar(50)), '') <> '0'
    GROUP BY m.[PARTNERID], m.[PARTNERNAME], m.[YEAR], m.[ProdType]

    UNION ALL

    SELECT
        CAST(m.[PARTNERID] AS varchar(50)) AS PartnerId,
        m.[PARTNERNAME] AS PartnerName,
        'Acumulado ate mes corrente' AS Periodo,
        CASE WHEN m.[ProdType] = 'I' THEN 'Prod. interna' ELSE 'Prod. externa' END AS TipoProd,
        m.[YEAR] AS Ano,
        SUM(m.[VALUE]) AS Valor
    FROM [dbo].[DocMovsAcum] m WITH (NOLOCK)
    WHERE m.[COMPANY] = ?
      AND m.[YEAR] IN (2024, 2025, 2026)
      AND m.[MONTH] <= ?
      AND ISNULL(CAST(m.[PARTNERID] AS varchar(50)), '') <> '0'
    GROUP BY m.[PARTNERID], m.[PARTNERNAME], m.[YEAR], m.[ProdType]
) x
GROUP BY x.PartnerId, x.PartnerName, x.Periodo, x.TipoProd
ORDER BY x.PartnerName, x.PartnerId, x.Periodo, x.TipoProd
"""


def fetch_sales_summary_ma(company: str, reference_date: date | None = None) -> dict[str, Any]:
    normalized_company = company.strip()
    if not normalized_company:
        raise ValueError("Company is required")

    reference_date = reference_date or date.today()
    current_month = reference_date.month
    with sales_db_cursor() as cursor:
        cursor.execute(
            SALES_MA_TOTAL_SQL,
            normalized_company,
            normalized_company,
            current_month,
            normalized_company,
            current_month,
        )
        rows_total = cursor.fetchall()

        cursor.execute(
            SALES_MA_CLIENTS_SQL,
            normalized_company,
            normalized_company,
            current_month,
            normalized_company,
            current_month,
        )
        rows_clients = cursor.fetchall()

    return {
        "Company": normalized_company,
        "ReferenceDate": reference_date,
        "Total": _parse_total_rows(rows_total),
        "Clients": _parse_client_rows(rows_clients),
    }


def fetch_sales_summary_ma_companies() -> list[str]:
    with sales_db_cursor() as cursor:
        cursor.execute(SALES_MA_COMPANIES_SQL)
        rows = cursor.fetchall()

    return [str(row[0]) for row in rows]


def _parse_total_rows(rows) -> dict[str, dict[str, dict[str, object]]]:
    data: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        period, production_type, v2024, v2025, v2026 = row
        data.setdefault(str(period), {})[str(production_type)] = {
            "v2024": v2024,
            "v2025": v2025,
            "v2026": v2026,
        }
    return data


def _parse_client_rows(rows) -> list[dict[str, Any]]:
    clients_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        partner_id, partner_name, period, production_type, v2024, v2025, v2026 = row
        key = (str(partner_id or ""), str(partner_name or ""))
        client = clients_by_key.setdefault(
            key,
            {
                "PartnerId": key[0],
                "PartnerName": key[1],
                "Periods": {},
            },
        )
        client["Periods"].setdefault(str(period), {})[str(production_type)] = {
            "v2024": v2024,
            "v2025": v2025,
            "v2026": v2026,
        }

    clients = list(clients_by_key.values())
    clients.sort(key=_client_sort_value, reverse=True)
    return clients


def _client_sort_value(client: dict[str, Any]) -> float:
    period = client.get("Periods", {}).get("Acumulado ate mes corrente", {})
    total = 0
    for production_values in period.values():
        total += float(production_values.get("v2026") or 0)
    return total
