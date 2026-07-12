from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db.connection import db_cursor
from app.services.label_printing import (
    get_document_print_config,
    get_document_print_configs,
    _station_debug_text,
    render_label_template,
    resolve_label_template,
    print_volume_label,
    send_raw_to_printer,
)

router = APIRouter(prefix="/labels", tags=["Etiquetas RFID"])


def _station_identifier(request: Request) -> str:
    return str(request.headers.get("X-Station-Identifier") or "").strip()


class LabelItem(BaseModel):
    item_id: str
    item_desc: str
    dimensions: bool = False


class LabelVariation(BaseModel):
    item_id: str
    color_id: str = ""
    grid_id: str = ""
    size_id: str = ""
    order_num: int = 0


class LabelDocType(BaseModel):
    doc_type: str
    doc_descr: str
    partner_type: str = ""


class LabelDocument(BaseModel):
    doc_type: str
    order_id: int
    client_id: str = ""
    client_name: str = ""


class LabelDocumentLine(BaseModel):
    order_row: int
    item_id: str
    item_desc: str = ""
    qty_ord: float = 0
    color_id: str = ""
    grid_id: str = ""
    size_id: str = ""
    has_dimensions: bool = False


class LabelPrintConfig(BaseModel):
    description: str
    file_name: str


class VolumeLabelReprintRequest(BaseModel):
    config_file: str


class VolumeLabelReprintResponse(BaseModel):
    printed: bool
    printer_message: str


class LabelPrintLine(BaseModel):
    item_id: str
    item_desc: str = ""
    color_id: str = ""
    grid_id: str = ""
    size_id: str = ""
    order_num: int = 0
    order_row: int | None = None
    print_qty: int = Field(default=0, ge=0)


class LabelPrintRequest(BaseModel):
    config_file: str
    lines: list[LabelPrintLine]


class LabelPrintResponse(BaseModel):
    labels_printed: int
    printer: str


class LabelItemPrintData(BaseModel):
    item_id: str
    item_desc: str = ""
    item_subdesc: str = ""
    client_ref: str = ""
    barcode: str = ""
    pvp: str = "0"
    pvp_socio: str = "0"


def _unique_print_configs(rows: list[tuple[str, str]]) -> list[LabelPrintConfig]:
    seen: set[str] = set()
    configs: list[LabelPrintConfig] = []
    for description, file_name in rows:
        normalized_file = str(file_name or "").strip()
        if not normalized_file:
            continue
        dedupe_key = normalized_file.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        configs.append(
            LabelPrintConfig(
                description=str(description or normalized_file).strip(),
                file_name=normalized_file,
            )
        )
    return configs


@router.get("/items", response_model=list[LabelItem])
def search_items(search: str = Query(default="", min_length=0), limit: int = Query(default=30, ge=1, le=100)):
    term = f"%{search.strip()}%"
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TOP (?)
                ItemID,
                ISNULL(ItemDesc, '') AS ItemDesc,
                ISNULL(Dimensions, 0) AS Dimensions
            FROM ItemMaster
            WHERE (? = '%%' OR ItemID LIKE ? OR ISNULL(ItemDesc, '') LIKE ?)
            ORDER BY ItemID
        """, (limit, term, term, term))
        rows = cursor.fetchall()

    return [
        LabelItem(item_id=row[0], item_desc=row[1], dimensions=bool(row[2]))
        for row in rows
    ]


@router.get("/items/{item_id}/variations", response_model=list[LabelVariation])
def item_variations(item_id: str):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                ItemID,
                ISNULL(ColorID, '') AS ColorID,
                ISNULL(GridID, '') AS GridID,
                ISNULL(SizeID, '') AS SizeID,
                ISNULL(OrderNum, 0) AS OrderNum
            FROM ItemMasterDim
            WHERE ItemID = ?
            ORDER BY ISNULL(OrderNum, 0), ColorID, GridID, SizeID
        """, (item_id,))
        rows = cursor.fetchall()

    return [
        LabelVariation(
            item_id=row[0],
            color_id=row[1],
            grid_id=row[2],
            size_id=row[3],
            order_num=int(row[4] or 0),
        )
        for row in rows
    ]


