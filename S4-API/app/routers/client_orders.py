from decimal import Decimal

from fastapi import APIRouter, Form, HTTPException, Query

from typing import Optional

from app.models.client_orders import UpdateCadConsumptionRequest
from app.services.client_orders import (
    get_active_subcontract_orders_by_subcontractor_id,
    get_all_components_by_document_color,
    get_cad_components_to_consume,
    get_client_order,
    get_doc_components_to_consume,
    get_order_row_dims_to_register_planning_production_by_color,
    update_cad_consumption_values,
)

router = APIRouter(prefix="/ClientOrders", tags=["ClientOrders"])


@router.get(
    "",
    summary="Get a client order header and optionally its lines",
)
def get_client_order_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderID", ge=1),
    get_lines: bool = Query(False, alias="GetLINES"),
) -> dict[str, object]:
    try:
        result = get_client_order(
            doc_type=doc_type,
            order_id=order_id,
            get_lines=get_lines,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch client order: {exc}",
        ) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Client order not found")

    return result


@router.get(
    "/GetAllComponentsByDocumentColor",
    summary="Get components by document color",
)
def get_all_components_by_document_color_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderID", ge=1),
    order_row: Optional[int] = Query(None, alias="OrderRow", ge=1),
    component_id: str = Query("", alias="ComponentID", max_length=100),
    color_id: str = Query("", alias="ColorID", max_length=50),
) -> list[dict[str, object]]:
    try:
        return get_all_components_by_document_color(
            doc_type=doc_type,
            order_id=order_id,
            order_row=order_row,
            component_id=component_id,
            color_id=color_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch components by document color: {exc}",
        ) from exc


@router.get(
    "/GetCADComponentsToConsume",
    summary="Get CAD components to consume",
)
def get_cad_components_to_consume_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderID", ge=1),
    order_row: Optional[int] = Query(None, alias="OrderRow", ge=1),
) -> list[dict[str, object]]:
    try:
        return get_cad_components_to_consume(
            doc_type=doc_type,
            order_id=order_id,
            order_row=order_row,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch CAD components to consume: {exc}",
        ) from exc


@router.get(
    "/GetDocComponentsToConsume",
    summary="Get document components to consume",
)
def get_doc_components_to_consume_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderID", ge=1),
    order_row: Optional[int] = Query(None, alias="OrderRow", ge=1),
) -> list[dict[str, object]]:
    try:
        return get_doc_components_to_consume(
            doc_type=doc_type,
            order_id=order_id,
            order_row=order_row,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch document components to consume: {exc}",
        ) from exc


@router.post(
    "/UpdateCadConsumption",
    summary="Update CAD consumption values",
)
def post_update_cad_consumption(
    doc_type: str = Form(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Form(..., alias="OrderID", ge=1),
    item_group_id: str = Form(..., alias="ItemGroupID", min_length=1, max_length=50),
    item_sub_group_id: str = Form(..., alias="ItemSubGroupID", min_length=1, max_length=50),
    item_id: str = Form(..., alias="ItemID", min_length=1, max_length=100),
    shrink_in_x: Decimal = Form(Decimal("0"), alias="ShrinkInX"),
    shrink_in_y: Decimal = Form(Decimal("0"), alias="ShrinkInY"),
    roll_width: Decimal = Form(Decimal("0"), alias="RollWidth"),
    qty_by_cad: Decimal = Form(Decimal("0"), alias="QtyByCad"),
    obs: str = Form("", alias="Obs", max_length=500),
) -> dict[str, object]:
    try:
        payload = UpdateCadConsumptionRequest(
            DocType=doc_type,
            OrderID=order_id,
            ItemGroupID=item_group_id,
            ItemSubGroupID=item_sub_group_id,
            ItemID=item_id,
            ShrinkInX=shrink_in_x,
            ShrinkInY=shrink_in_y,
            RollWidth=roll_width,
            QtyByCad=qty_by_cad,
            Obs=obs,
        )
        return update_cad_consumption_values(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update CAD consumption: {exc}",
        ) from exc


@router.get(
    "/GetOrderRowDimsToRegisterPlanningProductionByColor",
    summary="Get order row dimensions to register planning production by color",
)
def get_order_row_dims_to_register_planning_production_by_color_endpoint(
    doc_type: str = Query(..., alias="DocType", min_length=1, max_length=20),
    order_id: int = Query(..., alias="OrderID", ge=1),
    production_type: str = Query(..., alias="ProductionType", min_length=1, max_length=50),
) -> list[dict[str, object]]:
    try:
        return get_order_row_dims_to_register_planning_production_by_color(
            doc_type=doc_type,
            order_id=order_id,
            production_type=production_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch order row dimensions for planning production: {exc}",
        ) from exc


@router.get(
    "/GetActiveSubcontractOrdersBySubcontractorId",
    summary="Get active subcontract orders by subcontractor",
)
def get_active_subcontract_orders_by_subcontractor_id_endpoint(
    subcontract_id: str = Query(..., alias="SubcontractID", min_length=1, max_length=50),
    subcontract_operations: str = Query(..., alias="SubcontractOperations", min_length=1, max_length=500),
    subcontract_status: str = Query(..., alias="SubcontractStatus", min_length=1, max_length=500),
) -> list[dict[str, object]]:
    try:
        return get_active_subcontract_orders_by_subcontractor_id(
            subcontract_id=subcontract_id,
            subcontract_operations=subcontract_operations,
            subcontract_status=subcontract_status,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active subcontract orders: {exc}",
        ) from exc
