from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.db.connection import db_cursor


def fetch_coonsumption_for_itemmaster_and_bpartner(
    item_id: str,
    doc_type_area: str,
    bp_id: str,
) -> list[dict[str, object]]:
    query = """
        WITH Opss AS (
            SELECT DISTINCT
                cod.DocType,
                cod.OrderID,
                cod.OrderRow,
                cod.ItemID,
                imc.CharacteristicValue AS Project
            FROM ClientOrderDetails cod WITH (NOLOCK)
            JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
                ON imc.ItemID = cod.ItemID
               AND imc.Version = cod.Versao
               AND imc.CharacteristicID = 'PROJETO'
            JOIN ClientOrders co WITH (NOLOCK)
                ON co.DocType = cod.DocType
               AND co.OrderID = cod.OrderID
            JOIN DocumentConfig dc WITH (NOLOCK)
                ON dc.DocType = co.DocType
               AND dc.DocTypeArea = ?
            WHERE cod.ItemID = ?
              AND co.SubContratado = ?
        ),
        Abast AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'ABST'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        ),
        Ret AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'RABS'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        ),
        Cons AS (
            SELECT cod.ItemID, o.Project, SUM(cod.QtyOrd) AS QtyTot
            FROM Opss o
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocTypeOri = o.DocType
               AND codo.OrderIDOri = o.OrderID
               AND codo.OrderRowOri = o.OrderRow
               AND codo.DocType = 'CONS'
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codo.DocType
               AND cod.OrderID = codo.OrderID
               AND cod.OrderRow = codo.OrderRow
            GROUP BY cod.ItemID, o.Project
        )
        SELECT
            abast.ItemID,
            abast.Project,
            isnull(abast.QtyTot, 0) AS QtyAbastecido,
            isnull(ret.QtyTot, 0) AS QtyRetorno,
            isnull(cons.QtyTot, 0) AS QtyConsumido
        FROM Abast abast
        LEFT JOIN Ret ret
            ON ret.ItemID = abast.ItemID
           AND ret.Project = abast.Project
        LEFT JOIN Cons cons
            ON cons.ItemID = abast.ItemID
           AND cons.Project = abast.Project
        ORDER BY abast.ItemID, abast.Project
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (doc_type_area, item_id, bp_id))
        rows = cursor.fetchall()

    return [
        {
            "ItemID": row[0],
            "Project": row[1],
            "QtyAbastecido": row[2],
            "QtyRetorno": row[3],
            "QtyConsumido": row[4],
        }
        for row in rows
    ]


def fetch_production_entries_by_dates(
    from_date: date,
    to_date: date,
) -> list[dict[str, object]]:
    query = """
        WITH Movs AS (
            SELECT DISTINCT
                CAST(co.OrderDateTime AS date) AS DateMov,
                co.DocType,
                co.OrderID,
                codo.DocTypeOri,
                codo.OrderIDOri,
                codop.ItemID,
                coop.ClientID,
                bp.PartnerName AS ClientName,
                bps.PartnerID AS SubcontratadoId,
                bps.PartnerName AS SubcontratadoName,
                cod.IDIntegration,
                co.IDIntegration AS ClientOrdersIDIntegration
            FROM ClientOrders co WITH (NOLOCK)
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = co.DocType
               AND cod.OrderID = co.OrderID
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocType = cod.DocType
               AND codo.OrderID = cod.OrderID
               AND codo.OrderRow = cod.OrderRow
            JOIN ClientOrderDetails codop WITH (NOLOCK)
                ON codop.DocType = codo.DocTypeOri
               AND codop.OrderID = codo.OrderIDOri
               AND codop.OrderRow = codo.OrderRowOri
            JOIN ClientOrders coop WITH (NOLOCK)
                ON coop.DocType = codop.DocType
               AND coop.OrderID = codop.OrderID
            JOIN BusinessPartners bp WITH (NOLOCK)
                ON bp.PartnerType = 'C'
               AND bp.PartnerID = coop.ClientID
            JOIN BusinessPartners bps WITH (NOLOCK)
                ON bps.PartnerType = 'S'
               AND bps.PartnerID = coop.SubContratado
            WHERE co.DocType = 'ENTP'
              AND co.OrderDateTime >= ?
              AND co.OrderDateTime <= ?
              AND SUBSTRING(cod.IDIntegration, 1, 2) <> 'SM'
        )
        SELECT
            m.DateMov,
            m.DocType,
            m.OrderID,
            m.DocTypeOri,
            m.OrderIDOri,
            m.ItemID,
            m.ClientID,
            m.ClientName,
            m.SubcontratadoId,
            m.SubcontratadoName,
            m.IDIntegration,
            m.ClientOrdersIDIntegration,
            (
                SELECT SUM(cod.QtyOrd)
                FROM ClientOrderDetails cod WITH (NOLOCK)
                WHERE cod.DocType = m.DocType
                  AND cod.OrderID = m.OrderID
            ) AS Qty
        FROM Movs m
        ORDER BY m.OrderID ASC
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (from_date, to_date))
        rows = cursor.fetchall()

    return [
        {
            "DateMov": row[0],
            "DocType": row[1],
            "OrderID": row[2],
            "DocTypeOri": row[3],
            "OrderIDOri": row[4],
            "ItemID": row[5],
            "ClientID": row[6],
            "ClientName": row[7],
            "SubcontratadoId": row[8],
            "SubcontratadoName": row[9],
            "IDIntegration": row[10],
            "ClientOrdersIDIntegration": row[11],
            "Qty": row[12],
        }
        for row in rows
    ]