@router.get("/items/{item_id}/print-data", response_model=LabelItemPrintData)
def item_print_data(item_id: str):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT
                im.ItemID,
                ISNULL(im.ItemDesc, '') AS ItemDesc,
                ISNULL(im.ClientRef, '') AS RefCli,
                ISNULL(im.Barcode, '') AS Barcode,
                ISNULL(imc1.CharacteristicValue, 0) AS PVP,
                ISNULL(imc2.CharacteristicValue, 0) AS PVPSOCIO
            FROM ItemMaster im WITH (NOLOCK)
            LEFT JOIN ItemMasterCharacteristics imc1 WITH (NOLOCK)
              ON imc1.ItemID = im.ItemID
             AND imc1.CharacteristicID = 'PRECOPVP'
            LEFT JOIN ItemMasterCharacteristics imc2 WITH (NOLOCK)
              ON imc2.ItemID = im.ItemID
             AND imc2.CharacteristicID = 'PRECOSOCIO'
            WHERE im.ItemID = ?
        """, (item_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Artigo nao encontrado")

    return LabelItemPrintData(
        item_id=row[0],
        item_desc=_first_label_line(row[1]),
        item_subdesc=_second_label_line(row[1]),
        client_ref=row[2],
        barcode=row[3],
        pvp=str(row[4] or 0),
        pvp_socio=str(row[5] or 0),
    )


def _first_label_line(value: str) -> str:
    parts = str(value or "").strip().split()
    return " ".join(parts[:2]) if len(parts) > 2 else " ".join(parts)


def _second_label_line(value: str) -> str:
    parts = str(value or "").strip().split()
    return " ".join(parts[2:]) if len(parts) > 2 else ""


def _size_display_map(size_ids: list[str]) -> dict[str, str]:
    normalized = []
    seen = set()
    for size_id in size_ids:
        text = str(size_id or "").strip()
        if not text:
            continue
        upper = text.upper()
        if upper in seen:
            continue
        seen.add(upper)
        normalized.append(text)

    if not normalized:
        return {}

    placeholders = ",".join("?" for _ in normalized)
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"""
            SELECT
                ISNULL(SizeID, '') AS SizeID,
                ISNULL(SizeSmallDescr, '') AS SizeSmallDescr
            FROM Sizes
            WHERE SizeID IN ({placeholders})
            """,
            normalized,
        )
        rows = cursor.fetchall()

    display_map: dict[str, str] = {}
    for row in rows:
        key = str(row[0] or "").strip().upper()
        value = str(row[1] or "").strip()
        if key:
            display_map[key] = value
    return display_map


def _barcode_display_map(lines: list["LabelPrintLine"]) -> dict[tuple[str, str, str, str], str]:
    unique_items: list[str] = []
    seen_items: set[str] = set()
    variant_keys: list[tuple[str, str, str, str]] = []
    seen_variants: set[tuple[str, str, str, str]] = set()

    for line in lines:
        item_id = str(line.item_id or "").strip()
        if not item_id:
            continue

        item_key = item_id.upper()
        if item_key not in seen_items:
            seen_items.add(item_key)
            unique_items.append(item_id)

        variant_key = (
            item_id.upper(),
            str(line.color_id or "").strip().upper(),
            str(line.grid_id or "").strip().upper(),
            str(line.size_id or "").strip().upper(),
        )
        if variant_key not in seen_variants:
            seen_variants.add(variant_key)
            variant_keys.append(variant_key)

    if not unique_items:
        return {}

    placeholders = ",".join("?" for _ in unique_items)
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"""
            SELECT
                ISNULL(ItemID, '') AS ItemID,
                ISNULL(Dimensions, 0) AS Dimensions,
                ISNULL(Barcode, '') AS Barcode
            FROM ItemMaster
            WHERE ItemID IN ({placeholders})
            """,
            unique_items,
        )
        item_rows = cursor.fetchall()

    item_meta: dict[str, dict[str, object]] = {}
    for row in item_rows:
        item_meta[str(row[0] or "").strip().upper()] = {
            "dimensions": bool(row[1]),
            "barcode": str(row[2] or "").strip(),
        }

    dimensioned_keys = [
        key for key in variant_keys
        if bool(item_meta.get(key[0], {}).get("dimensions"))
    ]

    variant_barcodes: dict[tuple[str, str, str, str], str] = {}
    if dimensioned_keys:
        conditions = " OR ".join("(ItemID = ? AND ColorID = ? AND GridID = ? AND SizeID = ?)" for _ in dimensioned_keys)
        params: list[str] = []
        for item_id, color_id, grid_id, size_id in dimensioned_keys:
            params.extend([item_id, color_id, grid_id, size_id])

        with db_cursor() as (cursor, _):
            cursor.execute(
                f"""
                SELECT
                    ISNULL(ItemID, '') AS ItemID,
                    ISNULL(ColorID, '') AS ColorID,
                    ISNULL(GridID, '') AS GridID,
                    ISNULL(SizeID, '') AS SizeID,
                    ISNULL(Code, '') AS Code
                FROM ItemMasterDim
                WHERE {conditions}
                """,
                params,
            )
            for row in cursor.fetchall():
                key = (
                    str(row[0] or "").strip().upper(),
                    str(row[1] or "").strip().upper(),
                    str(row[2] or "").strip().upper(),
                    str(row[3] or "").strip().upper(),
                )
                variant_barcodes[key] = str(row[4] or "").strip()

    result: dict[tuple[str, str, str, str], str] = {}
    for key in variant_keys:
        item_info = item_meta.get(key[0], {})
        fallback = str(item_info.get("barcode") or "").strip()
        if bool(item_info.get("dimensions")):
            result[key] = variant_barcodes.get(key) or fallback
        else:
            result[key] = fallback
    return result


@router.get("/document-types", response_model=list[LabelDocType])
def document_types():
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT DocType, ISNULL(DocDesc, '') AS DocDescr, ISNULL(PartnerType, '') AS PartnerType
            FROM DocumentConfig
            WHERE ISNULL(Active, 1) = 1
            ORDER BY DocType
        """)
        rows = cursor.fetchall()

    return [
        LabelDocType(doc_type=row[0], doc_descr=row[1], partner_type=row[2])
        for row in rows
    ]


