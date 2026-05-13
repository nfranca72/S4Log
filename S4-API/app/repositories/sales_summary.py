from contextlib import contextmanager

import pyodbc

from app.settings import settings


SALES_SUMMARY_SECTIONS = [
    {"title": "VENDAS TOTAIS", "client_id": None},
    {"title": "MASSIMO DUTTI", "client_id": "6"},
    {"title": "INDITEX", "client_id": "1970"},
    {"title": "HUGO BOSS", "client_id": "3774"},
    {"title": "TOMMY HILFIGHER", "client_id": "2376"},
    {"title": "TOTEME AB", "client_id": "3813"},
    {"title": "THE KOOPLES", "client_id": "2444"},
    {"title": "LAMAREL", "client_id": "3648"},
    {"title": "100% CAPRI ITALIA", "client_id": "3890"},
    {"title": "H & M", "client_id": "3996"},
    {"title": "MACKINTOSH", "client_id": "4063"},
    {"title": "KOTN", "client_id": "4067"},
    {"title": "JAMES PERSE", "client_id": "4073"},
    {"title": "ONNE EFFICIENCY", "client_id": "4087"},
    {"title": "FUCHS SCHMITT", "client_id": "4088"},
    {"title": "LOOM", "client_id": "4100"},
]


SALES_SUMMARY_SQL = """
SELECT
    Indicador,
    SUM(CASE WHEN Ano = 2024 THEN Valor ELSE 0 END) AS v2024,
    SUM(CASE WHEN Ano = 2025 THEN Valor ELSE 0 END) AS v2025,
    SUM(CASE WHEN Ano = 2026 THEN Valor ELSE 0 END) AS v2026
FROM (
    SELECT 'Ano total' AS Indicador, 1 AS Ordem,
        YEAR(m.DataDoc) AS Ano, SUM(m.TotValue) AS Valor
    FROM DocMovs m
    WHERE m.AreaCod = 'VENDAS'
        AND YEAR(m.DataDoc) IN (2024, 2025, 2026)
        AND (? IS NULL OR CAST(m.PartnerID AS varchar(20)) = ?)
    GROUP BY YEAR(m.DataDoc)

    UNION ALL

    SELECT 'De 01/jan ate hoje', 2,
        YEAR(m.DataDoc),
        SUM(m.TotValue)
    FROM DocMovs m
    WHERE m.AreaCod = 'VENDAS'
        AND YEAR(m.DataDoc) IN (2024, 2025, 2026)
        AND (? IS NULL OR CAST(m.PartnerID AS varchar(20)) = ?)
        AND m.DataDoc <= DATEADD(YEAR, YEAR(m.DataDoc) - YEAR(GETDATE()), CAST(GETDATE() AS DATE))
    GROUP BY YEAR(m.DataDoc)

    UNION ALL

    SELECT 'Mes corrente', 3,
        YEAR(m.DataDoc),
        SUM(m.TotValue)
    FROM DocMovs m
    WHERE m.AreaCod = 'VENDAS'
        AND YEAR(m.DataDoc) IN (2024, 2025, 2026)
        AND (? IS NULL OR CAST(m.PartnerID AS varchar(20)) = ?)
        AND MONTH(m.DataDoc) = MONTH(GETDATE())
    GROUP BY YEAR(m.DataDoc)
) x
GROUP BY Indicador, Ordem
ORDER BY Ordem
"""


def fetch_sales_summary_sections() -> list[dict[str, object]]:
    with sales_db_cursor() as cursor:
        sections = []
        for section in SALES_SUMMARY_SECTIONS:
            client_id = section["client_id"]
            cursor.execute(SALES_SUMMARY_SQL, client_id, client_id, client_id, client_id, client_id, client_id)
            rows = cursor.fetchall()
            sections.append(
                {
                    "Title": section["title"],
                    "ClientId": client_id,
                    "Rows": _rows_to_summary(rows),
                }
            )
    return sections


def fetch_sales_summary() -> dict[str, dict[str, object]]:
    with sales_db_cursor() as cursor:
        cursor.execute(SALES_SUMMARY_SQL, None, None, None, None, None, None)
        rows = cursor.fetchall()

    return _rows_to_summary(rows)


def _rows_to_summary(rows) -> dict[str, dict[str, object]]:
    return {
        str(row[0]): {
            "v2024": row[1],
            "v2025": row[2],
            "v2026": row[3],
        }
        for row in rows
    }


@contextmanager
def sales_db_cursor():
    conn = pyodbc.connect(settings.sales_connection_string)
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()
