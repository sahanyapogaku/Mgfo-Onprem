
## Pipeline 1: DB-replica copy

This one pulls straight from the MGFO prod read-replica (credentials live in
the `.env` file in this folder) and does a full drop-and-reload of every
table under the `mgfo` schema. It's not incremental , every run wipes and
rebuilds those tables from scratch , but that also makes it completely safe
to re-run whenever you want. If something looks wrong, just run it again.

```bash
python extract_to_onprem.py
```

This is what feeds the part demand status report. The report itself lives at
`report/part_demand_status_report.sql` and is deployed as a stored procedure,
`mgfo.usp_PartDemandStatusReport`. You can call it directly:

```sql
EXEC mgfo.usp_PartDemandStatusReport @PartCode = '1003899-001';
```

## Pipeline 2: Manufacturo API ETL

This one pulls from the Manufacturo public API and writes into the
`stg.*` / `rpt.*` / `etl.*` schemas. It's strictly read-only against
Manufacturo — the only calls it ever makes are `GET /.../filter/.../list`,
and that's enforced by an allowlist, not just convention. Its own config
lives in `api_etl/.env`.

```bash
cd api_etl
python -m etl.run_all                # runs every extractor
python -m etl.run_all --group fast   # nonconformances + conditions — cheap and incremental, safe to run every 15-60 min
python -m etl.run_all --group slow   # everything else — does a full pull each time, so run this less often (every few hours is fine)
python -m etl.run_all --only equipment,products   # or just target specific extractors by name
```

Every run writes a row to `etl.run_log` with counts and status, and also
logs to `api_etl/logs/etl.log` , check either if you want to know what
actually happened on a given run. For details on individual extractors,
watermark/incremental logic, and known limitations, see
`api_etl/README.md`. One current gap worth knowing about: the
`purchase_orders` extractor is blocked because the API key doesn't have the
"Purchase Order read" scope yet.

## Checking connectivity

```bash
python connect.py
```

This just confirms the source MGFO DB is reachable — a good first thing to
run if either pipeline starts failing and you're not sure why.
