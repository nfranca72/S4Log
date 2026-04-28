from app.repositories.business_partners import (
    fetch_active_business_partners,
    fetch_active_subcontractors_for_itemmaster,
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
