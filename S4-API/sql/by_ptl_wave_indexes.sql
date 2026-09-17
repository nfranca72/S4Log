/*
    Recommended indexes for the BY-PTL wave / OrdersPicking flow.
    The script is idempotent:
    - checks whether the target table exists
    - checks whether the required columns exist
    - checks sys.indexes/sys.index_columns for an equivalent key definition
    - creates the index only when no equivalent index is found

    Review the CREATE INDEX statements before running in production.
*/

SET NOCOUNT ON;

DECLARE @msg nvarchar(4000);

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

DECLARE @existing_keys table (
    TableName sysname NOT NULL,
    IndexName sysname NOT NULL,
    KeyColumns nvarchar(max) NOT NULL
);

INSERT INTO @existing_keys (TableName, IndexName, KeyColumns)
SELECT
    t.name AS TableName,
    i.name AS IndexName,
    STUFF((
        SELECT
            N', ' + c2.name
        FROM sys.index_columns ic2
        JOIN sys.columns c2
          ON c2.object_id = ic2.object_id
         AND c2.column_id = ic2.column_id
        WHERE ic2.object_id = i.object_id
          AND ic2.index_id = i.index_id
          AND ic2.is_included_column = 0
        ORDER BY ic2.key_ordinal
        FOR XML PATH(''), TYPE
    ).value('.', 'nvarchar(max)'), 1, 2, N'') AS KeyColumns
FROM sys.indexes i
JOIN sys.tables t
  ON t.object_id = i.object_id
WHERE t.schema_id = SCHEMA_ID(N'dbo')
  AND i.type IN (1, 2)
  AND i.is_hypothetical = 0
  AND i.name IS NOT NULL;

/* -------------------------------------------------------------------------- */
/* dbo.OrdersPicking                                                          */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.OrdersPicking', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.OrdersPicking: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.OrdersPicking', N'OrderPickingGroup') IS NULL
     OR COL_LENGTH(N'dbo.OrdersPicking', N'deleted') IS NULL
     OR COL_LENGTH(N'dbo.OrdersPicking', N'ID') IS NULL
BEGIN
    PRINT N'Skipping dbo.OrdersPicking: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'OrdersPicking'
      AND KeyColumns = N'OrderPickingGroup, deleted, ID'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.OrdersPicking: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'OrdersPicking'
      AND KeyColumns = N'OrderPickingGroup, deleted, ID';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_orders_picking nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_OrdersPicking_OrderPickingGroup_Deleted
          ON dbo.OrdersPicking (OrderPickingGroup, deleted, ID)';

    DECLARE @inc_orders_picking nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.OrdersPicking', N'WhIDDest') IS NOT NULL
        SET @inc_orders_picking += N', WhIDDest';
    IF COL_LENGTH(N'dbo.OrdersPicking', N'LocationIDDest') IS NOT NULL
        SET @inc_orders_picking += N', LocationIDDest';
    IF COL_LENGTH(N'dbo.OrdersPicking', N'RouteID') IS NOT NULL
        SET @inc_orders_picking += N', RouteID';
    IF COL_LENGTH(N'dbo.OrdersPicking', N'edited_date') IS NOT NULL
        SET @inc_orders_picking += N', edited_date';

    IF @inc_orders_picking <> N''
        SET @sql_orders_picking += N' INCLUDE (' + STUFF(@inc_orders_picking, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_orders_picking;

    PRINT N'Created IX_OrdersPicking_OrderPickingGroup_Deleted.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.OrdersPickingDetails                                                   */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.OrdersPickingDetails', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.OrdersPickingDetails: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'OrderID') IS NULL
     OR COL_LENGTH(N'dbo.OrdersPickingDetails', N'deleted') IS NULL
     OR COL_LENGTH(N'dbo.OrdersPickingDetails', N'RowNumber') IS NULL