@router.get("/documents", response_model=list[LabelDocument])
def documents(
    doc_type: str = Query(...),
    search: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    term = f"%{search.strip()}%"
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TOP (?)
                co.DocType,
                co.OrderID,
                ISNULL(co.ClientID, '') AS ClientID,
                ISNULL(bp.PartnerName, '') AS ClientName
            FROM ClientOrders co
            JOIN DocumentConfig dc ON dc.DocType = co.DocType
            LEFT JOIN BusinessPartners bp
              ON bp.PartnerID = co.ClientID
             AND (ISNULL(dc.PartnerType, '') = '' OR bp.PartnerType = dc.PartnerType)
            WHERE co.DocType = ?
              AND (
                    ? = '%%'
                 OR CAST(co.OrderID AS varchar(30)) LIKE ?
                 OR ISNULL(co.ClientID, '') LIKE ?
                 OR ISNULL(bp.PartnerName, '') LIKE ?
              )
            ORDER BY co.OrderID DESC
        """, (limit, doc_type, term, term, term, term))
        rows = cursor.fetchall()

    return [
        LabelDocument(doc_type=row[0], order_id=row[1], client_id=row[2], client_name=row[3])
        for row in rows
    ]


@router.get("/documents/{doc_type}/{order_id}/lines", response_model=list[LabelDocumentLine])
def document_lines(doc_type: str, order_id: int):
    with db_cursor() as (cursor, _):
        cursor.execute("""
            IF EXISTS (
                SELECT 1
                FROM ClientOrdersDim
                WHERE DocType = ? AND OrderID = ?
            )
            BEGIN
                SELECT
                    cod.OrderRow,
                    cod.ItemID,
                    ISNULL(im.ItemDesc, '') AS ItemDesc,
                    ISNULL(codim.QtyOrd, 0) AS QtyOrd,
                    ISNULL(codim.ColorID, '') AS ColorID,
                    ISNULL(codim.GridID, '') AS GridID,
                    ISNULL(codim.SizeID, '') AS SizeID,
                    CAST(1 AS bit) AS HasDimensions
                FROM ClientOrdersDim codim
                JOIN ClientOrderDetails cod
                  ON cod.DocType = codim.DocType
                 AND cod.OrderID = codim.OrderID
                 AND cod.OrderRow = codim.OrderRow
                LEFT JOIN ItemMaster im ON im.ItemID = cod.ItemID
                WHERE codim.DocType = ? AND codim.OrderID = ?
                ORDER BY cod.OrderRow, codim.ColorID, codim.SizeID
            END
            ELSE
            BEGIN
                SELECT
                    cod.OrderRow,
                    cod.ItemID,
                    ISNULL(im.ItemDesc, '') AS ItemDesc,
                    ISNULL(cod.QtyOrd, 0) AS QtyOrd,
                    ISNULL(cod.ColorID, '') AS ColorID,
                    '' AS GridID,
                    '' AS SizeID,
                    CAST(0 AS bit) AS HasDimensions
                FROM ClientOrderDetails cod
                LEFT JOIN ItemMaster im ON im.ItemID = cod.ItemID
                WHERE cod.DocType = ? AND cod.OrderID = ?
                ORDER BY cod.OrderRow
            END
        """, (doc_type, order_id, doc_type, order_id, doc_type, order_id))
        rows = cursor.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Documento sem linhas para etiquetas")

    return [
        LabelDocumentLine(
            order_row=int(row[0]),
            item_id=row[1],
            item_desc=row[2],
            qty_ord=float(row[3] or 0),
            color_id=row[4],
            grid_id=row[5],
            size_id=row[6],
            has_dimensions=bool(row[7]),
        )
        for row in rows
    ]


@router.get("/print-configs", response_model=list[LabelPrintConfig])
def print_configs(request: Request):
    configs = get_document_print_configs("ETIQ", "ETIQ", station_identifier=_station_identifier(request))
    return _unique_print_configs([
        (
            str(config.get("DocPrintDescr") or config.get("DocPrintFile") or "").strip(),
            str(config.get("DocPrintFile") or "").strip(),
        )
        for config in configs
    ])


@router.get("/volume-print-configs", response_model=list[LabelPrintConfig])
def volume_print_configs(request: Request):
    configs = get_document_print_configs("VOLUMES", "CX", station_identifier=_station_identifier(request))
    return _unique_print_configs([
        (
            str(config.get("DocPrintDescr") or config.get("DocPrintFile") or "").strip(),
            str(config.get("DocPrintFile") or "").strip(),
        )
        for config in configs
    ])


@router.post("/volumes/{vol_num}/reprint", response_model=VolumeLabelReprintResponse)
def reprint_volume_label(vol_num: int, req: VolumeLabelReprintRequest, request: Request):
    if not str(req.config_file or "").strip():
        raise HTTPException(status_code=400, detail="Seleciona o tipo de etiqueta da caixa")

    result = print_volume_label(
        vol_num,
        config_file=req.config_file,
        require_direct_print=False,
        station_identifier=_station_identifier(request),
    )
    if not result["printed"]:
        raise HTTPException(status_code=400, detail=str(result["message"] or "Nao foi possivel reimprimir a etiqueta"))

    return VolumeLabelReprintResponse(
        printed=True,
        printer_message=str(result["message"] or ""),
    )


@router.post("/print", response_model=LabelPrintResponse)
def print_labels(req: LabelPrintRequest, request: Request):
    config = get_document_print_config(
        "ETIQ",
        "ETIQ",
        config_file=req.config_file,
        station_identifier=_station_identifier(request),
    )
    if not config:
        raise HTTPException(status_code=400, detail="Configuracao de impressao nao encontrada para a etiqueta selecionada")

    printer_name = str(config.get("PrinterName") or "").strip()
    if not printer_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "PrinterName nao configurado em DocumentPrintConfig para esta etiqueta. "
                f"{_station_debug_text(_station_identifier(request))}"
            ),
        )

    printable_lines = [line for line in req.lines if line.print_qty > 0]
    total_labels = sum(line.print_qty for line in printable_lines)
    if not printable_lines or total_labels <= 0:
        raise HTTPException(status_code=400, detail="Indica pelo menos uma quantidade de etiquetas")

    template_path = resolve_label_template(req.config_file)
    template = template_path.read_text(encoding="utf-8-sig")

    item_data = {line.item_id: item_print_data(line.item_id) for line in printable_lines}
    size_display_map = _size_display_map([line.size_id for line in printable_lines])
    barcode_display_map = _barcode_display_map(printable_lines)
    zpl_parts: list[str] = []
    for line in printable_lines:
        data = item_data[line.item_id]
        size_display = size_display_map.get(str(line.size_id or "").strip().upper()) or line.size_id
        barcode_key = (
            str(line.item_id or "").strip().upper(),
            str(line.color_id or "").strip().upper(),
            str(line.grid_id or "").strip().upper(),
            str(line.size_id or "").strip().upper(),
        )
        barcode_display = barcode_display_map.get(barcode_key) or data.barcode or line.item_id
        values = {
            "ITEM_ID": line.item_id,
            "ITEM_DESC": data.item_desc or line.item_desc,
            "ITEM_SUBDESC": data.item_subdesc,
            "CLIENT_REF": data.client_ref,
            "BARCODE": barcode_display,
            "PVP": data.pvp,
            "PVP_SOCIO": data.pvp_socio,
            "COLOR": line.color_id,
            "GRID": line.grid_id,
            "SIZE": size_display,
        }
        rendered = render_label_template(template, values)
        zpl_parts.extend(rendered for _ in range(line.print_qty))

    payload = "\n".join(zpl_parts)
    try:
        send_raw_to_printer(printer_name, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return LabelPrintResponse(
        labels_printed=total_labels,
        printer=printer_name,
    )
