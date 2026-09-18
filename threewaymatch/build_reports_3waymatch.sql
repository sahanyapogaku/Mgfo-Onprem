/* =====================================================================
   Reporting-layer copy of ThreeWayMatch.dbo.match_results.
   Target platform: SQL Server (on-prem, 10.10.4.174), T-SQL

   Creates a separate `reports` database, schema `fin`, table `3waymatch`
   (bracketed as [3waymatch] throughout - a T-SQL identifier can't start
   with a digit unquoted). This is a full-refresh COPY of
   ThreeWayMatch.dbo.match_results, not a view, per spec - kept as its
   own physical table so it can be queried/reported on independently of
   the ThreeWayMatch database.

   reports and ThreeWayMatch are on the SAME instance (10.10.4.174), so
   the refresh  below uses a plain 3-part name
   (ThreeWayMatch.dbo.match_results) with no linked server, same as
   every cross-database reference in build_match_results.sql.

   Run this once to create the database/schema/table/proc, then call
   fin.usp_refresh_3waymatch right after
   ThreeWayMatch.dbo.usp_refresh_match_results in whatever job/schedule
   already runs that proc, so reports.fin.[3waymatch] never drifts from
   the source table.
   ===================================================================== */

IF DB_ID('reports') IS NULL
BEGIN
    CREATE DATABASE reports;
END
GO

USE reports;
GO

IF SCHEMA_ID('fin') IS NULL
    EXEC('CREATE SCHEMA fin');
GO

SET NOCOUNT ON;
GO

/* ---------------------------------------------------------------------
   Table - mirrors ThreeWayMatch.dbo.match_results column-for-column.
   Dropped and recreated since fin.usp_refresh_3waymatch always does a
   full rebuild anyway, same rationale as dbo.match_results itself.
   --------------------------------------------------------------------- */
IF OBJECT_ID('fin.[3waymatch]', 'U') IS NOT NULL
    DROP TABLE fin.[3waymatch];
GO

CREATE TABLE fin.[3waymatch] (
    expense_id             VARCHAR(64)     NOT NULL,
    po_number              VARCHAR(64)     NULL,
    memo                   VARCHAR(500)    NULL,
    invoice_number         VARCHAR(255)    NULL,
    supplier               VARCHAR(255)    NULL,
    bill_amount             DECIMAL(18,2)   NULL,
    invoice_status          VARCHAR(50)     NULL,
    payment_status          VARCHAR(50)     NULL,
    bill_submitted_date     DATETIME2(3)    NULL,
    jira_authorized_amount  DECIMAL(18,2)   NULL,
    jira_status             VARCHAR(100)    NULL,
    is_fully_received       BIT             NULL,
    has_suspended_line      BIT             NULL,
    match_flag              VARCHAR(10)     NOT NULL,
    amount_variance         DECIMAL(18,2)   NULL,
    status_bucket           VARCHAR(32)     NOT NULL,
    matched_at               DATETIME2(0)    NOT NULL,
    CONSTRAINT PK_3waymatch PRIMARY KEY (expense_id)
);
GO

/* ---------------------------------------------------------------------
   Refresh procedure - full rebuild of fin.[3waymatch] from
   ThreeWayMatch.dbo.match_results. Call this immediately after
   ThreeWayMatch.dbo.usp_refresh_match_results so the two tables never
   disagree.
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE fin.usp_refresh_3waymatch
AS
BEGIN
    SET NOCOUNT ON;

    TRUNCATE TABLE fin.[3waymatch];

    INSERT INTO fin.[3waymatch] (
        expense_id, po_number, memo, invoice_number, supplier, bill_amount,
        invoice_status, payment_status, bill_submitted_date, jira_authorized_amount,
        jira_status, is_fully_received, has_suspended_line, match_flag,
        amount_variance, status_bucket, matched_at
    )
    SELECT
        expense_id, po_number, memo, invoice_number, supplier, bill_amount,
        invoice_status, payment_status, bill_submitted_date, jira_authorized_amount,
        jira_status, is_fully_received, has_suspended_line, match_flag,
        amount_variance, status_bucket, matched_at
    FROM ThreeWayMatch.dbo.match_results;
END
GO
