from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.connection import db_cursor


ORDER_QUERY_TEMPLATE = """
    SELECT co.DocType, co.OrderID, co.PartNum, co.OrderDateTime,
        ISNULL(co.RequesterID,'') RequesterID, co.ClientID, co.RouteID,
        co.ShippingCompanyID, co.Status, co.PepStatus, co.TotalQtyOrd,
        co.TotalQtyPend, co.CreationUser, co.CreationDateTime, co.ModifUser,
        co.ModifDateTime, co.ProductionStatus, co.OrderDatePrev,
        ISNULL(co.Obs,'') Obs, co.ObsInternal, bp.PartnerName,
        ISNULL(ISNULL(NULLIF(ISNULL(co.ResponsibleUserID,''),''),bp.ResponsibleUserID),'') ResponsibleUserID,
        co.OrderColor, co.PartnerName DocPartnerName, co.PartnerName2 DocPartnerName2,
        co.Address, co.PostalCode, co.City, co.Country, ISNULL(c.Description, co.Country) CountryName,
        co.Tipo, co.Email, co.Phone, co.SubContratado, co.SubContratadoLine,
        co.OrderDatePrevReal, co.Capacity, co.LeadTime, co.Growth, co.Consume,
        co.Nworkers, ISNULL(co.PaymentType,'') PaymentType, co.FinancialDiscount,
        co.Currency, co.ExangeRate, co.PercDsc, co.PercDsc2, ISNULL(co.SalesCondType, '') SalesCondType,
        co.TotalValue, co.TotalShipValue, co.UsedCreditValue, co.UrgencyStatusID,
        co.BarCode, co.ConsignmentDoc, co.RecuseDoc, co.TrackingNumber, co.IDIntegration,
        ds.IsInicial, ds.IsProcessing, ds.IsFinal, ds.IsAnulated, co.LoadPartnerName,
        co.LoadPartnerName2, co.LoadAddress, co.LoadPostalCode, co.LoadCity, co.LoadCountry,
        ISNULL(c2.Description, co.LoadCountry) LoadCountryName, co.LoadEmail, co.LoadPhone,
        co.LicensePlate, co.LoadDate, co.DeliveryDate, co.CreditApproved,
        ISNULL(co.CreditApprovedByUser,'') CreditApprovedByUser, co.CreditApprovedDate,
        co.IncludedOnCreditValue, co.OrderDateAgreedWithPartner, ISNULL(co.AgentCode, '') AgentCode,
        ISNULL(co.AgentCommission, 0) AgentCommission, co.PartnerCategory, co.VIESValidated,
        co.VIESValidationUserID, co.VIESValidationDate, co.VIESValidationMsg, co.ContactName,
        co.ContactEmail, co.ContactPhone, co.ContactMobilePhone, co.ExternalSystemIntegrated,
        co.Confirmed, co.ConfirmedByUser, co.ConfirmedDate, {project_code_select},
        (
            SELECT TOP 1 u.Emails
            FROM ClientOrderDetails cod WITH (NOLOCK)
            JOIN ItemMaster im WITH (NOLOCK) ON im.ItemID = cod.ItemID
            JOIN Users u WITH (NOLOCK) ON u.UserID = im.CreationUser
            WHERE cod.DocType = ? AND cod.OrderID = ?
        ) ConfirmedByUserEmail
    FROM ClientOrders co WITH (NOLOCK)
    JOIN DocumentStatus ds WITH (NOLOCK) ON ds.DocType = co.DocType AND ds.DocStatusID = co.ProductionStatus
    JOIN DocumentConfig dc WITH (NOLOCK) ON co.DocType = dc.DocType
    JOIN BusinessPartners bp WITH (NOLOCK) ON co.ClientID = bp.PartnerID AND bp.PartnerType = dc.PartnerType
    LEFT JOIN Countries c WITH (NOLOCK) ON c.Country = co.Country
    LEFT JOIN Countries c2 WITH (NOLOCK) ON c2.Country = co.LoadCountry
    WHERE co.DocType = ? AND co.OrderID = ?
"""