def fetch_production_entrie_status(
    doc_type: str,
    order_id: int,
) -> list[dict[str, object]]:
    query = """
        WITH Movimento AS (
            SELECT DISTINCT
                CAST(sm.MovDateTime AS date) AS DataMov,
                bp.PartnerID,
                bp.GLNCode,
                bp.PartnerName,
                sm.ItemID,
                sm.ColorID,
                sm.SizeID,
                sm.Qty,
                codim.QtyOrd AS QtyOrigem,
                codo.DocTypeOri,
                codo.OrderIDOri,
                codo.OrderRowOri,
                cod.Versao,
                (
                    SELECT TOP 1 coentp.IDIntegration
                    FROM ClientOrderDetails coentp WITH (NOLOCK)
                    WHERE coentp.DocType = ?
                      AND coentp.OrderID = ?
                ) AS IdIntegration,
                ISNULL(imc.CharacteristicValue, '') AS ProjectCode
            FROM StockMov sm WITH (NOLOCK)
            JOIN ClientOrderDetailsOri codo WITH (NOLOCK)
                ON codo.DocType = sm.DocTypeOrig
               AND codo.OrderID = sm.DocOrig
            JOIN ClientOrdersDim codim WITH (NOLOCK)
                ON codim.DocType = codo.DocTypeOri
               AND codim.OrderID = codo.OrderIDOri
               AND codim.OrderRow = codo.OrderRowOri
               AND codim.SizeID = sm.SizeID
               AND codim.ColorID = sm.ColorID
            JOIN ClientOrderDetails cod WITH (NOLOCK)
                ON cod.DocType = codim.DocType
               AND cod.OrderID = codim.OrderID
               AND cod.OrderRow = codim.OrderRow
            JOIN ItemMaster im WITH (NOLOCK)
                ON im.ItemID = cod.ItemID
            LEFT JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
                ON imc.ItemID = cod.ItemID
               AND imc.Version = cod.Versao
               AND imc.CharacteristicID = 'PROJETO'
            JOIN ClientOrders co WITH (NOLOCK)
                ON co.DocType = cod.DocType
               AND co.OrderID = cod.OrderID
            JOIN BusinessPartners bp WITH (NOLOCK)
                ON bp.PartnerType = 'S'
               AND bp.PartnerID = co.Subcontratado
            WHERE sm.DocTypeOrig = ?
              AND sm.DocOrig = ?
        ),
        Componentes AS (
            SELECT
                mov.DataMov,
                mov.PartnerID AS SubcontratadoS3,
                mov.GLNCode AS SubcontratadoSap,
                mov.PartnerName AS SubcontratadoName,
                mov.ProjectCode,
                ic.ComponentID,
                mov.IdIntegration,
                ic.Qty * mov.Qty AS QtyMov,
                ic.Qty * mov.QtyOrigem AS QtyOri,
                mov.DocTypeOri AS OPSDocType,
                mov.OrderIDOri AS OPSOrderId,
                mov.OrderRowOri AS OPSOrderRow
            FROM Movimento mov
            JOIN ClientOrdersDim codim WITH (NOLOCK)
                ON codim.DocType = mov.DocTypeOri
               AND codim.OrderID = mov.OrderIDOri
               AND codim.OrderRow = mov.OrderRowOri
               AND codim.ColorID = mov.ColorID
               AND codim.SizeID = mov.SizeID
            JOIN ClientOrderComp coc WITH (NOLOCK)
                ON coc.DocType = mov.DocTypeOri
               AND coc.OrderID = mov.OrderIDOri
               AND coc.OrderRow = mov.OrderRowOri
            JOIN ItemComp ic WITH (NOLOCK)
                ON ic.ItemID = mov.ItemID
               AND ic.Versao = mov.Versao
               AND ic.ComponentID = coc.ComponentID
               AND ic.ItemGroupID = coc.ItemGroupID
               AND ic.ItemSubGroupID = coc.ItemSubGroupID
               AND ic.Variacao = 0
               AND ic.IsNeeded = 1

            UNION

            SELECT
                mov.DataMov,
                mov.PartnerID AS SubcontratadoS3,
                mov.GLNCode AS SubcontratadoSap,
                mov.PartnerName AS SubcontratadoName,
                mov.ProjectCode,
                ic.ComponentIDEsp AS ComponentID,
                mov.IdIntegration,
                ic.Qty * mov.Qty AS QtyMov,
                ic.Qty * mov.QtyOrigem AS QtyOri,
                mov.DocTypeOri AS OPSDocType,
                mov.OrderIDOri AS OPSOrderId,
                mov.OrderRowOri AS OPSOrderRow
            FROM Movimento mov
            JOIN ClientOrdersDim codim WITH (NOLOCK)
                ON codim.DocType = mov.DocTypeOri
               AND codim.OrderID = mov.OrderIDOri
               AND codim.OrderRow = mov.OrderRowOri
               AND codim.ColorID = mov.ColorID
               AND codim.SizeID = mov.SizeID
            JOIN ClientOrderComp coc WITH (NOLOCK)
                ON coc.DocType = mov.DocTypeOri
               AND coc.OrderID = mov.OrderIDOri
               AND coc.OrderRow = mov.OrderRowOri
            JOIN ItemCompEsp ic WITH (NOLOCK)
                ON ic.ItemID = mov.ItemID
               AND ic.Versao = mov.Versao
               AND ic.ComponentIDEsp = coc.ComponentID
               AND ic.ItemGroupID = coc.ItemGroupID
               AND ic.ItemSubGroupID = coc.ItemSubGroupID
               AND (ic.ColorID = mov.ColorID OR ic.ColorID = '')
               AND (ic.SizeID = mov.SizeID OR ic.SizeID = '')
            WHERE ic.Variacao <> 0
              AND ic.IsNeeded = 1
        ),
        Result AS (
            SELECT
                comp.DataMov,
                comp.SubcontratadoS3,
                comp.SubcontratadoSap,
                comp.SubcontratadoName,
                comp.ProjectCode,
                comp.ComponentID,
                SUM(comp.QtyMov) AS QtyTot,
                SUM(comp.QtyOri) AS QtyOri,
                im.StkUnit,
                im.ItemValue,
                comp.OPSDocType,
                comp.OPSOrderId,
                comp.OPSOrderRow,
                comp.IdIntegration
            FROM Componentes comp
            JOIN ItemMaster im WITH (NOLOCK)
                ON im.ItemID = comp.ComponentID
            GROUP BY
                comp.DataMov,
                comp.SubcontratadoS3,
                comp.SubcontratadoSap,
                comp.SubcontratadoName,
                comp.ProjectCode,
                comp.ComponentID,
                im.StkUnit,
                im.ItemValue,
                comp.OPSDocType,
                comp.OPSOrderId,
                comp.OPSOrderRow,
                comp.IdIntegration
        ),
        Final AS (
            SELECT
                r.*,
                ISNULL((
                    SELECT SUM(cod.QtyOrd)
                    FROM ClientOrderDetailsOri codo WITH (NOLOCK)
                    JOIN ClientOrderDetails cod WITH (NOLOCK)
                        ON cod.DocType = codo.DocType
                       AND cod.OrderID = codo.OrderID
                       AND cod.OrderRow = codo.OrderRow
                    WHERE codo.DocTypeOri = r.OPSDocType
                      AND codo.OrderIDOri = r.OPSOrderId
                      AND codo.OrderRowOri = r.OPSOrderRow
                      AND codo.DocType = 'CONS'
                      AND cod.ItemID = r.ComponentID
                ), 0) AS QtyCons
            FROM Result r
        )
        SELECT
            f.DataMov,
            f.SubcontratadoS3,
            f.SubcontratadoSap,
            f.SubcontratadoName,
            f.ProjectCode,
            f.ComponentID,
            f.QtyOri AS QtyNecOPS,
            f.QtyTot AS QtyPrevENTP,
            f.QtyCons AS QtyConsOPS,
            f.QtyOri - f.QtyCons AS QtyTot,
            f.StkUnit,
            f.ItemValue,
            f.OPSDocType,
            f.OPSOrderId,
            f.OPSOrderRow,
            f.IdIntegration
        FROM Final f
        ORDER BY f.ComponentID, f.OPSDocType, f.OPSOrderId, f.OPSOrderRow
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, (doc_type, order_id, doc_type, order_id))
        rows = cursor.fetchall()
        columns = [str(column[0]) for column in cursor.description]

    return [dict(zip(columns, row)) for row in rows]


def fetch_consumption_context(item_id: str, project: str, subcontract_id: str) -> dict[str, Any]:
    del project  # Kept in contract for future filtering parity with legacy code.

    context = fetch_subcontractor_consumption_context(subcontract_id)

    origin_query = """
        SELECT TOP 1 cod.DocType, cod.OrderID, cod.OrderRow
        FROM ClientOrderDetails cod WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = cod.DocType
           AND co.OrderID = cod.OrderID
           AND co.SubContratado = ?
        WHERE cod.ItemID = ?
        ORDER BY cod.OrderID DESC, cod.OrderRow DESC
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(origin_query, (context["subcontract_partner_id"], item_id))
        origin_row = cursor.fetchone()

        if not origin_row:
            raise ValueError(
                "No origin OPS document was found for the supplied ItemId and PartnerID"
            )

    context.update(
        {
            "origin_doc_type": str(origin_row[0]),
            "origin_order_id": int(origin_row[1]),
            "origin_order_row": int(origin_row[2]),
        }
    )
    return context


