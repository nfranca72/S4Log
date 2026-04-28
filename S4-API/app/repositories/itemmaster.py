from __future__ import annotations

import mimetypes
from typing import Optional

from app.db.connection import db_cursor


def fetch_active_items(
    partner_id: str,
    production_type: str,
    include_image: bool = False,
    version: Optional[int] = None,
    client_sigla: Optional[str] = None,
) -> list[dict[str, object]]:
    include_has_image_clause = ""
    query_params: list[object] = []

    if include_image:
        if not client_sigla:
            raise ValueError(
                "ClientSigla is required when IncludeImage=true"
            )

        include_has_image_clause = """
            ,CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM OnS3_ATTACHMENTS.dbo.ItemMasterAttachments ima WITH (NOLOCK)
                    JOIN OnS3_ATTACHMENTS.dbo.Attachments a WITH (NOLOCK)
                        ON a.AttachmentID = ima.AttachmentNumber
                    JOIN OnS3_ATTACHMENTS.dbo.FileType ft WITH (NOLOCK)
                        ON ft.ExtensionFile = a.FileExtension
                    WHERE ima.Company = ?
                      AND ima.ItemID = cod.ItemID
                      AND ima.Deleted = 0
                      AND ft.AttachmentType = 'IMAGE'
                )
                THEN CAST(1 AS bit)
                ELSE CAST(0 AS bit)
            END AS HasImage
        """
        query_params.append(client_sigla)

    if version is not None:
        include_has_image_clause = include_has_image_clause.replace(
            "AND ima.Deleted = 0",
            "AND ima.Version = ?\n                      AND ima.Deleted = 0",
            1,
        )
        query_params.append(version)

    query_params.append(production_type)
    query_params.append(partner_id)

    query = """
        SELECT DISTINCT cod.ItemID, im.ItemDesc{include_has_image_clause}
        FROM DocumentConfig dc WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = dc.DocType
        JOIN ClientOrderDetails cod WITH (NOLOCK)
            ON cod.DocType = co.DocType
           AND cod.OrderID = co.OrderID
        JOIN ItemMaster im WITH (NOLOCK)
            ON im.ItemID = cod.ItemID
        WHERE dc.DocTypeArea = ?
          AND co.ClientID = ?
        ORDER BY im.ItemDesc
    """.format(include_has_image_clause=include_has_image_clause)

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(query_params))
        rows = cursor.fetchall()

        items = [
            _build_active_item_payload(row=row, include_image=include_image)
            for row in rows
        ]
        if not include_image:
            return items

        return items


def fetch_item_image(
    company: str,
    item_id: str,
    version: Optional[int],
) -> Optional[dict[str, object]]:
    version_clause = ""
    params: list[object] = [company, item_id]

    if version is None:
        version_clause = " AND ima.Version = 0 "
    else:
        version_clause = " AND ima.Version = ? "
        params.append(version)

    query = f"""
        SELECT TOP 1
            a.FileBytes,
            a.FileExtension
        FROM OnS3_ATTACHMENTS.dbo.ItemMasterAttachments ima WITH (NOLOCK)
        JOIN OnS3_ATTACHMENTS.dbo.Attachments a WITH (NOLOCK)
            ON a.AttachmentID = ima.AttachmentNumber
        JOIN OnS3_ATTACHMENTS.dbo.FileType ft WITH (NOLOCK)
            ON ft.ExtensionFile = a.FileExtension
        WHERE ima.Company = ?
          AND ima.ItemID = ?
          {version_clause}
          AND ima.Deleted = 0
          AND ft.AttachmentType = 'IMAGE'
        ORDER BY ima.Sequence
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        row = cursor.fetchone()

    if row is None:
        return None

    file_extension = _normalize_extension(row[1])
    media_type = mimetypes.types_map.get(file_extension, "application/octet-stream")

    return {
        "content": _coerce_file_bytes(row[0]),
        "media_type": media_type,
        "file_extension": file_extension,
    }


def _build_active_item_payload(
    row,
    include_image: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ItemID": row[0],
        "ItemDesc": row[1],
    }

    if include_image:
        payload["HasImage"] = bool(row[2])

    return payload


def _normalize_extension(file_extension: Optional[str]) -> str:
    if not file_extension:
        return ""

    normalized = file_extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"

    return normalized


def _coerce_file_bytes(file_bytes: object) -> bytes:
    if file_bytes is None:
        raise ValueError("Attachment found without FileBytes")

    if isinstance(file_bytes, memoryview):
        file_bytes = file_bytes.tobytes()

    if isinstance(file_bytes, bytearray):
        file_bytes = bytes(file_bytes)

    if not isinstance(file_bytes, bytes):
        raise TypeError(f"Unsupported FileBytes type: {type(file_bytes)!r}")

    return file_bytes