LINES_QUERY = """
    SELECT cod.DocType, cod.OrderID, cod.OrderRow, cod.PartNum, cod.ItemID,
        im.ItemDesc, cod.VolNum, cod.VolTypeID, cod.WHID, cod.WHIDOrig,
        cod.LocationIDOri, cod.LocationIDDest, cod.SerialNum, cod.InvVolNum,
        cod.width, cod.OrderRowOri, cod.OrderIDOri, cod.PartNumOri, cod.PercDescp,
        cod.PerCstAdic, cod.Phone, cod.PiecePartId, cod.POClient, cod.ColorDescr,
        cod.PostalCode, cod.ProductionStatus, cod.QtyDefIN, cod.QtyDefOUT,
        cod.QtyOrd, cod.QtyPend, cod.QtyPicked, cod.QtyProd, cod.QtyPVol,
        cod.QtySatisf, cod.QtyVols, cod.QtyWithDescount, cod.RateIncrease,
        cod.RecipientName, cod.RefCli, cod.RETax, ISNULL(cod.SalesCondType, '') SalesCondType,
        cod.ShippingCountry, cod.SizeMix, cod.StartConfectionDate,
        cod.StartConfectionDatePlanedInitial, cod.Status, cod.SubContratado,
        cod.SubContratadoLine, cod.Sync, cod.TotValue, cod.TransportTypeID,
        cod.Unit, cod.UnitConvFact, cod.UnitPrice, cod.UnitStk, cod.VariationCountry,
        cod.Versao, ISNULL(imdv.VersionName, '') VersionName, cod.VolDocCod,
        cod.ItemMix, cod.ItemSubGroupId, cod.IVA, cod.LeadTime, cod.length,
        cod.Location, cod.LoteMix, cod.MovID, cod.Obs, cod.ObsInternal,
        cod.offer, cod.DocTypeOri, cod.Email, cod.EndConfectionDate,
        cod.EndConfectionDateReal, cod.ExangeRate, cod.GridID, cod.Growth,
        cod.IDIntegration, cod.ItemDesc1, cod.ItemDesc2, cod.Itemgroupid,
        cod.ActivePickingID, cod.Address, cod.AddressID, ISNULL(cod.AgentCode, '') AgentCode,
        ISNULL(cod.AgentCommission, 0) AgentCommission, cod.AssignedUser, cod.Cadencia,
        cod.Capacity, cod.City, cod.ColorID, cod.ColorMix, cod.CountriesMix,
        cod.Consume, cod.Currency, cod.CurrencyExangeDate, cod.UnitConvFact,
        cod.Descount, ISNULL(cod.PriorityIndex, 0) PriorityIndex, cod.Unit,
        cod.UnitStk, cod.TotalNetPrice, cod.TotalGrossPrice, cod.TotalDiscountValue,
        cod.ItemIDTransform, cod.VersionTransform, cod.AddictionalCostsValue,
        cod.VATAddictionalCostsValue, cod.ValueDistribuctionType, cod.LotExpirationDate,
        cod.IDIntegration, cod.ExternalSystemIntegrated, cod.CreationUser,
        cod.CreationDateTime, cod.ModifDateTime, cod.ModifUser, ds.IsInicial,
        ds.IsProcessing, ds.IsFinal, ds.IsAnulated, ISNULL(imc.CharacteristicValue, '') Project
    FROM ClientOrderDetails cod WITH (NOLOCK)
    JOIN DocumentStatus ds WITH (NOLOCK) ON ds.DocType = cod.DocType AND ds.DocStatusID = cod.ProductionStatus
    JOIN ItemMaster im WITH (NOLOCK) ON cod.ItemID = im.ItemID
    LEFT JOIN ItemMasterCharacteristics imc WITH (NOLOCK)
        ON imc.ItemID = im.ItemID
       AND imc.CharacteristicID = 'PROJETO'
       AND imc.Version = cod.Versao
    LEFT JOIN ItemMasterDetailsVersion imdv WITH (NOLOCK)
        ON imdv.ItemID = cod.ItemID
       AND imdv.Version = cod.Versao
    WHERE cod.DocType = ? AND cod.OrderID = ?
    ORDER BY cod.OrderRow
"""


