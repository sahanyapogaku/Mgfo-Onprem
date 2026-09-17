-- Pipeline control tables: incremental watermarks and per-run observability log.

CREATE TABLE etl.watermark (
    endpoint_name VARCHAR(200) PRIMARY KEY,
    last_watermark DATETIME2 NULL,
    last_run_status VARCHAR(20),
    last_run_at DATETIME2
);
GO

-- Seed rows for the two endpoints that support an incremental filter.
-- All other endpoints are full-pull and never consult etl.watermark.
INSERT INTO etl.watermark (endpoint_name, last_watermark, last_run_status)
VALUES
    ('nonconformances', NULL, 'never_run'),
    ('conditions', NULL, 'never_run');
GO

CREATE TABLE etl.run_log (
    run_id BIGINT IDENTITY PRIMARY KEY,
    endpoint_name VARCHAR(200) NOT NULL,
    started_at DATETIME2 NOT NULL,
    ended_at DATETIME2 NOT NULL,
    rows_pulled INT NOT NULL,
    rows_upserted INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message NVARCHAR(MAX) NULL
);
CREATE INDEX ix_run_log_endpoint_started_at ON etl.run_log (endpoint_name, started_at DESC);
GO
