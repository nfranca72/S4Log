"""
integrations/account_balances.py - Sync SAP B1 account monthly balances to Ons3_Dash.dbo.ctb.

Source per company: SAP B1 SQL database (OACT / OJDT / JDT1)
Destination: dashboard SQL database, table dbo.ctb
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Iterable

import pyodbc

from ..config import Settings
from ..models.database import SapCompanySource, get_session
from .base import BaseIntegration

logger = logging.getLogger("integration.account_balances")


SAP_BALANCES_SQL = """
    SELECT
        YEAR(ojdt.RefDate) AS estr1_ano,
        oact.AcctCode AS estr2_conta,
        LEN(LTRIM(RTRIM(oact.AcctCode))) AS estr2_dig,
        MAX(oact.AcctName) AS estr2_descr,
        MONTH(ojdt.RefDate) AS mes,
        CASE
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '7' THEN 'Proveitos'
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '6' THEN 'Custos'
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '5' THEN 'Capital'
            ELSE 'Balanço'
        END AS origem,
        SUM(ISNULL(jdt1.Debit, 0)) AS vald,
        SUM(ISNULL(jdt1.Credit, 0)) AS valc
    FROM JDT1 jdt1 WITH (NOLOCK)
    JOIN OJDT ojdt WITH (NOLOCK)
      ON ojdt.TransId = jdt1.TransId
    JOIN OACT oact WITH (NOLOCK)
      ON oact.AcctCode = jdt1.Account
    WHERE YEAR(ojdt.RefDate) = ?
    GROUP BY
        YEAR(ojdt.RefDate),
        oact.AcctCode,
        LEN(LTRIM(RTRIM(oact.AcctCode))),
        MONTH(ojdt.RefDate),
        CASE
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '7' THEN 'Proveitos'
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '6' THEN 'Custos'
            WHEN LEFT(LTRIM(RTRIM(oact.AcctCode)), 1) = '5' THEN 'Capital'
            ELSE 'Balanço'
        END
"""


class SqlDatabase:
    def __init__(self, settings: Settings, database_name: str):
        self._conn_str = settings.sql_connection_string(database_name)

    @contextmanager
    def transaction(self) -> Generator[pyodbc.Cursor, None, None]:
        conn = pyodbc.connect(self._conn_str, autocommit=False, timeout=30)
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cursor.close()
            finally:
                conn.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        conn = pyodbc.connect(self._conn_str, autocommit=True, timeout=30)
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

    async def afetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_all, sql, params)


class AccountBalancesIntegration(BaseIntegration):
    name = "account_balances"

    def __init__(self, settings: Settings, _wms=None):
        super().__init__()
        self._settings = settings

    async def run(self) -> None:
        years = self._years_to_sync()
        companies = self._active_companies()
        if not companies:
            self.log_warning("Sem empresas SAP ativas para carregar acumulados.")
            return

        self._set_task(f"A carregar acumulados contabilisticos para anos: {', '.join(map(str, years))}")
        dashboard = SqlDatabase(self._settings, self._settings.dashboard_db_name)

        for company in companies:
            source_db_name = str(company["sap_company_db"]).strip()
            source = SqlDatabase(self._settings, source_db_name)
            for year in years:
                label = f"{company['empr_cod']} / {source_db_name} / {year}"
                self._set_task(f"A consultar SAP {label}...")
                try:
                    rows = await source.afetch_all(SAP_BALANCES_SQL, (year,))
                    self._set_task(f"A gravar {len(rows)} linhas em Ons3_Dash para {label}...")
                    await self._replace_dashboard_rows(dashboard, company, year, rows)
                    self._inc_synced(len(rows))
                    self.log_info(f"Acumulados carregados para {label}: {len(rows)} linhas.")
                except Exception as exc:
                    logger.warning("Account balances sync failed for %s: %s", label, exc)
                    self.record_error(
                        sap_key=label,
                        sap_object_type="AccountBalances",
                        error_msg=str(exc),
                        payload={"company": company, "year": year},
                    )

    def _years_to_sync(self) -> list[int]:
        raw = (self._settings.account_balances_years or "").strip()
        if not raw:
            return [datetime.utcnow().year]
        years: list[int] = []
        for part in raw.replace(";", ",").split(","):
            value = part.strip()
            if value:
                years.append(int(value))
        return sorted(set(years))

    @staticmethod
    def _active_companies() -> list[dict[str, Any]]:
        with get_session() as session:
            rows = (
                session.query(SapCompanySource)
                .filter(SapCompanySource.active == 1)
                .order_by(SapCompanySource.empr_cod)
                .all()
            )
            return [
                {
                    "empr_cod": row.empr_cod,
                    "empr_nome": row.empr_nome,
                    "sap_company_db": row.sap_company_db,
                }
                for row in rows
            ]

    async def _replace_dashboard_rows(
        self,
        dashboard: SqlDatabase,
        company: dict[str, Any],
        year: int,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._replace_dashboard_rows_sync,
            dashboard,
            company,
            year,
            list(rows),
        )

    @staticmethod
    def _replace_dashboard_rows_sync(
        dashboard: SqlDatabase,
        company: dict[str, Any],
        year: int,
        rows: list[dict[str, Any]],
    ) -> None:
        insert_sql = """
            INSERT INTO [dbo].[ctb] (
                [empr_cod],
                [empr_nome],
                [estr1_ano],
                [estr1_cod],
                [estr2_conta],
                [estr2_dig],
                [estr2_descr],
                [estr2_tipo],
                [mes],
                [origem],
                [vald],
                [valc]
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = [
            (
                int(company["empr_cod"]),
                str(company["empr_nome"]),
                int(row["estr1_ano"]),
                "SNC",
                str(row["estr2_conta"]),
                int(row["estr2_dig"]),
                str(row["estr2_descr"] or ""),
                "",
                int(row["mes"]),
                str(row["origem"]),
                row["vald"] or 0,
                row["valc"] or 0,
            )
            for row in rows
        ]
        with dashboard.transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM [dbo].[ctb]
                WHERE [empr_cod] = ?
                  AND [estr1_ano] = ?
                """,
                (int(company["empr_cod"]), int(year)),
            )
            if values:
                cursor.fast_executemany = True
                cursor.executemany(insert_sql, values)