COMPONENTS_BY_DOCUMENT_COLOR_QUERY = """
    SET NOCOUNT ON;

    IF OBJECT_ID('tempdb..#ic') IS NOT NULL
        DROP TABLE #ic;

    DECLARE @itemid AS varchar(50) = '';
    DECLARE @Versao AS int = 0;

    SELECT TOP (1)
        @itemid = ItemID,
        @Versao = Versao
    FROM ClientOrderDetails WITH (NOLOCK)
    WHERE DocType = ?
      AND OrderID = ?
      {detail_order_row_clause}
    ORDER BY OrderRow;

    SELECT
        MAX(RollWidth) RollWidth,
        MAX(ShrinkInY) ShrinkInY,
        MAX(ShrinkInX) ShrinkInX,
        MAX(QtyByCad) QtyByCad,
        ComponentID,
        ItemGroupId,
        ItemSubGroupId
    INTO #ic
    FROM (
        SELECT
            ISNULL(ic.RollWidth, 0) RollWidth,
            ISNULL(ic.ShrinkInY, 0) ShrinkInY,
            ISNULL(ic.ShrinkInX, 0) ShrinkInX,
            ISNULL(ic.QtyByCad, 0) QtyByCad,
            ic.ComponentID,
            ic.ItemGroupId,
            ic.ItemSubGroupId
        FROM ItemComp ic WITH (NOLOCK)
        WHERE ic.ItemID = @itemid
          AND ic.Versao = @Versao

        UNION ALL

        SELECT
            ISNULL(ic.RollWidth, 0) RollWidth,
            ISNULL(ic.ShrinkInY, 0) ShrinkInY,
            ISNULL(ic.ShrinkInX, 0) ShrinkInX,
            ISNULL(ic.QtyByCad, 0) QtyByCad,
            ic.ComponentIDEsp ComponentID,
            ic.ItemGroupId,
            ic.ItemSubGroupId
        FROM ItemCompEsp ic WITH (NOLOCK)
        WHERE ic.ItemID = @itemid
          AND ic.Versao = @Versao
    ) x
    GROUP BY ComponentID, ItemGroupId, ItemSubGroupId;

    SELECT
        ItemID,
        Versao,
        DocType,
        OrderID,
        ItemGroupID,
        ItemSubGroupId,
        ItemGroupDescr,
        ItemSubGroupDescr,
        ColorID,
        ComponentID,
        MAX(UnitQty) UnitQty,
        SUM(TotQty) TotQty,
        SUM(QtySatisf) QtySatisf,
        SUM(StockQty) StockQty,
        MAX(UnitPrice) UnitPrice,
        SUM(OrderBuyQtyOrd) OrderBuyQtyOrd,
        SUM(OrderBuyQtyRec) OrderBuyQtyRec,
        MAX(RollWidth) RollWidth,
        MAX(ShrinkInY) ShrinkInY,
        MAX(ShrinkInX) ShrinkInX,
        MAX(QtyByCad) QtyByCad,
        MAX(Obs) Obs,
        SUM(QtEstendida) QtEstendida,
        SUM(QtRetalho) QtRetalho,
        SUM(QtSobra) QtSobra,
        SUM(QtyRetAbast) QtyRetAbast,
        SUM(QtyAbast) QtyAbast,
        SUM(QtyFaltaMts) QtyFaltaMts,
        SUM(QtParaFitas) QtParaFitas,
        SUM(QtDefeito) QtDefeitos
    FROM (
        SELECT
            cod.ItemID,
            cod.Versao,
            coc.DocType,
            coc.OrderID,
            coc.OrderRow,
            cod.ColorID,
            coc.PartNum,
            coc.ItemGroupID,
            coc.ItemSubGroupId,
            coc.Sequence,
            coc.ComponentID,
            coc.Obs,
            coc.UnitQty,
            coc.TotQty,
            coc.QtySatisf,
            coc.StockQty,
            coc.LoteId,
            coc.WhOriId,
            coc.WhLocOriId,
            coc.WhDestId,
            coc.WhLocDestId,
            coc.UnitPrice,
            coc.Status,
            coc.OrderBuyDocType,
            coc.OrderBuyOrderID,
            coc.OrderBuyOrderRow,
            coc.OrderBuyDataPrev,
            coc.PartnerID,
            coc.UnitPriceReal,
            coc.OrderBuyQtyOrd,
            coc.OrderBuyQtyRec,
            coc.OrderBuyDataRec,
            coc.PerDesperdicio,
            coc.ModifUser,
            coc.ModifDateTime,
            coc.Unit,
            coc.NumTimesApplicable,
            coc.EstadoComponente,
            coc.PerCustoAdic,
            coc.Width,
            coc.Currency,
            coc.ExchangeRate,
            coc.RefSupplier,
            coc.RefSupplierDescr,
            coc.UnitSupplier,
            coc.ObsShops,
            coc.CreationUser,
            coc.CreationDateTime,
            ig.ItemGroupDescr,
            isg.ItemSubGroupDescr,
            ISNULL(ic.RollWidth, 0) RollWidth,
            ISNULL(ic.ShrinkInY, 0) ShrinkInY,
            ISNULL(ic.ShrinkInX, 0) ShrinkInX,
            ISNULL(ic.QtyByCad, 0) QtyByCad,
            ISNULL((
                SELECT SUM(x.Qty)
                FROM (
                    SELECT SUM(codsmov.QtyOrd) Qty
                    FROM ClientOrderDetailsOri codo WITH (NOLOCK)
                    JOIN ClientOrderDetails codsmov WITH (NOLOCK)
                        ON codsmov.DocType = codo.DocType
                       AND codsmov.OrderID = codo.OrderID
                       AND codsmov.OrderRow = codo.OrderRow
                    WHERE codo.DocTypeOri = cod.DocType
                      AND codo.OrderIDOri = cod.OrderID
                      AND codo.OrderRowOri = cod.OrderRow
                      AND codo.DocType = 'ABST'
                      AND codsmov.ItemID = coc.ComponentID
                ) x
            ), 0) QtyAbast,
            ISNULL((
                SELECT SUM(x.Qty)
                FROM (
                    SELECT SUM(codsmov.QtyOrd) Qty
                    FROM ClientOrderDetailsOri codo WITH (NOLOCK)
                    JOIN ClientOrderDetails codsmov WITH (NOLOCK)
                        ON codsmov.DocType = codo.DocType
                       AND codsmov.OrderID = codo.OrderID
                       AND codsmov.OrderRow = codo.OrderRow
                    WHERE codo.DocTypeOri = cod.DocType
                      AND codo.OrderIDOri = cod.OrderID
                      AND codo.OrderRowOri = cod.OrderRow
                      AND codo.DocType = 'RABS'
                      AND codsmov.ItemID = coc.ComponentID
                ) x
            ), 0) QtyRetAbast,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'ESTENDIMENTO'
            ), 0) QtEstendida,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'RETALHOS'
            ), 0) QtRetalho,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'SOBRAS'
            ), 0) QtSobra,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'faltamts'
            ), 0) QtyFaltaMts,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'parafitas'
            ), 0) QtParaFitas,
            ISNULL((
                SELECT SUM(wed.ProductionQty)
                FROM WorkerEventDate wed WITH (NOLOCK)
                WHERE wed.DocType = cod.DocType
                  AND wed.OrderID = cod.OrderID
                  AND wed.OrderRow = cod.OrderRow
                  AND wed.ItemID = cod.ItemID
                  AND wed.EventID = 'defeito'
            ), 0) QtDefeito
        FROM ClientOrderComp coc WITH (NOLOCK)
        JOIN ClientOrderDetails cod WITH (NOLOCK)
            ON cod.DocType = coc.DocType
           AND cod.OrderID = coc.OrderID
           AND cod.OrderRow = coc.OrderRow
        JOIN ItemGroup ig WITH (NOLOCK)
            ON ig.ItemGroupID = coc.ItemGroupID
        JOIN ItemSubGroup isg WITH (NOLOCK)
            ON isg.ItemGroupID = coc.ItemGroupID
           AND isg.ItemSubGroupID = coc.ItemSubGroupID
        JOIN #ic ic
            ON ic.ComponentID = coc.ComponentID
           AND ic.ItemGroupID = coc.ItemGroupID
           AND ic.ItemSubGroupID = coc.ItemSubGroupID
        WHERE coc.DocType = ?
          AND coc.OrderID = ?
          {component_order_row_clause}
          {color_id_clause}
          {component_id_clause}
    ) Componentes
    GROUP BY
        ItemID,
        Versao,
        DocType,
        OrderID,
        ItemGroupID,
        ItemSubGroupId,
        ItemGroupDescr,
        ItemSubGroupDescr,
        ColorID,
        ComponentID
    ORDER BY ItemGroupID, ItemSubGroupId, ComponentID;
"""


