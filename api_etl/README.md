# Manufacturo → MSSQL ETL

**This pipeline is strictly read-only against Manufacturo.** It only ever
calls `GET` and `POST .../filter` / `.../list` endpoints, enforced by a
hard-coded allowlist in `etl/http_client.py` (`ALLOWLIST`) — any call to a
path/method not in that set raises `DisallowedEndpointError` before a request
is sent. Every write this pipeline performs lands in MSSQL only. Nothing is
ever created, updated, or deleted in Manufacturo.

## What it does

For each of 14 Manufacturo endpoints, a dedicated extractor:

1. Pages through the endpoint (`pagination.limit`/`offset`, following
   `hasNext`) using the documented max page size.
2. For endpoints with an incremental filter (`nonconformances`,
   `conditions`), reads the last watermark from `etl.watermark` and filters
   with `lastModifiedOn: {gte: <watermark>}`. All other endpoints do a full
   pull every run.
3. Lands every raw item into a `stg.<entity>_raw` table (untouched JSON) —
   this happens *before* any parsing, so a bad mapping never loses data.
4. Maps and `MERGE`s (upserts) into a typed `rpt.<entity>` table keyed on the
   Manufacturo GUID/ID.
5. Advances the watermark, but only after staging + upsert both succeed.

One endpoint failing (network error, bad payload, schema mismatch) does not
stop the others — see `etl/run_all.py`.

## Project layout

```
etl/
  config.py              # env-driven config (base URL, API key, MSSQL conn string, page sizes)
  http_client.py         # ManufacturoClient — auth header, retries, the read-only allowlist
  db.py                  # MSSQL connection, staging insert, generic MERGE upsert
  engine.py              # ExtractorSpec + run_extractor: shared pagination/load/watermark logic
  mapping.py             # small helpers for the per-endpoint mapper functions
  logging_config.py
  run_all.py             # entrypoint — run all/some extractors, write etl.run_log
  extractors/
    nonconformances.py   # incremental
    conditions.py        # incremental
    dispositions.py
    equipment.py
    process_plans.py
    execution_operations.py
    execution_components.py
    wip_traces.py
    users.py
    skills.py
    work_centers.py
    products.py           # writes rpt.products AND rpt.product_revisions
    inspection_codes.py    # GET, no pagination
    purchase_orders.py     # GET by SiteCode, writes rpt.purchase_orders AND rpt.purchase_order_lines
sql/
  001_schemas.sql   # stg / rpt / etl schemas
  002_staging.sql   # stg.*_raw tables
  003_reporting.sql # rpt typed tables
  004_etl_control.sql # etl.watermark, etl.run_log
  005_purchase_orders.sql # stg/rpt purchase order tables, added post-deployment
.env.example
requirements.txt
```

## Setup

1. Provision an MSSQL database and run the DDL in order:
   `001_schemas.sql`, `002_staging.sql`, `003_reporting.sql`, `004_etl_control.sql`,
   `005_purchase_orders.sql`.
2. Request a Manufacturo API key scoped **read-only**: "Nonconformance Public
   API read", "Equipment read", "Order Read", "Process Plan Read",
   "User Data read", "Skills read", "Work Center read", "Product read",
   "Purchase Order read". Do not request create/update/delete/execute scopes
   for this integration.
3. Copy `.env.example` to `.env` and fill in the base URL, API key, and MSSQL
   connection details. `.env` is loaded by `etl/config.py` via
   `python-dotenv` — never commit it, and never hardcode the key in source.
4. `pip install -r requirements.txt` (requires the MSSQL ODBC driver — e.g.
   "ODBC Driver 18 for SQL Server" — installed on the host).

## Running

```bash
python -m etl.run_all                    # every extractor
python -m etl.run_all --group fast        # nonconformances + conditions only
python -m etl.run_all --group slow        # everything else (full-pull endpoints)
python -m etl.run_all --only equipment,products
```

Suggested schedule (via cron or Windows Task Scheduler):

- `--group fast` every 15–60 minutes — nonconformances/conditions support a
  cheap incremental filter, so frequent polling is low-cost.
- `--group slow` every few hours — these endpoints have no modified-date
  filter, so every run is a full pull; run them only as often as freshness
  actually requires, to limit API load.

Every run writes one row per endpoint to `etl.run_log` (start/end time, rows
pulled, rows upserted, status, error message) regardless of success or
failure, so a monitoring dashboard/alert can be built directly on top of it.

## Watermark / incremental logic

`etl.watermark` holds one row per incremental endpoint:
`endpoint_name, last_watermark, last_run_status, last_run_at`.

- Before calling the API, the extractor reads `last_watermark` and — if not
  `NULL` — adds `{"<field>": {"gte": <watermark>}}` to the filter body.
- The new high-water mark is the max of the field's values seen across all
  pulled rows this run.
- The watermark is only written after staging insert + MERGE both commit
  successfully. If either fails, the watermark is left untouched, so the
  next run re-pulls the same window instead of silently skipping data.
- Naive `DATETIME2` values (no timezone) are treated as UTC, matching
  `SYSUTCDATETIME()` and Manufacturo's timestamp fields.

Endpoints without a modified-date filter (dispositions, equipment,
execution operations/components, WIP traces, users, skills, work centers,
inspection codes, purchase orders) do a full pull every run and never touch
`etl.watermark`. Process plans and products retain their `updated_on` column
so a downstream consumer can diff client-side, but the extractor itself still
pulls the full set each run, per the documented API shape.

## Adding a new endpoint extractor

