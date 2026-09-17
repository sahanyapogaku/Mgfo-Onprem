/*
Part Demand Status Report
Input: @PartCode (mgfo.products.code)

Result sets:
  1. Part header (description, make/buy, tracking flags, lead time, default rev)
  2. Demand vs Supply, 1:1 allocated (demand sorted by need date, supply by ECD;
     inventory is on-hand so it naturally sorts first)
  3. Unallocated/excess supply (open POs & inventory left over after matching all demand)
  4. Blocked/on-hold inventory (never allocated) with best-effort non-conformance link

Source tables (on-prem mgfo schema, snapshotted from the MGFO prod read-replica):
  mgfo.summary_report_view  - decoded MRP netting rows; Type classifies each row as
                               demand (MasterSchedule, PlannedWorkOrder) or supply
                               (Inventory, PurchaseOrderLine, PlannedPurchaseOrder)
  mgfo.inventory_overview   - on-hand lots/serials, with inventory_status and pedigree_code
  mgfo.po_details / mgfo.purchase_order_overview - open PO lines (PONumber, qty remaining,
                               revision, pedigree)
  mgfo.nonconformance_overview - NC records; no confirmed join key to inventory in this
                               snapshot (tried trace_id/serial/lot, zero matches on current
                               blocked rows), so the link below is product_code + pedigree_code
                               best-effort and should be verified once real NC data overlaps.
*/
CREATE OR ALTER PROCEDURE mgfo.usp_PartDemandStatusReport
    @PartCode nvarchar(200)
