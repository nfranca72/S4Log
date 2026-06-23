"""
integrations/purchase_orders.py — Sync WMS purchase orders (DocType OC) → SAP B1

Strategy:
  - Active OC documents in WMS are mirrored to SAP PurchaseOrders
  - Changes are handled as "cancel and recreate" to keep the sync deterministic
  - Documents that disappear from the active OC set are cancelled/closed in SAP
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import select

from ..config import Settings
from .base import BaseIntegration
from ..models.database import PurchaseOrderSync, get_session
from ..sap.service_layer import SAPRequestError, get_sap_client
from ..wms.sql_server import WMSDatabase

logger = logging.getLogger("integration.purchase_orders")


ACTIVE_STATUS_EXCLUSIONS = ("ANULADA", "CANCELADA", "FECHADA")
RTF_CONTROL_RE = re.compile(r"\\[a-zA-Z]+-?\d* ?|\\'([0-9a-fA-F]{2})|[{}]")
WHITESPACE_RE = re.compile(r"\s+")

HEADERS_SQL = """
    SELECT
        co.DocType,
        co.OrderID,
        co.ClientID,
        ISNULL(bp.GLNCode, '') AS SupplierCode,
        ISNULL(bp.PartnerName, '') AS SupplierName,
        co.OrderDateTime,
        co.CreationDateTime,
        co.ModifDateTime,
        co.OrderDatePrev,
        ISNULL(co.ObsInternal, '') AS ObsInternal,
        UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)), '')))) AS Status
    FROM ClientOrders co WITH (NOLOCK)
    JOIN BusinessPartners bp WITH (NOLOCK)
      ON bp.PartnerType = 'F'
     AND bp.PartnerID = co.ClientID
    WHERE co.DocType = 'OC'
      AND UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)), '')))) NOT IN (?, ?, ?)
    ORDER BY co.OrderID
"""

ALL_LINES_SQL = """
    SELECT
        cod.OrderID,
        cod.OrderRow,
        cod.ItemID,
        ISNULL(cod.UnitPrice, 0) AS UnitPrice,
        ISNULL(cod.QtyOrd, 0) AS QtyOrd,
        ISNULL(cod.ObsInternal, ISNULL(cod.Obs, '')) AS Obs,
        ISNULL(prj.ProjectCode, '') AS ProjectCode
    FROM ClientOrderDetails cod WITH (NOLOCK)
    LEFT JOIN (
        SELECT
            codo.OrderID,
            codo.OrderRow,
            imc.CharacteristicValue AS ProjectCode
        FROM ClientOrderDetailsOri codo WITH (NOLOCK)
        JOIN DocumentConfig dc WITH (NOLOCK)
          ON dc.DocType = codo.DocTypeOri
         AND dc.DocTypeArea = 'PRODUCTION'
        JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
          ON imc.CharacteristicID = 'PROJETO'
        JOIN ClientOrderDetails codp WITH (NOLOCK)
          ON codp.DocType = codo.DocTypeOri
         AND codp.OrderID = codo.OrderIDOri
         AND codp.OrderRow = codo.OrderRowOri
         AND imc.ItemID = codp.ItemID
         AND imc.Version = codp.Versao
        WHERE codo.DocType = 'OC'
    ) prj
      ON prj.OrderID = cod.OrderID
     AND prj.OrderRow = cod.OrderRow
    JOIN ClientOrders co WITH (NOLOCK)
      ON co.DocType = cod.DocType
     AND co.OrderID = cod.OrderID
    WHERE cod.DocType = 'OC'
      AND UPPER(LTRIM(RTRIM(ISNULL(CAST(co.Status AS varchar(50)), '')))) NOT IN (?, ?, ?)
    ORDER BY cod.OrderID, cod.OrderRow
