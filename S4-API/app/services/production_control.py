from __future__ import annotations

from decimal import Decimal

from app.models.production_control import (
    ConsumptionRequest,
    ConsumptionResponse,
    ConsumptionResultLine,
)
from app.repositories.production_control import (
    create_local_consumption_document,
    fetch_component_metadata,
    fetch_consumption_context,
    fetch_coonsumption_for_itemmaster_and_bpartner,
)
from app.services.sap_service_layer import SapGoodsIssueLine, SapServiceLayerClient


def list_coonsumption_for_itemmaster_and_bpartner(
    item_id: str,
    doc_type_area: str,
    bp_id: str,
) -> list[dict[str, object]]:
    return fetch_coonsumption_for_itemmaster_and_bpartner(
        item_id=item_id,
        doc_type_area=doc_type_area,
        bp_id=bp_id,
    )


def create_consumption_order(payload: ConsumptionRequest) -> ConsumptionResponse:
    header = payload.header

    context = fetch_consumption_context(
        item_id=header.item_id,
        project=header.project,
        subcontract_id=header.partner_id,
    )

    requested_by_item: dict[str, Decimal] = {}
    for line in payload.lines:
        item = line.component_id.strip().upper()
        requested_by_item[item] = requested_by_item.get(item, Decimal("0")) + line.qty_consumir

    sap_client = SapServiceLayerClient()
    sap_lines: list[SapGoodsIssueLine] = []
    result_lines: list[ConsumptionResultLine] = []

    warehouse_code = "200"
    sap_location_code = header.location_code or context["local_consumo"]
    try:
        sap_client.login()

        for component_id, qty_requested in requested_by_item.items():
            available_warehouse = sap_client.get_item_stock(component_id, warehouse_code)
            available_location = sap_client.get_item_bin_stock(
                item_code=component_id,
                warehouse_code=warehouse_code,
                bin_code=sap_location_code,
            )
            available = min(available_warehouse, available_location)
            qty_applied = qty_requested if qty_requested <= available else available
            if qty_applied < 0:
                qty_applied = Decimal("0")

            qty_skipped = qty_requested - qty_applied
            if qty_applied > 0:
                sap_lines.append(SapGoodsIssueLine(item_code=component_id, quantity=qty_applied))

            result_lines.append(
                ConsumptionResultLine(
                    ComponentId=component_id,
                    QtyRequested=qty_requested,
                    QtyApplied=qty_applied,
                    QtySkipped=qty_skipped,
                )
            )

        if not sap_lines:
            raise ValueError(
                "No available stock was found for the requested components in warehouse "
                f"{warehouse_code} and location {sap_location_code}"
            )

        sap_response = sap_client.create_inventory_issue(
            movement_date=header.movement_date,
            project=header.project,
            warehouse_code=warehouse_code,
            location_code=sap_location_code,
            lines=sap_lines,
            comments=f"CONS API - Partner {header.partner_id} - Project {header.project}",
        )
    finally:
        sap_client.logout()

    sap_doc_entry = sap_response.get("DocEntry")
    sap_doc_num = sap_response.get("DocNum")

    component_metadata = fetch_component_metadata(list(requested_by_item.keys()))
    applied_lines_payload = [
        {
            "component_id": line.component_id,
            "qty_applied": line.qty_applied,
        }
        for line in result_lines
        if line.qty_applied > 0
    ]

    local_doc = create_local_consumption_document(
        partner_id=context["subcontract_partner_id"],
        movement_date=header.movement_date,
        location_code=context["subcontract_partner_id"],
        origin_doc_type=context["origin_doc_type"],
        origin_order_id=context["origin_order_id"],
        origin_order_row=context["origin_order_row"],
        sap_doc_type="InventoryGenExit",
        sap_doc_num=int(sap_doc_num) if sap_doc_num is not None else None,
        lines=applied_lines_payload,
        component_metadata=component_metadata,
    )

    sap_doc_num_int = int(sap_doc_num) if sap_doc_num is not None else None
    sap_doc_entry_int = int(sap_doc_entry) if sap_doc_entry is not None else None
    local_order_id = int(local_doc["order_id"])
    message_parts = [
        "Consumption created successfully",
        f"SAP document {sap_doc_num_int}" if sap_doc_num_int is not None else "SAP document created",
        f"local document {local_doc['doc_type']}.{local_order_id}",
    ]

    return ConsumptionResponse(
        Message=" | ".join(message_parts),
        SapDocEntry=sap_doc_entry_int,
        SapDocNum=sap_doc_num_int,
        SapDocType="InventoryGenExit",
        WarehouseCode=warehouse_code,
        LocationCode=sap_location_code,
        LocalDocType=local_doc["doc_type"],
        LocalOrderID=local_order_id,
        MovementDate=header.movement_date,
        Lines=result_lines,
    )
