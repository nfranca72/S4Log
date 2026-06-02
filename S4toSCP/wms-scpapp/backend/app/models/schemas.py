from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date


# ── CSV Preview ────────────────────────────────────────────────────────────────

class CSVHeader(BaseModel):
    doc_num: str
    delivery_date: str
    ref_supplier: str
    client_code_csv: str
    num_boxes: int
    total_qty: int
    value: float

class CSVRow(BaseModel):
    box_barcode: str
    style_code: str
    color_code: str
    size: str
    ean: str
    country: str
    qty_box: int
    qty_total: int
    season_desc: str
    item_id: str          # MC-style-color-size (gerado)
    exists_in_db: Optional[bool] = None

class CSVPreview(BaseModel):
    header: CSVHeader
    rows: list[CSVRow]
    total_boxes: int
    total_qty: int
    total_articles: int
    new_articles: int
    existing_articles: int
    warnings: list[str] = []
    packings: Optional[list["CSVPreview"]] = None


# ── Artigos ────────────────────────────────────────────────────────────────────

class ItemCreate(BaseModel):
    item_id: str
    item_desc: str
    ean: str
    country: str

class ItemCheckResult(BaseModel):
    item_id: str
    exists: bool


# ── Clientes ───────────────────────────────────────────────────────────────────

class Client(BaseModel):
    client_id: str
    client_name: str


# ── Packing List ───────────────────────────────────────────────────────────────

class PackingCreateRequest(BaseModel):
    client_id:      str
    csv_rows:       list[CSVRow]
    header:         CSVHeader
    escp_order_id:  Optional[int] = None
    packings:       Optional[list["PackingCreateRequest"]] = None

class PackingCreated(BaseModel):
    order_id: int
    client_id: str
    total_qty: int
    total_boxes: int
    total_lines: int
    qty_match: bool       # confirma se qtd CSV == qtd criada no packing


# ── Resultado importação ───────────────────────────────────────────────────────

class ImportResult(BaseModel):
    items_created: int
    items_skipped: int
    packing: Optional[PackingCreated] = None
    packings: list[PackingCreated] = []
    total_packings: int = 1
    warnings: list[str] = []


# ── Módulo 2 — Receção ─────────────────────────────────────────────────────────

class PackingListSummary(BaseModel):
    order_id:       int
    client_id:      str
    delivery_date:  Optional[str]
    obs:            Optional[str]
    total_qty:      int
    qty_received:   int
    total_boxes:    int
    verified_boxes: int
    status:         str   # pendente | parcial | conferido


class BoxSummary(BaseModel):
    vol_num:      int
    barcode:      str
    status:       str   # pendente | parcial | conferida | incidencia
    total_items:  int
    qty_expected: int
    qty_received: int = 0


class BoxItem(BaseModel):
    vol_item_number: int
    item_id:         str
    item_desc:       str
    qty_expected:    int
    qty_read:        int
    color_id:        str
    size_id:         str
    country:         str


class BoxDetail(BaseModel):
    vol_num:  int
    barcode:  str
    verified: bool
    status:   str
    order_id: int
    items:    list[BoxItem]


class WarehouseInfo(BaseModel):
    wh_id:   int
    wh_desc: str


class LocationInfo(BaseModel):
    location_id:   str
    location_desc: str


class ConfirmBoxRequest(BaseModel):
    wh_id:            int
    location_id:      str
    item_quantities:  dict[str, int]   # {item_id: qty_read}
    escp_order_id:    Optional[int] = None
    rfid_tags:        list[str] = []   # TAGs RFID lidas neste ciclo
    item_tags:        dict[str, list[str]] = {}  # {item_id: [epc1, epc2]}


class ConfirmBoxResult(BaseModel):
    success:      bool
    has_incident: bool = False
    message:      str = ''
    order_id:     Optional[int] = None


class CancelBoxConfirmationResult(BaseModel):
    success:  bool
    message:  str = ''
    order_id: Optional[int] = None


# ── Módulo 1B — Encomenda ESCP ─────────────────────────────────────────────────

class OrderRow(BaseModel):
    so_number:    str
    neg_dot:      str
    po_number:    str
    style_color:  str
    codigo_giaf:  str
    descricao:    str
    tamanho:      str
    quantidade:   int
    ship_to:      str
    nota_giaf:    str
    item_id:      str
    exists_in_db: Optional[bool] = None


class OrderPreview(BaseModel):
    rows:         list[OrderRow]
    total_lines:  int
    total_qty:    int
    unique_items: int
    po_numbers:   list[str]
    new_items:    int = 0
    existing_items: int = 0


class OrderItemCheck(BaseModel):
    item_id: str
    exists:  bool


class EscpOrderSummary(BaseModel):
    order_id:    int
    client_id:   str
    order_date:  Optional[str]
    obs:         Optional[str]
    total_qty:   int
    total_lines: int


class EscpMergeDiff(BaseModel):
    order_id:  int
    added:     list[dict]
    changed:   list[dict]
    unchanged: int


class EscpCreateRequest(BaseModel):
    client_id: str
    obs:       str = ''
    rows:      list[OrderRow]


class EscpMergeApplyRequest(BaseModel):
    order_id:       int
    rows_to_add:    list[OrderRow]
    rows_to_update: list[dict]
