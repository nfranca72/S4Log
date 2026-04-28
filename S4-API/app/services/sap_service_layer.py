from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import requests

from app.settings import settings


class SapServiceLayerError(RuntimeError):
    """Raised when SAP Service Layer requests fail."""


@dataclass
class SapGoodsIssueLine:
    item_code: str
    quantity: Decimal


class SapServiceLayerClient:
    BIN_STOCK_SQL_CODE = "CODX_BIN_STOCK"
    BIN_STOCK_SQL_NAME = "Codex Bin Stock"
    BIN_STOCK_SQL_TEXT = """
select isnull(sum(I.OnHandQty), 0) as OnHandQty
from OIBQ I
inner join OBIN B on B.AbsEntry = I.BinAbs
where I.ItemCode = :itemCode
  and I.WhsCode = :warehouseCode
  and B.BinCode = :binCode
    """.strip()

    def __init__(self) -> None:
        missing = [
            name
            for name, value in {
                "SAP_SL_BASE_URL": settings.sap_sl_base_url,
                "SAP_SL_COMPANY_DB": settings.sap_sl_company_db,
                "SAP_SL_USERNAME": settings.sap_sl_username,
                "SAP_SL_PASSWORD": settings.sap_sl_password,
            }.items()
            if not value
        ]
        if missing:
            raise SapServiceLayerError(
                "SAP Service Layer configuration is incomplete. Missing: " + ", ".join(missing)
            )

        configured_base_url = settings.sap_sl_base_url.rstrip("/")
        if configured_base_url.startswith("https://"):
            configured_base_url = "http://" + configured_base_url[len("https://") :]

        self.base_url = configured_base_url
        self.timeout = settings.sap_sl_timeout_seconds
        self.location_field = settings.sap_sl_location_field
        self.session = requests.Session()

    def login(self) -> None:
        payload = {
            "CompanyDB": settings.sap_sl_company_db,
            "UserName": settings.sap_sl_username,
            "Password": settings.sap_sl_password,
        }
        response = self.session.post(
            f"{self.base_url}/Login",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SapServiceLayerError(
                f"SAP login failed ({response.status_code}): {response.text}"
            )

    def logout(self) -> None:
        try:
            self.session.post(
                f"{self.base_url}/Logout",
                timeout=self.timeout,
            )
        except Exception:
            # Best-effort cleanup; login session expires server-side anyway.
            pass

    def get_item_stock(self, item_code: str, warehouse_code: str) -> Decimal:
        encoded_item_code = quote(item_code, safe="")
        response = self.session.get(
            f"{self.base_url}/Items('{encoded_item_code}')",
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SapServiceLayerError(
                f"SAP stock query failed for item '{item_code}' ({response.status_code}): {response.text}"
            )

        payload = response.json()
        rows = payload.get("ItemWarehouseInfoCollection", [])
        for row in rows:
            if str(row.get("WarehouseCode", "")).strip() == warehouse_code:
                return Decimal(str(row.get("InStock", 0) or 0))
        return Decimal("0")

    def get_item_bin_stock(
        self,
        item_code: str,
        warehouse_code: str,
        bin_code: str,
    ) -> Decimal:
        self._ensure_bin_stock_query()
        param_list = (
            f"itemCode={self._format_sql_query_param(item_code)}"
            f"&warehouseCode={self._format_sql_query_param(warehouse_code)}"
            f"&binCode={self._format_sql_query_param(bin_code)}"
        )
        response = self.session.post(
            f"{self.base_url}/SQLQueries('{self.BIN_STOCK_SQL_CODE}')/List",
            json={"ParamList": param_list},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SapServiceLayerError(
                "SAP bin stock query failed "
                f"for item '{item_code}' in warehouse '{warehouse_code}' and bin '{bin_code}' "
                f"({response.status_code}): {response.text}"
            )

        payload = response.json()
        rows = payload.get("value", [])
        if not rows:
            return Decimal("0")

        return Decimal(str(rows[0].get("OnHandQty", 0) or 0))

    def create_inventory_issue(
        self,
        movement_date: date,
        project: str,
        warehouse_code: str,
        location_code: str,
        lines: list[SapGoodsIssueLine],
        comments: str,
    ) -> dict[str, object]:
        if not lines:
            raise SapServiceLayerError("Cannot create SAP goods issue without lines")

        bin_abs_entry = self.get_bin_abs_entry(location_code=location_code, warehouse_code=warehouse_code)

        document_lines: list[dict[str, object]] = []
        for line_index, line in enumerate(lines):
            payload_line: dict[str, object] = {
                "ItemCode": line.item_code,
                "Quantity": float(line.quantity),
                "WarehouseCode": warehouse_code,
                "ProjectCode": project,
                "DocumentLinesBinAllocations": [
                    {
                        "BinAbsEntry": bin_abs_entry,
                        "Quantity": float(line.quantity),
                        "BaseLineNumber": line_index,
                    }
                ],
            }
            if self.location_field:
                payload_line[self.location_field] = location_code
            document_lines.append(payload_line)

        payload = {
            "DocDate": movement_date.isoformat(),
            "TaxDate": movement_date.isoformat(),
            "Comments": comments,
            "JournalMemo": comments,
            "DocumentLines": document_lines,
        }

        response = self.session.post(
            f"{self.base_url}/InventoryGenExits",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SapServiceLayerError(
                f"SAP goods issue failed ({response.status_code}): {response.text}"
            )

        return response.json()

    def get_bin_abs_entry(self, location_code: str, warehouse_code: str) -> int:
        response = self.session.get(
            f"{self.base_url}/BinLocations",
            params={
                "$select": "AbsEntry,BinCode,Warehouse",
                "$filter": f"Warehouse eq '{warehouse_code}' and BinCode eq '{location_code}'",
                "$top": 1,
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SapServiceLayerError(
                "SAP bin location query failed "
                f"for '{location_code}' in warehouse '{warehouse_code}' "
                f"({response.status_code}): {response.text}"
            )

        payload = response.json()
        rows = payload.get("value", [])
        if not rows:
            raise SapServiceLayerError(
                f"SAP bin location '{location_code}' was not found in warehouse '{warehouse_code}'"
            )

        return int(rows[0]["AbsEntry"])

    def _ensure_bin_stock_query(self) -> None:
        encoded_sql_code = quote(self.BIN_STOCK_SQL_CODE, safe="")
        response = self.session.get(
            f"{self.base_url}/SQLQueries('{encoded_sql_code}')",
            timeout=self.timeout,
        )
        if response.status_code == 404:
            create_response = self.session.post(
                f"{self.base_url}/SQLQueries",
                json={
                    "SqlCode": self.BIN_STOCK_SQL_CODE,
                    "SqlName": self.BIN_STOCK_SQL_NAME,
                    "SqlText": self.BIN_STOCK_SQL_TEXT,
                },
                timeout=self.timeout,
            )
            if create_response.status_code >= 400:
                raise SapServiceLayerError(
                    "Failed to create SAP SQL query for bin stock "
                    f"({create_response.status_code}): {create_response.text}"
                )
            return

        if response.status_code >= 400:
            raise SapServiceLayerError(
                "Failed to read SAP SQL query for bin stock "
                f"({response.status_code}): {response.text}"
            )

        payload: dict[str, Any] = response.json()
        current_name = str(payload.get("SqlName") or "")
        current_text = str(payload.get("SqlText") or "").strip()
        if current_name == self.BIN_STOCK_SQL_NAME and current_text == self.BIN_STOCK_SQL_TEXT:
            return

        update_response = self.session.patch(
            f"{self.base_url}/SQLQueries('{encoded_sql_code}')",
            json={
                "SqlName": self.BIN_STOCK_SQL_NAME,
                "SqlText": self.BIN_STOCK_SQL_TEXT,
            },
            timeout=self.timeout,
        )
        if update_response.status_code >= 400:
            raise SapServiceLayerError(
                "Failed to update SAP SQL query for bin stock "
                f"({update_response.status_code}): {update_response.text}"
            )

    @staticmethod
    def _format_sql_query_param(value: str) -> str:
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