CAD_COMPONENTS_TO_CONSUME_QUERY = """
    SET NOCOUNT ON;

    DECLARE @itemid AS varchar(50) = '';
    DECLARE @versao AS int = 0;

    SELECT TOP (1)
        @Versao = Versao,
        @itemid = ItemID
    FROM ClientOrderDetails WITH (NOLOCK)
    WHERE DocType = ?
      AND OrderID = ?
      {order_row_clause}
    ORDER BY OrderRow;

    SELECT
        'N' Tipo,
        ic.ItemID,
        @Versao Version,
        ic.ItemGroupID,
        ic.ItemSubGroupId,
        ic.ComponentID,
        '' ComponentIDEsp,
        ic.Observacao,
        '' ObservacaoEsp,
        ic.Qty,
        ic.UnitPrice,
        ic.EstadoComponente,
        ic.PerDesperdicio,
        ic.UnitSupplier,
        ic.NumTimesApplicable,
        ic.PerCustoAdic,
        ic.Currency,
        ic.ExchangeRate,
        ic.RefSupplier,
        ic.RefSupplierDescr,
        ic.ObsShops,
        ig.ItemGroupDescr,
        isg.ItemSubGroupDescr,
        ISNULL(ic.RollWidth, 0) RollWidth,
        ISNULL(ic.ShrinkInY, 0) ShrinkInY,
        ISNULL(ic.ShrinkInX, 0) ShrinkInX,
        ISNULL(ic.QtyByCad, 0) QtyByCad
    FROM ItemComp ic WITH (NOLOCK)
    JOIN ItemGroup ig WITH (NOLOCK)
        ON ig.ItemGroupID = ic.ItemGroupID
    JOIN ItemSubGroup isg WITH (NOLOCK)
        ON isg.ItemGroupID = ic.ItemGroupID
       AND isg.ItemSubGroupID = ic.ItemSubGroupID
    WHERE ic.ItemID = @itemid
      AND ic.Versao = @versao
      AND ic.Variacao = 0

    UNION ALL

    SELECT
        'E' Tipo,
        ic.ItemID,
        @Versao Version,
        ic.ItemGroupID,
        ic.ItemSubGroupId,
        ic.ComponentID,
        ic.ComponentIDEsp,
        icp.Observacao Observacao,
        ic.Observacao ObservacaoEsp,
        ic.Qty,
        ic.UnitPrice,
        ic.EstadoComponente,
        ic.PerDesperdicio,
        ic.UnitSupplier,
        ic.NumTimesApplicable,
        ic.PerCustoAdic,
        ic.Currency,
        ic.ExchangeRate,
        ic.RefSupplier,
        ic.RefSupplierDescr,
        ic.ObsShops,
        ig.ItemGroupDescr,
        isg.ItemSubGroupDescr,
        ISNULL(ic.RollWidth, 0) RollWidth,
        ISNULL(ic.ShrinkInY, 0) ShrinkInY,
        ISNULL(ic.ShrinkInX, 0) ShrinkInX,
        ISNULL(ic.QtyByCad, 0) QtyByCad
    FROM ItemCompEsp ic WITH (NOLOCK)
    LEFT JOIN ItemComp icp WITH (NOLOCK)
        ON icp.ItemID = @itemid
       AND icp.Versao = ic.Versao
       AND icp.ComponentID = ic.ComponentID
       AND icp.ItemGroupID = ic.ItemGroupID
       AND icp.ItemSubGroupID = ic.ItemSubGroupID
    JOIN ItemGroup ig WITH (NOLOCK)
        ON ig.ItemGroupID = ic.ItemGroupID
    JOIN ItemSubGroup isg WITH (NOLOCK)
        ON isg.ItemGroupID = ic.ItemGroupID
       AND isg.ItemSubGroupID = ic.ItemSubGroupID
    WHERE ic.ItemID = @itemid
      AND ic.Versao = @versao
"""