"""


class PurchaseOrdersIntegration(BaseIntegration):
    name = "purchase_orders"

    def __init__(self, settings: Settings, wms: WMSDatabase):
        super().__init__()
        self._settings = settings
        self._wms = wms
        self._series_cache: dict[tuple[str, str], int | None] = {}

    async def run(self) -> None:
        self._set_task("A ler encomendas OC do WMS…")
        docs = await self._load_active_documents()
        self.log_info(f"OC carregadas do WMS: {len(docs)}")
        active_keys = {doc["local_key"] for doc in docs}

        async with get_sap_client(self._settings) as sl:
            for doc in docs:
                order_label = f"{doc['doc_type']}.{doc['order_id']}"
                self._set_task(f"A sincronizar {order_label}…")
                try:
                    await self._sync_document(sl, doc)
                except Exception as e:
                    logger.warning("Purchase order sync failed for %s: %s", order_label, e)
                    self.record_error(
                        sap_key=order_label,
                        sap_object_type="PurchaseOrders",
                        error_msg=str(e),
                        payload=doc,
                    )
                    self._save_link_error(doc["local_key"], str(e))

            self._set_task("A verificar documentos OC removidos…")
            await self._cancel_missing_documents(sl, active_keys)

    async def _load_active_documents(self) -> List[Dict[str, Any]]:
        self.log_info("A consultar cabeçalhos OC no WMS.")
        headers = await self._wms.afetch_all(HEADERS_SQL, ACTIVE_STATUS_EXCLUSIONS)
        self.log_info(f"Cabeçalhos OC encontrados: {len(headers)}")
        self.log_info("A consultar linhas OC ativas no WMS.")
        all_lines = await self._wms.afetch_all(ALL_LINES_SQL, ACTIVE_STATUS_EXCLUSIONS)
        lines_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for line in all_lines:
            lines_by_order[int(line["OrderID"])].append(line)
        self.log_info(f"Linhas OC carregadas: {len(all_lines)}")

        docs: List[Dict[str, Any]] = []
        total_headers = len(headers)
        skipped_without_supplier = 0
        for idx, header in enumerate(headers, start=1):
            order_id = int(header["OrderID"])
            if idx == 1 or idx % 100 == 0 or idx == total_headers:
                self._set_task(f"A preparar OC {idx}/{total_headers}…")
            supplier_code = str(header.get("SupplierCode") or "").strip()
            if not supplier_code:
                skipped_without_supplier += 1
                continue
            lines = lines_by_order.get(order_id, [])
            if not lines:
                self.log_warning(f"OC.{order_id} ignorada porque não tem linhas.")
                continue
            docs.append(self._build_document_snapshot(header, lines))
        if skipped_without_supplier:
            self.log_warning(
                f"OC ignoradas sem BusinessPartners.GLNCode preenchido: {skipped_without_supplier}"
            )
        return docs

    def _build_document_snapshot(self, header: Dict[str, Any], lines: List[Dict[str, Any]]) -> Dict[str, Any]:
        doc_type = str(header["DocType"]).strip().upper()
        order_id = int(header["OrderID"])
        line_ref_field = self._normalize_udf_field(
            self._settings.sap_purchase_order_line_ref_field or "SEI_DocONS3"
        )

        normalized_lines: List[Dict[str, Any]] = []
        for row in lines:
            order_row = int(row["OrderRow"])
            normalized_lines.append(
                {
                    "order_row": order_row,
                    "item_code": str(row["ItemID"]).strip(),
                    "quantity": float(row["QtyOrd"] or 0),
                    "unit_price": float(row["UnitPrice"] or 0),
                    "line_comment": self._to_plain_text(row.get("Obs")),
                    "project_code": str(row.get("ProjectCode") or "").strip(),
                    "line_ref": f"{doc_type}.{order_id}.{order_row}",
                    "line_ref_field": line_ref_field,
                }
            )

        creation_dt = self._coerce_datetime(header.get("CreationDateTime") or header.get("OrderDateTime"))
        due_dt = self._coerce_datetime(
            header.get("OrderDatePrev") or header.get("OrderDateTime") or header.get("CreationDateTime")
        )
        payload_for_hash = {
            "doc_type": doc_type,
            "order_id": order_id,
            "supplier_code": str(header.get("SupplierCode") or "").strip(),
            "obs_internal": self._to_plain_text(header.get("ObsInternal")),
            "creation_datetime": creation_dt.isoformat() if creation_dt else None,
            "requested_delivery_datetime": due_dt.isoformat() if due_dt else None,
            "lines": normalized_lines,
        }

        return {
            "local_key": f"{doc_type}:{order_id}",
            "doc_type": doc_type,
            "order_id": order_id,
            "supplier_code": str(header.get("SupplierCode") or "").strip(),
            "supplier_name": str(header.get("SupplierName") or "").strip(),
            "obs_internal": self._to_plain_text(header.get("ObsInternal")),
            "creation_datetime": creation_dt,
            "requested_delivery_datetime": due_dt,
            "modif_datetime": self._coerce_datetime(header.get("ModifDateTime")),
            "lines": normalized_lines,
            "fingerprint": hashlib.sha256(
                json.dumps(payload_for_hash, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
            "payload_json": json.dumps(payload_for_hash, sort_keys=True, default=str),
        }

    async def _sync_document(self, sl, doc: Dict[str, Any]) -> None:
        link = self._get_link(doc["local_key"])
        if not link and await self._wms.ais_sap_integration_synced(
            self.name,
            "PurchaseOrders",
            doc["local_key"],
        ):
            self.log_warning(
                f"{doc['local_key']} ja existe em SapIntegrationSync; ignorado para evitar duplicado."
            )
            return
        if link and link.fingerprint == doc["fingerprint"] and link.status == "active":
            self.log_info(f"Sem alterações para {doc['doc_type']}.{doc['order_id']}.")
            return

        self._ensure_project_codes(doc)

        if link and link.sap_doc_entry:
            self.log_info(
                f"Alterações detetadas em {doc['doc_type']}.{doc['order_id']} — "
                f"a cancelar SAP {link.sap_doc_num or link.sap_doc_entry} antes de recriar."
            )
            await self._cancel_in_sap(sl, int(link.sap_doc_entry))

        purchase_series = await self._resolve_purchase_order_series(doc)
        sap_payload = self._build_sap_payload(doc, purchase_series=purchase_series)
        self.log_info(
            f"A criar PurchaseOrder SAP para OC {doc['order_id']} "
            f"com {len(doc['lines'])} linha(s)."
        )
        sap_result = await sl.post("PurchaseOrders", sap_payload)
        sap_doc_entry = int(sap_result.get("DocEntry") or 0) or None
        sap_doc_num = int(sap_result.get("DocNum") or 0) or None
        integration_id = self._build_integration_id(doc, sap_result)

        await self._wms.amark_order_integration(
            doc["doc_type"],
            doc["order_id"],
            integration_id,
        )

        self._upsert_link(
            doc=doc,
            sap_doc_entry=sap_doc_entry,
            sap_doc_num=sap_doc_num,
            status="active",
            last_error=None,
        )
        await self._wms.amark_sap_integration_synced(
            self.name,
            "PurchaseOrders",
            doc["local_key"],
            sap_doc_entry=sap_doc_entry,
            sap_doc_num=sap_doc_num,
            sap_series=str(purchase_series or ""),
            s3_reference=doc["local_key"],
        )
        self._inc_synced()
        self.log_info(
            f"OC {doc['order_id']} sincronizada para SAP PurchaseOrder "
            f"{sap_doc_num or sap_doc_entry}. IDIntegration={integration_id}"
        )

    def _ensure_project_codes(self, doc: Dict[str, Any]) -> None:
        missing_lines = [
            f"linha {line['order_row']} ({line['item_code']})"
            for line in doc["lines"]
            if not str(line.get("project_code") or "").strip()
        ]
        if not missing_lines:
            return

        preview = ", ".join(missing_lines[:5])
        if len(missing_lines) > 5:
            preview += f", +{len(missing_lines) - 5} linha(s)"

        raise ValueError(
            f"Projeto em falta na OC.{doc['order_id']}: {preview}. "
            f"A integração exige ProjectCode em todas as linhas."
        )

    def _build_integration_id(self, doc: Dict[str, Any], sap_result: Dict[str, Any]) -> str:
        year = str((doc.get("creation_datetime") or datetime.utcnow()).year)
        year_suffix = year[-2:]
        series_label = f"{doc['doc_type']}{year_suffix}F"
        sap_doc_num = sap_result.get("DocNum")
        sap_doc_entry = sap_result.get("DocEntry")
        return f"{series_label}.{sap_doc_num} ({sap_doc_entry})"

    async def _cancel_missing_documents(self, sl, active_keys: set[str]) -> None:
        with get_session() as session:
            rows = session.scalars(
                select(PurchaseOrderSync).where(PurchaseOrderSync.status == "active")
            ).all()

        for link in rows:
            if link.local_key in active_keys:
                continue
            order_label = f"{link.local_doc_type}.{link.local_order_id}"
            self._set_task(f"A cancelar no SAP o documento removido {order_label}…")
            try:
                if link.sap_doc_entry:
                    await self._cancel_in_sap(sl, int(link.sap_doc_entry))
                with get_session() as session:
                    current = session.get(PurchaseOrderSync, link.local_key)
                    if current:
                        current.status = "cancelled"
                        current.cancelled_at = datetime.utcnow()
                        current.synced_at = datetime.utcnow()
                        current.last_error = None
                self._inc_synced()
                self.log_info(f"{order_label} removida do conjunto ativo e refletida no SAP.")
            except Exception as e:
                self.record_error(
                    sap_key=order_label,
                    sap_object_type="PurchaseOrders",
                    error_msg=str(e),
                    payload={"local_key": link.local_key, "sap_doc_entry": link.sap_doc_entry},
                )
                self._save_link_error(link.local_key, str(e))

    async def _cancel_in_sap(self, sl, sap_doc_entry: int) -> None:
        try:
            await sl.action("PurchaseOrders", sap_doc_entry, "Cancel")
            return
        except SAPRequestError as cancel_error:
            self.log_warning(
                f"Cancel falhou para PurchaseOrders({sap_doc_entry}); a tentar Close.",
                details=str(cancel_error),
            )
        await sl.action("PurchaseOrders", sap_doc_entry, "Close")

    async def _resolve_purchase_order_series(self, doc: Dict[str, Any]) -> int | None:
        configured_series = self._parse_int(self._settings.sap_purchase_order_series)
        if configured_series is not None:
            return configured_series

        series_year = str((doc.get("creation_datetime") or datetime.utcnow()).year)
        cache_key = (str(doc.get("doc_type") or "").strip().upper(), series_year)
        if cache_key in self._series_cache:
            return self._series_cache[cache_key]

        raw_series = await self._wms.aget_sap_b1_series(cache_key[0], series_year)
        parsed_series = self._parse_int(raw_series)
        self._series_cache[cache_key] = parsed_series
        if parsed_series is None:
            self.log_warning(
                f"Série SAP não encontrada para {cache_key[0]} no ano {series_year}."
            )
        else:
            self.log_info(
                f"Série SAP resolvida para {cache_key[0]}/{series_year}: {parsed_series}."
            )
        return parsed_series

    def _build_sap_payload(self, doc: Dict[str, Any], *, purchase_series: int | None = None) -> Dict[str, Any]:
        doc_date = self._format_date(doc["creation_datetime"])
        due_date = self._format_date(doc["requested_delivery_datetime"])
        warehouse_code = str(self._settings.sap_purchase_order_warehouse_code or "").strip()

        payload: Dict[str, Any] = {
            "CardCode": doc["supplier_code"],
            "DocDate": doc_date,
            "TaxDate": doc_date,
            "DocDueDate": due_date,
            "Comments": doc["obs_internal"] or f"WMS {doc['doc_type']}.{doc['order_id']}",
            "JournalMemo": f"WMS {doc['doc_type']}.{doc['order_id']}",
            "NumAtCard": f"{doc['doc_type']}.{doc['order_id']}",
            "DocumentLines": [],
        }

        if purchase_series is not None:
            payload["Series"] = purchase_series

        for line in doc["lines"]:
            sap_line: Dict[str, Any] = {
                "ItemCode": line["item_code"],
                "Quantity": float(line["quantity"]),
                "UnitPrice": float(line["unit_price"]),
            }
            if warehouse_code:
                sap_line["WarehouseCode"] = warehouse_code
            if line["project_code"]:
                sap_line["ProjectCode"] = line["project_code"]
            if line["line_comment"]:
                sap_line["FreeText"] = line["line_comment"]
            if line["line_ref_field"]:
                sap_line[line["line_ref_field"]] = line["line_ref"]
            payload["DocumentLines"].append(sap_line)

        return payload

    def _get_link(self, local_key: str) -> PurchaseOrderSync | None:
        with get_session() as session:
            return session.get(PurchaseOrderSync, local_key)

    def _upsert_link(
        self,
        *,
        doc: Dict[str, Any],
        sap_doc_entry: int | None,
        sap_doc_num: int | None,
        status: str,
        last_error: str | None,
    ) -> None:
        with get_session() as session:
            row = session.get(PurchaseOrderSync, doc["local_key"])
            if row is None:
                row = PurchaseOrderSync(
                    local_key=doc["local_key"],
                    local_doc_type=doc["doc_type"],
                    local_order_id=doc["order_id"],
                )
                session.add(row)

            row.sap_doc_entry = sap_doc_entry
            row.sap_doc_num = sap_doc_num
            row.fingerprint = doc["fingerprint"]
            row.status = status
            row.payload = doc["payload_json"]
            row.last_seen_at = datetime.utcnow()
            row.synced_at = datetime.utcnow()
            row.cancelled_at = None if status == "active" else row.cancelled_at
            row.last_error = last_error

    def _save_link_error(self, local_key: str, error_msg: str) -> None:
        with get_session() as session:
            row = session.get(PurchaseOrderSync, local_key)
            if row:
                row.last_error = error_msg
                row.synced_at = datetime.utcnow()

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
            return datetime(value.year, value.month, value.day)
        value_str = str(value).strip()
        if not value_str:
            return None
        for candidate in (
            value_str.replace("T", " "),
            value_str[:19].replace("T", " "),
            value_str[:10],
        ):
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                continue
        return None

    @staticmethod
    def _format_date(value: datetime | None) -> str:
        return (value or datetime.utcnow()).strftime("%Y-%m-%d")

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return int(Decimal(raw))
        except Exception:
            return None

    @staticmethod
    def _normalize_udf_field(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return raw if raw.upper().startswith("U_") else f"U_{raw}"

    @classmethod
    def _to_plain_text(cls, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if raw.startswith("{\\rtf"):
            raw = re.sub(r"{\\fonttbl.*?}}", "", raw, flags=re.DOTALL)
            raw = re.sub(r"{\\\*\\generator.*?;}", "", raw, flags=re.DOTALL)
            raw = re.sub(r"\\par(?![a-zA-Z])", "\n", raw)
            raw = re.sub(r"\\line(?![a-zA-Z])", "\n", raw)
            raw = re.sub(r"\\tab(?![a-zA-Z])", "\t", raw)
            raw = re.sub(
                r"\\'([0-9a-fA-F]{2})",
                lambda m: bytes.fromhex(m.group(1)).decode("cp1252", errors="ignore"),
                raw,
            )
            raw = RTF_CONTROL_RE.sub("", raw)
        return WHITESPACE_RE.sub(" ", raw).strip()
