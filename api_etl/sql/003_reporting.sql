-- Typed reporting tables. Keyed on the Manufacturo GUID/ID; loaded via MERGE
-- from the corresponding stg.*_raw table (see etl/db.py:merge_upsert).
--
-- Column choices were verified against live sample payloads pulled from each
-- endpoint on 2026-08-19 (not just the build spec's field list, which in
-- several cases — equipment, conditions, execution operations/components,
-- wip traces, process plans, products — used different field names/nesting
-- than what the API actually returns). stg tables retain the untouched raw
-- JSON regardless, so any further mismatch can be fixed without re-pulling.

CREATE TABLE rpt.nonconformances (
    nonconformance_id UNIQUEIDENTIFIER PRIMARY KEY,
    number VARCHAR(50) NOT NULL,
    site_id UNIQUEIDENTIFIER,
    status_id INT,
    status_description VARCHAR(100),
    assignee_id UNIQUEIDENTIFIER,
    assignee_login VARCHAR(200),
    owner_id UNIQUEIDENTIFIER,
    owner_login VARCHAR(200),
    reported_on DATETIME2,
    last_modified_on DATETIME2,
    completed_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_nonconformances_last_modified_on ON rpt.nonconformances (last_modified_on);
GO

-- "Conditions" in the NC v2 API are reject-reason records on a nonconformance
-- (reject category/code, cause codes, where-found), not quantity/lot tracking.
CREATE TABLE rpt.nc_conditions (
    condition_id UNIQUEIDENTIFIER PRIMARY KEY,
    nonconformance_id UNIQUEIDENTIFIER,
    site_id UNIQUEIDENTIFIER,
    sequence_number INT,
    summary NVARCHAR(MAX),
    status_id INT,
    status_description VARCHAR(100),
    reject_category_id UNIQUEIDENTIFIER,
    reject_category_code VARCHAR(100),
    reject_code_id UNIQUEIDENTIFIER,
    reject_code_code VARCHAR(100),
    where_found VARCHAR(200),
    is_further_action_required BIT,
    last_modified_on DATETIME2,
    completed_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_nc_conditions_nonconformance_id ON rpt.nc_conditions (nonconformance_id);
GO

CREATE TABLE rpt.nc_dispositions (
    disposition_id UNIQUEIDENTIFIER PRIMARY KEY,
    nonconformance_id UNIQUEIDENTIFIER,
    sequence_number INT,
    type_id INT,
    type_code VARCHAR(100),
    type_description VARCHAR(200),
    status_id INT,
    status_description VARCHAR(100),
    assignee_id UNIQUEIDENTIFIER,
    instruction NVARCHAR(MAX),
    execution_note NVARCHAR(MAX),
    verification_note NVARCHAR(MAX),
    rationale NVARCHAR(MAX),
    summary NVARCHAR(MAX),
    require_verification BIT,
    is_repair BIT,
    is_customer_approval_required BIT,
    is_flexible BIT,
    last_modified_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_nc_dispositions_nonconformance_id ON rpt.nc_dispositions (nonconformance_id);
GO

-- This endpoint returns calibration/metrology equipment records (iTag,
-- calibration vendor, tolerance/accuracy/range units) — not shop-floor
-- machine/workcenter equipment as originally assumed.
CREATE TABLE rpt.equipment (
    equipment_id UNIQUEIDENTIFIER PRIMARY KEY,
    external_id VARCHAR(100),
    itag_code VARCHAR(100),
    is_active BIT,
    calibration_vendor_id UNIQUEIDENTIFIER,
    calibration_vendor_code VARCHAR(100),
    calibration_vendor_name VARCHAR(200),
    tolerance_unit_id UNIQUEIDENTIFIER,
    tolerance_unit_code VARCHAR(50),
    tolerance_unit_name VARCHAR(100),
    accuracy_unit_id UNIQUEIDENTIFIER,
    accuracy_unit_code VARCHAR(50),
    accuracy_unit_name VARCHAR(100),
    range_unit_id UNIQUEIDENTIFIER,
    range_unit_code VARCHAR(50),
    range_unit_name VARCHAR(100),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE rpt.process_plans (
    process_plan_id UNIQUEIDENTIFIER PRIMARY KEY,
    name VARCHAR(200),
    revision VARCHAR(50),
    is_latest BIT,
    type_id INT,
    type_description VARCHAR(100),
    status_id INT,
    status_description VARCHAR(100),
    bom_id UNIQUEIDENTIFIER,
    bom_name VARCHAR(200),
    bom_revision VARCHAR(50),
    pedigree_id INT,
    pedigree_description VARCHAR(100),
    process_family_id UNIQUEIDENTIFIER,
    process_family_number VARCHAR(100),
    created_on DATETIME2,
    updated_on DATETIME2,
    released_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_process_plans_updated_on ON rpt.process_plans (updated_on);
GO

-- A process plan can reference multiple products (item.products[]), so this
-- is a genuine one-to-many child table, not a single product_id column.
CREATE TABLE rpt.process_plan_products (
    process_plan_product_key VARCHAR(160) PRIMARY KEY,  -- "<process_plan_id>:<product_guid>"
    process_plan_id UNIQUEIDENTIFIER NOT NULL,
    product_guid UNIQUEIDENTIFIER,
    product_code VARCHAR(100),
    product_revision VARCHAR(50),
    product_description VARCHAR(500),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_process_plan_products_process_plan_id ON rpt.process_plan_products (process_plan_id);
GO

CREATE TABLE rpt.execution_operations (
    operation_id UNIQUEIDENTIFIER PRIMARY KEY,
    wip_trace_id UNIQUEIDENTIFIER,
    wip_order_operation_id UNIQUEIDENTIFIER,
    code_number INT,
    priority INT,
    serial_number VARCHAR(100),
    lot_number VARCHAR(100),
    description VARCHAR(500),
    status_id INT,
    status_description VARCHAR(100),
    redline_status_id INT,
    redline_status_description VARCHAR(100),
    work_center_id UNIQUEIDENTIFIER,
    work_center_code VARCHAR(100),
    order_id UNIQUEIDENTIFIER,
    order_number VARCHAR(50),
    product_id UNIQUEIDENTIFIER,
    product_code VARCHAR(100),
    product_revision VARCHAR(50),
    created_on DATETIME2,
    updated_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_execution_operations_order_id ON rpt.execution_operations (order_id);
GO

CREATE TABLE rpt.execution_components (
    component_id UNIQUEIDENTIFIER PRIMARY KEY,
    step_id UNIQUEIDENTIFIER,
    planned_quantity DECIMAL(18, 4),
    activity_type_code VARCHAR(50),
    consumption_type_code VARCHAR(50),
    product_id UNIQUEIDENTIFIER,
    product_code VARCHAR(100),
    product_name VARCHAR(200),
    product_revision_id UNIQUEIDENTIFIER,
    product_revision_code VARCHAR(50),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_execution_components_step_id ON rpt.execution_components (step_id);
GO

-- Each component can have multiple consumption records (item.records[]).
CREATE TABLE rpt.execution_component_records (
    record_id UNIQUEIDENTIFIER PRIMARY KEY,
    component_id UNIQUEIDENTIFIER NOT NULL,
    quantity DECIMAL(18, 4),
    removed_quantity DECIMAL(18, 4),
    reference_designator VARCHAR(200),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_execution_component_records_component_id ON rpt.execution_component_records (component_id);
GO

CREATE TABLE rpt.wip_traces (
    wip_trace_id UNIQUEIDENTIFIER PRIMARY KEY,
    serial_number VARCHAR(100),
    lot_number VARCHAR(100),
    status_id INT,
    status_description VARCHAR(100),
    redline_status_id INT,
    redline_status_description VARCHAR(100),
    order_id UNIQUEIDENTIFIER,
    order_number VARCHAR(50),
    product_id UNIQUEIDENTIFIER,
    product_code VARCHAR(100),
    product_revision VARCHAR(50),
    created_on DATETIME2,
    updated_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_wip_traces_order_id ON rpt.wip_traces (order_id);
GO

CREATE TABLE rpt.users (
    user_id UNIQUEIDENTIFIER PRIMARY KEY,
    code VARCHAR(200),
    login VARCHAR(200),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    is_active BIT,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE rpt.skills (
    skill_id UNIQUEIDENTIFIER PRIMARY KEY,
    code VARCHAR(100),
    name VARCHAR(200),
    is_active BIT,
    site_id UNIQUEIDENTIFIER,
    expiration_date_tracked BIT,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE rpt.work_centers (
    work_center_id UNIQUEIDENTIFIER PRIMARY KEY,
    code VARCHAR(100),
    name VARCHAR(200),
    work_center_type INT,
    is_active BIT,
    site_id UNIQUEIDENTIFIER,
    site_code VARCHAR(100),
    site_name VARCHAR(200),
    production_line_id UNIQUEIDENTIFIER,
    production_line_code VARCHAR(100),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE rpt.products (
    product_id UNIQUEIDENTIFIER PRIMARY KEY,
    site_id UNIQUEIDENTIFIER,
    part_number VARCHAR(100),
    description VARCHAR(500),
    is_active BIT,
    product_type VARCHAR(100),
    uom_code VARCHAR(50),
    tracking VARCHAR(50),
    is_equipment BIT,
    created_on DATETIME2,
    updated_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_products_updated_on ON rpt.products (updated_on);
GO

-- Revisions carry their own real GUID (revisions.items[].id) — no synthetic
-- key needed, unlike originally assumed.
CREATE TABLE rpt.product_revisions (
    product_revision_id UNIQUEIDENTIFIER PRIMARY KEY,
    product_id UNIQUEIDENTIFIER NOT NULL,
    code VARCHAR(50),
    is_active BIT,
    is_default BIT,
    inspection_code_id UNIQUEIDENTIFIER,
    status VARCHAR(100),
    created_on DATETIME2,
    updated_on DATETIME2,
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_product_revisions_product_id ON rpt.product_revisions (product_id);
GO

-- Confirmed live: this endpoint returns only {id, code} per item — no
-- description or active flag.
CREATE TABLE rpt.inspection_codes (
    inspection_code_id UNIQUEIDENTIFIER PRIMARY KEY,
    code VARCHAR(100),
    synced_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
