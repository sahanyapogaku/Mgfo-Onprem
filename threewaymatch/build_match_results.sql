/* =====================================================================
   3-way match: every Brex bill <-> its Jira approval <-> MFGO receipt
   Target platform: SQL Server (on-prem, 10.10.4.174), T-SQL

   Deployed into its own database (ThreeWayMatch) because the three
   sources live in three SEPARATE databases on this instance:
     JiraAnalytics, Brex, mgfo
   (mgfo was named "mfgo" through 2026-09-01; renamed on the server to
   match its own schema name - confirmed via sys.databases on 2026-09-02,
   same data, nothing lost, just update every reference below.)
   No single database has all the tables this proc needs, so every
   reference below is a fully qualified 3-part name. All three
   databases are on the same instance, so this needs no linked server.

   REWORK (2026-08-28): grain changed from "one row per PO" to "one row
   per Brex BILLPAY bill" - matches the actual ask ("validate ... for
   every bill received"), and fixes a real bug in the PO-grain version:
   it compared a single bill's amount (often a partial/down payment -
   several real memos literally say "... - Down Pay w/out Tax") against
   MFGO's TOTAL PO value, which will almost never agree even when
   nothing is wrong. The correct check per the business is:
      1. the combined bill_amount for a PO <= Jira's authorized $ for that
         PO (a cap, not an equality - partial bills are expected and fine)
     2. inventory receipt is a separate yes/no signal from MFGO, not
        another amount to reconcile
   Tier 3 (vendor-name + amount fallback) is dropped in this rework -
   it existed only to resolve Brex<->MFGO when the memo had no PO#,
   which has no role in the new Brex->Jira approval check. If Brex-side
   vendor fallback matching is wanted again later, dbo.fn_normalize_vendor_name
   (see git history / prior version of this file) can be reinstated.

   CORRECTIONS made after verifying live schema/data against 10.10.4.174
   on 2026-08-28 (the original version of this script assumed a schema
   that does not exist on this server):
     1. jira_issues has NO po_number / total_cost column. The real PO
        number + "Total Cost ($)" live on JiraAnalytics.dbo.jira_issue_
        purchase_orders (populated only when a POKRM_ token was found in
        the issue description - see that table's own comments). This is
        the only $ amount field that table has, so it's what "authorized
        $ amount" means here. A given po_number can appear on >1 Jira
        issue (confirmed live: 1 of 65 does), so this sums total_cost
        per po_number - one issue's approval can't be exceeded by a bill
        while a second issue's approval for the same PO sits unused.
     2. staging.stg_mgfo_po_summary never existed anywhere on this
        server. Built below as a view over the real mgfo tables
        (mgfo.mgfo.purchase_order_overview + po_header_statuses, landed
        nightly by extract_to_onprem.py in this repo's root) rather than
        a materialized table, so it can't go stale between runs.
        is_fully_received per PO: SUM(quantity_ordered) -
        SUM(quantity_completed) <= 0 over non-cancelled lines.
        Cancelled lines/headers excluded entirely.
     3. Brex staging.stg_expenses has NO memo column - the memo lives
        inside raw_json ("$.memo"), pulled via JSON_VALUE.

   CONFIRMED AGAINST brex_mssql_etl/sql (01_staging_tables.sql,
   08_bill_pay_transform_procs.sql):
     1. BILLPAY filter column is expense_type (not payment_type - that's
        an unrelated column on stg_payments/dim tables for ACH/WIRE/CHECK).
        Value is 'BILLPAY', no underscore.
     2. staging.stg_expenses's real PK is the surrogate stg_expense_key
        (IDENTITY); expense_id only has a non-unique index
        (IX_stg_expenses_expid). Deduped below the same way every other
        transform proc in 04_transform_procs.sql does it: ROW_NUMBER()
        OVER (PARTITION BY expense_id ORDER BY _ingested_at DESC), rn = 1.
   ===================================================================== */

IF DB_ID('ThreeWayMatch') IS NULL
BEGIN
    CREATE DATABASE ThreeWayMatch;
END
GO

USE ThreeWayMatch;
GO

IF SCHEMA_ID('staging') IS NULL
    EXEC('CREATE SCHEMA staging');
GO

SET NOCOUNT ON;
GO

/* ---------------------------------------------------------------------
   1. staging.stg_mgfo_po_summary - never existed on this server.
   Built as a view (not a materialized table) over the real mfgo tables
   so it can't go stale: extract_to_onprem.py already refreshes
   mfgo.mgfo.* nightly, this just aggregates on read.
   total_amount is kept on the view for anyone inspecting a PO directly,
   but usp_refresh_match_results below no longer uses it (see REWORK
   note at the top of this file) - only is_fully_received / has_suspended_line
   feed the bill-level match now.
   --------------------------------------------------------------------- */