DOC_COMPONENTS_TO_CONSUME_QUERY = """
    SELECT
        coc.OrderRow,
        coc.ComponentID ItemID,
        im.ItemDesc,
        coc.ItemGroupID,
        ig.ItemGroupDescr,
        isg.ItemSubGroupDescr,
        coc.ItemSubGroupId,
        cocaAbast.WHDest,
        cocaAbast.LocationDst,
        cocaAbast.Lot,
        coc.UnitQty,
        coc.TotQty,
        ISNULL(cocaAbast.QtySupplyied, 0) QtySupplyied,
        ISNULL(cocaConsumed.QtyConsumed, 0) QtyConsumed,
        (ISNULL(cocaAbast.QtySupplyied, 0) - ISNULL(cocaConsumed.QtyConsumed, 0)) QtyRemaining
    FROM (
        SELECT
            coc.DocType,
            coc.OrderID,
            coc.OrderRow,
            coc.ComponentID,
            coc.ItemGroupID,
            coc.ItemSubGroupId,
            coc.UnitQty,
            SUM(coc.TotQty) TotQty
        FROM ClientOrderComp coc WITH (NOLOCK)
        WHERE coc.DocType = ?
          AND coc.OrderID = ?
          {order_row_clause}
        GROUP BY
            coc.DocType,
            coc.OrderID,
            coc.OrderRow,
            coc.ComponentID,
            coc.ItemGroupID,
            coc.ItemSubGroupId,
            coc.UnitQty
    ) coc
    JOIN ItemMaster im WITH (NOLOCK)
        ON im.ItemID = coc.ComponentID
    LEFT JOIN ItemGroup ig WITH (NOLOCK)
        ON ig.ItemGroupID = coc.ItemGroupID
    LEFT JOIN ItemSubGroup isg WITH (NOLOCK)
        ON isg.ItemGroupID = coc.ItemGroupID
       AND isg.ItemSubGroupID = coc.ItemSubGroupID
    OUTER APPLY (
        SELECT
            coca.WHDest,
            coca.LocationDst,
            coca.LoteDst Lot,
            ISNULL(SUM(coca.QtyAbast), 0) QtySupplyied
        FROM ClientOrderCompAbast coca WITH (NOLOCK)
        WHERE coca.DocType = coc.DocType
          AND coca.OrderID = coc.OrderID
          AND coca.OrderRow = coc.OrderRow
          AND coca.ComponentID = coc.ComponentID
          AND coca.ItemGroupID = coc.ItemGroupID
          AND coca.ItemSubGroupID = coc.ItemSubGroupID
          AND coca.Canceled = 0
          AND coca.Type = 'ABASTECIMENTO'
        GROUP BY coca.WHDest, coca.LocationDst, coca.LoteDst
    ) cocaAbast
    OUTER APPLY (
        SELECT ISNULL(SUM(coca.QtyAbast), 0) QtyConsumed
        FROM ClientOrderCompAbast coca WITH (NOLOCK)
        WHERE coca.DocType = coc.DocType
          AND coca.OrderID = coc.OrderID
          AND coca.OrderRow = coc.OrderRow
          AND coca.ComponentID = coc.ComponentID
          AND coca.ItemGroupID = coc.ItemGroupID
          AND coca.ItemSubGroupID = coc.ItemSubGroupID
          AND coca.Canceled = 0
          AND (coca.Type = 'ABATE' OR coca.Type = 'RETORNO')
          AND coca.WHOri = cocaAbast.WHDest
          AND coca.LocationOri = cocaAbast.LocationDst
          AND coca.LoteOri = cocaAbast.Lot
    ) cocaConsumed
    ORDER BY coc.OrderRow, coc.ComponentID, cocaAbast.WHDest, cocaAbast.LocationDst, cocaAbast.Lot
"""


