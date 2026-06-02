from __future__ import annotations

from app.repositories.business_partners import (
    fetch_active_business_partners,
    fetch_active_subcontractors_for_itemmaster,
    fetch_business_partner,
    fetch_business_contact_person_list,
)


def list_active_business_partners(bp_type: str, doc_type_area: str) -> list[dict[str, str]]:
    return fetch_active_business_partners(bp_type=bp_type, doc_type_area=doc_type_area)


def list_active_subcontractors_for_itemmaster(
    item_id: str,
    bp_type: str,
    doc_type_area: str,
) -> list[dict[str, str]]:
    return fetch_active_subcontractors_for_itemmaster(
        item_id=item_id,
        bp_type=bp_type,
        doc_type_area=doc_type_area,
    )


def get_business_partner(partner_type: str, partner_id: str) -> dict[str, object] | None:
    return fetch_business_partner(
        partner_type=partner_type.strip(),
        partner_id=partner_id.strip(),
    )


def list_business_contact_persons(
    partner_type: str,
    partner_id: str,
    contact_id: str = "",
) -> list[dict[str, object]]:
    return fetch_business_contact_person_list(
        partner_type=partner_type.strip(),
        partner_id=partner_id.strip(),
        contact_id=contact_id.strip(),
    )