1. Add the `(METHOD, path)` pair to `ALLOWLIST` in `etl/http_client.py` —
   extraction will fail closed until this is done.
2. Add `stg.<entity>_raw` (copy the pattern in `sql/002_staging.sql`) and
   `rpt.<entity>` (copy the pattern in `sql/003_reporting.sql`) tables.
3. Create `etl/extractors/<entity>.py`:
   - a mapper function `raw_item(dict) -> rpt row dict`
   - an `ExtractorSpec` (path, stg/rpt table names, key column, columns,
     mapper, page size, and `incremental_field`/`incremental_field_column`
     if applicable)
   - a thin `extract_<entity>(client, conn)` that calls
     `engine.run_extractor(client, conn, SPEC)`
   (If the entity needs to fan out into more than one `rpt` table, follow
   `etl/extractors/products.py` instead, which drives `db.merge_upsert`
   directly rather than going through `run_extractor`'s single-table path.)
4. Register it in `GROUPS` in `etl/run_all.py` (`"fast"` if it has a cheap
   incremental filter, `"slow"` otherwise).
5. If it's incremental, seed a row in `etl.watermark` (see
   `sql/004_etl_control.sql`).

## Notes / caveats

- Field names in the `rpt` mapper functions are best-effort based on the
  documented response shapes in this project's build spec. `stg.*_raw`
  always retains the untouched JSON, so if a live payload uses different
  field names or nesting than assumed, only the relevant mapper + DDL need
  to change — no re-pull required to fix a mapping bug.
- `db.py` passes GUID strings as query parameters into `UNIQUEIDENTIFIER`
  columns; depending on ODBC driver version you may need
  `pyodbc.native_uuid = True` (or to pass `uuid.UUID` objects) if you see
  conversion errors — verify against your specific driver/SQL Server version
  before first production run.
- `purchase_orders` is a **hybrid, two-source extractor** — confirmed live
  that the public API cannot bulk-list POs at all: `GET .../purchase-orders`
  with only `SiteCode` returns HTTP 400 `"Order number is missing"`; it
  requires an exact `OrderNumber` per call, always.

  So `etl/extractors/purchase_orders.py` splits the problem:
  - **Order-number discovery** (optional per run): calls the internal
    "purchase order cockpit" endpoint that backs Manufacturo's own web UI —
    `POST /eworkin-plus/inventory/api/purchaseOrderCockpit/purchase-orders/list`.
    This is **not part of the public API and not in `ALLOWLIST`** — it was
    found via browser DevTools, is undocumented, and only accepts a
    short-lived (~5 min) interactive-login Bearer token, not `MNFO_API_KEY`.
    Paste one into `MANUFACTURO_BEARER_TOKEN` before a run that needs to find
    order numbers this pipeline hasn't seen yet. If it's absent or the token
    is rejected, this step is skipped/fails clearly rather than silently
    guessing — see `CockpitAuthError` in that file.
  - **Detail pull** (uses `MNFO_API_KEY` like every other extractor): for
    every order number known (freshly discovered + whatever's already in
    `rpt.purchase_orders` from a prior run), calls the public per-order
    endpoint and maps header + `orderLines[]` as normal. This is the only
    call whose response shape is fully verified against the documented
    schema — the cockpit endpoint's own item shape isn't confirmed beyond
    `orderNumber`/`guid`/`status`, so its raw response is staged for audit
    only and never mapped into `rpt`.

  **Live blocker as of this writing:** `MNFO_API_KEY` does not have the
  "Purchase Order read" privilege granted yet — the detail-pull call fails
  even for a real, confirmed-existing order number with
  `{"statusCode":401,"message":"Authentication failure: ApiKey unauthorized"}`.
  This has to be granted on Manufacturo's side before `purchase_orders` can
  land any real data; until then the extractor will fail clearly on Step B
  every run. `rpt.purchase_orders`/`rpt.purchase_order_lines` hold the PO
  header and line-level amounts (`unit_cost`, `currency_code`,
  `line_amount`); `rpt.vw_purchase_order_totals` rolls line amounts up per
  PO/currency for a 3-way-match (PO vs. receipt vs. payment) use case —
  matching against Jira/Brex records is downstream of this repo, which stays
  Manufacturo-read-only into MSSQL only.

## Known gaps for downstream reporting (e.g. MRP shortage reports)

Checked live and confirmed **not currently populated** — relevant if
someone asks for a report joining these:
- **Make/Buy flag per product**: Manufacturo's product payload has
  `supplyMrp.isMake`/`isBuy`, but `rpt.products` (2,362 rows as of this
  writing) has no columns for it — `products.py`'s mapper doesn't capture
  `supplyMrp` at all yet.
- **BOM parent-child (Product Structure)**: `rpt.process_plans` has
  `bom_id`/`bom_name`/`bom_revision` columns, but **both `rpt.process_plans`
  and `rpt.process_plan_products` currently have 0 rows** — the extractor
  exists but has apparently never been run, so there's no BOM/parent data to
  join against today regardless of schema.
- **MRP demand data**: not extractable via the public API at all — it only
  exposes `POST /mrp/api/v1/public/master-schedule/upload-items` and
  `.../runs/execute` (both write-side, feeding MRP), no read/list endpoint
  for MRP output. The closest documented read-side entity is Purchase Order
  Requisitions (`GET .../purchase-order-requisitions`), which carries
  `mrpItemId`/`quantityRequested` — but like Purchase Orders, it's a
  single-lookup-by-ID endpoint with no bulk list.
- **On-hand inventory quantity**: no extractor touches the Inventory
  Management module at all in this repo.
