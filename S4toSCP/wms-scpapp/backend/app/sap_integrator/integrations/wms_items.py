"""
integrations/wms_items.py — Sync WMS Items → SAP B1 Items

This flow is independent from the existing SAP → WMS items sync.
It is intended for projects where the article master is created in WMS
and must be pushed into SAP.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from .base import BaseIntegration
from ..config import Settings
from ..sap.service_layer import SAPRequestError, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.wms_items")


CHANGED_ITEMS_SQL = """
    SELECT
        im.ItemID,
        ISNULL(im.ItemDesc, '') AS ItemDesc,
        ISNULL(im.CategoryID, '') AS CategoryID,
        ISNULL(im.SaleUnit, '') AS SaleUnit,
        ISNULL(im.InterStat, '') AS InterStat,
        ISNULL(im.ItemCompos, '') AS ItemCompos,
        ISNULL(im.Comments, '') AS Comments,
        im.ModifDateTime,
        ISNULL(CAST(im.IntegrationID AS varchar(50)), '') AS IntegrationID
    FROM ItemMaster im WITH (NOLOCK)
    WHERE ISNULL(LTRIM(RTRIM(im.ItemID)), '') <> ''
      AND (
            NULLIF(LTRIM(RTRIM(CAST(im.IntegrationID AS varchar(50)))), '') IS NULL
         OR TRY_CONVERT(datetime, NULLIF(LTRIM(RTRIM(CAST(im.IntegrationID AS varchar(50)))), '')) IS NULL
         OR im.ModifDateTime >= TRY_CONVERT(datetime, NULLIF(LTRIM(RTRIM(CAST(im.IntegrationID AS varchar(50)))), ''))
      )
    ORDER BY im.ItemID
"""

DIMENSIONAL_ITEM_SQL = """
    SELECT DISTINCT
        im.ItemID AS BaseItemID,
        CASE
            WHEN LEN(
                CONCAT(
                    im.ItemID, '-',
                    REPLACE(REPLACE(ISNULL(imd.ColorID, ''), ' ', '_'), '/', '_'), '-',
                    REPLACE(REPLACE(ISNULL(imd.SizeID, ''), ' ', '_'), '/', '_')
                )
            ) <= 50
            THEN CONCAT(
                im.ItemID, '-',
                REPLACE(REPLACE(ISNULL(imd.ColorID, ''), ' ', '_'), '/', '_'), '-',
                REPLACE(REPLACE(ISNULL(imd.SizeID, ''), ' ', '_'), '/', '_')
            )
            ELSE CONCAT(
                LEFT(im.ItemID, 3), '-',
                REPLACE(REPLACE(ISNULL(imd.ColorID, ''), ' ', '_'), '/', '_'), '-',
                REPLACE(REPLACE(ISNULL(imd.SizeID, ''), ' ', '_'), '/', '_')
            )
        END AS ItemIDComp,
        ISNULL(im.ItemDesc, '') AS ItemDesc,
        CONCAT(
            ISNULL(im.ItemDesc, ''),
            ' Color:',
            REPLACE(REPLACE(ISNULL(imd.ColorID, ''), ' ', '_'), '/', '_'),
            ' Size:',
            REPLACE(REPLACE(ISNULL(imd.SizeID, ''), ' ', '_'), '/', '_')
        ) AS ItemDescComp,
        LEFT(REPLACE(REPLACE(ISNULL(imd.ColorID, ''), ' ', '_'), '/', '_'), 20) AS ColorID,
        LEFT(REPLACE(REPLACE(ISNULL(imd.SizeID, ''), ' ', '_'), '/', '_'), 10) AS SizeID,
        ISNULL(imd.OrderNum, 0) AS OrderNum,
        ISNULL(im.CategoryID, '') AS CategoryID,
        ISNULL(im.SaleUnit, '') AS SaleUnit,
        ISNULL(im.InterStat, '') AS InterStat,
        ISNULL(im.ItemCompos, '') AS ItemCompos,
        ISNULL(im.Comments, '') AS Comments
    FROM ItemMaster im WITH (NOLOCK)
    JOIN ItemMasterDim imd WITH (NOLOCK)
      ON imd.ItemID = im.ItemID
    WHERE im.ItemID = ?
    ORDER BY ISNULL(imd.OrderNum, 0), ItemIDComp
"""

BASE_ITEM_SQL = """
    SELECT
        im.ItemID AS BaseItemID,
        im.ItemID AS ItemIDComp,
        ISNULL(im.ItemDesc, '') AS ItemDesc,
        ISNULL(im.ItemDesc, '') AS ItemDescComp,
        '' AS ColorID,
        '' AS SizeID,
        0 AS OrderNum,
        ISNULL(im.CategoryID, '') AS CategoryID,
        ISNULL(im.SaleUnit, '') AS SaleUnit,
        ISNULL(im.InterStat, '') AS InterStat,
        ISNULL(im.ItemCompos, '') AS ItemCompos,
        ISNULL(im.Comments, '') AS Comments
    FROM ItemMaster im WITH (NOLOCK)
    WHERE im.ItemID = ?
