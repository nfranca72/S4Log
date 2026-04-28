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
