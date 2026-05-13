from __future__ import annotations

from app.models.by_ptl import ByPtlWaveRequest, ByPtlWaveResponse
from app.repositories.by_ptl import (
    create_or_update_articles,
    create_or_update_customers_and_orders,
)


def receive_wave(payload: ByPtlWaveRequest) -> ByPtlWaveResponse:
    order_lines_count = sum(len(order.detail_order) for order in payload.orders)
    articles_result = create_or_update_articles(
        [
            {
                "item_id": article.item_id,
                "description": article.description,
                "length": article.length,
                "height": article.height,
                "width": article.width,
                "net_weight": article.net_weight,
                "barcode": article.barcode,
            }
            for article in payload.articles
        ]
    )
    orders_payload = [
            {
                "order_id": order.order_id,
                "order_obs": order.order_obs,
                "customer_id": order.customer_id,
                "customer_name": order.customer_name,
                "detail_order": [
                    {
                        "line": line.line,
                        "item_id": line.item_id,
                        "quantity": line.quantity,
                    }
                    for line in order.detail_order
                ],
            }
            for order in payload.orders
        ]
    orders_result = create_or_update_customers_and_orders(
        wave_id=payload.wave_id,
        wave_obs=payload.wave_obs,
        ptl=payload.ptl,
        orders=orders_payload,
    )

    return ByPtlWaveResponse(
        WaveID=payload.wave_id,
        PTL=payload.ptl,
        ArticlesCount=len(payload.articles),
        ArticlesCreated=articles_result["created"],
        ArticlesUpdated=articles_result["updated"],
        CustomersCreated=orders_result["customers_created"],
        CustomersUpdated=orders_result["customers_updated"],
        OrdersCount=len(payload.orders),
        OrdersCreated=orders_result["orders_created"],
        OrdersUpdated=orders_result["orders_updated"],
        OrderLinesCount=order_lines_count,
        PickingCreated=False,
        PickingDetailsCount=0,
        Message="BY-PTL wave received successfully",
    )
