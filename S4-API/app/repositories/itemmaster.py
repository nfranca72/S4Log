from __future__ import annotations

import base64
import mimetypes
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import pyodbc

from app.db.connection import db_cursor


ITEMMASTER_SORT_COLUMNS = {
    "ItemID": "ItemID",
    "ItemDesc": "ItemDesc",
    "ClientRef": "ClientRef",
    "Modelo": "Modelo",
    "CategoryID": "CategoryID",
    "CategoryDesc": "CategoryDesc",
    "SubCategoryId": "SubCategoryId",
    "SubCategoryDescr": "SubCategoryDescr",
    "BrandID": "BrandID",
    "BrandDesc": "BrandDesc",
    "PartnerID": "PartnerID",
    "PartnerName": "PartnerName",
    "Version": "Version",
    "VersionName": "VersionName",
    "StkQty": "StkQty",
    "StkUnit": "StkUnit",
    "UnitDesc": "UnitDesc",
    "Barcode": "Barcode",
    "CreationDateTime": "CreationDateTime",
    "ModifDateTime": "ModifDateTime",
}


def fetch_active_items(
    partner_id: str,
    production_type: str,
    include_image: bool = False,
    version: Optional[int] = None,
    client_sigla: Optional[str] = None,
) -> list[dict[str, object]]:
    include_has_image_clause = ""
    query_params: list[object] = []

    if include_image and not client_sigla:
        include_has_image_clause = ",CAST(0 AS bit) AS HasImage"

    if include_image and client_sigla:
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
        if not include_image or not client_sigla:
            return items

        item_ids = [str(item["ItemID"]) for item in items]
        images = _fetch_first_item_images(
            cursor=cursor,
            company=client_sigla,
            item_ids=item_ids,
            version=version,
        )

    for item in items:
        item_image = images.get(str(item["ItemID"]))
        item["Image"] = item_image
        if include_image:
            item["HasImage"] = item_image is not None

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


def _fetch_first_item_images(
    cursor,
    company: str,
    item_ids: list[str],
    version: Optional[int],
) -> dict[str, dict[str, str]]:
    if not item_ids:
        return {}

    placeholders = ",".join("?" for _ in item_ids)
    version_clause = "AND ima.Version = 0"
    params: list[object] = [company, *item_ids]
    if version is not None:
        version_clause = "AND ima.Version = ?"
        params.append(version)

    cursor.execute(
        f"""
        SELECT ItemID, FileBytes, FileExtension
        FROM (
            SELECT
                ima.ItemID,
                a.FileBytes,
                a.FileExtension,
                ROW_NUMBER() OVER (
                    PARTITION BY ima.ItemID
                    ORDER BY ima.Sequence, ima.AttachmentNumber
                ) RowNum
            FROM OnS3_ATTACHMENTS.dbo.ItemMasterAttachments ima WITH (NOLOCK)
            JOIN OnS3_ATTACHMENTS.dbo.Attachments a WITH (NOLOCK)
                ON a.AttachmentID = ima.AttachmentNumber
            JOIN OnS3_ATTACHMENTS.dbo.FileType ft WITH (NOLOCK)
                ON ft.ExtensionFile = a.FileExtension
            WHERE ima.Company = ?
              AND ima.ItemID IN ({placeholders})
              AND ima.Deleted = 0
              AND ft.AttachmentType = 'IMAGE'
              {version_clause}
        ) images
        WHERE RowNum = 1
        """,
        tuple(params),
    )

    result: dict[str, dict[str, str]] = {}
    for row in cursor.fetchall():
        file_extension = _normalize_extension(row[2])
        media_type = mimetypes.types_map.get(file_extension, "application/octet-stream")
        content = _coerce_file_bytes(row[1])
        result[str(row[0])] = {
            "MediaType": media_type,
            "FileExtension": file_extension,
            "Base64": base64.b64encode(content).decode("ascii"),
        }

    return result


