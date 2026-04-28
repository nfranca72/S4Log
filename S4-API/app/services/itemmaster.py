from typing import Optional

from app.repositories.itemmaster import fetch_active_items, fetch_item_image


def list_active_items(
    partner_id: str,
    partner_type: str,
    production_type: str,
    include_image: bool = False,
    version: Optional[int] = None,
    client_sigla: Optional[str] = None,
) -> list[dict[str, object]]:
    # Accepted as part of the endpoint contract, although the source SQL does not filter by it.
    _ = partner_type
    return fetch_active_items(
        partner_id=partner_id,
        production_type=production_type,
        include_image=include_image,
        version=version,
        client_sigla=client_sigla,
    )


def get_item_image(
    item_id: str,
    client_sigla: str,
    version: Optional[int] = None,
) -> Optional[dict[str, object]]:
    return fetch_item_image(
        company=client_sigla,
        item_id=item_id,
        version=version,
    )
