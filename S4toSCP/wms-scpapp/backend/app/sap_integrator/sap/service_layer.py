"""
sap/service_layer.py — SAP B1 10.x Service Layer HTTP client

Features:
  - Cookie-based session with auto-login on expiry
  - Retry with exponential back-off (tenacity)
  - OData $filter helpers
  - Context-manager support
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings

logger = logging.getLogger("sap.service_layer")


class SAPAuthError(Exception):
    pass


class SAPRequestError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"SAP SL [{status_code}]: {message}")


class ServiceLayerClient:
    """
    Async client for SAP B1 Service Layer (10.x).
    Usage:
        async with ServiceLayerClient(settings) as sl:
            items = await sl.get_all("Items", filter="ItemType eq 'itItems'")
    """

    SESSION_TIMEOUT_MINUTES = 25  # SAP default is 30 min; refresh earlier

    def __init__(self, settings: Settings):
        self._settings = settings
        host = settings.sap_sl_host.rstrip("/")
        self._base_url = host if host.lower().endswith("/b1s/v1") else f"{host}/b1s/v1"
        self._verify_ssl = settings.sap_sl_verify_ssl
        self._client: Optional[httpx.AsyncClient] = None
        self._session_expiry: Optional[datetime] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=httpx.Timeout(float(self._settings.sap_sl_timeout_seconds)),
            follow_redirects=True,
        )
        await self.login()
        return self

    async def __aexit__(self, *_):
        await self.logout()
        if self._client:
            await self._client.aclose()

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self) -> None:
        payload = {
            "CompanyDB": self._settings.sap_sl_company,
            "UserName": self._settings.sap_sl_user,
            "Password": self._settings.sap_sl_password,
        }
        resp = await self._client.post(f"{self._base_url}/Login", json=payload)
        if resp.status_code != 200:
            raise SAPAuthError(f"SAP Login failed: {resp.status_code} — {resp.text}")
        self._session_expiry = datetime.utcnow() + timedelta(
            minutes=self.SESSION_TIMEOUT_MINUTES
        )
        logger.info("SAP Service Layer session established.")

    async def logout(self) -> None:
        try:
            if self._client:
                await self._client.post(f"{self._base_url}/Logout")
        except Exception:
            pass
        self._session_expiry = None

    async def _ensure_session(self) -> None:
        if not self._session_expiry or datetime.utcnow() >= self._session_expiry:
            logger.info("SAP session expired or missing — re-authenticating.")
            await self.login()

    # ── Core HTTP ─────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, url: str, params: dict | None = None) -> dict:
        await self._ensure_session()
        resp = await self._client.get(url, params=params)
        if resp.status_code == 401:
            # Session lost — login and retry once
            await self.login()
            resp = await self._client.get(url, params=params)
        if resp.status_code != 200:
            raise SAPRequestError(resp.status_code, resp.text[:500])
        return resp.json()

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _patch(self, url: str, payload: dict) -> None:
        await self._ensure_session()
        resp = await self._client.patch(url, json=payload)
        if resp.status_code not in (200, 204):
            raise SAPRequestError(resp.status_code, resp.text[:500])

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _post(self, url: str, payload: dict | None = None) -> dict:
        await self._ensure_session()
        resp = await self._client.post(url, json=payload or {})
        if resp.status_code not in (200, 201, 204):
            raise SAPRequestError(resp.status_code, resp.text[:500])
        if not resp.text.strip():
            return {}
        return resp.json()

    # ── High-level helpers ────────────────────────────────────────────────────

    async def get_collection(
        self,
        entity: str,
        *,
        select: str | None = None,
        filter: str | None = None,
        top: int = 100,
        skip: int = 0,
        order_by: str | None = None,
        expand: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Fetch one page from an OData collection."""
        params: dict = {"$top": top, "$skip": skip}
        if select:
            params["$select"] = select
        if filter:
            params["$filter"] = filter
        if order_by:
            params["$orderby"] = order_by
        if expand:
            params["$expand"] = expand

        url = f"{self._base_url}/{entity}"
        data = await self._get(url, params=params)
        return data.get("value", [])

    async def get_all(
        self,
        entity: str,
        *,
        select: str | None = None,
        filter: str | None = None,
        order_by: str | None = None,
        expand: str | None = None,
        page_size: int = 200,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Async generator that pages through ALL records of an OData collection.
        Usage:
            async for item in sl.get_all("Items", filter="..."):
                process(item)
        """
        skip = 0
        while True:
            page = await self.get_collection(
                entity,
                select=select,
                filter=filter,
                top=page_size,
                skip=skip,
                order_by=order_by,
                expand=expand,
            )
            if not page:
                break
            for record in page:
                yield record
            # Some SAP B1 Service Layer collections enforce a lower server-side
            # page cap than the requested $top. Advance by the actual page size
            # and stop only when the next page comes back empty.
            skip += len(page)

    async def get_by_key(self, entity: str, key: str | int) -> Dict[str, Any]:
        """Fetch a single entity by its primary key."""
        url = f"{self._base_url}/{entity}({key!r})"
        return await self._get(url)

    async def patch(self, entity: str, key: str | int, payload: dict) -> None:
        """PATCH (partial update) a single entity — used to set UDF flags."""
        url = f"{self._base_url}/{entity}({key!r})"
        await self._patch(url, payload)

    async def post(self, entity: str, payload: dict) -> Dict[str, Any]:
        """Create a new entity and return the Service Layer payload."""
        url = f"{self._base_url}/{entity}"
        return await self._post(url, payload)

    async def action(self, entity: str, key: str | int, action_name: str) -> Dict[str, Any]:
        """Execute a document action such as Cancel or Close."""
        url = f"{self._base_url}/{entity}({key!r})/{action_name}"
        return await self._post(url, {})

    # ── UDF flag helpers ──────────────────────────────────────────────────────

    async def mark_synced(
        self, entity: str, key: str | int, udf_field: str = "U_WMS_Synced"
    ) -> None:
        """Set the WMS sync flag to 'Y' on a SAP record."""
        await self.patch(entity, key, {udf_field: "Y"})

    async def mark_sync_failed(
        self, entity: str, key: str | int, udf_field: str = "U_WMS_Synced"
    ) -> None:
        """Set the WMS sync flag to 'E' (error) on a SAP record."""
        await self.patch(entity, key, {udf_field: "E"})

    # ── Convenience filters ───────────────────────────────────────────────────

    @staticmethod
    def not_synced_filter(udf_field: str = "U_WMS_Synced") -> str:
        """OData filter to get records not yet synced."""
        return f"{udf_field} ne 'Y'"

    @staticmethod
    def series_filter(series_list: List[str], series_field: str = "Series") -> str:
        """OData filter for a list of series codes."""
        if not series_list:
            return ""
        parts = [f"{series_field} eq {s}" for s in series_list]
        return "(" + " or ".join(parts) + ")"


@asynccontextmanager
async def get_sap_client(settings: Settings):
    """Dependency / context manager that yields a ready ServiceLayerClient."""
    async with ServiceLayerClient(settings) as client:
        yield client