def fetch_itemmaster_list(
    filters: dict[str, Any],
    show_items_components: bool = True,
    show_items_composed: bool = True,
    show_all_versions: bool = False,
    restrict_to_this_item_id_has_component: str = "",
    page_number: int = 1,
    page_size: int = 50,
    sort_by: str = "",
    item_budget: str = "",
    include_total_count: bool = False,
) -> dict[str, Any]:
    where_parts = [
        "im.Status = 1",
        "im.Blocked = 0",
        "im.Flag = 'N'",
        "im.TemporaryItem = 0",
    ]
    filter_params: list[Any] = []

    if not show_items_components:
        where_parts.append("im.IsComposed = 1")
    if not show_items_composed:
        where_parts.append("im.IsComposed = 0")
    if item_budget:
        where_parts.append("im.ItemID NOT LIKE ? + '%'")
        filter_params.append(item_budget)
    if restrict_to_this_item_id_has_component:
        where_parts.append(
            """
            EXISTS (
                SELECT 1
                FROM ItemComp ic WITH (NOLOCK)
                WHERE ic.ItemID = im.ItemID
                  AND ic.ComponentID = ?
            )
            """
        )
        filter_params.append(restrict_to_this_item_id_has_component)

    _add_filter(where_parts, filter_params, filters, "ItemID", "(im.ItemID LIKE ? + '%' OR im.Barcode = ?)", duplicate=True)
    _add_filter(where_parts, filter_params, filters, "ItemDesc", "im.ItemDesc LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "ClientRef", "im.ClientRef LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "Modelo", "im.Modelo LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "CategoryID", "im.CategoryID = ?")
    _add_filter(where_parts, filter_params, filters, "CategoryDesc", "c.CategoryDesc LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "SubCategoryId", "im.SubCategoryId = ?")
    _add_filter(where_parts, filter_params, filters, "SubCategoryDescr", "sc.SubCategoryDescr LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "BrandID", "im.BrandID = ?")
    _add_filter(where_parts, filter_params, filters, "BrandDesc", "b.BrandDesc LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "Version", "ISNULL(imvers.Version, 0) = ?")
    _add_filter(where_parts, filter_params, filters, "VersionName", "aux.VersionName LIKE '%' + ? + '%'")
    _add_filter(where_parts, filter_params, filters, "Qty", "stk.Qty = ?")
    _add_filter(where_parts, filter_params, filters, "StkUnit", "im.StkUnit = ?")
    _add_filter(where_parts, filter_params, filters, "UnitDesc", "un.UnitDesc = ?")
    _add_filter(where_parts, filter_params, filters, "Lots", "im.Lots = ?")
    _add_filter(where_parts, filter_params, filters, "ItemHasSerialNums", "im.SerialNum = ?")
    _add_filter(where_parts, filter_params, filters, "ItemHasVolNums", "im.VolNums = ?")
    _add_filter(where_parts, filter_params, filters, "Barcode", "im.Barcode LIKE ? + '%'")
    _add_filter(where_parts, filter_params, filters, "CreationDateTime", "CONVERT(date, im.CreationDateTime) = CONVERT(date, ?)")
    _add_filter(where_parts, filter_params, filters, "ModifDateTime", "CONVERT(date, im.ModifDateTime) = CONVERT(date, ?)")

    where_clause = "WHERE " + " AND ".join(where_parts)
    sql_base = f"""
        SELECT im.ItemID, im.ItemDesc, im.ClientRef, im.Modelo, im.CategoryID, c.CategoryDesc,
            im.SubCategoryId, sc.SubCategoryDescr, im.BrandID, b.BrandDesc, ip.ProviderId PartnerID,
            bp.PartnerName, ISNULL(imvers.Version, 0) Version, aux.VersionName,
            stk.Qty StkQty, im.StkUnit, un.UnitDesc, im.Lots, im.SerialNum ItemHasSerialNums,
            im.VolNums ItemHasVolNums, im.Barcode, im.CreationDateTime, im.ModifDateTime
        FROM ItemMaster im WITH (NOLOCK)
        JOIN Units un WITH (NOLOCK)
            ON un.UnitID = im.StkUnit
        LEFT JOIN Categories c WITH (NOLOCK)
            ON c.CategoryID = im.CategoryID
        LEFT JOIN SubCategory sc WITH (NOLOCK)
            ON sc.CategoryID = im.CategoryID
           AND sc.SubCategoryId = im.SubCategoryId
        LEFT JOIN GroupType ig WITH (NOLOCK)
            ON ig.GroupTypeID = im.ItemGroupType
        LEFT JOIN SubGroupType isg WITH (NOLOCK)
            ON isg.GroupTypeID = im.ItemGroupType
           AND isg.SubGroupTypeId = im.ItemSubGroupType
        LEFT JOIN Users uc WITH (NOLOCK)
            ON uc.UserID = im.CreationUser
        LEFT JOIN Users u2 WITH (NOLOCK)
            ON u2.UserID = im.ModifUser
        LEFT JOIN Brands b WITH (NOLOCK)
            ON b.BrandID = im.BrandID
        LEFT JOIN ItemProvider ip WITH (NOLOCK)
            ON ip.ItemId = im.ItemID
           AND ip.MainProvider = 1
        LEFT JOIN BusinessPartners bp WITH (NOLOCK)
            ON bp.PartnerType = 'F'
           AND bp.PartnerID = ip.ProviderId
        OUTER APPLY (
            SELECT im.Versao Version
            UNION
            SELECT imdv.Version
            FROM ItemMasterDetailsVersion imdv WITH (NOLOCK)
            WHERE imdv.ItemId = im.ItemID
              AND (imdv.Version = im.Versao OR ? = 1)
        ) imvers
        LEFT JOIN ItemMasterVersionsNames imvn WITH (NOLOCK)
            ON imvn.VersionStart = LEFT(CONVERT(nvarchar(50), imvers.Version), ?)
           AND LEN(CONVERT(nvarchar(50), imvers.Version)) = ? + ?
        CROSS APPLY (
            SELECT (
                CASE
                    WHEN imvn.Description IS NULL THEN 'V.' + CONVERT(nvarchar(50), imvers.Version)
                    ELSE imvn.Description + (
                        CASE
                            WHEN ? > 0 THEN ' R.' + RIGHT(CONVERT(nvarchar(50), imvers.Version), ?)
                            ELSE ''
                        END
                    )
                END
            ) VersionName
        ) aux
        CROSS APPLY (
            SELECT CONVERT(decimal(18, 5), ISNULL(SUM(iv.Qty), 0)) Qty
            FROM Inventory iv WITH (NOLOCK)
            JOIN Warehouses w WITH (NOLOCK)
                ON w.WHID = iv.WHID
               AND w.ExpeditionWH = 0
               AND w.ExcludeStock = 0
            JOIN Locations l WITH (NOLOCK)
                ON l.LocationID = iv.LocationID
               AND l.WHID = iv.WHID
               AND l.StatusID <> 0
            WHERE iv.ItemID = im.ItemID
              AND iv.Version = imvers.Version
        ) stk
        {where_clause}
    """

    with db_cursor() as (cursor, _conn):
        version_digits = _param_int(cursor, "VERSDIG", default=3)
        version_rev_digits = _param_int(cursor, "REVDIG", default=0)

    base_params: list[Any] = [
        1 if show_all_versions else 0,
        version_digits,
        version_digits,
        version_rev_digits,
        version_rev_digits,
        version_rev_digits,
    ]
    params = base_params + filter_params

    order_by = _itemmaster_order_by(sort_by)
    paging_sql = ""
    page_number = max(int(page_number or 1), 1)
    page_size = int(page_size or 50)
    fetch_size = page_size + 1 if not include_total_count else page_size
    paging_sql = " OFFSET (? - 1) * ? ROWS FETCH NEXT ? ROWS ONLY"

    sql = f"{sql_base}\n{order_by}\n{paging_sql}"
    query_params = params + [page_number, page_size, fetch_size]

    total_count: int | None = None
    with db_cursor() as (cursor, _conn):
        if include_total_count:
            count_sql = f"SELECT COUNT(*) Total FROM ({sql_base}) t"
            cursor.execute(count_sql, tuple(params))
            total_count = int(cursor.fetchone()[0] or 0)

        cursor.execute(sql, tuple(query_params))
        rows = cursor.fetchall()
        has_next_page = len(rows) > page_size if not include_total_count else (page_number * page_size) < int(total_count or 0)
        data = [_row_to_dict(cursor, row) for row in rows[:page_size]]

    return {
        "Data": data,
        "CurrentPage": page_number,
        "HasNextPage": has_next_page,
        "TotalRecordCount": total_count,
    }


def fetch_item_versions(item_id: str) -> list[dict[str, Any]]:
    query = """
        SELECT DISTINCT
            ic.Version Versao,
            ISNULL(
                NULLIF(ic.VersionName, ''),
                (
                    CASE
                        WHEN imvn.Description IS NULL THEN 'V.' + CONVERT(nvarchar(50), ic.Version)
                        ELSE imvn.Description + ' R.' + RIGHT(CONVERT(nvarchar(50), ic.Version), ?)
                    END
                )
            ) + PriceStatus VersionDescr,
            ISNULL(imvn.GeneratedDocument, '') GeneratedDocument,
            ISNULL(imvn.OpersetID, '') OpersetID,
            ic.Locked,
            ic.VersionType
        FROM ItemMasterDetailsVersion ic WITH (NOLOCK)
        LEFT JOIN ItemMasterVersionsNames imvn WITH (NOLOCK)
            ON imvn.VersionStart = LEFT(CONVERT(nvarchar(50), ic.Version), ?)
           AND LEN(CONVERT(nvarchar(50), ic.Version)) = ? + ?
        OUTER APPLY (
            SELECT ISNULL(MAX(
                CASE
                    WHEN ip.WaitingApprobation = 1 THEN ' Espera Aprovação'
                    WHEN ip.PriceApproved = 1 THEN ' Aprovado'
                    ELSE ' Não Aprovado'
                END
            ), '') PriceStatus
            FROM ItemProvider ip WITH (NOLOCK)
            WHERE ic.VersionType = 'SNAPSHOT'
              AND ip.ItemID = ic.ItemID
              AND ip.Version = ic.Version
        ) x
        WHERE ic.ItemID = ?
        ORDER BY ic.Version
    """

    with db_cursor() as (cursor, _conn):
        version_digits = _param_int(cursor, "VERSDIG", default=3)
        version_rev_digits = _param_int(cursor, "REVDIG", default=0)
        cursor.execute(
            query,
            (
                version_rev_digits,
                version_digits,
                version_digits,
                version_rev_digits,
                item_id,
            ),
        )
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def fetch_active_items_for_client(
    client_id: str,
    page_number: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    sql_base = """
        SELECT DISTINCT cod.ItemID, co.ClientID
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN DocumentConfig dc WITH (NOLOCK)
            ON dc.DocType = cod.DocType
           AND dc.DocTypeArea = 'PRODUCTION'
        JOIN DocumentStatus ds WITH (NOLOCK)
            ON ds.DocType = cod.DocType
           AND ds.DocStatusID = cod.ProductionStatus
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
        JOIN BusinessPartners bpop WITH (NOLOCK)
            ON bpop.PartnerType = 'C'
           AND bpop.PartnerID = co.ClientID
        LEFT JOIN BusinessPartners bpprinc WITH (NOLOCK)
            ON bpprinc.PartnerType = 'C'
           AND bpprinc.RouteID = bpop.PartnerID
        WHERE (bpop.PartnerID = ? OR bpprinc.PartnerID = ?)
          AND ds.AllowTransformation = 1
    """

    page_number = max(int(page_number or 1), 1)
    page_size = int(page_size or 50)
    sql = f"""
        {sql_base}
        ORDER BY cod.ItemID
        OFFSET (? - 1) * ? ROWS FETCH NEXT ? ROWS ONLY
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            f"SELECT COUNT(*) Total FROM ({sql_base}) t",
            (client_id, client_id),
        )
        total_count = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            sql,
            (client_id, client_id, page_number, page_size, page_size),
        )
        data = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    return {
        "Data": data,
        "CurrentPage": page_number,
        "HasNextPage": (page_number * page_size) < total_count,
        "TotalRecordCount": total_count,
    }


def fetch_item_active_production_orders(
    item_id: str,
    page_number: int = 0,
    page_size: int = 50,
) -> dict[str, Any]:
    sql_base = """
        SELECT
            cod.DocType,
            cod.OrderID,
            co.RequesterID AS PoCabec,
            cod.POClient AS POlinha,
            cod.VariationCountry,
            cod.QtyOrd,
            cod.ColorID,
            ISNULL((
                SELECT dbo.GROUP_CONCAT_D(DISTINCT TRIM(coo.OperCode), ' / ')
                FROM ClientOrderOperations coo WITH (NOLOCK)
                WHERE coo.DocType = cod.DocType
                  AND coo.OrderID = cod.OrderID
                  AND coo.OrderRow = cod.OrderRow
            ), '') AS Operacoes,
            ISNULL((
                SELECT dbo.GROUP_CONCAT_D(
                    CONCAT(
                        CONVERT(VARCHAR(10), x.[Date], 103),
                        ' --> ',
                        REPLACE(FORMAT(x.QtdTotal, 'N0'), ',', ' '),
                        ' Uni  OBS : ',
                        ISNULL(x.Obs, '')
                    ),
                    CHAR(13) + CHAR(10)
                )
                FROM (
                    SELECT
                        ddt.[Date],
                        ddt.Obs,
                        SUM(dd.Qtd) AS QtdTotal
                    FROM DeliveryDatesDim dd WITH (NOLOCK)
                    JOIN DeliveryDates ddt WITH (NOLOCK)
                        ON ddt.DocType = dd.DocType
                       AND ddt.OrderID = dd.OrderID
                    WHERE dd.DocType = cod.DocType
                      AND dd.OrderID = cod.OrderID
                      AND dd.ColorID = cod.ColorID
                      AND dd.TpDate = 'ENT'
                    GROUP BY ddt.[Date], ddt.Obs
                ) x
            ), '') AS DatasEntrega,
            ISNULL((
                SELECT STRING_AGG(
                    CONCAT(codim.SizeID, '-', REPLACE(FORMAT(codim.QtyOrd, 'N0'), ',', ' ')),
                    ' | '
                ) WITHIN GROUP (ORDER BY codim.SizeOrderNum)
                FROM ClientOrdersDim codim WITH (NOLOCK)
                WHERE codim.DocType = cod.DocType
                  AND codim.OrderID = cod.OrderID
                  AND codim.OrderRow = cod.OrderRow
            ), '') AS QtyDims
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN DocumentConfig dc WITH (NOLOCK)
            ON dc.DocType = cod.DocType
           AND dc.DocTypeArea = 'PLANING'
        JOIN DocumentStatus ds WITH (NOLOCK)
            ON ds.DocType = cod.DocType
           AND ds.DocStatusID = cod.ProductionStatus
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
        WHERE cod.ItemID = ?
          AND ds.AllowTransformation = 1
    """

    page_number = int(page_number or 0)
    page_size = int(page_size or 50)
    order_sql = "ORDER BY cod.OrderID DESC, cod.OrderRow"
    paging_sql = ""
    params: list[Any] = [item_id]

    if page_number > 0:
        paging_sql = " OFFSET (? - 1) * ? ROWS FETCH NEXT ? ROWS ONLY"
        params.extend([page_number, page_size, page_size])

    with db_cursor() as (cursor, _conn):
        total_count = 0
        if page_number > 0:
            cursor.execute(
                f"SELECT COUNT(*) Total FROM ({sql_base}) t",
                (item_id,),
            )
            total_count = int(cursor.fetchone()[0] or 0)

        cursor.execute(f"{sql_base}\n{order_sql}{paging_sql}", tuple(params))
        data = [_row_to_dict(cursor, row) for row in cursor.fetchall()]

    if page_number <= 0:
        total_count = len(data)

    return {
        "Data": data,
        "CurrentPage": page_number,
        "HasNextPage": (page_number * page_size) < total_count if page_number > 0 else False,
        "TotalRecordCount": total_count,
    }


def create_item_attachment(
    company: str,
    item_id: str,
    version: int,
    observation: str,
    user_id: str,
    file_name: str,
    file_content: bytes,
) -> dict[str, object]:
    if not file_content:
        raise ValueError("File is empty")

    normalized_file_name = file_name.strip()
    if not normalized_file_name:
        raise ValueError("FileName is required")

    file_name_without_extension = _file_stem(normalized_file_name)
    file_extension = _file_extension(normalized_file_name)
    creation_user = user_id.strip() or "API"

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            INSERT INTO OnS3_ATTACHMENTS.dbo.Attachments (
                FileBytes,
                FileName,
                FileExtension,
                DirectoryFile,
                isDirectory,
                FileBytesMiniature,
                FileBytesMedium
            )
            OUTPUT INSERTED.AttachmentId
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pyodbc.Binary(file_content),
                file_name_without_extension,
                file_extension,
                "",
                0,
                None,
                None,
            ),
        )
        attachment_id = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT ISNULL(MAX(Sequence), 0) + 1
            FROM OnS3_ATTACHMENTS.dbo.ItemMasterFileAttachments WITH (NOLOCK)
            WHERE Company = ?
              AND ItemID = ?
              AND Version = ?
            """,
            (company, item_id, version),
        )
        sequence = int(cursor.fetchone()[0] or 1)

        if _column_is_identity(cursor, "OnS3_ATTACHMENTS", "dbo", "ItemMasterFileAttachments", "ID"):
            cursor.execute(
                """
                INSERT INTO OnS3_ATTACHMENTS.dbo.ItemMasterFileAttachments (
                    Company,
                    ItemID,
                    Version,
                    Sequence,
                    Description,
                    Observation,
                    AttachmentNumber,
                    CreationDateTime,
                    CreationUser,
                    modifDateTime,
                    modifUser,
                    Deleted
                )
                OUTPUT INSERTED.ID
                VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, NULL, NULL, ?)
                """,
                (
                    company,
                    item_id,
                    version,
                    sequence,
                    file_name_without_extension,
                    observation,
                    attachment_id,
                    creation_user,
                    0,
                ),
            )
        else:
            cursor.execute(
                """
                SELECT ISNULL(MAX(ID), 0) + 1
                FROM OnS3_ATTACHMENTS.dbo.ItemMasterFileAttachments WITH (NOLOCK)
                """
            )
            association_id = int(cursor.fetchone()[0] or 1)
            cursor.execute(
                """
                INSERT INTO OnS3_ATTACHMENTS.dbo.ItemMasterFileAttachments (
                    Company,
                    ItemID,
                    Version,
                    ID,
                    Sequence,
                    Description,
                    Observation,
                    AttachmentNumber,
                    CreationDateTime,
                    CreationUser,
                    modifDateTime,
                    modifUser,
                    Deleted
                )
                OUTPUT INSERTED.ID
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, NULL, NULL, ?)
                """,
                (
                    company,
                    item_id,
                    version,
                    association_id,
                    sequence,
                    file_name_without_extension,
                    observation,
                    attachment_id,
                    creation_user,
                    0,
                ),
            )

        association_id = int(cursor.fetchone()[0])

    return {
        "Company": company,
        "ItemID": item_id,
        "Version": version,
        "ID": association_id,
        "Sequence": sequence,
        "AttachmentNumber": attachment_id,
        "OriginalFileName": normalized_file_name,
        "FileName": file_name_without_extension,
        "Description": file_name_without_extension,
        "FileExtension": file_extension,
        "CreationUser": creation_user,
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


def _add_filter(
    where_parts: list[str],
    params: list[Any],
    filters: dict[str, Any],
    key: str,
    clause: str,
    duplicate: bool = False,
) -> None:
    value = filters.get(key)
    if value is None:
        return

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return

    where_parts.append(clause)
    params.append(value)
    if duplicate:
        params.append(value)


def _itemmaster_order_by(sort_by: str) -> str:
    value = (sort_by or "").strip()
    if not value:
        return "ORDER BY ItemID"

    parts = value.split()
    column = parts[0]
    direction = parts[1].upper() if len(parts) > 1 else "ASC"
    if len(parts) > 2 or column not in ITEMMASTER_SORT_COLUMNS or direction not in {"ASC", "DESC"}:
        raise ValueError("Invalid SortBy value")

    return f"ORDER BY {ITEMMASTER_SORT_COLUMNS[column]} {direction}"


def _param_int(cursor, param_id: str, default: int) -> int:
    cursor.execute(
        "SELECT ParamValue FROM ParamValue WITH (NOLOCK) WHERE ParamID = ?",
        (param_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return default

    try:
        return int(str(row[0]).strip())
    except (TypeError, ValueError):
        return default


def _row_to_dict(cursor, row) -> dict[str, Any]:
    names = [column[0] for column in cursor.description]
    return {name: _json_value(value) for name, value in zip(names, row)}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _normalize_extension(file_extension: Optional[str]) -> str:
    if not file_extension:
        return ""

    normalized = file_extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"

    return normalized


def _file_extension(file_name: str) -> str:
    extension = ""
    if "." in file_name:
        extension = file_name.rsplit(".", 1)[1]
    return f".{extension.lower()}" if extension else ""


def _file_stem(file_name: str) -> str:
    if "." not in file_name:
        return file_name

    stem = file_name.rsplit(".", 1)[0].strip()
    return stem or file_name


def _column_is_identity(
    cursor,
    database_name: str,
    schema_name: str,
    table_name: str,
    column_name: str,
) -> bool:
    cursor.execute(
        """
        SELECT COLUMNPROPERTY(
            OBJECT_ID(? + '.' + ? + '.' + ?),
            ?,
            'IsIdentity'
        )
        """,
        (database_name, schema_name, table_name, column_name),
    )
    row = cursor.fetchone()
    return bool(row and row[0])


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
