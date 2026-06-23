"""
integrations/partners.py — Sync SAP BusinessPartners → WMS Partners + ItemProvider

SAP entity: BusinessPartners (OCRD)
  CardType = 'cCustomer' → PartnerType = 'C'
  CardType = 'cSupplier' → PartnerType = 'F'
  CardType = 'cLead'     → skipped

Also syncs Items-supplier links (OPDN / ItemVendors) → WMS ItemProvider
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..config import Settings
from .base import BaseIntegration
from ..sap.service_layer import ServiceLayerClient, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.partners")

CARD_TYPE_MAP = {
    "cCustomer": "C",
    "cSupplier": "F",
}


class PartnersIntegration(BaseIntegration):
    name = "partners"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms

    async def run(self) -> None:
        async with get_sap_client(self._settings) as sl:
            await self._sync_partners(sl)
            await self._sync_item_providers(sl)

    # ── Business Partners ─────────────────────────────────────────────────────

    async def _sync_partners(self, sl: ServiceLayerClient) -> None:
        self._set_task("Syncing Business Partners…")
        synced = 0
        failed = 0

        filter_str = (
            f"(CardType eq 'cCustomer' or CardType eq 'cSupplier') "
            f"and {sl.not_synced_filter('U_WMS_Synced')}"
        )

        async for bp in sl.get_all(
            "BusinessPartners",
            filter=filter_str,
            select=(
                "CardCode,CardName,CardType,Phone1,Phone2,Fax,"
                "BillToState,BillToDef,U_WMS_Synced,"
                "MailAddress,MailCity,MailCounty,MailZipCode,MailCountry,"
                "ContactPerson,EmailAddress,VatLiable,FederalTaxID"
            ),
        ):
            card_code = bp.get("CardCode", "")
            card_type = bp.get("CardType", "")
            partner_type = CARD_TYPE_MAP.get(card_type)

            if not partner_type:
                continue  # Skip leads
            if await self._wms.ais_sap_integration_synced(
                self.name,
                "BusinessPartners",
                str(card_code),
            ):
                continue

            self._set_task(f"Syncing partner {card_code}…")
            try:
                mapped = self._map_partner(bp, partner_type)
                await self._wms.aupsert("Partners", "PartnerID", card_code, mapped)
                mark_error = None
                try:
                    await sl.mark_synced("BusinessPartners", card_code)
                except Exception as exc:
                    mark_error = str(exc)
                    self.log_warning(
                        f"Parceiro {card_code} sincronizado no S3, mas o SAP recusou atualizar U_WMS_Synced.",
                        details=mark_error,
                    )
                await self._wms.amark_sap_integration_synced(
                    self.name,
                    "BusinessPartners",
                    str(card_code),
                    s3_reference=str(card_code),
                    last_error=mark_error,
                )
                synced += 1
                self._inc_synced()
            except Exception as e:
                failed += 1
                self._inc_failed()
                self.record_error(
                    sap_key=card_code,
                    error_msg=str(e),
                    payload=bp,
                    sap_object_type="BusinessPartners",
                )
                try:
                    await sl.mark_sync_failed("BusinessPartners", card_code)
                except Exception:
                    pass

        self.log_info(f"Partners synced: {synced}, failed: {failed}")

    # ── Item Providers (supplier–item links) ──────────────────────────────────

    async def _sync_item_providers(self, sl: ServiceLayerClient) -> None:
        self._set_task("Syncing Item–Supplier links (ItemProvider)…")
        synced = 0
        failed = 0

        # Fetch items that have a preferred vendor
        async for item in sl.get_all(
            "Items",
            select="ItemCode,ItemName,PrfSupplier",
            filter="PrfSupplier ne ''",
        ):
            item_code = item.get("ItemCode", "")
            supplier_code = item.get("PrfSupplier", "")
            if not supplier_code:
                continue

            data = {
                "ItemID": item_code,
                "ProviderID": supplier_code,
                "ProviderItemID": item_code,  # default — override if UDF exists
                "IsDefault": 1,
            }
            try:
                # Composite key: ItemID + ProviderID
                await self._wms.aexecute(
                    """
                    MERGE [ItemProvider] AS target
                    USING (SELECT ? AS ItemID, ? AS ProviderID) AS source
                      ON target.ItemID = source.ItemID AND target.ProviderID = source.ProviderID
                    WHEN MATCHED THEN
                        UPDATE SET IsDefault = ?
                    WHEN NOT MATCHED THEN
                        INSERT (ItemID, ProviderID, ProviderItemID, IsDefault)
                        VALUES (?, ?, ?, ?);
                    """,
                    (
                        item_code, supplier_code,
                        data["IsDefault"],
                        item_code, supplier_code, item_code, data["IsDefault"],
                    ),
                )
                synced += 1
            except Exception as e:
                failed += 1
                self.record_error(
                    sap_key=f"{item_code}|{supplier_code}",
                    error_msg=str(e),
                    payload=item,
                    sap_object_type="ItemVendors",
                )

        self.log_info(f"ItemProvider links synced: {synced}, failed: {failed}")

    # ── Mapping ───────────────────────────────────────────────────────────────

    @staticmethod
    def _map_partner(bp: Dict[str, Any], partner_type: str) -> Dict[str, Any]:
        return {
            "PartnerID":      bp.get("CardCode", ""),
            "PartnerName":    (bp.get("CardName") or "")[:100],
            "PartnerType":    partner_type,
            "Phone1":         (bp.get("Phone1") or "")[:20],
            "Phone2":         (bp.get("Phone2") or "")[:20],
            "Fax":            (bp.get("Fax") or "")[:20],
            "Email":          (bp.get("EmailAddress") or "")[:100],
            "ContactPerson":  (bp.get("ContactPerson") or "")[:100],
            "Address":        (bp.get("MailAddress") or "")[:150],
            "City":           (bp.get("MailCity") or "")[:50],
            "ZipCode":        (bp.get("MailZipCode") or "")[:20],
            "Country":        (bp.get("MailCountry") or "")[:3],
            "VatNumber":      (bp.get("FederalTaxID") or "")[:30],
        }