def fetch_subcontractor_consumption_context(subcontract_id: str) -> dict[str, Any]:
    normalized_subcontract_id = subcontract_id.strip()
    if not normalized_subcontract_id:
        raise ValueError("PartnerID is required to resolve subcontractor context")

    subcontract_resolve_query = """
        SELECT TOP 1 bp.PartnerID, bp.GLNCode
        FROM BusinessPartners bp WITH (NOLOCK)
        WHERE bp.PartnerType = 'S'
          AND (
              bp.PartnerID = ?
              OR bp.GLNCode = ?
          )
        ORDER BY CASE WHEN bp.PartnerID = ? THEN 0 ELSE 1 END, bp.PartnerID
    """

    with db_cursor() as (cursor, _conn):
        cursor.execute(
            subcontract_resolve_query,
            (normalized_subcontract_id, normalized_subcontract_id, normalized_subcontract_id),
        )
        subcontract_row = cursor.fetchone()
        if not subcontract_row:
            raise ValueError(
                "No subcontractor was found for the supplied PartnerID "
                "(expected BusinessPartners.PartnerID or BusinessPartners.GLNCode)"
            )

        resolved_subcontract_id = str(subcontract_row[0]).strip()
        resolved_gln_code = str(subcontract_row[1] or "").strip()

    if not resolved_gln_code:
        raise ValueError("No consumption location (GLNCode) was found for the supplied PartnerID")

    return {
        "subcontract_partner_id": resolved_subcontract_id,
        "local_consumo": f"200-{resolved_gln_code}",
    }


