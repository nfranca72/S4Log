from __future__ import annotations

import json
from typing import Any, Optional

import requests

from app.models.by_ptl import ByPtlWaveRequest, ByPtlWaveResponse
from app.models.by_ptl import ByPtlDispatchRequest, ByPtlDispatchResponse
from app.repositories.by_ptl import (
    create_or_update_articles,
    create_or_update_customers_and_orders,
)
from app.settings import settings


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


def dispatch_to_wms(payload: ByPtlDispatchRequest) -> ByPtlDispatchResponse:
    if not settings.by_ptl_wms_url:
        raise ValueError("BY-PTL WMS configuration is incomplete. Missing: BY_PTL_WMS_URL")

    outbound_payload = {
        payload.action_to_send.value: [
            {
                "DATA": payload.validated_payload.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            }
        ]
    }

    headers = {"Content-Type": "application/json"}
    if settings.by_ptl_wms_api_key:
        headers[settings.by_ptl_wms_api_key_header] = settings.by_ptl_wms_api_key

    session = requests.Session()
    auth_headers = _authenticate_wms_session(session)
    headers.update(auth_headers)

    response = session.post(
        settings.by_ptl_wms_url,
        json=outbound_payload,
        headers=headers,
        timeout=settings.by_ptl_wms_timeout_seconds,
        verify=settings.by_ptl_wms_verify_ssl,
    )

    response_body = response.text.strip()
    if not response_body:
        response_body = "<empty>"

    if response.status_code >= 400:
        raise RuntimeError(
            "BY-PTL WMS request failed "
            f"({response.status_code}): {response_body}"
        )

    try:
        parsed_response = response.json()
        response_body = json.dumps(parsed_response, ensure_ascii=True)
    except ValueError:
        pass

    return ByPtlDispatchResponse(
        ActionRequested=payload.action,
        ActionSent=payload.action_to_send.value,
        Endpoint=settings.by_ptl_wms_url,
        HttpStatus=response.status_code,
        RequestPayload=outbound_payload,
        ResponseBody=response_body,
        Message="BY-PTL message sent to WMS successfully",
    )


def _authenticate_wms_session(session: requests.Session) -> dict[str, str]:
    if not settings.by_ptl_wms_login_url:
        return {}

    missing = [
        name
        for name, value in {
            "BY_PTL_WMS_LOGIN_USER": settings.by_ptl_wms_login_user,
            "BY_PTL_WMS_LOGIN_PASSWORD": settings.by_ptl_wms_login_password,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(
            "BY-PTL WMS login configuration is incomplete. Missing: " + ", ".join(missing)
        )

    response = session.get(
        settings.by_ptl_wms_login_url,
        params={
            settings.by_ptl_wms_login_user_param: settings.by_ptl_wms_login_user,
            settings.by_ptl_wms_login_password_param: settings.by_ptl_wms_login_password,
        },
        timeout=settings.by_ptl_wms_timeout_seconds,
        verify=settings.by_ptl_wms_verify_ssl,
    )

    response_body = response.text.strip() or "<empty>"
    if response.status_code >= 400:
        raise RuntimeError(
            "BY-PTL WMS login failed "
            f"({response.status_code}): {response_body}"
        )

    token = _extract_auth_token(response)
    if not token:
        return {}

    prefix = settings.by_ptl_wms_auth_token_prefix or ""
    return {settings.by_ptl_wms_auth_token_header: f"{prefix}{token}"}


def _extract_auth_token(response: requests.Response) -> Optional[str]:
    try:
        payload = response.json()
    except ValueError:
        return None

    return _find_token_in_payload(payload)


def _find_token_in_payload(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key).strip().lower().replace("-", "").replace("_", "")
            if normalized_key in {
                "token",
                "accesstoken",
                "authtoken",
                "jwttoken",
                "jwt",
                "sessiontoken",
                "sessionid",
            } and value:
                return str(value).strip()

            nested_token = _find_token_in_payload(value)
            if nested_token:
                return nested_token
        return None

    if isinstance(payload, list):
        for item in payload:
            nested_token = _find_token_in_payload(item)
            if nested_token:
                return nested_token

    return None
