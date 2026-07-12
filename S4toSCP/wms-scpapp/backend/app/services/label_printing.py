from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.db.connection import db_cursor
from app.settings import settings

_MAC_COLUMN_CANDIDATES = (
    "Post",
    "MacAddress",
    "MACAddress",
    "Mac",
    "MAC",
    "PhysicalAddress",
)

_SIMPLIFIED_MOVEMENT_TEMPLATE = "MS-CX-CAIXA.zpl"
_SIMPLIFIED_MOVEMENT_LINES_PER_PAGE = 11


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


def get_document_print_configs(
    area: str,
    doc_type: str,
    station_identifier: str | None = None,
) -> list[dict[str, Any]]:
    with db_cursor() as (cursor, _):
        normalized_station_identifier = _normalized_station_identifier(station_identifier)
        profile = _resolve_station_profile(cursor, normalized_station_identifier)
        if profile is not None:
            cursor.execute(
                """
                SELECT *
                FROM DocumentPrintConfig
                WHERE Area = ? AND DocType = ? AND DocPrintProfile = ?
                ORDER BY ISNULL(DocPrintDescr, ''), ISNULL(DocPrintFile, '')
                """,
                (area, doc_type, profile),
            )
            rows = cursor.fetchall()
            if not rows and profile != -1:
                cursor.execute(
                    """
                    SELECT *
                    FROM DocumentPrintConfig
                    WHERE Area = ? AND DocType = ? AND DocPrintProfile = -1
                    ORDER BY ISNULL(DocPrintDescr, ''), ISNULL(DocPrintFile, '')
                    """,
                    (area, doc_type),
                )
                rows = cursor.fetchall()
            if not rows:
                cursor.execute(
                    """
                    SELECT *
                    FROM DocumentPrintConfig
                    WHERE Area = ? AND DocType = ?
                    ORDER BY ISNULL(DocPrintDescr, ''), ISNULL(DocPrintFile, '')
                    """,
                    (area, doc_type),
                )
                rows = cursor.fetchall()
        else:
            cursor.execute(
                """
                SELECT *
                FROM DocumentPrintConfig
                WHERE Area = ? AND DocType = ?
                ORDER BY
                    CASE WHEN ISNULL(DocPrintProfile, -1) = -1 THEN 0 ELSE 1 END,
                    ISNULL(DocPrintDescr, ''),
                    ISNULL(DocPrintFile, '')
                """,
                (area, doc_type),
            )
            rows = cursor.fetchall()

        columns = [col[0] for col in cursor.description]
        return [
            {column: row[idx] for idx, column in enumerate(columns)}
            for row in rows
        ]


def get_document_print_config(
    area: str,
    doc_type: str,
    config_file: str | None = None,
    station_identifier: str | None = None,
) -> dict[str, Any] | None:
    configs = get_document_print_configs(area, doc_type, station_identifier=station_identifier)
    if config_file:
        requested = str(config_file).strip().lower()
        for config in configs:
            if str(config.get("DocPrintFile") or "").strip().lower() == requested:
                return config
        return None
    return configs[0] if configs else None


def _select_volume_print_config(
    configs: list[dict[str, Any]],
    require_direct_print: bool,
) -> dict[str, Any] | None:
    if not configs:
        return None

    def has_template(config: dict[str, Any]) -> bool:
        return bool(str(config.get("DocPrintFile") or "").strip())

    def has_printer(config: dict[str, Any]) -> bool:
        return bool(str(config.get("PrinterName") or "").strip())

    if require_direct_print:
        for config in configs:
            if _is_truthy_db_value(config.get("DirectPrint")) and has_template(config) and has_printer(config):
                return config

    for config in configs:
        if has_template(config) and has_printer(config):
            return config

    for config in configs:
        if has_template(config):
            return config

    return configs[0]


def _station_debug_text(station_identifier: str | None = None) -> str:
    raw_value = str(station_identifier or settings.STATION_IDENTIFIER or "").strip()
    normalized_value = _normalized_station_identifier(station_identifier)
    return f"MAC/Station='{raw_value or '(vazio)'}' normalizado='{normalized_value or '(vazio)'}'"