BEGIN
    PRINT N'Skipping dbo.OrdersPickingDetails: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'OrdersPickingDetails'
      AND KeyColumns = N'OrderID, deleted, RowNumber'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.OrdersPickingDetails: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'OrdersPickingDetails'
      AND KeyColumns = N'OrderID, deleted, RowNumber';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_orders_picking_details nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_OrdersPickingDetails_OrderID_Deleted_RowNumber
          ON dbo.OrdersPickingDetails (OrderID, deleted, RowNumber)';

    DECLARE @inc_orders_picking_details nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'DocTypeOri') IS NOT NULL
        SET @inc_orders_picking_details += N', DocTypeOri';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'OrderIDOri') IS NOT NULL
        SET @inc_orders_picking_details += N', OrderIDOri';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'OrderRowOri') IS NOT NULL
        SET @inc_orders_picking_details += N', OrderRowOri';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'ItemID') IS NOT NULL
        SET @inc_orders_picking_details += N', ItemID';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'Qty') IS NOT NULL
        SET @inc_orders_picking_details += N', Qty';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'QtyPicked') IS NOT NULL
        SET @inc_orders_picking_details += N', QtyPicked';
    IF COL_LENGTH(N'dbo.OrdersPickingDetails', N'LocationIDDest') IS NOT NULL
        SET @inc_orders_picking_details += N', LocationIDDest';

    IF @inc_orders_picking_details <> N''
        SET @sql_orders_picking_details += N' INCLUDE (' + STUFF(@inc_orders_picking_details, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_orders_picking_details;

    PRINT N'Created IX_OrdersPickingDetails_OrderID_Deleted_RowNumber.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.PTLDefinitions                                                         */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.PTLDefinitions', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.PTLDefinitions: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.PTLDefinitions', N'PickToLightID') IS NULL
BEGIN
    PRINT N'Skipping dbo.PTLDefinitions: PickToLightID is missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'PTLDefinitions'
      AND KeyColumns = N'PickToLightID'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.PTLDefinitions: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'PTLDefinitions'
      AND KeyColumns = N'PickToLightID';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_ptl_definitions nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_PTLDefinitions_PickToLightID
          ON dbo.PTLDefinitions (PickToLightID)';

    DECLARE @inc_ptl_definitions nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.PTLDefinitions', N'WhidDest') IS NOT NULL
        SET @inc_ptl_definitions += N', WhidDest';
    IF COL_LENGTH(N'dbo.PTLDefinitions', N'LocationidDest') IS NOT NULL
        SET @inc_ptl_definitions += N', LocationidDest';

    IF @inc_ptl_definitions <> N''
        SET @sql_ptl_definitions += N' INCLUDE (' + STUFF(@inc_ptl_definitions, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_ptl_definitions;

    PRINT N'Created IX_PTLDefinitions_PickToLightID.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.ClientOrders                                                           */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.ClientOrders', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.ClientOrders indexes: table not found.';
END
ELSE
BEGIN
    IF COL_LENGTH(N'dbo.ClientOrders', N'DocType') IS NOT NULL
       AND COL_LENGTH(N'dbo.ClientOrders', N'OrderID') IS NOT NULL
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, OrderID'
        )
        BEGIN
            SELECT @msg =
                N'Skipping dbo.ClientOrders (DocType, OrderID): equivalent key index already exists (' + IndexName + N').'
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, OrderID';
            PRINT @msg;
        END
        ELSE
        BEGIN
            DECLARE @sql_client_orders_doctype_orderid nvarchar(max) =
                N'CREATE NONCLUSTERED INDEX IX_ClientOrders_DocType_OrderID
                  ON dbo.ClientOrders (DocType, OrderID)';

            DECLARE @inc_client_orders_doctype_orderid nvarchar(max) = N'';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RouteID') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', RouteID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'ClientID') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', ClientID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RequesterID') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', RequesterID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RefCli') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', RefCli';
            IF COL_LENGTH(N'dbo.ClientOrders', N'IDIntegration') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', IDIntegration';
            IF COL_LENGTH(N'dbo.ClientOrders', N'ModifDateTime') IS NOT NULL
                SET @inc_client_orders_doctype_orderid += N', ModifDateTime';

            IF @inc_client_orders_doctype_orderid <> N''
                SET @sql_client_orders_doctype_orderid += N' INCLUDE (' + STUFF(@inc_client_orders_doctype_orderid, 1, 2, N'') + N')';

            EXEC sp_executesql @sql_client_orders_doctype_orderid;

            PRINT N'Created IX_ClientOrders_DocType_OrderID.';
        END;
    END
    ELSE
    BEGIN
        PRINT N'Skipping dbo.ClientOrders (DocType, OrderID): one or more required columns are missing.';
    END;

    IF COL_LENGTH(N'dbo.ClientOrders', N'DocType') IS NOT NULL
       AND COL_LENGTH(N'dbo.ClientOrders', N'RefCli') IS NOT NULL
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, RefCli'
        )
        BEGIN
            SELECT @msg =
                N'Skipping dbo.ClientOrders (DocType, RefCli): equivalent key index already exists (' + IndexName + N').'
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, RefCli';
            PRINT @msg;
        END
        ELSE
        BEGIN
            DECLARE @sql_client_orders_doctype_refcli nvarchar(max) =
                N'CREATE NONCLUSTERED INDEX IX_ClientOrders_DocType_RefCli
                  ON dbo.ClientOrders (DocType, RefCli)';

            DECLARE @inc_client_orders_doctype_refcli nvarchar(max) = N'';
            IF COL_LENGTH(N'dbo.ClientOrders', N'OrderID') IS NOT NULL
                SET @inc_client_orders_doctype_refcli += N', OrderID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RouteID') IS NOT NULL
                SET @inc_client_orders_doctype_refcli += N', RouteID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'ClientID') IS NOT NULL
                SET @inc_client_orders_doctype_refcli += N', ClientID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RequesterID') IS NOT NULL
                SET @inc_client_orders_doctype_refcli += N', RequesterID';

            IF @inc_client_orders_doctype_refcli <> N''
                SET @sql_client_orders_doctype_refcli += N' INCLUDE (' + STUFF(@inc_client_orders_doctype_refcli, 1, 2, N'') + N')';

            EXEC sp_executesql @sql_client_orders_doctype_refcli;

            PRINT N'Created IX_ClientOrders_DocType_RefCli.';
        END;
    END
    ELSE
    BEGIN
        PRINT N'Skipping dbo.ClientOrders (DocType, RefCli): one or more required columns are missing.';
    END;

    IF COL_LENGTH(N'dbo.ClientOrders', N'DocType') IS NOT NULL
       AND COL_LENGTH(N'dbo.ClientOrders', N'IDIntegration') IS NOT NULL
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, IDIntegration'
        )
        BEGIN
            SELECT @msg =
                N'Skipping dbo.ClientOrders (DocType, IDIntegration): equivalent key index already exists (' + IndexName + N').'
            FROM @existing_keys
            WHERE TableName = N'ClientOrders'
              AND KeyColumns = N'DocType, IDIntegration';
            PRINT @msg;
        END
        ELSE
        BEGIN
            DECLARE @sql_client_orders_doctype_idintegration nvarchar(max) =
                N'CREATE NONCLUSTERED INDEX IX_ClientOrders_DocType_IDIntegration
                  ON dbo.ClientOrders (DocType, IDIntegration)';

            DECLARE @inc_client_orders_doctype_idintegration nvarchar(max) = N'';
            IF COL_LENGTH(N'dbo.ClientOrders', N'OrderID') IS NOT NULL
                SET @inc_client_orders_doctype_idintegration += N', OrderID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RouteID') IS NOT NULL
                SET @inc_client_orders_doctype_idintegration += N', RouteID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'ClientID') IS NOT NULL
                SET @inc_client_orders_doctype_idintegration += N', ClientID';
            IF COL_LENGTH(N'dbo.ClientOrders', N'RequesterID') IS NOT NULL
                SET @inc_client_orders_doctype_idintegration += N', RequesterID';

            IF @inc_client_orders_doctype_idintegration <> N''
                SET @sql_client_orders_doctype_idintegration += N' INCLUDE (' + STUFF(@inc_client_orders_doctype_idintegration, 1, 2, N'') + N')';

            EXEC sp_executesql @sql_client_orders_doctype_idintegration;

            PRINT N'Created IX_ClientOrders_DocType_IDIntegration.';
        END;
    END
    ELSE
    BEGIN
        PRINT N'Skipping dbo.ClientOrders (DocType, IDIntegration): one or more required columns are missing.';
    END;
