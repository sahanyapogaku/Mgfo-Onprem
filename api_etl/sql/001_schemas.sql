-- Schemas used by the Manufacturo -> MSSQL ETL pipeline.
-- stg = raw JSON landing zone, one table per Manufacturo endpoint.
-- rpt = typed reporting tables, keyed on the Manufacturo GUID/ID.
-- etl = pipeline control tables (watermarks, run log).

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'stg')
    EXEC('CREATE SCHEMA stg');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'rpt')
    EXEC('CREATE SCHEMA rpt');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'etl')
    EXEC('CREATE SCHEMA etl');
GO