ORDER_ROW_DIMS_PLANNING_PRODUCTION_BY_COLOR_QUERY = """
    SELECT *
    FROM (
        SELECT
            codi.DocType,
            codi.OrderID,
            codi.ColorID,
            c.ColorSmallDescr,
            codi.GridID,
            g.GridSmallDescr,
            codi.SizeId,
            s.SizeSmallDescr,
            co.RequesterID,
            SUM(codi.QtyOrd) QtyOrd,
            SUM(codi.QtySatisf) QtySatisf,
            ISNULL(SUM(wpm.ProductionTypeRegisteredQty), 0) ProductionTypeRegisteredQty,
            MAX(codi.SizeOrderNum) SizeOrderNum
        FROM ClientOrdersDim codi WITH (NOLOCK)
        JOIN ClientOrders co WITH (NOLOCK)
            ON co.DocType = codi.DocType
           AND co.OrderID = codi.OrderID
        JOIN Colors c WITH (NOLOCK)
            ON c.ColorID = codi.ColorID
        JOIN Grids g WITH (NOLOCK)
            ON g.GridID = codi.GridID
        JOIN Sizes s WITH (NOLOCK)
            ON s.SizeID = codi.SizeId
        OUTER APPLY (
            SELECT SUM(wpm.Qty) ProductionTypeRegisteredQty
            FROM WPMProductionLog wpm WITH (NOLOCK)
            WHERE wpm.DocType = codi.DocType
              AND wpm.OrderID = codi.OrderID
              AND wpm.OrderRow = codi.OrderRow
              AND wpm.SizeId = codi.SizeId
              AND wpm.ProductionType = ?
        ) wpm
        WHERE codi.DocType = ?
          AND codi.OrderID = ?
        GROUP BY
            codi.DocType,
            codi.OrderID,
            codi.ColorID,
            c.ColorSmallDescr,
            codi.GridID,
            g.GridSmallDescr,
            codi.SizeId,
            s.SizeSmallDescr,
            co.RequesterID
    ) x
    ORDER BY SizeOrderNum
"""


