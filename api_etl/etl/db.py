"""Shared MSSQL access: connections, staging inserts, and generic MERGE upserts.

This module only ever writes to the local MSSQL database. Nothing here talks to
Manufacturo — see etl/http_client.py for the only outbound network calls this
pipeline makes.
"""
import json
import logging

import pyodbc

from etl import config

logger = logging.getLogger("etl.db")

# SQL Server caps a single query at 2100 parameters. Batch size is derived
# per-call from the column count (see merge_upsert) to stay safely under that.
MAX_QUERY_PARAMS = 2000


def get_connection():
    conn = pyodbc.connect(config.mssql_connection_string(), autocommit=False)
    return conn


def insert_staging(conn, table, raw_items, source_endpoint):
    """Land raw JSON payloads (one row per item) into a stg.<table> table."""
    if not raw_items:
        return 0
    cursor = conn.cursor()
    cursor.fast_executemany = True
    sql = (
        f"INSERT INTO stg.{table} (raw_json, source_endpoint) VALUES (?, ?)"
    )
    rows = [(json.dumps(item, default=str), source_endpoint) for item in raw_items]
    cursor.executemany(sql, rows)
    return len(rows)


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def merge_upsert(conn, table, key_column, columns, rows):
    """Upsert `rows` (list of dicts keyed by column name) into rpt.<table>.

    `columns` is the ordered list of column names to write, and must include
    key_column. Batches the MERGE in chunks to keep statement size sane.
    """
    if not rows:
        return 0

    other_columns = [c for c in columns if c != key_column]
    update_clause = ", ".join(f"tgt.{c} = src.{c}" for c in other_columns)
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join(f"src.{c}" for c in columns)
    col_list_sql = ", ".join(columns)

    batch_size = max(1, MAX_QUERY_PARAMS // len(columns))

    total = 0
    cursor = conn.cursor()
    for batch in _chunk(rows, batch_size):
        values_sql = ", ".join(
            "(" + ", ".join("?" for _ in columns) + ")" for _ in batch
        )
        merge_sql = f"""
MERGE rpt.{table} AS tgt
USING (VALUES {values_sql}) AS src ({col_list_sql})
ON tgt.{key_column} = src.{key_column}
WHEN MATCHED THEN UPDATE SET {update_clause}, tgt.synced_at = SYSUTCDATETIME()
WHEN NOT MATCHED THEN INSERT ({insert_cols}, synced_at)
    VALUES ({insert_vals}, SYSUTCDATETIME());
"""
        params = [row.get(c) for row in batch for c in columns]
        cursor.execute(merge_sql, params)
        total += len(batch)
    return total


def get_watermark(conn, endpoint_name):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_watermark FROM etl.watermark WHERE endpoint_name = ?",
        (endpoint_name,),
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO etl.watermark (endpoint_name, last_watermark, last_run_status) "
            "VALUES (?, NULL, 'never_run')",
            (endpoint_name,),
        )
        return None
    return row[0]


def set_watermark(conn, endpoint_name, new_watermark, status):
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE etl.watermark
        SET last_watermark = ?, last_run_status = ?, last_run_at = SYSUTCDATETIME()
        WHERE endpoint_name = ?
        """,
        (new_watermark, status, endpoint_name),
    )


def write_run_log(conn, endpoint_name, started_at, ended_at, rows_pulled,
                   rows_upserted, status, error_message=None):
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO etl.run_log
            (endpoint_name, started_at, ended_at, rows_pulled, rows_upserted,
             status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (endpoint_name, started_at, ended_at, rows_pulled, rows_upserted,
         status, error_message),
    )
