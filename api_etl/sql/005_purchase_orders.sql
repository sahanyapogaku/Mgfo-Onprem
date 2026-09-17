-- Purchase orders. Added after initial deployment (001-004 already applied to
-- the live `mnfo` database), so this ships as its own numbered script rather
-- than editing 002_staging.sql/003_reporting.sql in place.
--
-- Source: GET /eworkin-plus/inventory/api/integrations/orders/purchase-orders
-- (SiteCode, OrderNumber query params). Unlike every other endpoint in this
-- pipeline, this one is NOT documented with a {items, pagination} envelope —
-- the sample response is a single PO object with a nested orderLines[] array.
-- The extractor (etl/extractors/purchase_orders.py) calls it once per known
-- site code (pulled from rpt.work_centers.site_code) with OrderNumber omitted,
-- and normalizes whatever comes back (single object vs array) defensively.
-- ASSUMPTION TO VERIFY LIVE: that omitting OrderNumber returns all POs for a
-- site rather than erroring — adjust the extractor once confirmed against a
-- real call, per this project's practice of verifying field shapes live.

CREATE TABLE stg.purchase_orders_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE rpt.purchase_orders (
    purchase_order_id UNIQUEIDENTIFIER PRIMARY KEY,
    order_number VARCHAR(100) NOT NULL,
    site_code VARCHAR(100),
    transit_site_code VARCHAR(100),
    partner_code VARCHAR(100),
    partner_name VARCHAR(200),
    area_code VARCHAR(100),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_purchase_orders_order_number ON rpt.purchase_orders (order_number);
GO

-- One row per orderLines[] entry. unit_cost/currency_alphabetic_code/
-- quantity_ordered are the fields a 3-way match (PO vs. receipt vs. payment)
-- needs to compare against Jira/Brex records; line_amount is precomputed
-- (unit_cost * quantity_ordered) so downstream consumers don't recompute it.
CREATE TABLE rpt.purchase_order_lines (
    line_id UNIQUEIDENTIFIER PRIMARY KEY,
    purchase_order_id UNIQUEIDENTIFIER NOT NULL,
    order_detail_number VARCHAR(100),
    product_id UNIQUEIDENTIFIER,
    product_code VARCHAR(100),
    product_description VARCHAR(500),
    product_revision VARCHAR(50),
    product_uom_code VARCHAR(50),
    quantity_ordered DECIMAL(18, 4),
    quantity_completed DECIMAL(18, 4),
    uom_code VARCHAR(50),
    due_date DATETIME2,
    delivery_date DATETIME2,
    status_id INT,
    status_description VARCHAR(100),
    comment NVARCHAR(MAX),
    pedigree_code VARCHAR(100),
    project_code VARCHAR(100),
    inspection_code VARCHAR(100),
    inventory_status_id INT,
    inventory_status_description VARCHAR(100),
    under_tolerance DECIMAL(9, 4),
    over_tolerance DECIMAL(9, 4),
    unit_cost DECIMAL(18, 4),
    currency_code VARCHAR(10),
    line_amount DECIMAL(18, 4),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_purchase_order_lines_purchase_order_id ON rpt.purchase_order_lines (purchase_order_id);
GO

-- Convenience rollup for a 3-way match tool: total PO amount per currency
-- (kept separate by currency rather than summed across, since mixed-currency
-- lines on one PO can't be added together meaningfully).
CREATE VIEW rpt.vw_purchase_order_totals AS
SELECT
    po.purchase_order_id,
    po.order_number,
    po.site_code,
    po.partner_code,
    po.partner_name,
    l.currency_code,
    SUM(l.line_amount) AS total_amount,
    COUNT(*) AS line_count
FROM rpt.purchase_orders po
JOIN rpt.purchase_order_lines l ON l.purchase_order_id = po.purchase_order_id
GROUP BY
    po.purchase_order_id, po.order_number, po.site_code,
    po.partner_code, po.partner_name, l.currency_code;
GO
