from __future__ import annotations

from html import escape

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db.connection import db_cursor
from app.services.label_printing import (
    get_document_print_config,
    get_document_print_configs,
    _station_debug_text,
    blank_separator_label_zpl,
    collect_printer_host_epcs,
    inject_rfid_read_host_commands,
    open_printer_connection,
    parse_epcs_from_rfid_log_entries,
    read_printer_rfid_log_entries,
    reset_printer_rfid_log,
    render_label_template,
    resolve_label_template,
    print_volume_label,
    save_item_rfid_tag,
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
    rfid_tags: list[str] = []
    rfid_registered: int = 0
    rfid_warning: str = ""


class LabelPreviewResponse(BaseModel):
    config_file: str
    label_count: int
    preview_index: int
    preview_note: str = ""
    rendered_zpl: str
    preview_svg: str


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
                ISNULL(imc_label.CharacteristicValue, '') AS LabelItemDesc,
                ISNULL(imc_line1.CharacteristicValue, '') AS LabelLine1,
                ISNULL(imc_line2.CharacteristicValue, '') AS LabelLine2,
                ISNULL(im.ClientRef, '') AS RefCli,
                ISNULL(im.Barcode, '') AS Barcode,
                ISNULL(imc1.CharacteristicValue, 0) AS PVP,
                ISNULL(imc2.CharacteristicValue, 0) AS PVPSOCIO
            FROM ItemMaster im WITH (NOLOCK)
            LEFT JOIN ItemMasterCharacteristics imc_label WITH (NOLOCK)
              ON imc_label.ItemID = im.ItemID
             AND imc_label.CharacteristicID = 'ARTIGOETIQUETA'
            LEFT JOIN ItemMasterCharacteristics imc1 WITH (NOLOCK)
              ON imc1.ItemID = im.ItemID
             AND imc1.CharacteristicID = 'PRECOPVP'
            LEFT JOIN ItemMasterCharacteristics imc2 WITH (NOLOCK)
              ON imc2.ItemID = im.ItemID
             AND imc2.CharacteristicID = 'PRECOSOCIO'
            LEFT JOIN ItemMasterCharacteristics imc_line1 WITH (NOLOCK)
              ON imc_line1.ItemID = im.ItemID
             AND imc_line1.CharacteristicID = 'ARTIGOLINHA1'
            LEFT JOIN ItemMasterCharacteristics imc_line2 WITH (NOLOCK)
              ON imc_line2.ItemID = im.ItemID
             AND imc_line2.CharacteristicID = 'ARTIGOLINHA2'
            WHERE im.ItemID = ?
        """, (item_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Artigo nao encontrado")

    item_desc, item_subdesc = _label_description_lines(row[3], row[4], row[2], row[1])

    return LabelItemPrintData(
        item_id=row[0],
        item_desc=item_desc,
        item_subdesc=item_subdesc,
        client_ref=row[5],
        barcode=row[6],
        pvp=_format_price_value(row[7]),
        pvp_socio=_format_price_value(row[8]),
    )


def _label_description_text(characteristic_value: str, item_desc: str) -> str:
    custom_label = str(characteristic_value or "").strip()
    if custom_label:
        return custom_label
    return str(item_desc or "").strip()


def _label_description_lines(
    line1_value: str,
    line2_value: str,
    characteristic_value: str,
    item_desc: str,
) -> tuple[str, str]:
    line1 = str(line1_value or "").strip()
    line2 = str(line2_value or "").strip()
    if line1 or line2:
        return line1, line2

    label_description = _label_description_text(characteristic_value, item_desc)
    return _first_label_line(label_description), _second_label_line(label_description)


def _first_label_line(value: str) -> str:
    parts = str(value or "").strip().split()
    return " ".join(parts[:2]) if len(parts) > 2 else " ".join(parts)


def _second_label_line(value: str) -> str:
    parts = str(value or "").strip().split()
    return " ".join(parts[2:]) if len(parts) > 2 else ""


def _format_price_value(value: object) -> str:
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        return "0.00"
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return raw


def _size_display_map(lines: list["LabelPrintLine"]) -> dict[tuple[str, str, str, str, int | None], str]:
    unique_items: list[str] = []
    seen_items: set[str] = set()
    line_keys: list[tuple[str, str, str, str, int | None]] = []

    for line in lines:
        item_id = str(line.item_id or "").strip()
        if not item_id:
            continue

        item_key = item_id.upper()
        if item_key not in seen_items:
            seen_items.add(item_key)
            unique_items.append(item_id)

        line_keys.append(
            (
                item_key,
                str(line.color_id or "").strip().upper(),
                str(line.grid_id or "").strip().upper(),
                str(line.size_id or "").strip().upper(),
                line.order_row,
            )
        )

    if not unique_items:
        return {}

    placeholders = ",".join("?" for _ in unique_items)
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"""
            SELECT
                ISNULL(im.ItemID, '') AS ItemID,
                ISNULL(im.Dimensions, 0) AS Dimensions,
                ISNULL(imc.CharacteristicValue, '') AS CharacteristicSizeID
            FROM ItemMaster im WITH (NOLOCK)
            LEFT JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
              ON imc.ItemID = im.ItemID
             AND imc.CharacteristicID = 'SizeId'
            WHERE im.ItemID IN ({placeholders})
            """,
            unique_items,
        )
        item_rows = cursor.fetchall()

    item_meta: dict[str, dict[str, object]] = {}
    size_candidates: list[str] = []
    seen_size_candidates: set[str] = set()

    for row in item_rows:
        item_id = str(row[0] or "").strip().upper()
        size_id = str(row[2] or "").strip()
        item_meta[item_id] = {
            "dimensions": bool(row[1]),
            "characteristic_size_id": size_id,
        }
        if size_id:
            normalized_size = size_id.upper()
            if normalized_size not in seen_size_candidates:
                seen_size_candidates.add(normalized_size)
                size_candidates.append(size_id)

    for line in lines:
        size_id = str(line.size_id or "").strip()
        if size_id:
            normalized_size = size_id.upper()
            if normalized_size not in seen_size_candidates:
                seen_size_candidates.add(normalized_size)
                size_candidates.append(size_id)

    size_lookup: dict[str, str] = {}
    if size_candidates:
        placeholders = ",".join("?" for _ in size_candidates)
        with db_cursor() as (cursor, _):
            cursor.execute(
                f"""
                SELECT
                    ISNULL(SizeID, '') AS SizeID,
                    ISNULL(SizeSmallDescr, '') AS SizeSmallDescr
                FROM Sizes WITH (NOLOCK)
                WHERE SizeID IN ({placeholders})
                """,
                size_candidates,
            )
            for row in cursor.fetchall():
                key = str(row[0] or "").strip().upper()
                value = str(row[1] or "").strip()
                if key:
                    size_lookup[key] = value

    display_map: dict[tuple[str, str, str, str, int | None], str] = {}
    for line in lines:
        item_id = str(line.item_id or "").strip().upper()
        raw_line_size = str(line.size_id or "").strip()
        item_info = item_meta.get(item_id, {})
        if bool(item_info.get("dimensions")):
            resolved_size_id = raw_line_size
        else:
            resolved_size_id = str(item_info.get("characteristic_size_id") or "").strip() or raw_line_size

        resolved_key = (
            item_id,
            str(line.color_id or "").strip().upper(),
            str(line.grid_id or "").strip().upper(),
            str(line.size_id or "").strip().upper(),
            line.order_row,
        )
        display_map[resolved_key] = size_lookup.get(resolved_size_id.upper(), resolved_size_id) if resolved_size_id else ""

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


def _selected_printable_lines(lines: list["LabelPrintLine"]) -> list["LabelPrintLine"]:
    printable_lines = [line for line in lines if line.print_qty > 0]
    if not printable_lines:
        raise HTTPException(status_code=400, detail="Indica pelo menos uma quantidade de etiquetas")
    return printable_lines


def _is_slb_sem_preco(config_file: str) -> bool:
    normalized = str(config_file or "").strip().lower()
    return normalized == "slb-pecas-sempreco" or normalized == "slb-pecas-sempreco.zpl"


def _wrap_text_without_breaking_words(text: str, max_chars: int, max_lines: int) -> list[str]:
    words = str(text or "").strip().split()
    if not words or max_chars <= 0 or max_lines <= 0:
        return [""] * max(max_lines, 0)

    lines: list[str] = []
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip()
        if current_line and len(candidate) > max_chars and len(lines) < max_lines - 1:
            lines.append(current_line)
            current_line = word
            continue
        current_line = candidate if current_line else word

    lines.append(current_line)

    while len(lines) < max_lines:
        lines.append("")

    return lines[:max_lines]


def _split_sem_preco_description(item_desc: str, item_subdesc: str) -> tuple[str, str, str]:
    full_text = " ".join(part for part in (str(item_desc or "").strip(), str(item_subdesc or "").strip()) if part).strip()
    line1, line2, line3 = _wrap_text_without_breaking_words(full_text, max_chars=20, max_lines=3)
    return line1, line2, line3


def _label_values_for_lines(config_file: str, lines: list["LabelPrintLine"]) -> list[dict[str, str]]:
    printable_lines = _selected_printable_lines(lines)
    item_data = {line.item_id: item_print_data(line.item_id) for line in printable_lines}
    size_display_map = _size_display_map(printable_lines)
    barcode_display_map = _barcode_display_map(printable_lines)
    is_sem_preco = _is_slb_sem_preco(config_file)

    values_list: list[dict[str, str]] = []
    for line in printable_lines:
        data = item_data[line.item_id]
        size_key = (
            str(line.item_id or "").strip().upper(),
            str(line.color_id or "").strip().upper(),
            str(line.grid_id or "").strip().upper(),
            str(line.size_id or "").strip().upper(),
            line.order_row,
        )
        size_display = size_display_map.get(size_key) or line.size_id
        barcode_key = (
            str(line.item_id or "").strip().upper(),
            str(line.color_id or "").strip().upper(),
            str(line.grid_id or "").strip().upper(),
            str(line.size_id or "").strip().upper(),
        )
        barcode_display = barcode_display_map.get(barcode_key) or data.barcode or line.item_id
        item_desc = str(data.item_desc or line.item_desc or "").strip()
        item_subdesc = str(data.item_subdesc or "").strip()
        item_subsubdesc = ""
        if is_sem_preco:
            item_desc, item_subdesc, item_subsubdesc = _split_sem_preco_description(item_desc, item_subdesc)
        values = {
            "ITEM_ID": str(line.item_id or "").strip(),
            "ITEM_DESC": item_desc,
            "ITEM_SUBDESC": item_subdesc,
            "ITEM_SUBSUBDESC": item_subsubdesc,
            "CLIENT_REF": str(data.client_ref or "").strip(),
            "BARCODE": str(barcode_display or "").strip(),
            "PVP": str(data.pvp or "0").strip(),
            "PVP_SOCIO": str(data.pvp_socio or "0").strip(),
            "COLOR": str(line.color_id or "").strip(),
            "GRID": str(line.grid_id or "").strip(),
            "SIZE": str(size_display or "").strip(),
        }
        values["ITEM_DESC_FONT_SIZE_MAIN"] = str(_benfica_item_desc_font_size(values["ITEM_DESC"], 32))
        values["ITEM_DESC_FONT_SIZE_HORIZONTAL"] = str(_benfica_item_desc_font_size(values["ITEM_DESC"], 37))
        values["ITEM_DESC_FONT_SIZE_VERTICAL"] = str(_benfica_item_desc_font_size(values["ITEM_DESC"], 22))
        for _ in range(line.print_qty):
            values_list.append(values.copy())

    return values_list


def _render_labels_payload(template: str, values_list: list[dict[str, str]]) -> str:
    return "\n".join(render_label_template(template, values) for values in values_list)


def _barcode_preview_svg(value: str) -> str:
    barcode = str(value or "").strip() or "SEM-CODIGO"
    x = 0
    bars: list[str] = []
    for idx, char in enumerate(barcode):
        code = ord(char)
        for shift in range(7):
            bit = (code >> shift) & 1
            width = 2 if bit else 1
            bars.append(
                f'<rect x="{x}" y="0" width="{width}" height="120" fill="#111827" opacity="{0.96 if bit else 0.35}" rx="0.4" />'
            )
            x += width + 1
        if idx % 3 == 2:
            x += 1
    total_width = max(x, 120)
    return (
        f'<svg viewBox="0 0 {total_width} 140" preserveAspectRatio="none" aria-hidden="true">'
        + "".join(bars)
        + f'<text x="{total_width / 2}" y="136" text-anchor="middle" font-size="14" font-family="monospace" fill="#111827">{escape(barcode)}</text>'
        + '</svg>'
    )


def _benfica_item_desc_font_size(item_desc: str, default_size: int) -> int:
    return default_size


def _slb_preview_svg(values: dict[str, str], config_file: str) -> str:
    raw_item_desc = str(values.get("ITEM_DESC") or "")
    size_text = escape(values.get("SIZE") or "-")
    item_desc = escape(raw_item_desc)
    item_subdesc = escape(values.get("ITEM_SUBDESC") or "")
    client_ref = escape(values.get("CLIENT_REF") or "")
    pvp = escape(values.get("PVP") or "0")
    pvp_socio = escape(values.get("PVP_SOCIO") or "0")
    barcode_svg = _barcode_preview_svg(values.get("BARCODE") or values.get("ITEM_ID") or "")
    label_name = escape(config_file)
    item_desc_font_size = _benfica_item_desc_font_size(raw_item_desc, 30)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 280" role="img" aria-label="Pre-visualizacao da etiqueta {label_name}">
  <rect x="2" y="2" width="676" height="276" rx="18" fill="#fffdf8" stroke="#d6d3d1" stroke-width="3"/>
  <rect x="18" y="18" width="86" height="244" rx="12" fill="#f3f4f6" stroke="#d1d5db"/>
  <rect x="115" y="18" width="130" height="244" rx="12" fill="#ffffff" stroke="#d1d5db"/>
  <rect x="255" y="18" width="112" height="244" rx="12" fill="#ffffff" stroke="#d1d5db"/>
  <rect x="377" y="18" width="120" height="244" rx="12" fill="#ffffff" stroke="#d1d5db"/>
  <rect x="507" y="18" width="155" height="244" rx="12" fill="#ffffff" stroke="#d1d5db"/>

  <text x="61" y="142" text-anchor="middle" transform="rotate(-90 61 142)" font-size="18" font-weight="700" fill="#4b5563" letter-spacing="1.2">TAMANHO / SIZE</text>
  <text x="61" y="142" text-anchor="middle" transform="rotate(-90 61 142)" dy="52" font-size="62" font-weight="800" fill="#111827">{size_text}</text>

  <text x="180" y="140" text-anchor="middle" transform="rotate(-90 180 140)" font-size="{item_desc_font_size}" font-weight="700" fill="#111827">{item_desc}</text>
  <text x="212" y="140" text-anchor="middle" transform="rotate(-90 212 140)" font-size="22" fill="#4b5563">{item_subdesc}</text>

  <text x="311" y="140" text-anchor="middle" transform="rotate(-90 311 140)" font-size="38" font-weight="700" fill="#111827">{client_ref}</text>

  <text x="437" y="190" text-anchor="middle" transform="rotate(-90 437 190)" font-size="24" font-weight="700" fill="#6b7280">PVP</text>
  <text x="437" y="98" text-anchor="middle" transform="rotate(-90 437 98)" font-size="28" font-weight="800" fill="#111827">{pvp} €</text>

  <text x="468" y="190" text-anchor="middle" transform="rotate(-90 468 190)" font-size="24" font-weight="700" fill="#6b7280">SOCIO</text>
  <text x="468" y="88" text-anchor="middle" transform="rotate(-90 468 88)" font-size="28" font-weight="800" fill="#111827">{pvp_socio} €</text>

  <foreignObject x="528" y="38" width="114" height="192">
    <div xmlns="http://www.w3.org/1999/xhtml" style="width:114px;height:192px;transform:rotate(-90deg) translate(-192px, 0);transform-origin:top left;">
      {barcode_svg}
    </div>
  </foreignObject>
</svg>"""


def _slb_horizontal_preview_svg(values: dict[str, str], config_file: str) -> str:
    raw_item_desc = str(values.get("ITEM_DESC") or "")
    size_text = escape(values.get("SIZE") or "-")
    item_desc = escape(raw_item_desc)
    item_subdesc = escape(values.get("ITEM_SUBDESC") or "")
    client_ref = escape(values.get("CLIENT_REF") or "")
    pvp = escape(values.get("PVP") or "0")
    pvp_socio = escape(values.get("PVP_SOCIO") or "0")
    barcode_svg = _barcode_preview_svg(values.get("BARCODE") or values.get("ITEM_ID") or "")
    label_name = escape(config_file)
    item_desc_font_size = _benfica_item_desc_font_size(raw_item_desc, 20)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 280" role="img" aria-label="Pre-visualizacao horizontal da etiqueta {label_name}">
  <rect x="2" y="2" width="436" height="276" rx="18" fill="#fffdf8" stroke="#d6d3d1" stroke-width="3"/>

  <rect x="12" y="20" width="78" height="244" rx="12" fill="#f6f6f7" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="92" y="20" width="122" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="214" y="20" width="42" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="256" y="20" width="74" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="330" y="20" width="98" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>

  <text x="24" y="138" transform="rotate(-90 24 138)" font-size="14" font-weight="700" fill="#6b7280" letter-spacing=".8">TAMANHO / SIZE</text>
  <text x="52" y="170" text-anchor="middle" transform="rotate(-90 52 170)" font-size="54" font-weight="800" fill="#111827">{size_text}</text>

  <text x="122" y="146" text-anchor="middle" transform="rotate(-90 122 146)" font-size="{item_desc_font_size}" font-weight="700" fill="#111827">{item_desc}</text>
  <text x="158" y="146" text-anchor="middle" transform="rotate(-90 158 146)" font-size="18" fill="#6b7280">{item_subdesc}</text>

  <text x="235" y="142" text-anchor="middle" transform="rotate(-90 235 142)" font-size="22" font-weight="700" fill="#111827">{client_ref}</text>

  <text x="278" y="186" transform="rotate(-90 278 186)" text-anchor="start" font-size="17" font-weight="700" fill="#6b7280">PVP</text>
  <text x="278" y="108" transform="rotate(-90 278 108)" text-anchor="end" font-size="18" font-weight="800" fill="#111827">{pvp} €</text>

  <text x="306" y="194" transform="rotate(-90 306 194)" text-anchor="start" font-size="17" font-weight="700" fill="#6b7280">SOCIO</text>
  <text x="306" y="108" transform="rotate(-90 306 108)" text-anchor="end" font-size="18" font-weight="800" fill="#111827">{pvp_socio} €</text>

  <foreignObject x="342" y="42" width="74" height="196">
    <div xmlns="http://www.w3.org/1999/xhtml" style="width:74px;height:196px;display:flex;align-items:center;justify-content:center;">
      <div style="width:72px;height:132px;transform:rotate(-90deg);transform-origin:center;display:flex;align-items:center;justify-content:center;">
        {barcode_svg}
      </div>
    </div>
  </foreignObject>
</svg>"""


def _slb_sem_preco_preview_svg(values: dict[str, str], config_file: str) -> str:
    raw_item_desc = str(values.get("ITEM_DESC") or "")
    size_text = escape(values.get("SIZE") or "-")
    item_desc = escape(raw_item_desc)
    item_subdesc = escape(values.get("ITEM_SUBDESC") or "")
    item_subsubdesc = escape(values.get("ITEM_SUBSUBDESC") or "")
    client_ref = escape(values.get("CLIENT_REF") or "")
    barcode_svg = _barcode_preview_svg(values.get("BARCODE") or values.get("ITEM_ID") or "")
    label_name = escape(config_file)
    item_desc_font_size = _benfica_item_desc_font_size(raw_item_desc, 20)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 280" role="img" aria-label="Pre-visualizacao horizontal da etiqueta {label_name}">
  <rect x="2" y="2" width="436" height="276" rx="18" fill="#fffdf8" stroke="#d6d3d1" stroke-width="3"/>

  <rect x="12" y="20" width="78" height="244" rx="12" fill="#f6f6f7" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="92" y="20" width="146" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="238" y="20" width="62" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>
  <rect x="300" y="20" width="128" height="244" rx="12" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>

  <text x="24" y="138" transform="rotate(-90 24 138)" font-size="14" font-weight="700" fill="#6b7280" letter-spacing=".8">TAMANHO / SIZE</text>
  <text x="52" y="170" text-anchor="middle" transform="rotate(-90 52 170)" font-size="54" font-weight="800" fill="#111827">{size_text}</text>

  <text x="120" y="146" text-anchor="middle" transform="rotate(-90 120 146)" font-size="{item_desc_font_size}" font-weight="700" fill="#111827">{item_desc}</text>
  <text x="158" y="146" text-anchor="middle" transform="rotate(-90 158 146)" font-size="18" fill="#6b7280">{item_subdesc}</text>
  <text x="190" y="146" text-anchor="middle" transform="rotate(-90 190 146)" font-size="18" fill="#9ca3af">{item_subsubdesc}</text>

  <text x="268" y="142" text-anchor="middle" transform="rotate(-90 268 142)" font-size="22" font-weight="700" fill="#111827">{client_ref}</text>

  <foreignObject x="322" y="42" width="94" height="196">
    <div xmlns="http://www.w3.org/1999/xhtml" style="width:94px;height:196px;display:flex;align-items:center;justify-content:center;">
      <div style="width:92px;height:132px;transform:rotate(-90deg);transform-origin:center;display:flex;align-items:center;justify-content:center;">
        {barcode_svg}
      </div>
    </div>
  </foreignObject>
</svg>"""


def _fallback_preview_svg(values: dict[str, str], config_file: str) -> str:
    rows = [
        ("Template", config_file),
        ("Artigo", values.get("ITEM_ID") or ""),
        ("Descricao", values.get("ITEM_DESC") or ""),
        ("Subdescricao", values.get("ITEM_SUBDESC") or ""),
        ("Cliente", values.get("CLIENT_REF") or ""),
        ("Tamanho", values.get("SIZE") or ""),
        ("PVP", values.get("PVP") or ""),
        ("PVP Socio", values.get("PVP_SOCIO") or ""),
        ("Codigo barras", values.get("BARCODE") or ""),
    ]
    row_svg: list[str] = []
    y = 54
    for label, value in rows:
        row_svg.append(f'<text x="28" y="{y}" font-size="14" font-weight="700" fill="#4b5563">{escape(label)}</text>')
        row_svg.append(f'<text x="170" y="{y}" font-size="16" fill="#111827">{escape(str(value or "-"))}</text>')
        y += 28
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 280" role="img" aria-label="Pre-visualizacao da etiqueta">'
        '<rect x="2" y="2" width="676" height="276" rx="18" fill="#fffdf8" stroke="#d6d3d1" stroke-width="3"/>'
        '<text x="28" y="30" font-size="18" font-weight="800" fill="#111827">Pre-visualizacao da etiqueta</text>'
        + "".join(row_svg)
        + '</svg>'
    )


