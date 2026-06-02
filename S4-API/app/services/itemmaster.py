from typing import Optional

from app.repositories.itemmaster import (
    create_item_attachment,
    fetch_active_items,
    fetch_active_items_for_client,
    fetch_item_active_production_orders,
    fetch_item_image,
    fetch_item_versions,
    fetch_itemmaster_list,
)


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


def list_itemmaster(
    filters: dict[str, object],
    show_items_components: bool = True,
    show_items_composed: bool = True,
    show_all_versions: bool = False,
    restrict_to_this_item_id_has_component: str = "",
    page_number: int = 1,
    page_size: int = 50,
    sort_by: str = "",
    item_budget: str = "",
    include_total_count: bool = False,
) -> dict[str, object]:
    return fetch_itemmaster_list(
        filters=filters,
        show_items_components=show_items_components,
        show_items_composed=show_items_composed,
        show_all_versions=show_all_versions,
        restrict_to_this_item_id_has_component=restrict_to_this_item_id_has_component.strip(),
        page_number=page_number,
        page_size=page_size,
        sort_by=sort_by,
        item_budget=item_budget.strip(),
        include_total_count=include_total_count,
    )


def list_item_versions(item_id: str) -> list[dict[str, object]]:
    return fetch_item_versions(item_id=item_id.strip())


def list_active_items_for_client(
    client_id: str,
    page_number: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    return fetch_active_items_for_client(
        client_id=client_id.strip(),
        page_number=page_number,
        page_size=page_size,
    )


def list_item_active_production_orders(
    item_id: str,
    page_number: int = 0,
    page_size: int = 50,
) -> dict[str, object]:
    return fetch_item_active_production_orders(
        item_id=item_id.strip(),
        page_number=page_number,
        page_size=page_size,
    )


def save_item_attachment(
    company: str,
    item_id: str,
    version: int,
    observation: str,
    user_id: str,
    file_name: str,
    file_content: bytes,
) -> dict[str, object]:
    return create_item_attachment(
        company=company.strip(),
        item_id=item_id.strip(),
        version=version,
        observation=observation.strip(),
        user_id=user_id.strip(),
        file_name=file_name,
        file_content=file_content,
    )
