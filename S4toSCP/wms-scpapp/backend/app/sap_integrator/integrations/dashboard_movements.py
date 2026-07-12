"""
integrations/dashboard_movements.py - Sync SAP B1 document movements to Ons3_Dash.dbo.DocMovs.

Strategy:
  - First successful run performs a complete load of the requested slices.
  - Subsequent runs load only new/changed SAP documents using CreationDate /
    UpdateDate and replace only the affected dashboard rows.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any, Callable, Generator, Iterable, Sequence

import pyodbc

from ..config import Settings
from ..models.database import IntegrationCursor, SyncState, get_session
from ..sap.service_layer import get_sap_client
from .base import BaseIntegration

logger = logging.getLogger("integration.dashboard_movements")

WAREHOUSE_200 = "200"
ORIGIN_FIELD = "U_SEI_DocONS3"
DOCMOVS_COLUMNS = (
    "AreaCod",
    "SubAreaCod",
    "PartnerID",
    "DocType",
    "OrderID",
    "OrderRow",
    "ItemID",
    "QtyDoc",
    "UnitPrice",
    "TotValue",
    "DataDoc",
    "DocTypeEnc",
    "OrderidEnc",
    "OrderRowEnc",
    "Projectid",
    "Status",
)
FULL_LOAD_BATCH_SIZE = 20
SQL_FLUSH_ROWS = 2000


@dataclass
class DocMovRow:
    area_doc: str
    sub_area_cod: str
    partner_id: str | None
    doc_type: str
    order_id: int
    order_row: int
    item_id: str
    qty_doc: Decimal
    unit_price: Decimal
    tot_value: Decimal
    data_doc: str
    doc_type_ori: str | None
    order_id_ori: str | None
    order_row_ori: int | None
    project_id: str | None
    status: int = 1

    def as_sql_tuple(self) -> tuple[Any, ...]:
        return (
            self.area_doc,
            self.sub_area_cod,
            self.partner_id or "",
            self.doc_type,
            self.order_id,
            self.order_row,
            self.item_id,
            float(self.qty_doc),
            float(self.unit_price),
            float(self.tot_value),
            self.data_doc,
            self.doc_type_ori,
            self.order_id_ori,
            self.order_row_ori,
            self.project_id,
            self.status,
        )


class SqlDatabase:
    def __init__(self, settings: Settings, database_name: str):
        self._conn_str = settings.sql_connection_string(database_name)

    @contextmanager
    def transaction(self) -> Generator[pyodbc.Cursor, None, None]:
        conn = pyodbc.connect(self._conn_str, autocommit=False, timeout=30)
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cursor.close()
            finally:
                conn.close()

    def clear_dashboard_slices(self) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM [dbo].[DocMovs]
                WHERE ([AreaCod] = 'COMPRAS' AND [SubAreaCod] = 'RECECAO')
                   OR ([AreaCod] = 'ABASTECIMENTO' AND [SubAreaCod] = 'ABASTECIMENTO')
                   OR ([AreaCod] = 'CONSUMO' AND [SubAreaCod] = 'CONSUMO')
                """
            )

    def append_rows(self, rows: Sequence[DocMovRow]) -> None:
        if not rows:
            return
        insert_sql = f"""
            INSERT INTO [dbo].[DocMovs] ({", ".join(f"[{column}]" for column in DOCMOVS_COLUMNS)})
            VALUES ({", ".join("?" for _ in DOCMOVS_COLUMNS)})
        """
        values = [row.as_sql_tuple() for row in rows]
        with self.transaction() as cursor:
            cursor.fast_executemany = True
            cursor.executemany(insert_sql, values)

    def replace_document_rows(
        self,
        *,
        area_cod: str,
        sub_area_cod: str,
        order_id: int,
        rows: Sequence[DocMovRow],
    ) -> None:
        insert_sql = f"""
            INSERT INTO [dbo].[DocMovs] ({", ".join(f"[{column}]" for column in DOCMOVS_COLUMNS)})
            VALUES ({", ".join("?" for _ in DOCMOVS_COLUMNS)})
        """
        with self.transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM [dbo].[DocMovs]
                WHERE [AreaCod] = ?
                  AND [SubAreaCod] = ?
                  AND [OrderID] = ?
                """,
                (area_cod, sub_area_cod, order_id),
            )
            if rows:
                cursor.fast_executemany = True
                cursor.executemany(insert_sql, [row.as_sql_tuple() for row in rows])


class DashboardMovementsIntegration(BaseIntegration):
    name = "dashboard_movements"

    def __init__(self, settings: Settings, _wms=None):
        super().__init__()
        self._settings = settings

    async def run(self) -> None:
        dashboard = SqlDatabase(self._settings, self._settings.dashboard_db_name)
        last_success_at, full_load_required = self._sync_checkpoint()

        async with get_sap_client(self._settings) as sl:
            if full_load_required:
                await self._run_full_load(sl, dashboard)
            else:
                assert last_success_at is not None
                await self._run_incremental(sl, dashboard, last_success_at)
        self._save_sync_checkpoint()

    async def _run_full_load(self, sl, dashboard: SqlDatabase) -> None:
        self._set_task("Carga inicial completa de DocMovs...")
        await asyncio.get_event_loop().run_in_executor(None, dashboard.clear_dashboard_slices)

        purchase_order_cache: dict[int, str | None] = {}
        pending_rows: list[DocMovRow] = []
        total_rows = 0

        total_rows += await self._full_load_entity(
            sl,
            entity="PurchaseDeliveryNotes",
            label="rececoes de mercadorias",
            builder=lambda doc: self._map_goods_receipt(doc, purchase_order_cache),
            pending_rows=pending_rows,
            dashboard=dashboard,
        )
        total_rows += await self._full_load_entity(
            sl,
            entity="StockTransfers",
            label="abastecimentos e retornos",
            builder=self._map_stock_transfer,
            pending_rows=pending_rows,
            dashboard=dashboard,
        )
        total_rows += await self._full_load_entity(
            sl,
            entity="InventoryGenExits",
            label="consumos",
            builder=lambda doc: self._map_inventory_doc(doc, sign=Decimal("1")),
            pending_rows=pending_rows,
            dashboard=dashboard,
        )
        total_rows += await self._full_load_entity(
            sl,
            entity="InventoryGenEntries",
            label="correcoes de consumo",
            builder=lambda doc: self._map_inventory_doc(doc, sign=Decimal("-1")),
            pending_rows=pending_rows,
            dashboard=dashboard,
        )

        if pending_rows:
            await self._append_rows_async(dashboard, pending_rows)
            total_rows += len(pending_rows)
            pending_rows.clear()

        self._inc_synced(total_rows)
        self.log_info(f"DocMovs carregada em modo completo: {total_rows} linhas.")

    async def _run_incremental(self, sl, dashboard: SqlDatabase, last_success_at: datetime) -> None:
        since_date = (last_success_at - timedelta(days=1)).strftime("%Y-%m-%d")
        self._set_task(f"Sincronizacao incremental desde {since_date}...")

        purchase_order_cache: dict[int, str | None] = {}
        total_rows = 0

        total_rows += await self._incremental_entity(
            sl,
            dashboard=dashboard,
            entity="PurchaseDeliveryNotes",
            label="rececoes de mercadorias",
            area_cod="COMPRAS",
            sub_area_cod="RECECAO",
            builder=lambda doc: self._map_goods_receipt(doc, purchase_order_cache),
            since_date=since_date,
        )
        total_rows += await self._incremental_entity(
            sl,
            dashboard=dashboard,
            entity="StockTransfers",
            label="abastecimentos e retornos",
            area_cod="ABASTECIMENTO",
            sub_area_cod="ABASTECIMENTO",
            builder=self._map_stock_transfer,
            since_date=since_date,
        )
        total_rows += await self._incremental_entity(
            sl,
            dashboard=dashboard,
            entity="InventoryGenExits",
            label="consumos",
            area_cod="CONSUMO",
            sub_area_cod="CONSUMO",
            builder=lambda doc: self._map_inventory_doc(doc, sign=Decimal("1")),
            since_date=since_date,
        )
        total_rows += await self._incremental_entity(
            sl,
            dashboard=dashboard,
            entity="InventoryGenEntries",
            label="correcoes de consumo",
            area_cod="CONSUMO",
            sub_area_cod="CONSUMO",
            builder=lambda doc: self._map_inventory_doc(doc, sign=Decimal("-1")),
            since_date=since_date,
        )

        self._inc_synced(total_rows)
        self.log_info(f"DocMovs atualizada em modo incremental: {total_rows} linhas afetadas.")

    async def _full_load_entity(
        self,
        sl,
        *,
        entity: str,
        label: str,
        builder: Callable[[dict[str, Any]], list[DocMovRow]],
        pending_rows: list[DocMovRow],
        dashboard: SqlDatabase,
    ) -> int:
        self._set_task(f"Carga completa de {label}...")
        total_docs = 0
        total_rows = 0
        header_batch: list[dict[str, Any]] = []

        async for header in sl.get_all(entity, select="DocEntry", order_by="DocEntry asc", page_size=200):
            header_batch.append(header)
            if len(header_batch) >= FULL_LOAD_BATCH_SIZE:
                docs = await self._fetch_docs(sl, entity, header_batch)
                total_docs += len(docs)
                for doc in docs:
                    rows = builder(doc)
                    pending_rows.extend(rows)
                    total_rows += len(rows)
                    if len(pending_rows) >= SQL_FLUSH_ROWS:
                        await self._append_rows_async(dashboard, pending_rows)
                        pending_rows.clear()
                header_batch.clear()

        if header_batch:
            docs = await self._fetch_docs(sl, entity, header_batch)
            total_docs += len(docs)
            for doc in docs:
                rows = builder(doc)
                pending_rows.extend(rows)
                total_rows += len(rows)
                if len(pending_rows) >= SQL_FLUSH_ROWS:
                    await self._append_rows_async(dashboard, pending_rows)
                    pending_rows.clear()

        self.log_info(f"Carga completa {label}: {total_docs} documentos, {total_rows} linhas.")
        return total_rows

    async def _incremental_entity(
        self,
        sl,
        *,
        dashboard: SqlDatabase,
        entity: str,
        label: str,
        area_cod: str,
        sub_area_cod: str,
        builder: Callable[[dict[str, Any]], list[DocMovRow]],
        since_date: str,
    ) -> int:
        filter_str = f"(UpdateDate ge '{since_date}' or CreationDate ge '{since_date}')"
        self._set_task(f"A verificar {label} alterados desde {since_date}...")
        total_rows = 0
        header_batch: list[dict[str, Any]] = []

        async for header in sl.get_all(
            entity,
            select="DocEntry",
            filter=filter_str,
            order_by="DocEntry asc",
            page_size=200,
        ):
            header_batch.append(header)
            if len(header_batch) >= FULL_LOAD_BATCH_SIZE:
                total_rows += await self._replace_changed_docs(
                    sl,
                    dashboard=dashboard,
                    entity=entity,
                    area_cod=area_cod,
                    sub_area_cod=sub_area_cod,
                    builder=builder,
                    header_batch=header_batch,
                )
                header_batch.clear()

        if header_batch:
            total_rows += await self._replace_changed_docs(
                sl,
                dashboard=dashboard,
                entity=entity,
                area_cod=area_cod,
                sub_area_cod=sub_area_cod,
                builder=builder,
                header_batch=header_batch,
            )

        self.log_info(f"Incremental {label}: {total_rows} linhas afetadas.")
        return total_rows

    async def _replace_changed_docs(
        self,
        sl,
        *,
        dashboard: SqlDatabase,
        entity: str,
        area_cod: str,
        sub_area_cod: str,
        builder: Callable[[dict[str, Any]], list[DocMovRow]],
        header_batch: Sequence[dict[str, Any]],
    ) -> int:
        docs = await self._fetch_docs(sl, entity, header_batch)
        affected_rows = 0
        for doc in docs:
            order_id = self._to_int(doc.get("DocNum"))
            rows = builder(doc)
            await self._replace_document_rows_async(
                dashboard,
                area_cod=area_cod,
                sub_area_cod=sub_area_cod,
                order_id=order_id,
                rows=rows,
            )
            affected_rows += len(rows)
        return affected_rows

    async def _fetch_docs(self, sl, entity: str, headers: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        tasks = [sl.get_by_key(entity, int(header["DocEntry"])) for header in headers]
        return await asyncio.gather(*tasks)

    async def _append_rows_async(self, dashboard: SqlDatabase, rows: Sequence[DocMovRow]) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, dashboard.append_rows, list(rows))

    async def _replace_document_rows_async(
        self,
        dashboard: SqlDatabase,
        *,
        area_cod: str,
        sub_area_cod: str,
        order_id: int,
        rows: Sequence[DocMovRow],
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                dashboard.replace_document_rows,
                area_cod=area_cod,
                sub_area_cod=sub_area_cod,
                order_id=order_id,
                rows=list(rows),
            ),
        )

    def _map_goods_receipt(
        self,
        doc: dict[str, Any],
        purchase_order_cache: dict[int, str | None],
    ) -> list[DocMovRow]:
        if self._is_cancelled(doc):
            return []
        rows: list[DocMovRow] = []
        doc_type = self._doc_type_from_series(doc, fallback_prefix="RM")
        data_doc = self._parse_date(doc.get("DocDate"))
        partner_id = self._as_text(doc.get("CardCode"))
        order_id = self._to_int(doc.get("DocNum"))

        for line in doc.get("DocumentLines", []):
            item_id = self._as_text(line.get("ItemCode"))
            if not item_id:
                continue
            qty = self._to_decimal(line.get("Quantity"))
            if qty == 0:
                continue
            unit_price = self._resolve_unit_price(line)
            total_value = self._resolve_total_value(line, qty, unit_price)
            base_type = self._sap_base_doc_type(line.get("BaseType"))
            base_doc_num = self._resolve_source_doc_num_cached(
                purchase_order_cache,
                line.get("PoNum") or line.get("BaseRef") or line.get("BaseEntry"),
            )
            rows.append(
                DocMovRow(
                    area_doc="COMPRAS",
                    sub_area_cod="RECECAO",
                    partner_id=partner_id or None,
                    doc_type=doc_type,
                    order_id=order_id,
                    order_row=self._to_int(line.get("LineNum")),
                    item_id=item_id,
                    qty_doc=qty,
                    unit_price=unit_price,
                    tot_value=total_value,
                    data_doc=data_doc,
                    doc_type_ori=base_type,
                    order_id_ori=base_doc_num,
                    order_row_ori=self._nullable_int(line.get("BaseLine")),
                    project_id=self._nullable_text(line.get("ProjectCode")),
                )
            )
        return rows

    def _map_stock_transfer(self, doc: dict[str, Any]) -> list[DocMovRow]:
        if self._is_cancelled(doc):
            return []
        rows: list[DocMovRow] = []
        doc_type = self._doc_type_from_series(doc, fallback_prefix="TI")
        data_doc = self._parse_date(doc.get("DocDate"))
        order_id = self._to_int(doc.get("DocNum"))

        for line in doc.get("StockTransferLines", []):
            from_wh = self._as_text(line.get("FromWarehouseCode") or doc.get("FromWarehouse"))
            to_wh = self._as_text(line.get("WarehouseCode") or doc.get("ToWarehouse"))
            if not self._is_warehouse_200_flow(from_wh, to_wh):
                continue

            item_id = self._as_text(line.get("ItemCode"))
            if not item_id:
                continue
            sign = Decimal("-1") if from_wh == WAREHOUSE_200 and to_wh != WAREHOUSE_200 else Decimal("1")
            qty = self._to_decimal(line.get("Quantity")) * sign
            if qty == 0:
                continue
            unit_price = self._resolve_unit_price(line)
            total_value = self._resolve_total_value(line, abs(qty), unit_price) * sign
            ori_type, ori_id, ori_row = self._parse_origin_reference(
                line.get(ORIGIN_FIELD) or doc.get(ORIGIN_FIELD)
            )
            rows.append(
                DocMovRow(
                    area_doc="ABASTECIMENTO",
                    sub_area_cod="ABASTECIMENTO",
                    partner_id="",
                    doc_type=doc_type,
                    order_id=order_id,
                    order_row=self._to_int(line.get("LineNum")),
                    item_id=item_id,
                    qty_doc=qty,
                    unit_price=unit_price,
                    tot_value=total_value,
                    data_doc=data_doc,
                    doc_type_ori=ori_type,
                    order_id_ori=ori_id,
                    order_row_ori=ori_row,
                    project_id=self._nullable_text(line.get("ProjectCode")),
                )
            )
        return rows

    def _map_inventory_doc(self, doc: dict[str, Any], *, sign: Decimal) -> list[DocMovRow]:
        if self._is_cancelled(doc):
            return []
        rows: list[DocMovRow] = []
        doc_type = self._doc_type_from_series(doc, fallback_prefix="SM")
        data_doc = self._parse_date(doc.get("DocDate"))
        order_id = self._to_int(doc.get("DocNum"))

        for line in doc.get("DocumentLines", []):
            origin_value = line.get(ORIGIN_FIELD) or doc.get(ORIGIN_FIELD)
            ori_type, ori_id, ori_row = self._parse_origin_reference(origin_value)
            if not any((ori_type, ori_id, ori_row, line.get("ProjectCode"))):
                continue

            item_id = self._as_text(line.get("ItemCode"))
            if not item_id:
                continue
            qty = self._to_decimal(line.get("Quantity")) * sign
            if qty == 0:
                continue
            unit_price = self._resolve_unit_price(line)
            total_value = self._resolve_total_value(line, abs(qty), unit_price) * sign
            rows.append(
                DocMovRow(
                    area_doc="CONSUMO",
                    sub_area_cod="CONSUMO",
                    partner_id="",
                    doc_type=doc_type,
                    order_id=order_id,
                    order_row=self._to_int(line.get("LineNum")),
                    item_id=item_id,
                    qty_doc=qty,
                    unit_price=unit_price,
                    tot_value=total_value,
                    data_doc=data_doc,
                    doc_type_ori=ori_type,
                    order_id_ori=ori_id,
                    order_row_ori=ori_row,
                    project_id=self._nullable_text(line.get("ProjectCode")),
                )
            )
        return rows

    @staticmethod
    def _sync_checkpoint() -> tuple[datetime | None, bool]:
        source_key = DashboardMovementsIntegration._source_key_static()
        with get_session() as session:
            cursor = session.get(IntegrationCursor, DashboardMovementsIntegration.name)
            if cursor is None:
                return None, True
            if cursor.source_key != source_key:
                return None, True
            if not cursor.full_load_completed:
                return None, True
            return cursor.last_success_at, cursor.last_success_at is None

    def _save_sync_checkpoint(self) -> None:
        source_key = self._source_key()
        now = datetime.utcnow()
        with get_session() as session:
            row = session.get(IntegrationCursor, self.name)
            if row is None:
                row = IntegrationCursor(integration=self.name, source_key=source_key)
                session.add(row)
            row.source_key = source_key
            row.last_success_at = now
            row.full_load_completed = 1
            row.updated_at = now

    def _source_key(self) -> str:
        return self._source_key_static(
            self._settings.sap_sl_host,
            self._settings.sap_sl_company,
            self._settings.dashboard_db_name,
        )

    @staticmethod
    def _source_key_static(host: str | None = None, company: str | None = None, dashboard_db: str | None = None) -> str:
        host = host or ""
        company = company or ""
        dashboard_db = dashboard_db or ""
        return f"{host}|{company}|{dashboard_db}"

    @staticmethod
    def _doc_type_from_series(doc: dict[str, Any], *, fallback_prefix: str) -> str:
        series = DashboardMovementsIntegration._as_text(doc.get("SeriesName"))
        if series and any(char.isalpha() for char in series):
            return series
        series = DashboardMovementsIntegration._as_text(doc.get("SeriesString"))
        if series and any(char.isalpha() for char in series):
            return series
        series = DashboardMovementsIntegration._as_text(doc.get("Series"))
        if series and any(char.isalpha() for char in series):
            return series
        doc_date = DashboardMovementsIntegration._parse_date(doc.get("DocDate"))
        year = doc_date[:4] if doc_date else str(datetime.utcnow().year)
        return f"{fallback_prefix}{year[-2:]}"

    @staticmethod
    def _resolve_source_doc_num_cached(
        cache: dict[int, str | None],
        doc_entry: Any,
    ) -> str | None:
        raw = DashboardMovementsIntegration._nullable_text(doc_entry)
        if raw is None:
            return None
        try:
            key = int(Decimal(raw))
        except Exception:
            return raw
        if key in cache:
            return cache[key]
        cache[key] = raw
        return raw

    @staticmethod
    def _sap_base_doc_type(base_type: Any) -> str | None:
        mapping = {
            22: "OC",
            "22": "OC",
            202: "OF",
            "202": "OF",
        }
        return mapping.get(base_type, DashboardMovementsIntegration._nullable_text(base_type))

    @staticmethod
    def _parse_origin_reference(value: Any) -> tuple[str | None, str | None, int | None]:
        raw = DashboardMovementsIntegration._as_text(value)
        if not raw:
            return None, None, None
        parts = raw.split(".")
        if len(parts) != 3:
            return raw, None, None
        doc_type, order_id, order_row = (part.strip() for part in parts)
        return (
            doc_type or None,
            order_id or None,
            DashboardMovementsIntegration._nullable_int(order_row),
        )

    @staticmethod
    def _parse_date(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        raw = str(value or "").strip()
        if not raw:
            return datetime.utcnow().strftime("%Y-%m-%d")
        return raw[:10]

    @staticmethod
    def _resolve_unit_price(line: dict[str, Any]) -> Decimal:
        for key in ("UnitPrice", "Price", "StockPrice"):
            value = DashboardMovementsIntegration._to_decimal(line.get(key))
            if value != 0:
                return value
        return Decimal("0")

    @staticmethod
    def _resolve_total_value(line: dict[str, Any], qty: Decimal, unit_price: Decimal) -> Decimal:
        for key in ("LineTotal", "RowTotal", "GrossTotal"):
            value = DashboardMovementsIntegration._to_decimal(line.get(key))
            if value != 0:
                return value
        return qty * unit_price

    @staticmethod
    def _is_cancelled(doc: dict[str, Any]) -> bool:
        for key in ("Cancelled", "Canceled", "CancelStatus"):
            value = str(doc.get(key) or "").strip().lower()
            if value in {"tyes", "yes", "y", "cancelled", "canceled"}:
                return True
        return False

    @staticmethod
    def _is_warehouse_200_flow(from_wh: str, to_wh: str) -> bool:
        return from_wh == WAREHOUSE_200 or to_wh == WAREHOUSE_200

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        raw = str(value or "").strip()
        if not raw:
            return Decimal("0")
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _to_int(value: Any) -> int:
        return int(DashboardMovementsIntegration._to_decimal(value))

    @staticmethod
    def _nullable_int(value: Any) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        return DashboardMovementsIntegration._to_int(raw)

    @staticmethod
    def _as_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _nullable_text(value: Any) -> str | None:
        raw = DashboardMovementsIntegration._as_text(value)
        return raw or None