def _label_preview_svg(values: dict[str, str], config_file: str) -> str:
    normalized = str(config_file or "").strip().lower()
    if "slb-pecas-sempreco" in normalized:
        return _slb_sem_preco_preview_svg(values, config_file)
    if "slb-pecas-horizontal" in normalized:
        return _slb_horizontal_preview_svg(values, config_file)
    if normalized.startswith("slb-pecas"):
        return _slb_preview_svg(values, config_file)
    return _fallback_preview_svg(values, config_file)


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


@router.post("/preview", response_model=LabelPreviewResponse)
def preview_labels(req: LabelPrintRequest, request: Request):
    config = get_document_print_config(
        "ETIQ",
        "ETIQ",
        config_file=req.config_file,
        station_identifier=_station_identifier(request),
    )
    if not config:
        raise HTTPException(status_code=400, detail="Configuracao de impressao nao encontrada para a etiqueta selecionada")

    template_path = resolve_label_template(req.config_file)
    template = template_path.read_text(encoding="utf-8-sig")
    values_list = _label_values_for_lines(req.config_file, req.lines)
    payload = _render_labels_payload(template, values_list)
    preview_index = 1
    preview_note = ""
    if len(values_list) > 1:
        preview_note = f"A pre-visualizacao mostra a etiqueta 1 de {len(values_list)}."

    return LabelPreviewResponse(
        config_file=req.config_file,
        label_count=len(values_list),
        preview_index=preview_index,
        preview_note=preview_note,
        rendered_zpl=payload,
        preview_svg=_label_preview_svg(values_list[0], req.config_file),
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

    template_path = resolve_label_template(req.config_file)
    template = template_path.read_text(encoding="utf-8-sig")
    values_list = _label_values_for_lines(req.config_file, req.lines)
    total_labels = len(values_list)
    printable_lines = _selected_printable_lines(req.lines)
    expanded_lines: list[LabelPrintLine] = []
    for line in printable_lines:
        for _ in range(line.print_qty):
            expanded_lines.append(
                LabelPrintLine(
                    item_id=line.item_id,
                    item_desc=line.item_desc,
                    color_id=line.color_id,
                    grid_id=line.grid_id,
                    size_id=line.size_id,
                    order_num=line.order_num,
                    order_row=line.order_row,
                    print_qty=1,
                )
            )

    grouped_batches: list[list[tuple[LabelPrintLine, dict[str, str]]]] = []
    current_batch: list[tuple[LabelPrintLine, dict[str, str]]] = []
    current_item_id: str | None = None
    for line, values in zip(expanded_lines, values_list):
        normalized_item_id = str(line.item_id or "").strip().upper()
        if current_batch and normalized_item_id != current_item_id:
            grouped_batches.append(current_batch)
            current_batch = []
        current_batch.append((line, values))
        current_item_id = normalized_item_id
    if current_batch:
        grouped_batches.append(current_batch)

    rfid_tags: list[str] = []
    rfid_registered = 0
    rfid_errors: list[str] = []
    separator_labels = max(len(grouped_batches) - 1, 0)
    try:
        with open_printer_connection(printer_name) as printer_sock:
            with db_cursor() as (cursor, _):
                for batch_index, batch in enumerate(grouped_batches):
                    reset_printer_rfid_log(printer_name, sock=printer_sock)
                    batch_payload = "".join(
                        inject_rfid_read_host_commands(render_label_template(template, values))
                        for _, values in batch
                    )
                    send_raw_to_printer(printer_name, batch_payload, sock=printer_sock)

                    host_epcs, host_response = collect_printer_host_epcs(printer_sock, len(batch))
                    resolved_epcs = host_epcs
                    if len(resolved_epcs) < len(batch):
                        log_entries = read_printer_rfid_log_entries(printer_name, sock=printer_sock)
                        log_epcs = parse_epcs_from_rfid_log_entries(log_entries)
                        if len(log_epcs) >= len(batch):
                            resolved_epcs = log_epcs[:len(batch)]
                        else:
                            combined: list[str] = []
                            seen: set[str] = set()
                            for epc in host_epcs + log_epcs:
                                normalized = str(epc or "").strip().upper()
                                if normalized and normalized not in seen:
                                    seen.add(normalized)
                                    combined.append(normalized)
                            resolved_epcs = combined
                        if len(resolved_epcs) < len(batch):
                            rfid_errors.append(
                                f"{batch[0][0].item_id}: esperados {len(batch)} EPC(s), recebidos {len(resolved_epcs)}. Host='{host_response}'"
                            )

                    for (line, _), epc in zip(batch, resolved_epcs):
                        rfid_tags.append(epc)
                        try:
                            if save_item_rfid_tag(
                                line.item_id,
                                epc,
                                color_id=line.color_id,
                                size_id=line.size_id,
                                order_num=line.order_num,
                                cursor=cursor,
                            ):
                                rfid_registered += 1
                        except RuntimeError as exc:
                            rfid_errors.append(f"{line.item_id}: {exc}")

                    if batch_index < len(grouped_batches) - 1:
                        send_raw_to_printer(printer_name, blank_separator_label_zpl(), sock=printer_sock)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if separator_labels:
        rfid_errors.append(f"Foram impressas {separator_labels} etiqueta(s) em branco para separar artigos.")

    return LabelPrintResponse(
        labels_printed=total_labels,
        printer=printer_name,
        rfid_tags=rfid_tags,
        rfid_registered=rfid_registered,
        rfid_warning=" | ".join(rfid_errors),
    )
