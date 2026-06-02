from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.connection import db_cursor


def fetch_active_business_partners(bp_type: str, doc_type_area: str) -> list[dict[str, str]]:
    query = """
        SELECT bp.PartnerID, bp.PartnerName
        FROM (
            SELECT DISTINCT co.ClientID
            FROM ClientOrders co
            JOIN DocumentConfig dc WITH (NOLOCK)
                ON dc.DocType = co.DocType
            WHERE dc.DocTypeArea = ?
        ) clients
        JOIN BusinessPartners bp WITH (NOLOCK)
            ON bp.PartnerID = clients.ClientID
        WHERE bp.PartnerType = ?
        ORDER BY bp.PartnerName
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (doc_type_area, bp_type))
        rows = cursor.fetchall()

    return [{"PartnerID": row[0], "PartnerName": row[1]} for row in rows]


def fetch_active_subcontractors_for_itemmaster(
    item_id: str,
    bp_type: str,
    doc_type_area: str,
) -> list[dict[str, str]]:
    query = """
        SELECT DISTINCT bp.PartnerID, bp.PartnerName
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN DocumentConfig dc WITH (NOLOCK)
            ON dc.DocType = cod.DocType
           AND dc.DocTypeArea = ?
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
        JOIN BusinessPartners bp WITH (NOLOCK)
            ON bp.PartnerType = ?
           AND bp.PartnerID = co.SubContratado
        WHERE cod.ItemID = ?
        ORDER BY bp.PartnerName
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (doc_type_area, bp_type, item_id))
        rows = cursor.fetchall()

    return [{"PartnerID": row[0], "PartnerName": row[1]} for row in rows]


def fetch_business_partner(partner_type: str, partner_id: str) -> dict[str, Any] | None:
    query = """
        SELECT bp.PartnerType, pt.PartnerTypeDesc, bp.PartnerID, bp.PartnerName,
            bp.Address, bp.City, bp.PostalCode, bp.Country, bp.VATNo,
            bp.ContactPerson, bp.Phone, bp.MobilePhone, ISNULL(bp.RouteID, '') RouteID,
            ISNULL(bp.PrintLabels, 0) PrintLabels,
            ISNULL(bp.PickingByContainer, 0) PickingByContainer,
            ISNULL(bp.QtyTolerance, 0) QtyTolerance,
            ISNULL(bp.QtyToleranceType, 0) QtyToleranceType,
            ISNULL(bp.QtyToleranceCriteria, 0) QtyToleranceCriteria,
            bp.Flag, bp.ProviderCode, bp.LANGUAGE, bp.ResponsibleUserID,
            bp.PaymentType, bp.Market, bp.SalesCondType, bp.AgentCode,
            bp.AgentCommission, ISNULL(a.AgentName, '') AgentName,
            ISNULL(a.DefaultCommission, 0) DefaultCommission, bp.CreditLimit,
            0 CurrentCreditValue, bp.BaseCurrency, bp.TransportTypeID, bp.BPColor,
            bp.ClientVersionCode, bp.Email, bp.IDIntegration, bp.CreditLimitEnsurance,
            bp.CreditLimitExpiredDays, bp.CurrentCreditValueExpired,
            bp.CurrentCreditExpiredDays, bp.WaringCredit, bp.WarnigExpiredCredit,
            bp.BlocksCredit, bp.BlocksExpiredCredit, bp.ShippingCompanyID,
            bp.ComercialDescount, bp.PartnerCategory, bp.WebPage, bp.GLNCode,
            bp.VIESValidation, bp.CreationUser, bp.CreationDateTime, bp.ModifUser,
            bp.ModifDateTime
        FROM BusinessPartners bp WITH (NOLOCK)
        JOIN PartnerTypes pt WITH (NOLOCK)
            ON bp.PartnerType = pt.PartnerType
        LEFT JOIN Agents a WITH (NOLOCK)
            ON a.AgentCode = bp.AgentCode
        WHERE bp.PartnerType = ?
          AND bp.PartnerID = ?
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (partner_type, partner_id))
        row = cursor.fetchone()
        if row is None:
            return None

        return _row_to_dict(cursor, row)


def fetch_business_contact_person_list(
    partner_type: str,
    partner_id: str,
    contact_id: str = "",
) -> list[dict[str, Any]]:
    query = """
        SELECT bpcp.PartnerType, bpcp.PartnerID, bpcp.ContactID, bpcp.Name,
            bpcp.Email, bpcp.Phone, bpcp.MobilePhone, bpcp.Department,
            bpcp.IDIntegration, bpcp.created_by, bpcp.created_date,
            bpcp.edited_by, bpcp.edited_date
        FROM BusinessPartnersContactPersons bpcp WITH (NOLOCK)
        WHERE bpcp.PartnerType = ?
          AND bpcp.PartnerID = ?
          AND (bpcp.Name = ? OR ? = '')
        ORDER BY bpcp.Name
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (partner_type, partner_id, contact_id, contact_id))
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