ACTIVE_SUBCONTRACT_ORDERS_BY_SUBCONTRACTOR_QUERY = """
    ;WITH OperationsFilter AS (
        SELECT LTRIM(RTRIM(value)) OperCode
        FROM SplitString(?, ',')
        WHERE LTRIM(RTRIM(value)) <> ''
    ),
    StatusFilter AS (
        SELECT LTRIM(RTRIM(value)) ProductionStatus
        FROM SplitString(?, ',')
        WHERE LTRIM(RTRIM(value)) <> ''
    ),
    FilteredOrders AS (
        SELECT
            co.DocType,
            co.OrderID,
            co.CreationDateTime,
            co.OrderDateTime,
            co.OrderDatePrev,
            co.ClientID,
            co.SubContratado,
            co.SubContratadoLine,
            co.Obs
        FROM ClientOrders co WITH (NOLOCK)
        JOIN DocumentConfig dc WITH (NOLOCK)
            ON dc.DocType = co.DocType
           AND dc.DocTypeArea = 'PLANING'
        JOIN StatusFilter sf
            ON sf.ProductionStatus = co.ProductionStatus
        WHERE co.SubContratado = ?
    ),
    OperationTotals AS (
        SELECT
            coo.DocType,
            coo.OrderID,
            coo.OrderRow,
            coo.ColorID,
            coo.GridID,
            coo.SizeID,
            SUM(coo.QtyOrd) QtCorte,
            SUM(coo.QtyTrat) QtCortada
        FROM ClientOrderOperations coo WITH (NOLOCK)
        JOIN OperationsFilter op
            ON op.OperCode = coo.OperCode
        JOIN FilteredOrders fo
            ON fo.DocType = coo.DocType
           AND fo.OrderID = coo.OrderID
        GROUP BY
            coo.DocType,
            coo.OrderID,
            coo.OrderRow,
            coo.ColorID,
            coo.GridID,
            coo.SizeID
    ),
    DetailRows AS (
        SELECT
            fo.DocType,
            fo.OrderID,
            fo.CreationDateTime,
            cod.OrderRow,
            CAST(MAX(fo.OrderDateTime) AS date) DataPrevIni,
            CAST(MAX(fo.OrderDatePrev) AS date) DataPrevEntrega,
            MAX(fo.ClientID) ClientID,
            MAX(fo.SubContratado) SubcontratadoID,
            MAX(fo.SubContratadoLine) LineID,
            MAX(fo.Obs) Obs,
            SUM(codim.QtyOrd) QtyOrd,
            MAX(cod.ItemID) ItemID,
            SUM(ISNULL(ot.QtCorte, 0)) QtCorte,
            SUM(ISNULL(ot.QtCortada, 0)) QtCortada,
            MAX(ct.ConfectionTypeID) ConfectionTypeID,
            MAX(ct.EmailControls) EmailControls
        FROM FilteredOrders fo
        JOIN ClientOrderDetails cod WITH (NOLOCK)
            ON cod.DocType = fo.DocType
           AND cod.OrderID = fo.OrderID
        JOIN ClientOrdersDim codim WITH (NOLOCK)
            ON codim.DocType = cod.DocType
           AND codim.OrderID = cod.OrderID
           AND codim.OrderRow = cod.OrderRow
        JOIN OperationTotals ot
            ON ot.DocType = cod.DocType
           AND ot.OrderID = cod.OrderID
           AND ot.OrderRow = cod.OrderRow
           AND ot.ColorID = cod.ColorID
           AND ot.GridID = cod.GridID
           AND ot.SizeID = codim.SizeID
        JOIN ConfectionLines cl WITH (NOLOCK)
            ON cl.Confection = fo.SubContratado
           AND cl.ConfectionLine = fo.SubContratadoLine
        JOIN ConfectionTypes ct WITH (NOLOCK)
            ON ct.ConfectionTypeID = cl.ConfectionType
        GROUP BY
            fo.DocType,
            fo.OrderID,
            fo.CreationDateTime,
            cod.OrderRow,
            cod.ColorID,
            cod.GridID,
            codim.SizeID
    )
    SELECT
        DocType,
        OrderID,
        OrderRow,
        CreationDateTime,
        DataPrevIni,
        DataPrevEntrega,
        ClientID,
        SubcontratadoID Subcontratado,
        LineID SubContratadoLine,
        Obs,
        SUM(QtyOrd) QtyOrd,
        SUM(QtCorte) QtCorte,
        SUM(QtCortada) QtCortada,
        MAX(ItemID) ItemID,
        MAX(ConfectionTypeID) ConfectionTypeID,
        MAX(EmailControls) EmailControls
    FROM DetailRows
    GROUP BY
        DocType,
        OrderID,
        OrderRow,
        CreationDateTime,
        DataPrevIni,
        DataPrevEntrega,
        ClientID,
        SubcontratadoID,
        LineID,
        Obs
    ORDER BY DataPrevEntrega, OrderID, OrderRow
    OPTION (RECOMPILE)
"""


def fetch_client_order(doc_type: str, order_id: int, get_lines: bool = False) -> dict[str, Any] | None:
    with db_cursor() as (cursor, _conn):
        cursor.execute(_order_query(cursor), (doc_type, order_id, doc_type, order_id))
        row = cursor.fetchone()
        if not row:
            return None

        result = _row_to_dict(cursor, row)

        if get_lines:
            cursor.execute(LINES_QUERY, (doc_type, order_id))
            result["Lines"] = [_row_to_dict(cursor, line) for line in cursor.fetchall()]

    return result