def _config_debug_text(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    return (
        f"DB='{settings.DB_HOST}/{settings.DB_NAME}' "
        f"Profile='{cfg.get('DocPrintProfile', '(n/a)')}' "
        f"Area='{str(cfg.get('Area') or '').strip() or '(vazio)'}' "
        f"DocType='{str(cfg.get('DocType') or '').strip() or '(vazio)'}' "
        f"Descr='{str(cfg.get('DocPrintDescr') or '').strip() or '(vazio)'}' "
        f"File='{str(cfg.get('DocPrintFile') or '').strip() or '(vazio)'}' "
        f"Printer='{str(cfg.get('PrinterName') or '').strip() or '(vazio)'}' "
        f"DirectPrint='{str(cfg.get('DirectPrint') if cfg.get('DirectPrint') is not None else '(vazio)')}'"
    )


def print_volume_label(
    vol_num: int,
    config_file: str | None = None,
    require_direct_print: bool = True,
    station_identifier: str | None = None,
) -> dict[str, str | bool]:
    if config_file:
        config = get_document_print_config(
            "VOLUMES",
            "CX",
            config_file=config_file,
            station_identifier=station_identifier,
        )
    else:
        configs = get_document_print_configs(
            "VOLUMES",
            "CX",
            station_identifier=station_identifier,
        )
        config = _select_volume_print_config(configs, require_direct_print=require_direct_print)
    if not config:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Sem configuracao DocumentPrintConfig para Area=VOLUMES e DocType=CX. "
                f"DB='{settings.DB_HOST}/{settings.DB_NAME}' {_station_debug_text(station_identifier)}"
                if not config_file else
                f"Configuracao de impressao nao encontrada para o ficheiro {config_file}. "
                f"DB='{settings.DB_HOST}/{settings.DB_NAME}' {_station_debug_text(station_identifier)}"
            ),
        }

    if require_direct_print and not _is_truthy_db_value(config.get("DirectPrint")):
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Configuracao de impressao encontrada mas DirectPrint esta desativado. "
                f"{_station_debug_text(station_identifier)} {_config_debug_text(config)}"
            ),
        }

    template_name = str(config.get("DocPrintFile") or "").strip()
    printer_name = str(config.get("PrinterName") or "").strip()
    if not template_name:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Configuracao de impressao sem DocPrintFile. "
                f"{_station_debug_text(station_identifier)} {_config_debug_text(config)}"
            ),
        }
    if not printer_name:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Configuracao de impressao sem PrinterName. "
                f"{_station_debug_text(station_identifier)} {_config_debug_text(config)}"
            ),
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
                ISNULL(im.ClientRef, '') AS ClientRef,
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
    distinct_client_refs: list[str] = []
    distinct_barcodes: list[str] = []
    seen_items = set()
    seen_client_refs = set()
    seen_barcodes = set()

    for _, _, item_id, client_ref, item_barcode, item_desc in rows:
        item_id_text = str(item_id or "").strip()
        item_desc_text = str(item_desc or "").strip()
        item_line = item_id_text if not item_desc_text else f"{item_id_text} {item_desc_text}"
        if item_line and item_line not in seen_items:
            distinct_items.append(item_line)
            seen_items.add(item_line)

        client_ref_text = str(client_ref or "").strip()
        if client_ref_text and client_ref_text not in seen_client_refs:
            distinct_client_refs.append(client_ref_text)
            seen_client_refs.add(client_ref_text)

        barcode_text = str(item_barcode or "").strip()
        if barcode_text and barcode_text not in seen_barcodes:
            distinct_barcodes.append(barcode_text)
            seen_barcodes.add(barcode_text)

    distinct_items_text = " | ".join(distinct_items[:6])
    if len(distinct_items) > 6:
        distinct_items_text += f" | +{len(distinct_items) - 6}"

    item_barcode_value = (
        distinct_client_refs[0]
        if distinct_client_refs
        else distinct_barcodes[0]
        if distinct_barcodes
        else box_barcode
    )
    return {
        "COMPANY_NAME": company_name or "Empresa",
        "BOX_NUMBER": str(vol_num),
        "BOX_BARCODE": box_barcode,
        "ITEM_BARCODE": item_barcode_value,
        "DISTINCT_ITEMS": distinct_items_text,
        "DISTINCT_COUNT": str(len(distinct_items)),
    }


def print_simplified_movement_label(
    label_payload: dict[str, Any],
    require_direct_print: bool = True,
    station_identifier: str | None = None,
) -> dict[str, str | bool]:
    configs = get_document_print_configs(
        "VOLUMES",
        "CX",
        station_identifier=station_identifier,
    )
    config = _select_volume_print_config(configs, require_direct_print=require_direct_print)
    if not config:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Sem configuracao de impressao de caixas para reutilizar nos movimentos simplificados. "
                f"DB='{settings.DB_HOST}/{settings.DB_NAME}' {_station_debug_text(station_identifier)}"
            ),
        }

    if require_direct_print and not _is_truthy_db_value(config.get("DirectPrint")):
        return {
            "attempted": False,
            "printed": False,
            "message": "",
        }

    printer_name = str(config.get("PrinterName") or "").strip()
    if not printer_name:
        return {
            "attempted": False,
            "printed": False,
            "message": (
                "Configuracao de impressao sem PrinterName para movimentos simplificados. "
                f"{_station_debug_text(station_identifier)} {_config_debug_text(config)}"
            ),
        }

    pages = _build_simplified_movement_label_pages(label_payload)
    if not pages:
        return {
            "attempted": False,
            "printed": False,
            "message": "Sem dados para imprimir a etiqueta do movimento simplificado.",
        }

    template = resolve_label_template(_SIMPLIFIED_MOVEMENT_TEMPLATE).read_text(encoding="utf-8-sig")
    rendered = "".join(render_label_template(template, page) for page in pages)
    try:
        send_raw_to_printer(printer_name, rendered)
    except Exception as exc:
        return {
            "attempted": True,
            "printed": False,
            "message": str(exc),
        }

    return {
        "attempted": True,
        "printed": True,
        "message": f"{len(pages)} etiqueta(s) enviada(s) para {printer_name}",
    }