CREATE OR ALTER VIEW staging.stg_mgfo_po_summary AS
SELECT
    o.order_header_number AS po_number,
    MAX(o.order_header_partner_name) AS supplier_name,
    SUM(CASE WHEN o.order_line_status_code <> 'CANCELLED'
              THEN ISNULL(o.order_line_unit_cost, 0) * o.order_line_quantity_ordered
              ELSE 0 END) AS total_amount,
    MAX(CASE WHEN o.order_line_status_code <> 'CANCELLED' AND o.order_line_is_suspended = 1
              THEN 1 ELSE 0 END) AS has_suspended_line,
    CASE WHEN SUM(CASE WHEN o.order_line_status_code <> 'CANCELLED'
                        THEN o.order_line_quantity_ordered - o.order_line_quantity_completed
                        ELSE 0 END) <= 0
         THEN 1 ELSE 0 END AS is_fully_received
FROM mgfo.mgfo.purchase_order_overview o
JOIN mgfo.mgfo.po_header_statuses h
    ON h.purchase_order_header_id = o.order_header_id
WHERE h.purchase_order_header_status_code <> 'CANCELLED'
GROUP BY o.order_header_number;
GO

/* ---------------------------------------------------------------------
   2. Output table - one row per Brex BILLPAY bill (expense_id).
   Schema changed with this rework (previously one row per po_number);
   dropped and recreated since usp_refresh_match_results always does a
   full rebuild anyway, so no history is lost by doing this.
   --------------------------------------------------------------------- */
IF OBJECT_ID('dbo.match_results', 'U') IS NOT NULL
    DROP TABLE dbo.match_results;
GO

CREATE TABLE dbo.match_results (
    expense_id             VARCHAR(64)     NOT NULL,
    po_number              VARCHAR(64)     NULL,       -- NULL if memo had no POKRM_ token
    memo                   VARCHAR(500)    NULL,
    invoice_number         VARCHAR(255)    NULL,        -- Brex raw_json.bill_extension.invoice_number - the vendor's actual invoice #, for matching against it directly
    supplier               VARCHAR(255)    NULL,        -- Brex staging.stg_vendors.vendor_name (Brex is the source of truth for vendor name, per finance)
    bill_amount            DECIMAL(18,2)   NULL,        -- NULL on ~2% of BILLPAY rows (draft/incomplete bills); those skip the over-authorization check below since there's nothing to compare
    invoice_status         VARCHAR(50)     NULL,        -- stg_expenses.status - Brex bill workflow status (DRAFT/SUBMITTED/APPROVED/...)
    payment_status         VARCHAR(50)     NULL,        -- raw_json.payment_status - whether the BILL has actually been PAID (e.g. CLEARED). Not to be confused with is_fully_received (below, whether the INVENTORY showed up - a separate binary MFGO signal) or jira_authorized_amount (the $ that was approved to spend). All three are independent - none is derived from another.
    bill_submitted_date    DATETIME2(3)    NULL,        -- stg_expenses.submitted_date - the bill's OWN date, for real recency sort/filter. matched_at is NOT usable for this: every row in a given refresh shares the identical batch timestamp (confirmed live, e.g. all 1,357 rows = "2026-09-02T15:18:25"), so "most recent by create date" needs this column, not matched_at.
    jira_authorized_amount DECIMAL(18,2)   NULL,        -- SUM(total_cost) across Jira issues citing this PO
    jira_status            VARCHAR(100)    NULL,        -- Jira issue status for the PO issue(s) citing this po_number (e.g. "Order Placed")
    is_fully_received      BIT             NULL,        -- NULL when po_number has no MFGO PO at all
    has_suspended_line     BIT             NULL,
    match_flag             VARCHAR(10)     NOT NULL,    -- 'Match' when status_bucket = 'Fully validated', 'Pending' for 'Awaiting Invoice' (nothing wrong, just no bill yet), else 'Mismatch'
    amount_variance        DECIMAL(18,2)   NULL,        -- total bills for the PO - jira_authorized_amount; positive = the PO exceeds authorized $, NULL when there's no authorized $ to compare against
    status_bucket          VARCHAR(32)     NOT NULL,
    matched_at             DATETIME2(0)    NOT NULL,
    CONSTRAINT PK_match_results PRIMARY KEY (expense_id)
);
GO

