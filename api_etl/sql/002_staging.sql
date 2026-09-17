-- Raw landing tables: one row per API item, per pull. Nothing here is ever
-- transformed in place — stg tables are append-only and exist so the exact
-- API response is always recoverable, even if a rpt mapping was wrong.

CREATE TABLE stg.nonconformances_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.conditions_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.dispositions_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.equipment_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.process_plans_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.execution_operations_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.execution_components_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.wip_traces_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.users_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.skills_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.work_centers_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.products_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO

CREATE TABLE stg.inspection_codes_raw (
    id BIGINT IDENTITY PRIMARY KEY,
    pulled_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    raw_json NVARCHAR(MAX) NOT NULL,
    source_endpoint VARCHAR(200) NOT NULL
);
GO