AS
BEGIN
    SET NOCOUNT ON;

    -- product codes are NOT unique (multi-site master data - 2075 of 3352 codes
    -- exist under more than one site_id), so pick the site's row that actually
    -- has MRP activity rather than an arbitrary match
    DECLARE @ProductId uniqueidentifier =
        (SELECT TOP 1 p.id
         FROM mgfo.products p
         WHERE p.code = @PartCode
         ORDER BY (SELECT COUNT(*) FROM mgfo.summary_report_view s WHERE s.ProductId = p.id) DESC);

    IF @ProductId IS NULL
    BEGIN
        RAISERROR('Part code "%s" not found in mgfo.products', 16, 1, @PartCode);
        RETURN;
    END

    ------------------------------------------------------------------
    -- 1) Part header
    ------------------------------------------------------------------
    SELECT
        p.code                                                  AS PartNumber,
        n.name                                                  AS Description,
        CASE WHEN p.is_make = 1 AND p.is_buy = 1 THEN 'Make/Buy'
             WHEN p.is_make = 1 THEN 'Make'
             WHEN p.is_buy = 1 THEN 'Buy'
             ELSE 'Neither' END                                  AS MakeBuy,
        p.active                                                AS Active,
        p.is_serial_tracked                                     AS SerialTracked,
        p.is_lot_tracked                                        AS LotTracked,
        p.is_inspection_required                                AS InspectionRequired,
        p.lead_time                                             AS LeadTimeDays,
        (SELECT TOP 1 r.revision FROM mgfo.product_revisions r
           WHERE r.product_id = p.id AND r.is_default = 1 AND r.active = 1)
                                                                 AS DefaultRevision
    FROM mgfo.products p
    LEFT JOIN mgfo.product_names n ON n.id = p.id
    WHERE p.id = @ProductId;

    ------------------------------------------------------------------
    -- Demand: MRP requirement lines, sorted by need date
    ------------------------------------------------------------------
    DECLARE @Demand TABLE (
        RowNum int IDENTITY(1,1) PRIMARY KEY,
        NeedDate date,
        Rev nvarchar(50),
        Quantity decimal(18,5),
        RemainingQty decimal(18,5)
    );
    DECLARE @DefaultRev nvarchar(50) =
        (SELECT TOP 1 revision FROM mgfo.product_revisions WHERE product_id = @ProductId AND is_default = 1 AND active = 1);

    INSERT INTO @Demand (NeedDate, Rev, Quantity, RemainingQty)
    SELECT DueDate, @DefaultRev + ' (best-effort - not tracked per demand line)', Quantity, Quantity
    FROM mgfo.summary_report_view
    WHERE ProductId = @ProductId
      AND Type IN ('MasterSchedule', 'PlannedWorkOrder')
    ORDER BY DueDate;

    ------------------------------------------------------------------
    -- Supply: allocatable pool = open PO lines + AVAILABLE inventory
    ------------------------------------------------------------------
    DECLARE @Supply TABLE (
        RowNum int IDENTITY(1,1) PRIMARY KEY,
        EcdDate date,
        Rev nvarchar(50),
        SourceType nvarchar(30),
        Reference nvarchar(200),
        Pedigree nvarchar(20),
        Quantity decimal(18,5),
        RemainingQty decimal(18,5)
    );

    INSERT INTO @Supply (EcdDate, Rev, SourceType, Reference, Pedigree, Quantity, RemainingQty)
    SELECT
        CAST(GETDATE() AS date),
        i.product_revision,
        'Inventory',
        COALESCE(i.trace_serial_number, i.trace_lot_number, i.itag_code, CAST(i.inventory_id AS nvarchar(50))),
        i.pedigree_code,
        i.quantity_on_hand,
        i.quantity_on_hand
    FROM mgfo.inventory_overview i
    WHERE i.product_id = @ProductId AND i.inventory_status = 'AVAILABLE';

    INSERT INTO @Supply (EcdDate, Rev, SourceType, Reference, Pedigree, Quantity, RemainingQty)
    SELECT
        TRY_CAST(o.order_line_due_date AS date),
        o.order_line_product_revision,
        'Open PO',
        o.order_header_number + ' / line ' + o.order_line_number,
        o.order_line_pedigree_code,
        d.QuantityRemaining,
        d.QuantityRemaining
    FROM mgfo.po_details d
    JOIN mgfo.purchase_order_overview o ON o.order_line_id = d.PurchaseOrderLineId
    WHERE d.ProductId = @ProductId
      AND d.PurchaseOrderDetailStatusCode NOT IN ('CANCELLED', 'COMPLETED')
      AND d.QuantityRemaining > 0;

    ------------------------------------------------------------------
    -- Greedy 1:1 allocation: earliest demand pulls from earliest-ECD supply
    ------------------------------------------------------------------
    DECLARE @Result TABLE (
        NeedDate date, DemandRev nvarchar(100), DemandQty decimal(18,5),
        EcdDate date, SupplyRev nvarchar(50), SourceType nvarchar(30),
        Reference nvarchar(200), Pedigree nvarchar(20), AllocatedQty decimal(18,5)
    );

    DECLARE @dRow int, @dRemain decimal(18,5), @dNeed date, @dRev nvarchar(100);
    DECLARE @sRow int, @sRemain decimal(18,5), @sEcd date, @sRev nvarchar(50), @sType nvarchar(30), @sRef nvarchar(200), @sPed nvarchar(20);
    DECLARE @alloc decimal(18,5);

    SELECT TOP 1 @dRow = RowNum, @dRemain = RemainingQty, @dNeed = NeedDate, @dRev = Rev
    FROM @Demand WHERE RemainingQty > 0 ORDER BY NeedDate, RowNum;

    WHILE @dRow IS NOT NULL
    BEGIN
        SET @sRow = NULL;
        SELECT TOP 1 @sRow = RowNum, @sRemain = RemainingQty, @sEcd = EcdDate,
               @sRev = Rev, @sType = SourceType, @sRef = Reference, @sPed = Pedigree
        FROM @Supply WHERE RemainingQty > 0 ORDER BY EcdDate, RowNum;

        IF @sRow IS NULL
        BEGIN
            -- no supply left: record remaining demand as unfulfilled (shortage)
            INSERT INTO @Result (NeedDate, DemandRev, DemandQty, EcdDate, SupplyRev, SourceType, Reference, Pedigree, AllocatedQty)
            VALUES (@dNeed, @dRev, @dRemain, NULL, NULL, 'SHORTAGE - no supply available', NULL, NULL, 0);
            UPDATE @Demand SET RemainingQty = 0 WHERE RowNum = @dRow;
        END
        ELSE
        BEGIN
            SET @alloc = CASE WHEN @dRemain <= @sRemain THEN @dRemain ELSE @sRemain END;

            INSERT INTO @Result (NeedDate, DemandRev, DemandQty, EcdDate, SupplyRev, SourceType, Reference, Pedigree, AllocatedQty)
            VALUES (@dNeed, @dRev, @alloc, @sEcd, @sRev, @sType, @sRef, @sPed, @alloc);

            UPDATE @Demand SET RemainingQty = RemainingQty - @alloc WHERE RowNum = @dRow;
            UPDATE @Supply SET RemainingQty = RemainingQty - @alloc WHERE RowNum = @sRow;
        END

        SET @dRow = NULL;
        SELECT TOP 1 @dRow = RowNum, @dRemain = RemainingQty, @dNeed = NeedDate, @dRev = Rev
        FROM @Demand WHERE RemainingQty > 0 ORDER BY NeedDate, RowNum;
    END

    ------------------------------------------------------------------
    -- 2) Demand vs Supply, 1:1 matched, sorted by need date
    ------------------------------------------------------------------
    SELECT
        NeedDate, DemandRev, DemandQty,
        EcdDate, SupplyRev, SourceType, Reference, Pedigree, AllocatedQty
    FROM @Result
    ORDER BY NeedDate;

    ------------------------------------------------------------------
    -- 3) Unallocated/excess supply (left over after all demand satisfied)
    ------------------------------------------------------------------
    SELECT EcdDate, Rev, SourceType, Reference, Pedigree, RemainingQty AS ExcessQty
    FROM @Supply
    WHERE RemainingQty > 0
    ORDER BY EcdDate;

    ------------------------------------------------------------------
    -- 4) Blocked / on-hold inventory - excluded from allocation, shown separately
    --    NC link is best-effort (product_code + pedigree_code); no confirmed key
    --    (trace_id/serial/lot) matched current NC data in this snapshot.
    ------------------------------------------------------------------
    SELECT
        i.inventory_status, i.product_revision AS Rev,
        COALESCE(i.trace_serial_number, i.trace_lot_number, i.itag_code) AS Reference,
        i.pedigree_code, i.quantity_on_hand,
        nc.nonconformance_number, nc.nonconformance_status, nc.condition_reject_category
    FROM mgfo.inventory_overview i
    OUTER APPLY (
        SELECT TOP 1 n.nonconformance_number, n.nonconformance_status, n.condition_reject_category
        FROM mgfo.nonconformance_overview n
        WHERE n.where_found_trace_product_code = i.product_code
          AND (n.where_found_trace_product_revision = i.product_revision OR n.where_found_trace_product_revision IS NULL)
        ORDER BY n.nonconformance_created_on DESC
    ) nc
    WHERE i.product_id = @ProductId
      AND i.inventory_status IN ('BLOCKED', 'ON_HOLD');
END
