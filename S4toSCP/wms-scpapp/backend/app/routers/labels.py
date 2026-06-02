from __future__ import annotations

import socket
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.connection import db_cursor
from app.settings import settings

router = APIRouter(prefix="/labels", tags=["Etiquetas RFID"])


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
def print_configs():
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT ISNULL(DocPrintDescr, '') AS DocPrintDescr, ISNULL(DocPrintFile, '') AS DocPrintFile
            FROM DocumentPrintConfig
            WHERE Area = 'ETIQ' AND DocType = 'ETIQ'
            ORDER BY DocPrintDescr
        """)
        rows = cursor.fetchall()

    return [
        LabelPrintConfig(description=row[0], file_name=row[1])
        for row in rows
    ]


@router.post("/print", response_model=LabelPrintResponse)
def print_labels(req: LabelPrintRequest):
    printer_ip = (settings.ZEBRA_PRINTER_IP or "").strip()
    if not printer_ip or printer_ip == "0.0.0.0":
        raise HTTPException(
            status_code=400,
            detail="Configura ZEBRA_PRINTER_IP no .env com o IP da impressora Zebra",
        )

    printable_lines = [line for line in req.lines if line.print_qty > 0]
    total_labels = sum(line.print_qty for line in printable_lines)
    if not printable_lines or total_labels <= 0:
        raise HTTPException(status_code=400, detail="Indica pelo menos uma quantidade de etiquetas")

    template_path = _resolve_label_template(req.config_file)
    template = template_path.read_text(encoding="utf-8-sig")

    item_data = {line.item_id: item_print_data(line.item_id) for line in printable_lines}
    zpl_parts: list[str] = []
    for line in printable_lines:
        data = item_data[line.item_id]
        values = {
            "ITEM_ID": line.item_id,
            "ITEM_DESC": data.item_desc or line.item_desc,
            "ITEM_SUBDESC": data.item_subdesc,
            "CLIENT_REF": data.client_ref,
            "BARCODE": data.barcode or line.item_id,
            "PVP": data.pvp,
            "PVP_SOCIO": data.pvp_socio,
            "COLOR": line.color_id,
            "GRID": line.grid_id,
            "SIZE": line.size_id,
        }
        rendered = _render_label_template(template, values)
        zpl_parts.extend(rendered for _ in range(line.print_qty))

    payload = "\n".join(zpl_parts).encode("utf-8")
    try:
        with socket.create_connection((printer_ip, settings.ZEBRA_PRINTER_PORT), timeout=8) as sock:
            sock.sendall(payload)
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nao foi possivel enviar para a impressora {printer_ip}:{settings.ZEBRA_PRINTER_PORT}: {exc}",
        ) from exc

    return LabelPrintResponse(
        labels_printed=total_labels,
        printer=f"{printer_ip}:{settings.ZEBRA_PRINTER_PORT}",
    )


def _resolve_label_template(file_name: str) -> Path:
    requested = Path(file_name.strip())
    if not requested.name or requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(status_code=400, detail="Ficheiro de etiqueta invalido")

    template_dir = Path(settings.LABEL_TEMPLATE_DIR)
    if not template_dir.is_absolute():
        template_dir = Path.cwd() / template_dir
    template_dir = template_dir.resolve()

    candidates = [template_dir / requested]
    if not requested.suffix:
        candidates.extend(template_dir / f"{requested.name}{suffix}" for suffix in (".zpl", ".prn", ".txt"))

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and template_dir in resolved.parents:
            return resolved

    raise HTTPException(status_code=404, detail=f"Template de etiqueta nao encontrado: {file_name}")


def _render_label_template(template: str, values: dict[str, object]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", _zpl_field_value(value))
    return rendered


def _zpl_field_value(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("^", " ").replace("~", " ").strip()