def _build_simplified_movement_label_pages(label_payload: dict[str, Any]) -> list[dict[str, str]]:
    movement_title = str(label_payload.get("movement_title") or "Movimento simplificado").strip()
    movement_number = str(label_payload.get("movement_number") or "").strip()
    emission_date = str(label_payload.get("emission_date") or "").strip()
    groups = label_payload.get("groups") or []
    company_name = _company_name()

    raw_pages: list[dict[str, str]] = []
    for group in groups:
        box_number = str(group.get("box_number") or "SEM CAIXA").strip() or "SEM CAIXA"
        box_barcode = str(group.get("box_barcode") or box_number).strip() or box_number
        items = group.get("items") or []
        item_lines = [_simplified_movement_item_line_text(item) for item in items]
        item_lines = [line for line in item_lines if line]
        if not item_lines:
            item_lines = ["(sem artigos)"]

        for chunk in _chunked(item_lines, _SIMPLIFIED_MOVEMENT_LINES_PER_PAGE):
            raw_pages.append({
                "COMPANY_NAME": company_name or "Empresa",
                "MOVEMENT_TITLE": movement_title,
                "MOVEMENT_NUMBER": movement_number,
                "EMISSION_DATE": emission_date,
                "BOX_NUMBER": box_number,
                "BOX_BARCODE": box_barcode,
                "LINES_BLOCK": r"\&".join(chunk),
            })

    total_pages = len(raw_pages)
    for index, page in enumerate(raw_pages, start=1):
        page["PAGE_LABEL"] = f"Etiqueta {index}/{total_pages}"
    return raw_pages


def _simplified_movement_item_line_text(item: dict[str, Any]) -> str:
    item_id = str(item.get("item_id") or "").strip()
    item_desc = str(item.get("item_desc") or "").strip()
    qty = float(item.get("qty") or 0)
    qty_text = f"{qty:.0f}" if qty.is_integer() else f"{qty:.2f}".rstrip("0").rstrip(".")
    desc = f"{item_id} {item_desc}".strip()
    desc = _truncate_text(desc, 42)
    return f"{desc}  x {qty_text}".strip()


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:max(0, limit - 3)].rstrip()}..."