/* ---------------------------------------------------------------------
   3. Refresh procedure - full rebuild of match_results
   Status buckets, in priority order:
     No PO in Brex memo      - memo has no extractable POKRM_ token
     No Jira approval found  - PO# extracted, but no Jira issue authorizes it
                                (or none of the issues that do have a $ amount)
      Within 10% of approved amount - total bills for the PO exceed the authorized $ (+ tolerance)
                                by 10% or less
      Over Authorized Amount  - total bills for the PO exceed the authorized $ by more than 10%
      Not yet received        - total bills for the PO are within the authorized $, but MFGO
                                doesn't show the PO as fully received
     Fully validated         - within authorized $ AND fully received
     Awaiting Invoice        - PO is approved in Jira with a $ amount, but no
                                Brex bill references it at all yet (one
                                synthetic row per such PO, not a real bill -
                                expense_id is 'NOINVOICE:<po_number>')
   --------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE dbo.usp_refresh_match_results
AS
BEGIN
    SET NOCOUNT ON;

    -- "small tolerance" per spec: a bill up to $1 over the authorized
    -- amount still counts as within-cap (rounding noise, not an overage).
    DECLARE @tolerance DECIMAL(18,2) = 1.00;

    TRUNCATE TABLE dbo.match_results;

    ;WITH
    -- Authorized $ amount per PO - summed because a po_number can be
    -- cited on more than one Jira issue (confirmed live: 1 of 65 is).
    -- jira_status: MAX() as a tie-break on the rare PO with >1 issue -
    -- good enough since those issues almost always share the same status.
    jira_by_po AS (
        SELECT
            p.po_number,
            SUM(p.total_cost) AS jira_authorized_amount,
            MAX(i.status) AS jira_status
        FROM JiraAnalytics.dbo.jira_issue_purchase_orders p
        JOIN JiraAnalytics.dbo.jira_issues i ON i.issue_id = p.issue_id
        WHERE p.po_number IS NOT NULL
        GROUP BY p.po_number
    ),

    -- Dedupe to one row per natural expense_id, same pattern used by every
    -- transform proc in brex_mssql_etl/sql/04_transform_procs.sql
    -- (stg_expense_key is a surrogate IDENTITY; expense_id can repeat
    -- across re-sync batches).
    stg_expenses_deduped AS (
        SELECT *
        FROM (
            SELECT
                e.*,
                ROW_NUMBER() OVER (PARTITION BY e.expense_id ORDER BY e._ingested_at DESC) AS rn
            FROM Brex.staging.stg_expenses e
            WHERE e.expense_type = 'BILLPAY'
        ) d
        WHERE d.rn = 1
    ),

    -- Extract "POKRM_" + 10 alphanumeric chars from the memo, which
    -- lives in raw_json.memo (stg_expenses has no memo column). Also pull
    -- invoice_number, payment_status, and vendor_id out of the same JSON.
    brex_billpay AS (
        SELECT
            e.expense_id,
            -- brex_mssql_etl/python/flatten.py:flatten_expense() previously stored
            -- Brex's raw money-object amount (cents, Brex's API convention) with no
            -- /100 conversion. Fixed at the source now: flatten.py converts on
            -- future ingests, and brex_mssql_etl/migrations/
            -- 001_fix_amount_cents_to_dollars.sql backfilled existing staging rows
            -- (applied 2026-08-31 - see migrations.applied_migrations). So
            -- stg_expenses.amount is correct dollars again - no conversion needed
            -- here anymore. Do NOT re-add a /100 here; that would double-divide.
            e.amount AS bill_amount,
            e.status AS invoice_status,
            e.submitted_date AS bill_submitted_date,
            JSON_VALUE(e.raw_json, '$.memo') AS memo,
            JSON_VALUE(e.raw_json, '$.payment_status') AS payment_status,
            JSON_VALUE(e.raw_json, '$.bill_extension.invoice_number') AS invoice_number,
            JSON_VALUE(e.raw_json, '$.vendor_id') AS vendor_id,
            CASE
                WHEN PATINDEX(
                        '%POKRM[_][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z]%',
                        JSON_VALUE(e.raw_json, '$.memo')) > 0
                THEN SUBSTRING(
                        JSON_VALUE(e.raw_json, '$.memo'),
                        PATINDEX(
                            '%POKRM[_][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z][0-9A-Za-z]%',
                            JSON_VALUE(e.raw_json, '$.memo')),
                        16)  -- len('POKRM_') + 10
                ELSE NULL
            END AS po_number
        FROM stg_expenses_deduped e
    ),

    -- Multiple invoices can reference one PO. Compare their combined value
    -- with the one Jira authorization, while retaining invoice-level rows
    -- in the output for review.
    --
    -- FIX (2026-09-10): a VOID bill must not count toward the PO's billed
    -- total. Confirmed live: PO with SPY_2764 ($20,649.51, APPROVED/CLEARED)
    -- also had a second, VOID bill for the identical $20,649.51 (a blank
    -- invoice-number record) - summing both produced $41,299.02 against a
    -- $20,649.51 Jira authorization, flagging a real, correctly-paid bill as
    -- "Over Authorized Amount" by exactly the void amount. A voided bill was
    -- never actually charged, so it must be excluded from this sum - same
    -- principle as excluding CANCELLED lines in staging.stg_mgfo_po_summary
    -- above.
    bill_totals_by_po AS (
        SELECT
            po_number,
            SUM(bill_amount) AS po_billed_amount
        FROM brex_billpay
        WHERE po_number IS NOT NULL
          AND (invoice_status IS NULL OR invoice_status <> 'VOID')
        GROUP BY po_number
    ),

    joined AS (
        SELECT
            b.expense_id,
            b.po_number,
            b.memo,
            b.invoice_number,
            v.vendor_name AS supplier,
            b.bill_amount,
            b.invoice_status,
            b.payment_status,
            b.bill_submitted_date,
            t.po_billed_amount,
            j.jira_authorized_amount,
            j.jira_status,
            m.is_fully_received,
            m.has_suspended_line
        FROM brex_billpay b
        LEFT JOIN bill_totals_by_po t          ON t.po_number = b.po_number
        LEFT JOIN Brex.staging.stg_vendors v    ON v.vendor_id = b.vendor_id
        LEFT JOIN jira_by_po j                  ON j.po_number = b.po_number
        LEFT JOIN staging.stg_mgfo_po_summary m ON m.po_number = b.po_number
    ),

    classified AS (
        SELECT
            *,
            CASE
                WHEN po_number IS NULL THEN 'No PO in Brex memo'
                WHEN jira_authorized_amount IS NULL THEN 'No Jira approval found'
                -- Split by how far the PO's combined invoices are over the
                -- cap. This prevents several individually-valid partial bills
                -- from collectively exceeding the Jira authorization.
                WHEN po_billed_amount > jira_authorized_amount + @tolerance
                     AND po_billed_amount <= jira_authorized_amount * 1.10 THEN 'Within 10% of approved amount'
                WHEN po_billed_amount > jira_authorized_amount + @tolerance THEN 'Over Authorized Amount'
                WHEN ISNULL(is_fully_received, 0) = 0 THEN 'Not yet received'
                ELSE 'Fully validated'
            END AS status_bucket
        FROM joined
    ),

    -- Every po_number any Brex bill references at all (matched to Jira or
    -- not) - used only to find Jira-approved POs with ZERO bills against
    -- them yet, not to filter the bill-grain rows above.
    brex_po_numbers AS (
        SELECT DISTINCT po_number FROM brex_billpay WHERE po_number IS NOT NULL
    ),

    -- New category: PO is approved in Jira with a $ amount, but Brex has no
    -- bill for it at all yet - distinct from "Not yet received" (which
    -- requires a bill to already exist) and from "No Jira approval found"
    -- (which requires a bill that couldn't find its Jira approval). One
    -- synthetic row per such PO, since there's no real bill/expense_id to
    -- key on.
    awaiting_invoice AS (
        SELECT
            j.po_number,
            j.jira_authorized_amount,
            j.jira_status,
            m.supplier_name AS supplier,   -- Brex has nothing yet for this PO, so MFGO is the only source of a name here
            m.is_fully_received,
            m.has_suspended_line
        FROM jira_by_po j
        LEFT JOIN staging.stg_mgfo_po_summary m ON m.po_number = j.po_number
        WHERE j.po_number NOT IN (SELECT po_number FROM brex_po_numbers)
    )

    INSERT INTO dbo.match_results (
        expense_id, po_number, memo, invoice_number, supplier, bill_amount,
        invoice_status, payment_status, bill_submitted_date, jira_authorized_amount, jira_status,
        is_fully_received, has_suspended_line, match_flag, amount_variance,
        status_bucket, matched_at
    )
    SELECT
        expense_id,
        po_number,
        memo,
        invoice_number,
        supplier,
        bill_amount,
        invoice_status,
        payment_status,
        bill_submitted_date,
        jira_authorized_amount,
        jira_status,
        is_fully_received,
        has_suspended_line,
        CASE WHEN status_bucket = 'Fully validated' THEN 'Match' ELSE 'Mismatch' END AS match_flag,
        po_billed_amount - jira_authorized_amount AS amount_variance,
        status_bucket,
        SYSDATETIME() AS matched_at
    FROM classified

    UNION ALL

    SELECT
        CONCAT('NOINVOICE:', po_number) AS expense_id,
        po_number,
        NULL AS memo,
        NULL AS invoice_number,
        supplier,
        NULL AS bill_amount,
        NULL AS invoice_status,
        NULL AS payment_status,
        NULL AS bill_submitted_date,   -- no real bill exists yet for this row
        jira_authorized_amount,
        jira_status,
        is_fully_received,
        has_suspended_line,
        'Pending' AS match_flag,
        NULL AS amount_variance,
        'Awaiting Invoice' AS status_bucket,
        SYSDATETIME() AS matched_at
    FROM awaiting_invoice;
END
GO
