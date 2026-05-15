"""
integrations/items.py — Sync SAP Items → WMS ITEMMASTER + auxiliary tables

SAP entities:
  Items      → ITEMMASTER
  ItemGroups → Categories + GroupType  (endpoint: ItemGroups)
  UoM        → Units  (tries UnitsOfMeasurement, falls back to extracting
                        unique UOM codes directly from Items)

Each sub-sync is independent — failure in Units does NOT abort Items.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Set

from ..config import Settings
from .base import BaseIntegration
from ..sap.service_layer import ServiceLayerClient, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.items")


class ItemsIntegration(BaseIntegration):
    name = "items"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms

    # ── Main entry ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        async with get_sap_client(self._settings) as sl:
            # Each step is independent — errors don't abort the cycle
            await self._sync_item_groups(sl)
            await self._sync_units(sl)
            await self._sync_items(sl)

    # ── Units of Measure ──────────────────────────────────────────────────────

    async def _sync_units(self, sl: ServiceLayerClient) -> None:
        self._set_task("A sincronizar Unidades de Medida…")

        # Try the dedicated UoM endpoint first; fall back to extracting
        # unique codes from the Items collection if not available.
        uom_endpoint_candidates = [
            ("UnitsOfMeasurement", "Code",    "Name"),
            ("UnitOfMeasurements",  "Code",    "Name"),
            ("UoMGroups",           "Code",    "Name"),
        ]

        for endpoint, code_field, name_field in uom_endpoint_candidates:
            try:
                count = 0
                async for uom in sl.get_all(endpoint, select=f"{code_field},{name_field}"):
                    code = (uom.get(code_field) or "")[:3]
                    name = (uom.get(name_field) or "")[:20]
                    if not code:
                        continue
                    try:
                        await self._wms.aupsert("Units", "UnitID", code, {
                            "UnitID": code, "UnitDesc": name, "Round": 2,
                        })
                        count += 1
                    except Exception as e:
                        self.record_error(str(code), str(e), uom, "Units")
                self.log_info(f"Unidades de Medida (via {endpoint}): {count} sincronizadas")
                return  # success — stop trying candidates
            except Exception as e:
                if "Unrecognized resource path" in str(e) or "400" in str(e):
                    logger.info(f"Endpoint '{endpoint}' não disponível — a tentar alternativa…")
                    continue
                # Unexpected error — log and move on
                self.log_warning(f"Erro ao sincronizar UoM via {endpoint}: {e}")
                return

        # Fallback: extract unique UOM codes from Items
        logger.info("Endpoint UoM não encontrado — a extrair códigos de UoM dos Artigos…")
        await self._sync_units_from_items(sl)

    async def _sync_units_from_items(self, sl: ServiceLayerClient) -> None:
        """Extract unique UOM codes directly from Items as a fallback."""
        seen: Set[str] = set()
        count = 0
        try:
            async for item in sl.get_all(
                "Items",
                select="InventoryUOM,SalesUnit,PurchaseUnit",
            ):
                for field in ("InventoryUOM", "SalesUnit", "PurchaseUnit"):
                    code = (item.get(field) or "")[:3].strip()
                    if code and code not in seen:
                        seen.add(code)
                        try:
                            await self._wms.aupsert("Units", "UnitID", code, {
                                "UnitID": code, "UnitDesc": code, "Round": 2,
                            })
                            count += 1
                        except Exception as e:
                            logger.warning(f"Erro ao inserir unidade '{code}': {e}")
            self.log_info(f"Unidades de Medida (extraídas dos Artigos): {count} inseridas")
        except Exception as e:
            self.log_warning(f"Falha no fallback de UoM: {e}")

    # ── Item Groups → Categories + GroupType ──────────────────────────────────

    async def _sync_item_groups(self, sl: ServiceLayerClient) -> None:
        self._set_task("A sincronizar Grupos de Artigos…")

        # SAP B1 10.x uses 'ItemGroups'; some builds use 'ItemsGroups'
        candidates = [
            ("ItemGroups",  "Number", "GroupName"),
            ("ItemsGroups", "Number", "GroupName"),
        ]

        for endpoint, num_field, name_field in candidates:
            try:
                count = 0
                async for grp in sl.get_all(endpoint, select=f"{num_field},{name_field}"):
                    group_id   = str(grp.get(num_field, ""))[:20]
                    group_name = (grp.get(name_field) or "")[:30]
                    if not group_id:
                        continue
                    try:
                        await self._wms.aupsert("Categories", "CategoryID", group_id, {
                            "CategoryID":              group_id,
                            "CategoryDesc":            group_name,
                            "DefaultWH":               None,
                            "DefaultExpirationPeriod": None,
                            "QtyPerLabel":             None,
                        })
                        await self._wms.aupsert("GroupType", "GroupTypeID", group_id, {
                            "GroupTypeID":    group_id,
                            "GroupTypeDescr": group_name[:50],
                        })
                        count += 1
                    except Exception as e:
                        self.record_error(group_id, str(e), grp, endpoint)
                self.log_info(f"Grupos (via {endpoint}): {count} sincronizados")
                return
            except Exception as e:
                if "Unrecognized resource path" in str(e) or "400" in str(e):
                    logger.info(f"Endpoint '{endpoint}' não disponível — a tentar alternativa…")
                    continue
                self.log_warning(f"Erro ao sincronizar grupos via {endpoint}: {e}")
                return

        self.log_warning("Nenhum endpoint de Grupos de Artigos encontrado — a extrair de Items…")
        await self._sync_groups_from_items(sl)

    async def _sync_groups_from_items(self, sl: ServiceLayerClient) -> None:
        """Extract unique group codes directly from Items as fallback."""
        seen: Set[str] = set()
        count = 0
        try:
            async for item in sl.get_all("Items", select="ItmsGrpCod,ItmsGrpNam"):
                grp_id   = str(item.get("ItmsGrpCod") or "")[:20].strip()
                grp_name = (item.get("ItmsGrpNam") or grp_id)[:30]
                if grp_id and grp_id not in seen:
                    seen.add(grp_id)
                    try:
                        await self._wms.aupsert("Categories", "CategoryID", grp_id, {
                            "CategoryID": grp_id, "CategoryDesc": grp_name,
                            "DefaultWH": None, "DefaultExpirationPeriod": None, "QtyPerLabel": None,
                        })
                        await self._wms.aupsert("GroupType", "GroupTypeID", grp_id, {
                            "GroupTypeID": grp_id, "GroupTypeDescr": grp_name[:50],
                        })
                        count += 1
                    except Exception as e:
                        logger.warning(f"Erro grupo '{grp_id}': {e}")
            self.log_info(f"Grupos (extraídos de Items): {count} inseridos")
        except Exception as e:
            self.log_warning(f"Falha no fallback de grupos: {e}")

    # ── Items ─────────────────────────────────────────────────────────────────

    async def _sync_items(self, sl: ServiceLayerClient) -> None:
        self._set_task("A sincronizar Artigos…")
        synced = 0
        failed = 0

        # Build $select — only request fields that exist in SAP B1 standard schema.
        # UDFs (U_*) are added only if U_WMS_Synced exists (already created).
        select_fields = (
            "ItemCode,ItemName,FirmName,ItmsGrpCod,ItmsGrpNam,"
            "SalesUnit,PurchaseUnit,InventoryUOM,"
            "Frozen,ManSerialNum,ManBatchNum,SalesItem,"
            "BarCode,UserText,"
            "U_WMS_Synced"
        )

        filter_str = sl.not_synced_filter("U_WMS_Synced")

        async for item in sl.get_all(
            "Items",
            filter=filter_str,
            select=select_fields,
        ):
            item_code = item.get("ItemCode", "")
            self._set_task(f"A sincronizar artigo {item_code}…")
            try:
                mapped = self._map_item(item)
                await self._wms.aupsert("ITEMMASTER", "Itemid", item_code, mapped)
                await sl.mark_synced("Items", item_code)
                synced += 1
                self._inc_synced()
            except Exception as e:
                failed += 1
                self._inc_failed()
                logger.warning(f"Artigo {item_code} falhou: {e}")
                self.record_error(
                    sap_key=item_code,
                    error_msg=str(e),
                    payload=item,
                    sap_object_type="Items",
                )
                try:
                    await sl.mark_sync_failed("Items", item_code)
                except Exception:
                    pass

        self.log_info(f"Artigos — sincronizados: {synced}, erros: {failed}")
        self._set_task(f"Artigos concluído — {synced} OK, {failed} erros")

    # ── Mapping ───────────────────────────────────────────────────────────────

    @staticmethod
    def _map_item(item: Dict[str, Any]) -> Dict[str, Any]:
        frozen = item.get("Frozen", "N")
        return {
            "Itemid":           item.get("ItemCode", ""),
            "ItemDesc":         (item.get("ItemName") or "")[:100],
            "Brandid":          (item.get("FirmName") or "")[:50],
            "CategoryId":       str(item.get("ItmsGrpCod") or ""),
            "SubCategoryId":    (item.get("U_WMS_SubCategory") or ""),
            "ITemGRoupType":    str(item.get("ItmsGrpCod") or ""),
            "ItemSubGroupType": (item.get("U_WMS_SubGroupType") or ""),
            "StkUnit":          (item.get("InventoryUOM") or "")[:3],
            "PackUnit":         (item.get("PurchaseUnit") or "")[:3],
            "SaleUnit":         (item.get("SalesUnit") or "")[:3],
            "Status":           0 if frozen == "Y" else 1,
            "Lots":             1 if item.get("ManBatchNum") == "Y" else 0,
            "SerialNum":        1 if item.get("ManSerialNum") == "Y" else 0,
            "Comments":         (item.get("UserText") or ""),
            "MovStock":         1 if item.get("SalesItem") == "Y" else 0,
            "InterStat":        (item.get("IntrastatExt") or ""),
            "Barcode":          (item.get("BarCode") or ""),
        }