def fetch_component_metadata(component_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not component_ids:
        return {}

    placeholders = ",".join("?" for _ in component_ids)
    with db_cursor() as (cursor, _conn):
        try:
            cursor.execute(
                f"""
                SELECT ItemID, ISNULL(StkUnit, 'UN') AS StkUnit, ISNULL(ItemValue, 0) AS ItemValue
                FROM ItemMaster WITH (NOLOCK)
                WHERE ItemID IN ({placeholders})
                """,
                tuple(component_ids),
            )
            rows = cursor.fetchall()
        except Exception:
            cursor.execute(
                f"""
                SELECT ItemID, ISNULL(StkUnit, 'UN') AS StkUnit
                FROM ItemMaster WITH (NOLOCK)
                WHERE ItemID IN ({placeholders})
                """,
                tuple(component_ids),
            )
            rows = cursor.fetchall()
            return {
                str(row[0]).upper(): {"StkUnit": str(row[1]), "ItemValue": Decimal("0")}
                for row in rows
            }

    return {
        str(row[0]).upper(): {
            "StkUnit": str(row[1]) if row[1] else "UN",
            "ItemValue": _to_decimal(row[2]),
        }
        for row in rows
    }


def create_local_consumption_document(
    partner_id: str,
    movement_date: date,
    location_code: str,
    origin_doc_type: str,
    origin_order_id: int,
    origin_order_row: int,
    sap_doc_type: str,
    sap_doc_num: int | None,
    lines: list[dict[str, Any]],
    component_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not lines:
        raise ValueError("Cannot create local consumption document without lines")

    with db_cursor() as (cursor, _conn):
        cache: dict[str, dict[str, str]] = {}
        now = datetime.now()
        movement_dt = datetime.combine(movement_date, datetime.min.time())

        order_id = _next_doc_order_id(cursor, "CONS")
        sap_obs = f"{sap_doc_type}.{sap_doc_num}" if sap_doc_num is not None else sap_doc_type

        total_qty = sum(_to_decimal(line["qty_applied"]) for line in lines)
        total_value = Decimal("0")

        header_values = {
            "DocType": "CONS",
            "OrderID": order_id,
            "PartNum": 0,
            "CreateDateTime": now,
            "OrderDateTime": movement_dt,
            "PartnerID": partner_id,
            "ClientID": partner_id,
            "RequesterID": partner_id,
            "RouteID": "",
            "Status": 0,
            "PepStatus": 0,
            "ProductionStatus": "INICIAL",
            "OrderDatePrev": now,
            "Obs": sap_obs,
            "CreationUser": "OnS3",
            "CreationDateTime": now,
            "Currency": "EUR",
            "ExangeRate": 1,
            "ExchangeRate": 1,
            "TotalQtyOrd": float(total_qty),
            "TotalValue": 0,
            "TotalShipValue": 0,
            "Tipo": 0,
            "PercDsc2": 0,
            "CreditApproved": 0,
            "UrgencyStatusID": 0,
            "ConsignmentDoc": 0,
            "RecuseDoc": 0,
            "PartnerCategory": "S",
        }
        _insert_dynamic(
            cursor,
            "ClientOrders",
            header_values,
            required_columns={"DocType", "OrderID"},
            cache=cache,
        )

        cursor.execute(
            """
            SELECT ISNULL(MAX(OrderRow), 0)
            FROM ClientOrderDetails
            WHERE DocType = 'CONS' AND OrderID = ?
            """,
            (order_id,),
        )
        next_order_row = int(cursor.fetchone()[0]) + 1

        persisted_lines: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            order_row = next_order_row + index
            item_id = str(line["component_id"]).upper().strip()
            qty = _quantize_5(_to_decimal(line["qty_applied"]))

            metadata = component_metadata.get(item_id, {})
            stk_unit = str(metadata.get("StkUnit") or "UN")
            item_value = _to_decimal(metadata.get("ItemValue", 0))
            total_line_value = _quantize_5(item_value * qty)
            total_value += total_line_value

            detail_values = {
                "DocType": "CONS",
                "OrderID": order_id,
                "OrderRow": order_row,
                "PartNum": 0,
                "VolNum": 0,
                "ItemID": item_id,
                "QtyProd": float(qty),
                "QtyOrdered": float(qty),
                "QtyOrd": float(qty),
                "Unit": stk_unit,
                "UnitPrice": float(item_value),
                "ItemValue": float(item_value),
                "QtyPicked": 0,
                "QtyPVolume": 0,
                "Location": location_code,
                "Status": 0,
                "ActivePickingId": 0,
                "Descount": 0,
                "PercCstAdic": 0,
                "Currency": "EUR",
                "ExchangeRate": 1,
                "ExangeRate": 1,
                "ColorID": "UN",
                "GRidID": "UN",
                "GridID": "UN",
                "DocTypeOri": origin_doc_type,
                "OrderIdORi": origin_order_id,
                "OrderIDOri": origin_order_id,
                "OrderRowOri": origin_order_row,
                "PartNumOri": 0,
                "Version": 0,
                "Versao": 0,
                "Totvalue": float(total_line_value),
                "TotValue": float(total_line_value),
                "ProductionStatus": "INICIAL",
                "CreationUser": "OnS3",
                "CreationDateTime": now,
                "QtySatisf": 0,
                "QtyVols": 0,
                "IDIntegration": "",
                "RefCli": "",
            }
            _insert_dynamic(
                cursor,
                "ClientOrderDetails",
                detail_values,
                required_columns={"DocType", "OrderID", "OrderRow", "ItemID"},
                cache=cache,
            )

            ori_values = {
                "DocType": "CONS",
                "OrderID": order_id,
                "OrderRow": order_row,
                "PartNum": 0,
                "VolNum": 0,
                "DocTypeOri": origin_doc_type,
                "OrderIDOri": origin_order_id,
                "OrderRowOri": origin_order_row,
                "PartNumOri": 0,
                "VolNumOri": 0,
                "QtyOrd": 0,
                "QtyVols": 0,
                "QtyOrdDest": 0,
            }
            _insert_dynamic(
                cursor,
                "ClientOrderDetailsOri",
                ori_values,
                required_columns={"DocType", "OrderID", "OrderRow"},
                cache=cache,
            )

            inherited_origin = _fetch_detail_origin(
                cursor,
                doc_type=origin_doc_type,
                order_id=origin_order_id,
                order_row=origin_order_row,
            )
            if inherited_origin is not None:
                inherited_ori_values = {
                    **ori_values,
                    "DocTypeOri": inherited_origin["doc_type_ori"],
                    "OrderIDOri": inherited_origin["order_id_ori"],
                    "OrderRowOri": inherited_origin["order_row_ori"],
                    "PartNumOri": inherited_origin["part_num_ori"],
                    "VolNumOri": inherited_origin["vol_num_ori"],
                }
                _insert_dynamic(
                    cursor,
                    "ClientOrderDetailsOri",
                    inherited_ori_values,
                    required_columns={"DocType", "OrderID", "OrderRow"},
                    cache=cache,
                )

            mov_id = _insert_stock_movement(
                cursor=cursor,
                cache=cache,
                movement_dt=movement_dt,
                location_code=location_code,
                order_id=order_id,
                order_row=order_row,
                origin_doc_type=origin_doc_type,
                origin_order_id=origin_order_id,
                item_id=item_id,
                qty=qty,
                move_unit=stk_unit,
                unit_value=item_value,
            )

            apply_inventory_output(
                cursor=cursor,
                cache=cache,
                movement_dt=movement_dt,
                item_id=item_id,
                whid=200,
                location_id=location_code,
                qty=qty,
                mov_id=mov_id,
            )

            if mov_id is not None:
                _update_detail_movement_id(cursor, cache, mov_id, order_id, order_row)

            persisted_lines.append(
                {
                    "component_id": item_id,
                    "qty_applied": qty,
                    "order_row": order_row,
                    "mov_id": mov_id,
                }
            )

        if total_value > 0:
            client_orders_columns = _table_columns(cursor, "ClientOrders", cache)
            if "totalvalue" in client_orders_columns:
                cursor.execute(
                    f"""
                    UPDATE ClientOrders
                    SET {client_orders_columns['totalvalue']} = ?
                    WHERE DocType = 'CONS' AND OrderID = ?
                    """,
                    (float(_quantize_5(total_value)), order_id),
                )

    return {
        "doc_type": "CONS",
        "order_id": order_id,
        "lines": persisted_lines,
    }


def _next_doc_order_id(cursor, doc_type: str) -> int:
    year = datetime.now().year
    base = year * 1000000
    cursor.execute(
        """
        SELECT ISNULL(MAX(OrderID), ?)
        FROM ClientOrders
        WHERE OrderID >= ? AND DocType = ?
        """,
        (base, base, doc_type),
    )
    return int(cursor.fetchone()[0]) + 1


def _fetch_detail_origin(
    cursor,
    doc_type: str,
    order_id: int,
    order_row: int,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT TOP 1
            DocTypeOri,
            OrderIDOri,
            OrderRowOri,
            PartNumOri,
            VolNumOri
        FROM ClientOrderDetailsOri WITH (NOLOCK)
        WHERE DocType = ?
          AND OrderID = ?
          AND OrderRow = ?
        ORDER BY OrderRowOri
        """,
        (doc_type, order_id, order_row),
    )
    row = cursor.fetchone()
    if not row:
        return None

    return {
        "doc_type_ori": str(row[0]),
        "order_id_ori": int(row[1]),
        "order_row_ori": int(row[2]),
        "part_num_ori": int(row[3] or 0),
        "vol_num_ori": int(row[4] or 0),
    }


def _table_columns(
    cursor,
    table_name: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    if table_name in cache:
        return cache[table_name]

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        """,
        (table_name,),
    )
    rows = cursor.fetchall()
    columns = {str(row[0]).lower(): str(row[0]) for row in rows}
    cache[table_name] = columns
    return columns


def _insert_dynamic(
    cursor,
    table_name: str,
    values: dict[str, Any],
    required_columns: set[str],
    cache: dict[str, dict[str, str]],
) -> None:
    columns = _table_columns(cursor, table_name, cache)
    if not columns:
        raise ValueError(f"Table '{table_name}' does not exist or has no visible columns")

    selected_columns: list[str] = []
    params: list[Any] = []
    selected_normalized: set[str] = set()

    for key, value in values.items():
        normalized = key.lower()
        if normalized not in columns:
            continue
        if normalized in selected_normalized:
            continue
        selected_columns.append(columns[normalized])
        params.append(value)
        selected_normalized.add(normalized)

    missing_required = [
        col for col in required_columns if col.lower() not in {c.lower() for c in selected_columns}
    ]
    if missing_required:
        raise ValueError(
            f"Cannot insert into '{table_name}'. Missing required columns in DB: "
            + ", ".join(sorted(missing_required))
        )

    if not selected_columns:
        raise ValueError(f"No matching columns found to insert into '{table_name}'")

    placeholders = ", ".join("?" for _ in selected_columns)
    sql = f"INSERT INTO {table_name} ({', '.join(selected_columns)}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(params))


def _insert_stock_movement(
    cursor,
    cache: dict[str, dict[str, str]],
    movement_dt: datetime,
    location_code: str,
    order_id: int,
    order_row: int,
    origin_doc_type: str,
    origin_order_id: int,
    item_id: str,
    qty: Decimal,
    move_unit: str,
    unit_value: Decimal,
) -> int | None:
    columns = _table_columns(cursor, "StockMov", cache)
    if not columns:
        return None

    explicit_mov_id: int | None = None
    if "movid" in columns:
        cursor.execute("SELECT ISNULL(MAX(MovID), 0) + 1 FROM StockMov WITH (UPDLOCK, HOLDLOCK)")
        explicit_mov_id = int(cursor.fetchone()[0])

    values: dict[str, Any] = {
        "MovDateTime": movement_dt,
        "MoveDateTime": movement_dt,
        "ItemID": item_id,
        "MovType": "O",
        "MovDir": "O",
        "MoveDirection": "Output",
        "WHIDOrig": 200,
        "LocOrig": location_code,
        "LocationOrig": location_code,
        "WHIDDest": 0,
        "LocDest": "",
        "LocationDest": "",
        "Qty": float(qty),
        "Quantity": float(qty),
        "Unit": move_unit,
        "MoveUnit": move_unit,
        "MovUnit": move_unit,
        "DocTypeOrig": "CONS",
        "DocOrig": order_id,
        "DocRowOrig": order_row,
        "EquipmentID": 0,
        "UserID": "OnS3",
        "Obs": f"{origin_doc_type}.{origin_order_id}",
        "UnitValue": float(unit_value),
        "TotValue": float(_quantize_5(qty * unit_value)),
        "Lot": "",
        "SerialNum": "",
        "SerialNumber": "",
        "VolNum": 0,
    }
    if explicit_mov_id is not None:
        values["MovID"] = explicit_mov_id

    try:
        _insert_dynamic(cursor, "StockMov", values, required_columns={"ItemID"}, cache=cache)
    except Exception as exc:
        if explicit_mov_id is None or "identity" not in str(exc).lower():
            raise

        # Identity column scenario: retry without explicit MovID.
        values.pop("MovID", None)
        _insert_dynamic(cursor, "StockMov", values, required_columns={"ItemID"}, cache=cache)
        explicit_mov_id = None

    if "movid" not in columns:
        return None

    if explicit_mov_id is not None:
        return explicit_mov_id

    try:
        cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS BIGINT)")
        row = cursor.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        pass

    cursor.execute("SELECT ISNULL(MAX(MovID), 0) FROM StockMov WITH (NOLOCK)")
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _update_detail_movement_id(
    cursor,
    cache: dict[str, dict[str, str]],
    mov_id: int,
    order_id: int,
    order_row: int,
) -> None:
    columns = _table_columns(cursor, "ClientOrderDetails", cache)
    mov_col = columns.get("movid")
    if not mov_col:
        return

    cursor.execute(
        f"""
        UPDATE ClientOrderDetails
        SET {mov_col} = ?
        WHERE DocType = 'CONS' AND OrderID = ? AND OrderRow = ?
        """,
        (mov_id, order_id, order_row),
    )


def apply_inventory_output(
    cursor,
    cache: dict[str, dict[str, str]],
    movement_dt: datetime,
    item_id: str,
    whid: int,
    location_id: str,
    qty: Decimal,
    mov_id: int | None,
) -> None:
    inventory_columns = _table_columns(cursor, "Inventory", cache)
    qty_col = inventory_columns.get("qty")
    last_output_col = inventory_columns.get("lastoutput")
    if not qty_col:
        raise ValueError("Inventory table is missing required Qty column")
    if not last_output_col:
        raise ValueError("Inventory table is missing required LastOutput column")

    set_parts = [
        f"{qty_col} = {qty_col} - ?",
        f"{last_output_col} = ?",
    ]
    params: list[Any] = [float(_quantize_5(qty)), movement_dt]

    last_move_col = inventory_columns.get("lastmoveid")
    if last_move_col and mov_id is not None:
        set_parts.append(f"{last_move_col} = ?")
        params.append(mov_id)

    params.extend([item_id, whid, location_id])
    sql = f"""
        UPDATE Inventory
        SET {', '.join(set_parts)}
        WHERE ItemID = ?
          AND WHID = ?
          AND LocationID = ?
    """
    cursor.execute(sql, tuple(params))
    if cursor.rowcount == 0:
        raise ValueError(
            "No inventory row found for ItemID/WHID/LocationID to apply output "
            f"({item_id}, {whid}, {location_id})"
        )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _quantize_5(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
