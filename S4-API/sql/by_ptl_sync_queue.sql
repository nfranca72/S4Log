/*
    Defaults required by the short BY-PTL event INSERT statements.
    Run once on the WMS database that contains dbo.SyncQueue.
*/

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'SyncID', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_SyncID
        DEFAULT NEWID() FOR SyncID;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'Priority', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_Priority
        DEFAULT (0) FOR Priority;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'Async', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_Async
        DEFAULT (1) FOR Async;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'SyncSucceeded', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_SyncSucceeded
        DEFAULT (0) FOR SyncSucceeded;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'SyncError', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_SyncError
        DEFAULT (0) FOR SyncError;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'SyncResponse', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_SyncResponse
        DEFAULT (N'') FOR SyncResponse;

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'dbo.SyncQueue')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'dbo.SyncQueue'), N'CreationUser', 'ColumnId')
)
    ALTER TABLE dbo.SyncQueue ADD CONSTRAINT DF_SyncQueue_CreationUser
        DEFAULT (N'BY-PTL') FOR CreationUser;

/* PTL_START */
INSERT dbo.SyncQueue
    (Area, RequestDate, SyncStarted, SyncEnded, Field01)
VALUES
    (N'PTL_START', GETDATE(), 0, 0, CONVERT(nvarchar(100), @OrdersPickingID));

/* PTL_CHANGE: Field02 is the new PTL */
INSERT dbo.SyncQueue
    (Area, RequestDate, SyncStarted, SyncEnded, Field01, Field02)
VALUES
    (N'PTL_CHANGE', GETDATE(), 0, 0,
     CONVERT(nvarchar(100), @OrdersPickingID), @NewPTL);

/* PACKING_LIST */
INSERT dbo.SyncQueue
    (Area, RequestDate, SyncStarted, SyncEnded, Field01, Field02)
VALUES
    (N'PACKING_LIST', GETDATE(), 0, 0,
     CONVERT(nvarchar(100), @OrdersPickingID), @PackingListID);

/* PACKED_BOX */
INSERT dbo.SyncQueue
    (Area, RequestDate, SyncStarted, SyncEnded, Field01, Field02, Field03)
VALUES
    (N'PACKED_BOX', GETDATE(), 0, 0,
     CONVERT(nvarchar(100), @OrdersPickingID), @VolDocCod,
     CONVERT(nvarchar(100), @VolNum));
