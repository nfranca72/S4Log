from __future__ import annotations
from fastapi import APIRouter, HTTPException
from app.db.connection import db_cursor
from app.models.schemas import Client

router = APIRouter(prefix="/clients", tags=["Clientes"])


@router.get("/", response_model=list[Client])
def list_clients(search: str = ""):
    """Lista clientes para o dropdown de seleção."""
    with db_cursor() as (cursor, _):
        if search:
            cursor.execute("""
                SELECT TOP 50 PartnerID, PartnerName
                FROM BusinessPartners
                WHERE PartnerType = 'C'
                  AND (PartnerName LIKE ? OR PartnerID LIKE ?)
                ORDER BY PartnerName
            """, (f"%{search}%", f"%{search}%"))
        else:
            cursor.execute("""
                SELECT TOP 100 PartnerID, PartnerName
                FROM BusinessPartners
                WHERE PartnerType = 'C'
                ORDER BY PartnerName
            """)
        rows = cursor.fetchall()

    if not rows:
        return []

    return [Client(client_id=r[0], client_name=r[1]) for r in rows]
