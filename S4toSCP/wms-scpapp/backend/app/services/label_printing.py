from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.db.connection import db_cursor
from app.settings import settings


def resolve_label_template(file_name: str) -> Path:
    requested = Path((file_name or "").strip())
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


def render_label_template(template: str, values: dict[str, object]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", zpl_field_value(value))
    return rendered


def zpl_field_value(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("^", " ").replace("~", " ").strip()


def send_raw_to_printer(printer_name: str, payload: str, port: int | None = None) -> None:
    target = (printer_name or "").strip()
    if not target:
        raise RuntimeError("PrinterName nao configurado em DocumentPrintConfig")

    printer_port = int(port or settings.ZEBRA_PRINTER_PORT or 9100)
    try:
        with socket.create_connection((target, printer_port), timeout=8) as sock:
            sock.sendall(payload.encode("utf-8"))
    except OSError as exc:
        raise RuntimeError(
            f"Nao foi possivel enviar para a impressora {target}:{printer_port}: {exc}"
        ) from exc


def get_document_print_configs(area: str, doc_type: str) -> list[dict[str, Any]]:
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT *
            FROM DocumentPrintConfig
            WHERE Area = ? AND DocType = ?
            ORDER BY ISNULL(DocPrintDescr, ''), ISNULL(DocPrintFile, '')
            """,
            (area, doc_type),
        )
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [
            {column: row[idx] for idx, column in enumerate(columns)}
            for row in rows
        ]


def get_document_print_config(area: str, doc_type: str, config_file: str | None = None) -> dict[str, Any] | None:
    configs = get_document_print_configs(area, doc_type)
    if config_file:
        requested = str(config_file).strip().lower()
        for config in configs:
            if str(config.get("DocPrintFile") or "").strip().lower() == requested:
                return config
        return None
    return configs[0] if configs else None


def print_volume_label(
    vol_num: int,
    config_file: str | None = None,
    require_direct_print: bool = True,
) -> dict[str, str | bool]:
    config = get_document_print_config("VOLUMES", "CX", config_file=config_file)
    if not config:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Sem configuracao DocumentPrintConfig para Area=VOLUMES e DocType=CX"
                if not config_file else
                f"Configuracao de impressao nao encontrada para o ficheiro {config_file}"
            ),
        }

    if require_direct_print and not _is_truthy_db_value(config.get("DirectPrint")):
        return {
            "attempted": False,
            "printed": False,
            "message": "Configuracao de impressao encontrada mas DirectPrint esta desativado",
        }

    template_name = str(config.get("DocPrintFile") or "").strip()
    printer_name = str(config.get("PrinterName") or "").strip()
    if not template_name:
        return {
            "attempted": False,
            "printed": False,
            "message": "Configuracao de impressao sem DocPrintFile",
        }
    if not printer_name:
        return {
            "attempted": False,
            "printed": False,
            "message": "Configuracao de impressao sem PrinterName",
        }

    values = _build_volume_label_values(vol_num)
    template = resolve_label_template(template_name).read_text(encoding="utf-8-sig")
    rendered = render_label_template(template, values)
    send_raw_to_printer(printer_name, rendered)
    return {
        "attempted": True,
        "printed": True,
        "message": f"Etiqueta enviada para {printer_name}",
    }


def _build_volume_label_values(vol_num: int) -> dict[str, str]:
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT TOP 1 ISNULL(PartnerName, '') AS PartnerName
            FROM BusinessPartners
            WHERE PartnerType = 'E'
            ORDER BY PartnerID
            """
        )
        company_row = cursor.fetchone()
        company_name = str(company_row[0] or "").strip() if company_row else ""

        cursor.execute(
            """
            SELECT
                v.VolNum,
                ISNULL(v.VolNum2N, '') AS BoxBarcode,
                vi.ItemID,
                ISNULL(im.Barcode, '') AS ItemBarcode,
                ISNULL(im.ItemDesc, '') AS ItemDesc
            FROM VolMaster v
            JOIN VolItem vi
              ON vi.VolNum = v.VolNum
             AND vi.VolDocCod = 'CX'
            LEFT JOIN ItemMaster im
              ON im.ItemID = vi.ItemID
            WHERE v.VolNum = ?
              AND v.VolDocCod = 'CX'
            ORDER BY vi.VolItemNumber
            """,
            (vol_num,),
        )
        rows = cursor.fetchall()

    if not rows:
        raise RuntimeError(f"Caixa {vol_num} nao encontrada para impressao")

    box_barcode = str(rows[0][1] or rows[0][0] or "").strip()
    distinct_items: list[str] = []
    distinct_barcodes: list[str] = []
    seen_items = set()
    seen_barcodes = set()

    for _, _, item_id, item_barcode, item_desc in rows:
        item_id_text = str(item_id or "").strip()
        item_desc_text = str(item_desc or "").strip()
        item_line = item_id_text if not item_desc_text else f"{item_id_text} {item_desc_text}"
        if item_line and item_line not in seen_items:
            distinct_items.append(item_line)
            seen_items.add(item_line)

        barcode_text = str(item_barcode or "").strip()
        if barcode_text and barcode_text not in seen_barcodes:
            distinct_barcodes.append(barcode_text)
            seen_barcodes.add(barcode_text)

    distinct_items_text = " | ".join(distinct_items[:6])
    if len(distinct_items) > 6:
        distinct_items_text += f" | +{len(distinct_items) - 6}"

    item_barcode_value = distinct_barcodes[0] if distinct_barcodes else box_barcode
    return {
        "COMPANY_NAME": company_name or "Empresa",
        "BOX_NUMBER": str(vol_num),
        "BOX_BARCODE": box_barcode,
        "ITEM_BARCODE": item_barcode_value,
        "DISTINCT_ITEMS": distinct_items_text,
        "DISTINCT_COUNT": str(len(distinct_items)),
    }


def _is_truthy_db_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0

    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y", "sim"}
