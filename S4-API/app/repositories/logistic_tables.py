from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db.connection import db_cursor


def create_or_update_volume(
    volume_type: str,
    length: Decimal,
    height: Decimal,
    width: Decimal,
    net_weight: Decimal | None,
    volume: Decimal,
    vol_doc_cod: str,
) -> dict[str, Any]:
    weight_value = net_weight if net_weight is not None else Decimal("0")

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            UPDATE VolType
            SET VolTypeDescr = ?,
                VolDocCod = ?,
                VolTypeWidth = ?,
                VolTypeLength = ?,
                VolTypeHeight = ?,
                VolTypeWeight = ?,
                IDIntegration = ?
            WHERE VolTypeID = ?
            """,
            (
                volume_type,
                vol_doc_cod,
                float(width),
                float(length),
                float(height),
                float(weight_value),
                volume_type,
                volume_type,
            ),
        )

        if cursor.rowcount and cursor.rowcount > 0:
            action = "updated"
        else:
            cursor.execute(
                """
                INSERT INTO VolType (
                    VolTypeID,
                    VolTypeDescr,
                    VolDocCod,
                    VolTypeWidth,
                    VolTypeLength,
                    VolTypeHeight,
                    VolTypeWeight,
                    VolTypeMaxWeight,
                    PickingVolType,
                    VolTypeItemID,
                    MovVolTypeItemStock,
                    IDIntegration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    volume_type,
                    volume_type,
                    vol_doc_cod,
                    float(width),
                    float(length),
                    float(height),
                    float(weight_value),
                    0,
                    0,
                    "",
                    0,
                    volume_type,
                ),
            )
            action = "created"

    return {
        "VolumeType": volume_type,
        "Long": length,
        "High": height,
        "Width": width,
        "NetWeight": net_weight,
        "Volume": volume,
        "Action": action,
    }