"""


class WMSItemsIntegration(BaseIntegration):
    name = "wms_items"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms

    async def run(self) -> None:
        self._set_task("A ler artigos alterados no WMS…")
        changed_items = await self._wms.afetch_all(CHANGED_ITEMS_SQL)
        self.log_info(f"Artigos WMS candidatos a sincronização: {len(changed_items)}")

        async with get_sap_client(self._settings) as sl:
            total = len(changed_items)
            for idx, item in enumerate(changed_items, start=1):
                base_item_id = str(item.get("ItemID") or "").strip().upper()
                if not base_item_id:
                    continue
                self._set_task(f"A sincronizar artigo {idx}/{total}: {base_item_id}…")
                try:
                    variants = await self._load_wms_variants(base_item_id)
                    if not variants:
                        raise ValueError(f"Sem dados preparados para o artigo {base_item_id}.")

                    for variant in variants:
                        await self._sync_variant(sl, base_item_id, variant)

                    await self._wms.amark_item_integration(
                        base_item_id,
                        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    self._inc_synced()
                    self.log_info(
                        f"Artigo WMS {base_item_id} sincronizado para SAP ({len(variants)} variante(s))."
                    )
                except Exception as e:
                    error_msg = self._format_operator_error(base_item_id, e, variants)
                    self.record_error(
                        sap_key=base_item_id,
                        sap_object_type="Items",
                        error_msg=error_msg,
                        payload=item,
                    )

    async def _load_wms_variants(self, item_id: str) -> List[Dict[str, Any]]:
        sql = DIMENSIONAL_ITEM_SQL if self._uses_dimensional_variants(item_id) else BASE_ITEM_SQL
        rows = await self._wms.afetch_all(sql, (item_id,))
        return [self._normalize_variant_row(row) for row in rows]

    async def _sync_variant(self, sl, base_item_id: str, variant: Dict[str, Any]) -> None:
        item_code = variant["item_code"]
        payload = self._build_sap_payload(variant)
        create_payload = dict(payload)
        update_payload = dict(payload)
        update_payload.pop("ItemCode", None)
        update_payload.pop("UoMGroupEntry", None)

        try:
            await sl.get_by_key("Items", item_code)
        except SAPRequestError as e:
            if e.status_code == 404:
                await sl.post("Items", create_payload)
                self.log_info(f"Artigo SAP criado: {item_code} (origem {base_item_id}).")
                return
            raise

        await sl.patch("Items", item_code, update_payload)
        self.log_info(f"Artigo SAP atualizado: {item_code} (origem {base_item_id}).")

    @staticmethod
    def _uses_dimensional_variants(item_id: str) -> bool:
        prefix = (item_id or "").strip().upper()[:1]
        return prefix in {"F", "S", "5"}

    @staticmethod
    def _normalize_variant_row(row: Dict[str, Any]) -> Dict[str, Any]:
        base_item_id = str(row.get("BaseItemID") or "").strip().upper()
        item_code = str(row.get("ItemIDComp") or base_item_id).strip().upper()
        item_name = str(row.get("ItemDescComp") or row.get("ItemDesc") or item_code).strip()
        color_id = str(row.get("ColorID") or "").strip().upper()
        size_id = str(row.get("SizeID") or "").strip().upper()
        category_id = str(row.get("CategoryID") or "").strip().upper()
        sale_unit = str(row.get("SaleUnit") or "").strip()
        inter_stat = str(row.get("InterStat") or "").strip().upper()
        item_parent = base_item_id[:29] if len(base_item_id) > 30 else base_item_id

        return {
            "base_item_id": base_item_id,
            "item_code": item_code[:50],
            "item_name": item_name[:100],
            "foreign_name": str(row.get("ItemDesc") or item_name).strip()[:100],
            "color_id": color_id[:20],
            "size_id": size_id[:10],
            "order_num": str(row.get("OrderNum") or 0).strip(),
            "category_id": category_id,
            "sale_unit": sale_unit,
            "inter_stat": inter_stat,
            "item_compos": str(row.get("ItemCompos") or "").strip()[:254],
            "comments": str(row.get("Comments") or "").strip()[:254],
            "item_parent": item_parent.upper(),
        }

    @classmethod
    def _build_sap_payload(cls, variant: Dict[str, Any]) -> Dict[str, Any]:
        mapping = cls._resolve_mapping(variant)
        payload: Dict[str, Any] = {
            "ItemCode": variant["item_code"],
            "ItemName": variant["item_name"],
            "ForeignName": variant["foreign_name"],
            "ItemsGroupCode": mapping["item_group_code"],
            "SalesVATGroup": mapping["sales_vat_group"],
            "PurchaseVATGroup": mapping["purchase_vat_group"],
            "DefaultWarehouse": mapping["default_warehouse"],
            "PurchaseItem": cls._sap_bool(mapping["purchase_item"]),
            "SalesItem": cls._sap_bool(mapping["sales_item"]),
            "InventoryItem": cls._sap_bool(mapping["inventory_item"]),
            "PurchaseUnit": mapping["purchase_uom"],
            "SalesUnit": mapping["sales_uom"],
            "InventoryUOM": mapping["inventory_uom"],
            "User_Text": variant["comments"],
            "DefaultSalesUoMEntry": mapping["default_uom_entry"],
            "DefaultPurchasingUoMEntry": mapping["default_uom_entry"],
            "U_SEI_Cor": variant["color_id"],
            "U_SEI_Comp": variant["item_compos"],
            "U_SEI_Tamanho": variant["size_id"],
            "U_SEI_Ordem": variant["order_num"],
            "U_SEI_ArtigoPai": variant["item_parent"],
        }

        if mapping["uom_group_entry"] is not None:
            payload["UoMGroupEntry"] = mapping["uom_group_entry"]
        if mapping["country_of_origin"]:
            payload["ItemCountryOrg"] = mapping["country_of_origin"]
        if variant["inter_stat"]:
            payload["ItemIntrastatExtension"] = {
                "CommodityCode": variant["inter_stat"],
                "IntrastatRelevant": "tYES",
                "ImportRegionCountry": mapping["country_of_origin"] or "PT",
                "ExportRegionCountry": mapping["country_of_origin"] or "PT",
            }

        return payload

    @classmethod
    def _resolve_mapping(cls, variant: Dict[str, Any]) -> Dict[str, Any]:
        prefix = variant["base_item_id"][:1].upper()
        category_id = variant["category_id"].upper()
        purchase_uom = cls._map_purchase_uom(variant["sale_unit"])

        mapping = {
            "item_group_code": 100,
            "uom_group_entry": -1,
            "default_uom_entry": 1,
            "sales_uom": "UN",
            "purchase_uom": purchase_uom,
            "inventory_uom": "UN",
            "default_warehouse": "001",
            "sales_vat_group": "L3",
            "purchase_vat_group": "D3",
            "purchase_item": prefix in {"M", "A", "E", "S", "C"} or category_id == "T",
            "sales_item": prefix in {"5", "F", "S"},
            "inventory_item": prefix not in {"S", "C"},
            "country_of_origin": "PT",
        }

        if prefix == "M":
            mapping.update(
                item_group_code=102,
                uom_group_entry=1,
                default_uom_entry=3,
                sales_uom="Metros",
                purchase_uom="Metros",
                inventory_uom="Metros",
                default_warehouse="001",
            )
        elif prefix == "A":
            mapping.update(
                item_group_code=105,
                uom_group_entry=2,
                default_uom_entry=1,
                sales_uom="Unidade",
                purchase_uom="Unidade",
                inventory_uom="Unidade",
                default_warehouse="001",
            )
        elif prefix == "E":
            mapping.update(
                item_group_code=106,
                uom_group_entry=2,
                default_uom_entry=1,
                sales_uom="Unidade",
                purchase_uom="Unidade",
                inventory_uom="Unidade",
                default_warehouse="001",
            )
        elif prefix in {"S", "5"}:
            mapping.update(
                item_group_code=101 if category_id == "T" else 104,
                uom_group_entry=-1,
                default_uom_entry=11,
                sales_uom="UN",
                purchase_uom="UN",
                inventory_uom="UN",
                default_warehouse="010",
            )
        elif prefix == "F":
            mapping.update(
                item_group_code=101,
                uom_group_entry=-1,
                default_uom_entry=11,
                sales_uom="UN",
                purchase_uom="UN",
                inventory_uom="UN",
                default_warehouse="010",
            )
        elif prefix == "C":
            mapping.update(
                item_group_code=110,
                uom_group_entry=-1,
                default_uom_entry=11,
                sales_uom="UN",
                purchase_uom="UN",
                inventory_uom="UN",
                default_warehouse="900",
                purchase_vat_group="D10",
            )

        return mapping

    @staticmethod
    def _map_purchase_uom(raw_value: str) -> str:
        mapping = {
            "3": "Metros",
            "13": "YD",
            "9": "CEM",
            "1": "UN",
        }
        key = str(raw_value or "").strip()
        return mapping.get(key, key or "UN")

    @staticmethod
    def _sap_bool(value: bool) -> str:
        return "tYES" if value else "tNO"

    @staticmethod
    def _format_operator_error(
        item_id: str,
        error: Exception,
        variants: List[Dict[str, Any]],
    ) -> str:
        base_msg = f"Artigo WMS→SAP falhou para {item_id}: {error}"
        if not variants:
            return base_msg

        inter_stat = str(variants[0].get("inter_stat") or "").strip()
        if not inter_stat:
            return base_msg

        raw_error = str(error)
        if isinstance(error, SAPRequestError) and error.status_code == 404 and "-2028" in raw_error:
            return (
                f"Artigo {item_id} não foi integrado no SAP porque o CommodityCode "
                f"'{inter_stat}' não existe/configurado no SAP. "
                "O operador deve pedir a criação desse CommodityCode antes de repetir a integração."
            )

        return base_msg
