from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.connection import db_cursor


def fetch_production_type(
    production_type: str = "",
    indentification_code: str = "",
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []

    if production_type.strip():
        where_parts.append("wpt.ProductionType = ?")
        params.append(production_type.strip())

    if indentification_code.strip():
        where_parts.append("ISNULL(wpt.IndentificationCode, '') = ?")
        params.append(indentification_code.strip())

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    query = f"""
        SELECT
            wpt.ProductionType,
            wpt.ProductionTypeDescr,
            wpt.IsDefectType,
            wpt.ProductionTypeIndex,
            wpt.IsControlType,
            ISNULL(wpt.IndentificationCode, '') IndentificationCode,
            wpt.DocTypeToRegister
        FROM WPMProductionTypes wpt WITH (NOLOCK)
        {where_clause}
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def _row_to_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: _json_value(value) for name, value in zip(names, row)}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