END;

/* -------------------------------------------------------------------------- */
/* dbo.ClientOrderDetails                                                     */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.ClientOrderDetails', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.ClientOrderDetails: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.ClientOrderDetails', N'DocType') IS NULL
     OR COL_LENGTH(N'dbo.ClientOrderDetails', N'OrderID') IS NULL
     OR COL_LENGTH(N'dbo.ClientOrderDetails', N'OrderRow') IS NULL
BEGIN
    PRINT N'Skipping dbo.ClientOrderDetails: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'ClientOrderDetails'
      AND KeyColumns = N'DocType, OrderID, OrderRow'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.ClientOrderDetails: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'ClientOrderDetails'
      AND KeyColumns = N'DocType, OrderID, OrderRow';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_client_order_details nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_ClientOrderDetails_DocType_OrderID_OrderRow
          ON dbo.ClientOrderDetails (DocType, OrderID, OrderRow)';

    DECLARE @inc_client_order_details nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'ItemID') IS NOT NULL
        SET @inc_client_order_details += N', ItemID';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'QtyOrd') IS NOT NULL
        SET @inc_client_order_details += N', QtyOrd';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'QtyPicked') IS NOT NULL
        SET @inc_client_order_details += N', QtyPicked';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'QtySatisf') IS NOT NULL
        SET @inc_client_order_details += N', QtySatisf';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'IDIntegration') IS NOT NULL
        SET @inc_client_order_details += N', IDIntegration';
    IF COL_LENGTH(N'dbo.ClientOrderDetails', N'RefCli') IS NOT NULL
        SET @inc_client_order_details += N', RefCli';

    IF @inc_client_order_details <> N''
        SET @sql_client_order_details += N' INCLUDE (' + STUFF(@inc_client_order_details, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_client_order_details;

    PRINT N'Created IX_ClientOrderDetails_DocType_OrderID_OrderRow.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.VolMaster                                                              */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.VolMaster', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.VolMaster: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.VolMaster', N'ParentDocType') IS NULL
     OR COL_LENGTH(N'dbo.VolMaster', N'ParentOrderID') IS NULL
     OR COL_LENGTH(N'dbo.VolMaster', N'VolDocCod') IS NULL
     OR COL_LENGTH(N'dbo.VolMaster', N'VolNum') IS NULL
BEGIN
    PRINT N'Skipping dbo.VolMaster: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'VolMaster'
      AND KeyColumns = N'ParentDocType, ParentOrderID, VolDocCod, VolNum'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.VolMaster: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'VolMaster'
      AND KeyColumns = N'ParentDocType, ParentOrderID, VolDocCod, VolNum';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_vol_master nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_VolMaster_ParentDocType_ParentOrderID
          ON dbo.VolMaster (ParentDocType, ParentOrderID, VolDocCod, VolNum)';

    DECLARE @inc_vol_master nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.VolMaster', N'VolWeight') IS NOT NULL
        SET @inc_vol_master += N', VolWeight';
    IF COL_LENGTH(N'dbo.VolMaster', N'VolTypeID') IS NOT NULL
        SET @inc_vol_master += N', VolTypeID';
    IF COL_LENGTH(N'dbo.VolMaster', N'CreationUser') IS NOT NULL
        SET @inc_vol_master += N', CreationUser';

    IF @inc_vol_master <> N''
        SET @sql_vol_master += N' INCLUDE (' + STUFF(@inc_vol_master, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_vol_master;

    PRINT N'Created IX_VolMaster_ParentDocType_ParentOrderID.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.VolItem                                                                */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.VolItem', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.VolItem: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.VolItem', N'VolDocCod') IS NULL
     OR COL_LENGTH(N'dbo.VolItem', N'VolNum') IS NULL
     OR COL_LENGTH(N'dbo.VolItem', N'VolItemNumber') IS NULL
BEGIN
    PRINT N'Skipping dbo.VolItem: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'VolItem'
      AND KeyColumns = N'VolDocCod, VolNum, VolItemNumber'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.VolItem: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'VolItem'
      AND KeyColumns = N'VolDocCod, VolNum, VolItemNumber';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_vol_item nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_VolItem_VolDocCod_VolNum_VolItemNumber
          ON dbo.VolItem (VolDocCod, VolNum, VolItemNumber)';

    DECLARE @inc_vol_item nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.VolItem', N'ParentOrderRow') IS NOT NULL
        SET @inc_vol_item += N', ParentOrderRow';
    IF COL_LENGTH(N'dbo.VolItem', N'ItemID') IS NOT NULL
        SET @inc_vol_item += N', ItemID';
    IF COL_LENGTH(N'dbo.VolItem', N'ItemQty') IS NOT NULL
        SET @inc_vol_item += N', ItemQty';
    IF COL_LENGTH(N'dbo.VolItem', N'ItemQtyIni') IS NOT NULL
        SET @inc_vol_item += N', ItemQtyIni';

    IF @inc_vol_item <> N''
        SET @sql_vol_item += N' INCLUDE (' + STUFF(@inc_vol_item, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_vol_item;

    PRINT N'Created IX_VolItem_VolDocCod_VolNum_VolItemNumber.';
END;

/* -------------------------------------------------------------------------- */
/* dbo.BusinessPartners                                                       */
/* -------------------------------------------------------------------------- */

IF OBJECT_ID(N'dbo.BusinessPartners', N'U') IS NULL
BEGIN
    PRINT N'Skipping dbo.BusinessPartners: table not found.';
END
ELSE IF COL_LENGTH(N'dbo.BusinessPartners', N'PartnerType') IS NULL
     OR COL_LENGTH(N'dbo.BusinessPartners', N'PartnerID') IS NULL
BEGIN
    PRINT N'Skipping dbo.BusinessPartners: one or more required columns are missing.';
END
ELSE IF EXISTS (
    SELECT 1
    FROM @existing_keys
    WHERE TableName = N'BusinessPartners'
      AND KeyColumns = N'PartnerType, PartnerID'
)
BEGIN
    SELECT @msg =
        N'Skipping dbo.BusinessPartners: equivalent key index already exists (' + IndexName + N').'
    FROM @existing_keys
    WHERE TableName = N'BusinessPartners'
      AND KeyColumns = N'PartnerType, PartnerID';
    PRINT @msg;
END
ELSE
BEGIN
    DECLARE @sql_business_partners nvarchar(max) =
        N'CREATE NONCLUSTERED INDEX IX_BusinessPartners_PartnerType_PartnerID
          ON dbo.BusinessPartners (PartnerType, PartnerID)';

    DECLARE @inc_business_partners nvarchar(max) = N'';
    IF COL_LENGTH(N'dbo.BusinessPartners', N'PartnerName') IS NOT NULL
        SET @inc_business_partners += N', PartnerName';
    IF COL_LENGTH(N'dbo.BusinessPartners', N'GLNCode') IS NOT NULL
        SET @inc_business_partners += N', GLNCode';
    IF COL_LENGTH(N'dbo.BusinessPartners', N'Active') IS NOT NULL
        SET @inc_business_partners += N', Active';
    IF COL_LENGTH(N'dbo.BusinessPartners', N'Status') IS NOT NULL
        SET @inc_business_partners += N', Status';

    IF @inc_business_partners <> N''
        SET @sql_business_partners += N' INCLUDE (' + STUFF(@inc_business_partners, 1, 2, N'') + N')';

    EXEC sp_executesql @sql_business_partners;

    PRINT N'Created IX_BusinessPartners_PartnerType_PartnerID.';
END;