def fetch_components_by_document_color(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
    component_id: str = "",
    color_id: str = "",
) -> list[dict[str, Any]]:
    detail_order_row_clause = ""
    component_order_row_clause = ""
    component_id_clause = ""
    color_id_clause = ""
    params: list[Any] = [doc_type, order_id]

    if order_row is not None:
        detail_order_row_clause = "AND OrderRow = ?"
        component_order_row_clause = "AND coc.OrderRow = ?"
        params.append(order_row)

    params.extend([doc_type, order_id])

    if order_row is not None:
        params.append(order_row)

    if color_id:
        color_id_clause = "AND cod.ColorID = ?"
        params.append(color_id)

    if component_id:
        component_id_clause = "AND coc.ComponentID = ?"
        params.append(component_id)

    query = COMPONENTS_BY_DOCUMENT_COLOR_QUERY.format(
        detail_order_row_clause=detail_order_row_clause,
        component_order_row_clause=component_order_row_clause,
        color_id_clause=color_id_clause,
        component_id_clause=component_id_clause,
    )

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        while cursor.description is None and cursor.nextset():
            pass

        if cursor.description is None:
            return []

        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def fetch_cad_components_to_consume(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
) -> list[dict[str, Any]]:
    order_row_clause = ""
    params: list[Any] = [doc_type, order_id]

    if order_row is not None:
        order_row_clause = "AND OrderRow = ?"
        params.append(order_row)

    query = CAD_COMPONENTS_TO_CONSUME_QUERY.format(order_row_clause=order_row_clause)

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        while cursor.description is None and cursor.nextset():
            pass

        if cursor.description is None:
            return []

        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def fetch_doc_components_to_consume(
    doc_type: str,
    order_id: int,
    order_row: int | None = None,
) -> list[dict[str, Any]]:
    order_row_clause = ""
    params: list[Any] = [doc_type, order_id]

    if order_row is not None and order_row > 0:
        order_row_clause = "AND coc.OrderRow = ?"
        params.append(order_row)

    query = DOC_COMPONENTS_TO_CONSUME_QUERY.format(order_row_clause=order_row_clause)

    with db_cursor() as (cursor, _conn):
        cursor.execute(query, tuple(params))
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def update_cad_consumption(
    doc_type: str,
    order_id: int,
    item_group_id: str,
    item_sub_group_id: str,
    component_id: str,
    shrink_in_x: Decimal,
    shrink_in_y: Decimal,
    roll_width: Decimal,
    qty_by_cad: Decimal,
    obs: str,
) -> dict[str, Any]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            """
            SELECT TOP (1) cod.ItemID, cod.Versao
            FROM ClientOrderDetails cod WITH (NOLOCK)
            WHERE cod.DocType = ?
              AND cod.OrderID = ?
            ORDER BY cod.OrderRow
            """,
            (doc_type, order_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Client order detail not found")

        item_id = row[0]
        version = int(row[1] or 0)

        cursor.execute(
            """
            UPDATE ic
            SET Observacao = ?,
                ShrinkInX = ?,
                ShrinkInY = ?,
                RollWidth = ?,
                QtyByCad = ?
            FROM ItemComp ic
            WHERE ic.ItemID = ?
              AND ic.Versao = ?
              AND ic.ItemGroupID = ?
              AND ic.ItemSubGroupID = ?
              AND ic.ComponentID = ?
            """,
            (
                obs,
                float(shrink_in_x),
                float(shrink_in_y),
                float(roll_width),
                float(qty_by_cad),
                item_id,
                version,
                item_group_id,
                item_sub_group_id,
                component_id,
            ),
        )
        item_comp_updated = max(cursor.rowcount or 0, 0)

        cursor.execute(
            """
            UPDATE ic
            SET ShrinkInX = ?,
                ShrinkInY = ?,
                RollWidth = ?,
                QtyByCad = ?
            FROM ItemCompEsp ic
            WHERE ic.ItemID = ?
              AND ic.Versao = ?
              AND ic.ItemGroupID = ?
              AND ic.ItemSubGroupID = ?
              AND ic.ComponentIDEsp = ?
            """,
            (
                float(shrink_in_x),
                float(shrink_in_y),
                float(roll_width),
                float(qty_by_cad),
                item_id,
                version,
                item_group_id,
                item_sub_group_id,
                component_id,
            ),
        )
        item_comp_esp_updated = max(cursor.rowcount or 0, 0)

    return {
        "DocType": doc_type,
        "OrderID": order_id,
        "ItemID": item_id,
        "Version": version,
        "ComponentID": component_id,
        "ItemGroupID": item_group_id,
        "ItemSubGroupID": item_sub_group_id,
        "ItemCompUpdated": item_comp_updated,
        "ItemCompEspUpdated": item_comp_esp_updated,
        "Updated": item_comp_updated + item_comp_esp_updated,
    }


def fetch_order_row_dims_to_register_planning_production_by_color(
    doc_type: str,
    order_id: int,
    production_type: str,
) -> list[dict[str, Any]]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            ORDER_ROW_DIMS_PLANNING_PRODUCTION_BY_COLOR_QUERY,
            (production_type, doc_type, order_id),
        )
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def fetch_active_subcontract_orders_by_subcontractor_id(
    subcontract_id: str,
    subcontract_operations: str,
    subcontract_status: str,
) -> list[dict[str, Any]]:
    with db_cursor() as (cursor, _conn):
        cursor.execute(
            ACTIVE_SUBCONTRACT_ORDERS_BY_SUBCONTRACTOR_QUERY,
            (
                subcontract_operations,
                subcontract_status,
                subcontract_id,
            ),
        )
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def _order_query(cursor) -> str:
    project_code_select = (
        "co.ProjectCode"
        if _column_exists(cursor, "ClientOrders", "ProjectCode")
        else "'' ProjectCode"
    )
    return ORDER_QUERY_TEMPLATE.format(project_code_select=project_code_select)


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
          AND COLUMN_NAME = ?
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _row_to_dict(cursor, row) -> dict[str, Any]:
    names = _unique_column_names([column[0] for column in cursor.description])
    return {name: _json_value(value) for name, value in zip(names, row)}


def _unique_column_names(names: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = counts.get(name, 0) + 1
        counts[name] = count
        result.append(name if count == 1 else f"{name}_{count}")
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