def _chunked(values: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [values]
    return [values[index:index + size] for index in range(0, len(values), size)]


def _company_name() -> str:
    with db_cursor() as (cursor, _):
        cursor.execute(
            """
            SELECT TOP 1 ISNULL(PartnerName, '') AS PartnerName
            FROM BusinessPartners
            WHERE PartnerType = 'E'
            ORDER BY PartnerID
            """
        )
        row = cursor.fetchone()
    return str(row[0] or "").strip() if row else ""


def _is_truthy_db_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0

    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y", "sim"}


def _normalized_station_identifier(value: str | None = None) -> str:
    source = value if value is not None else settings.STATION_IDENTIFIER
    return _normalize_mac_text(source)


def _normalize_text(value: object) -> str:
    return str(value or "").strip().upper()


def _normalize_mac_text(value: object) -> str:
    text = _normalize_text(value)
    return text.replace(":", "").replace("-", "").replace(".", "").replace(" ", "")


def _quote_identifier(identifier: str) -> str:
    text = str(identifier or "").strip()
    if not text:
        raise RuntimeError("Identificador SQL vazio")
    return "[" + text.replace("]", "]]") + "]"


def _qualify_table(table_name: str) -> str:
    parts = [part.strip() for part in str(table_name or "").split(".") if part.strip()]
    if not parts:
        raise RuntimeError("Nome da tabela de mapeamento vazio")
    return ".".join(_quote_identifier(part) for part in parts)


def _resolve_station_profile(cursor, station_identifier: str) -> int | None:
    if not station_identifier:
        return _fallback_profile_exists(cursor)

    mapping = _resolve_station_mapping(cursor)
    if not mapping:
        return _fallback_profile_exists(cursor)

    table_name = _qualify_table(mapping["table_name"])
    mac_column = _quote_identifier(mapping["mac_column"])
    profile_column = mapping.get("profile_column")
    user_id_column = mapping.get("user_id_column")

    if profile_column:
        sql = f"""
            SELECT TOP 1 CAST(m.{_quote_identifier(profile_column)} AS int) AS Profile
            FROM {table_name} m
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(
                UPPER(LTRIM(RTRIM(ISNULL(CAST(m.{mac_column} AS varchar(255)), '')))),
                ':', ''
            ), '-', ''), '.', ''), ' ', '') = REPLACE(REPLACE(REPLACE(REPLACE(
                UPPER(LTRIM(RTRIM(ISNULL(CAST(? AS varchar(255)), '')))),
                ':', ''
            ), '-', ''), '.', ''), ' ', '')
        """
        cursor.execute(sql, (station_identifier,))
    elif user_id_column:
        sql = f"""
            SELECT TOP 1 CAST(u.Profile AS int) AS Profile
            FROM {table_name} m
            JOIN Users u ON u.UserID = m.{_quote_identifier(user_id_column)}
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(
                UPPER(LTRIM(RTRIM(ISNULL(CAST(m.{mac_column} AS varchar(255)), '')))),
                ':', ''
            ), '-', ''), '.', ''), ' ', '') = REPLACE(REPLACE(REPLACE(REPLACE(
                UPPER(LTRIM(RTRIM(ISNULL(CAST(? AS varchar(255)), '')))),
                ':', ''
            ), '-', ''), '.', ''), ' ', '')
        """
        cursor.execute(sql, (station_identifier,))
    else:
        return _fallback_profile_exists(cursor)

    row = cursor.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return _fallback_profile_exists(cursor)


def _fallback_profile_exists(cursor) -> int | None:
    cursor.execute(
        """
        SELECT TOP 1 CAST(DocPrintProfile AS int)
        FROM DocumentPrintConfig
        WHERE DocPrintProfile = -1
        """
    )
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _resolve_station_mapping(cursor) -> dict[str, str] | None:
    explicit = _explicit_station_mapping()
    if explicit:
        return explicit
    return _autodiscover_station_mapping(cursor)


def _explicit_station_mapping() -> dict[str, str] | None:
    table_name = (settings.STATION_MAPPING_TABLE or "").strip()
    mac_column = (settings.STATION_MAPPING_MAC_COLUMN or "").strip()
    user_id_column = (settings.STATION_MAPPING_USERID_COLUMN or "").strip()
    profile_column = (settings.STATION_MAPPING_PROFILE_COLUMN or "").strip()

    if not table_name or not mac_column:
        return None
    if not user_id_column and not profile_column:
        return None

    mapping = {
        "table_name": table_name,
        "mac_column": mac_column,
    }
    if user_id_column:
        mapping["user_id_column"] = user_id_column
    if profile_column:
        mapping["profile_column"] = profile_column
    return mapping


def _autodiscover_station_mapping(cursor) -> dict[str, str] | None:
    placeholders = ",".join("?" for _ in _MAC_COLUMN_CANDIDATES)
    cursor.execute(
        f"""
        SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME IN ({placeholders}, 'UserID', 'Profile')
        ORDER BY TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
        """,
        _MAC_COLUMN_CANDIDATES,
    )
    rows = cursor.fetchall()
    table_columns: dict[tuple[str, str], set[str]] = {}
    for schema, table_name, column_name in rows:
        key = (str(schema or "").strip(), str(table_name or "").strip())
        table_columns.setdefault(key, set()).add(str(column_name or "").strip())

    preferred_keys: list[tuple[str, str]] = []
    fallback_keys: list[tuple[str, str]] = []
    for key in table_columns:
        _, table_name = key
        if table_name.lower() == "posts":
            preferred_keys.append(key)
        else:
            fallback_keys.append(key)
    ordered_keys = preferred_keys + fallback_keys

    preferred_mac_columns = ["Post", *_MAC_COLUMN_CANDIDATES]

    for schema, table_name in ordered_keys:
        columns = table_columns[(schema, table_name)]
        if "Profile" in columns:
            for mac_column in preferred_mac_columns:
                if mac_column in columns:
                    return {
                        "table_name": f"{schema}.{table_name}" if schema else table_name,
                        "mac_column": mac_column,
                        "profile_column": "Profile",
                    }

    for schema, table_name in ordered_keys:
        columns = table_columns[(schema, table_name)]
        if table_name.lower() == "users":
            continue
        if "UserID" in columns:
            for mac_column in preferred_mac_columns:
                if mac_column in columns:
                    return {
                        "table_name": f"{schema}.{table_name}" if schema else table_name,
                        "mac_column": mac_column,
                        "user_id_column": "UserID",
                    }
    return None
