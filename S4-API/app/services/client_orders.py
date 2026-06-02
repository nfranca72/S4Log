from __future__ import annotations

from typing import Any

from app.repositories.client_orders import (
    fetch_active_subcontract_orders_by_subcontractor_id,
    fetch_cad_components_to_consume,
    fetch_client_order,
    fetch_components_by_document_color,
    fetch_doc_components_to_consume,
    fetch_order_row_dims_to_register_planning_production_by_color,
    update_cad_consumption,
)
from app.models.client_orders import UpdateCadConsumptionRequest


def get_client_order(doc_type: str, order_id: int, get_lines: bool = False) -> dict[str, Any] | None:
    return fetch_client_order(
        doc_type=doc_type.strip(),
        order_id=order_id,
        get_lines=get_lines,
    )


def get_all_components_by_document_color(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
    component_id: str = "",
    color_id: str = "",
) -> list[dict[str, Any]]:
    return fetch_components_by_document_color(
        doc_type=doc_type.strip(),
        order_id=order_id,
        order_row=order_row,
        component_id=component_id.strip(),
        color_id=color_id.strip(),
    )


def get_cad_components_to_consume(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
) -> list[dict[str, Any]]:
    return fetch_cad_components_to_consume(
        doc_type=doc_type.strip(),
        order_id=order_id,
        order_row=order_row,
    )


def get_doc_components_to_consume(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
) -> list[dict[str, Any]]:
    return fetch_doc_components_to_consume(
        doc_type=doc_type.strip(),
        order_id=order_id,
        order_row=order_row,
    )


def update_cad_consumption_values(payload: UpdateCadConsumptionRequest) -> dict[str, Any]:
    return update_cad_consumption(
        doc_type=payload.doc_type.strip(),
        order_id=payload.order_id,
        item_group_id=payload.item_group_id.strip(),
        item_sub_group_id=payload.item_sub_group_id.strip(),
        component_id=payload.item_id.strip(),
        shrink_in_x=payload.shrink_in_x,
        shrink_in_y=payload.shrink_in_y,
        roll_width=payload.roll_width,
        qty_by_cad=payload.qty_by_cad,
        obs=payload.obs.strip(),
    )


def get_order_row_dims_to_register_planning_production_by_color(
    doc_type: str,
    order_id: int,
    production_type: str,
) -> list[dict[str, Any]]:
    return fetch_order_row_dims_to_register_planning_production_by_color(
        doc_type=doc_type.strip(),
        order_id=order_id,
        production_type=production_type.strip(),
    )


def get_active_subcontract_orders_by_subcontractor_id(
    subcontract_id: str,
    subcontract_operations: str,
    subcontract_status: str,
) -> list[dict[str, Any]]:
    return fetch_active_subcontract_orders_by_subcontractor_id(
        subcontract_id=subcontract_id.strip(),
        subcontract_operations=subcontract_operations.strip(),
        subcontract_status=subcontract_status.strip(),
    )
