from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import db_cursor


def fetch_workflow_list(
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
    by_date_value = int(by_date or 0)
    status_join = ""
    params: list[Any] = []

    if by_date_value == 0:
        status_doc_type_clause = ""
        if doc_type.strip():
            status_doc_type_clause = "AND DocType = ?"
            params.append(doc_type.strip())

        status_join = f"""
        JOIN (
            SELECT DocType, DocStatusID
            FROM DocumentStatus WITH (NOLOCK)
            WHERE IsAnulated = 0
              AND IsFinal = 0
              {status_doc_type_clause}
        ) dc
            ON dc.DocType = cod.DocType
           AND dc.DocStatusID = cod.ProductionStatus
        """
    else:
        status_join = """
        JOIN DocumentStatus dc WITH (NOLOCK)
            ON dc.DocType = cod.DocType
           AND dc.DocStatusID = cod.ProductionStatus
        """

    user_join = ""
    if user_id.strip():
        user_join = """
            JOIN UserBusinessPartners ubp WITH (NOLOCK)
                ON ubp.UserID = ?
               AND ubp.PartnerType = 'C'
               AND (ubp.PartnerID = bp.PartnerID OR ubp.AllPartners = 1)
        """
        params.append(user_id.strip())

    where_parts: list[str] = []
    if doc_type.strip():
        where_parts.append("cod.DocType = ?")
        params.append(doc_type.strip())
    if order_id:
        where_parts.append("cod.OrderID = ?")
        params.append(order_id)
    if order_row:
        where_parts.append("cod.OrderRow = ?")
        params.append(order_row)

    if by_date_value == 1:
        where_parts.append("co.OrderDateTime >= ?")
        where_parts.append("co.OrderDateTime <= ?")
        params.extend([from_date, to_date])
    else:
        default_from_date = from_date or (date.today() - timedelta(days=183))
        default_to_date = to_date or date.today()
        where_parts.append("co.OrderDateTime >= ?")
        where_parts.append("co.OrderDateTime < DATEADD(day, 1, ?)")
        params.extend([default_from_date, default_to_date])

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    page_number = max(int(page_number or 1), 1)
    page_size = int(page_size or 50)
    fetch_size = page_size + 1

    query = f"""
        SELECT
            cod.DocType,
            cod.OrderID,
            cod.OrderRow,
            CAST(co.OrderDateTime AS date) CreationDate,
            CAST(co.OrderDatePrev AS date) DatePrev,
            CAST(co.OrderDatePrevReal AS date) ClientDatePrev,
            bp.PartnerID,
            bp.PartnerName,
            cod.ProductionStatus,
            cod.ItemID,
            cod.Versao
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
        {status_join}
        JOIN BusinessPartners bp WITH (NOLOCK)
            ON bp.PartnerID = co.ClientID
           AND bp.PartnerType = 'C'
        {user_join}
        {where_clause}
        ORDER BY cod.DocType, cod.OrderID, cod.OrderRow
        OFFSET (? - 1) * ? ROWS FETCH NEXT ? ROWS ONLY
        OPTION (RECOMPILE)
    """
    params.extend([page_number, page_size, fetch_size])

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        has_next_page = len(rows) > page_size
        workflows = [_row_to_dict(cursor, row) for row in rows[:page_size]]

        lines_by_key: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
        if include_lines:
            lines_by_key = _fetch_workflow_lines_batch(
                cursor=cursor,
                keys=[
                    (
                        str(workflow.get("DocType") or ""),
                        int(workflow.get("OrderID") or 0),
                        int(workflow.get("OrderRow") or 0),
                    )
                    for workflow in workflows
                ],
                user_id=user_id.strip(),
            )

        for workflow in workflows:
            key = (
                str(workflow.get("DocType") or ""),
                int(workflow.get("OrderID") or 0),
                int(workflow.get("OrderRow") or 0),
            )
            workflow["DocumentWorkFlowLines"] = lines_by_key.get(key, [])

    return {
        "Data": workflows,
        "CurrentPage": page_number,
        "HasNextPage": has_next_page,
        "TotalRecordCount": None,
    }


def update_workflow_fase(
    doc_type: str,
    order_id: int,
    order_row: int,
    fase_id: str,
    operation: int,
    date_close: date | None = None,
    date_prev: date | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    if operation == 1 and date_close is None:
        raise ValueError("DateClose is required when Operation=1")
    if operation == 2 and date_prev is None:
        raise ValueError("DatePrev is required when Operation=2")

    if operation == 0:
        set_clause = "Activated = 1, DtEndReal = NULL"
        params: list[Any] = [doc_type, order_id, order_row, fase_id]
    elif operation == 1:
        set_clause = "Activated = 1, DtEndReal = ?"
        params = [date_close, doc_type, order_id, order_row, fase_id]
    else:
        set_clause = "Activated = 1, DtEndPrev = ?"
        params = [date_prev, doc_type, order_id, order_row, fase_id]

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            f"""
            UPDATE cof
            SET {set_clause}
            FROM ClientOrderFases cof
            WHERE cof.DocType = ?
              AND cof.OrderID = ?
              AND cof.OrderRow = ?
              AND cof.DocumentFase = ?
            """,
            tuple(params),
        )
        updated = max(cursor.rowcount or 0, 0)

    return {
        "DocType": doc_type,
        "OrderID": order_id,
        "OrderRow": order_row,
        "FaseID": fase_id,
        "Operation": operation,
        "UserID": user_id,
        "Updated": updated,
    }


def _fetch_workflow_lines(
    cursor,
    doc_type: str,
    order_id: int,
    order_row: int,
    user_id: str,
) -> list[dict[str, Any]]:
    user_join = ""
    params: list[Any] = []
    if user_id:
        user_join = """
            JOIN AcessUserDocumentFases audf WITH (NOLOCK)
                ON audf.UserID = ?
               AND audf.DocumentFase = cof.DocumentFase
        """
        params.append(user_id)
    else:
        user_join = """
            LEFT JOIN AcessUserDocumentFases audf WITH (NOLOCK)
                ON audf.DocumentFase = cof.DocumentFase
        """

    params.extend([doc_type, order_id, order_row])
    cursor.execute(
        f"""
        SELECT
            cof.DocType,
            cof.OrderID,
            cof.OrderRow,
            audf.AcessType,
            cof.DocumentFase,
            df.DocumentFaseDescr,
            CAST(cof.DtStratPrev AS date) DtStratPrev,
            CAST(cof.DtEndPrev AS date) DtEndPrev,
            CAST(cof.DtEndReal AS date) DtEndReal,
            cof.CompletePrecentage,
            cof.DefaultDuration,
            cof.Obs,
            cof.Incomplete,
            CAST(cof.DtstartCalculated AS date) DtstartCalculated,
            CAST(cof.DtEndCalculated AS date) DtEndCalculated,
            cof.AssignedUserID,
            cof.OrderIndex
        FROM ClientOrderFases cof WITH (NOLOCK)
        JOIN DocumentFases df WITH (NOLOCK)
            ON df.DocType = cof.DocType
           AND df.DocumentFaseID = cof.DocumentFase
        {user_join}
        WHERE cof.DocType = ?
          AND cof.OrderID = ?
          AND cof.OrderRow = ?
        ORDER BY cof.OrderIndex
        """,
        tuple(params),
    )
    return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def _fetch_workflow_lines_batch(
    cursor,
    keys: list[tuple[str, int, int]],
    user_id: str,
) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    if not keys:
        return {}

    values_sql = ", ".join("(?, ?, ?)" for _ in keys)
    key_params: list[Any] = []
    for doc_type, order_id, order_row in keys:
        key_params.extend([doc_type, order_id, order_row])

    if user_id:
        access_select = "audf.AcessType"
        access_join = """
            JOIN AcessUserDocumentFases audf WITH (NOLOCK)
                ON audf.UserID = ?
               AND audf.DocumentFase = cof.DocumentFase
        """
        params: list[Any] = [*key_params, user_id]
    else:
        access_select = "'' AcessType"
        access_join = ""
        params = key_params

    cursor.execute(
        f"""
        SELECT
            cof.DocType,
            cof.OrderID,
            cof.OrderRow,
            {access_select},
            cof.DocumentFase,
            df.DocumentFaseDescr,
            CAST(cof.DtStratPrev AS date) DtStratPrev,
            CAST(cof.DtEndPrev AS date) DtEndPrev,
            CAST(cof.DtEndReal AS date) DtEndReal,
            cof.CompletePrecentage,
            cof.DefaultDuration,
            cof.Obs,
            cof.Incomplete,
            CAST(cof.DtstartCalculated AS date) DtstartCalculated,
            CAST(cof.DtEndCalculated AS date) DtEndCalculated,
            cof.AssignedUserID,
            cof.OrderIndex
        FROM (VALUES {values_sql}) AS wfkeys(DocType, OrderID, OrderRow)
        JOIN ClientOrderFases cof WITH (NOLOCK)
            ON cof.DocType = wfkeys.DocType
           AND cof.OrderID = wfkeys.OrderID
           AND cof.OrderRow = wfkeys.OrderRow
        JOIN DocumentFases df WITH (NOLOCK)
            ON df.DocType = cof.DocType
           AND df.DocumentFaseID = cof.DocumentFase
        {access_join}
        ORDER BY cof.DocType, cof.OrderID, cof.OrderRow, cof.OrderIndex
        """,
        tuple(params),
    )

    result: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        payload = _row_to_dict(cursor, row)
        key = (
            str(payload.get("DocType") or ""),
            int(payload.get("OrderID") or 0),
            int(payload.get("OrderRow") or 0),
        )
        result.setdefault(key, []).append(payload)

    return result


def _row_to_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: _json_value(value) for name, value in zip(names, row)}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
