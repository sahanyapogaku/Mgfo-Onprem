"""
Extracts the tables/views needed for the 3-way match tool and the part
demand status report from the MGFO read-only replica, landing them as
snapshot tables in the on-prem SQL Server, next to the existing Jira and
Brex tables.

MGFO grants only CONNECT/EXECUTE/SELECT (no VIEW DEFINITION), so column
shapes are read from INFORMATION_SCHEMA rather than sys.sql_modules.
Each run does a full drop-and-reload of every target table (simple
snapshot, not an incremental sync) - fine for nightly/on-demand refreshes.
"""
import sys
import pyodbc

from connect import load_env, build_connection_string

BATCH_SIZE = 500

# (source table/view, target table) - target lives under a dedicated "mgfo"
# schema on-prem so it doesn't collide with existing Jira/Brex tables.
VIEWS = [
    # 3-way match (PO/invoice)
    ("external.purchase_order_overview", "mgfo.purchase_order_overview"),
    ("inventory.vw_mrp_purchase_order_header_statuses", "mgfo.po_header_statuses"),
    ("inventory.MRP_PurchaseOrdersDetails", "mgfo.po_details"),
    # part demand status report
    ("master.Products", "mgfo.products"),
    ("master.vw_products", "mgfo.product_names"),
    # revision is NOT known per demand line (master_schedule_item/scheduled_object
    # carry no revision column) - this is only the part's default/current revision,
    # a best-effort substitute, not a confirmed fact about any specific demand row
    ("master.Product_Revisions", "mgfo.product_revisions"),
    ("mrp.scheduled_object", "mgfo.scheduled_object"),
    # decoded MRP shortage-report source (Type/PedigreeCode as text, no hand-decoding
    # needed) - replaces mrp.scheduled_object as the demand/supply/orphan source below
    ("mrp.SummaryReportView", "mgfo.summary_report_view"),
    ("external.inventory_overview", "mgfo.inventory_overview"),
    ("external.nonconformance_condition_overview", "mgfo.nonconformance_overview"),
]


def target_env(env):
    driver = env.get("TARGET_DB_DRIVER") or env.get("MSSQL_DRIVER") or "ODBC Driver 18 for SQL Server"
    server = env.get("TARGET_DB_SERVER") or env.get("MSSQL_SERVER")
    port = env.get("TARGET_DB_PORT") or env.get("MSSQL_PORT", "1433")
    database = env.get("TARGET_DB_NAME") or env.get("MSSQL_DATABASE")
    user = env.get("TARGET_DB_USER") or env.get("MSSQL_USER")
    password = env.get("TARGET_DB_PASSWORD") or env.get("MSSQL_PASSWORD")
    encrypt = env.get("TARGET_DB_ENCRYPT") or env.get("MSSQL_ENCRYPT", "yes")
    trust_cert = env.get("TARGET_DB_TRUST_SERVER_CERTIFICATE") or env.get("MSSQL_TRUST_SERVER_CERTIFICATE", "no")

    missing = [name for name, value in {
        "DB_SERVER": server,
        "DB_NAME": database,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }.items() if value in (None, "")]
    if missing:
        raise KeyError(f"Missing target DB settings: {', '.join(missing)}")

    return {
        "DB_DRIVER": driver,
        "DB_SERVER": server,
        "DB_PORT": port,
        "DB_NAME": database,
        "DB_USER": user,
        "DB_PASSWORD": password,
        "DB_ENCRYPT": encrypt,
        "DB_TRUST_SERVER_CERTIFICATE": trust_cert,
    }


def get_columns(cursor, schema, name):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
               NUMERIC_PRECISION, NUMERIC_SCALE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        schema,
        name,
    )
    columns = cursor.fetchall()
    if not columns:
        raise RuntimeError(f"No columns found for {schema}.{name} - check the name/permissions")
    return columns


def sql_type_decl(data_type, max_len, precision, scale):
    if data_type in ("varchar", "nvarchar", "char", "nchar"):
        length = "MAX" if max_len == -1 else max_len
        return f"{data_type}({length})"
    if data_type in ("decimal", "numeric"):
        return f"{data_type}({precision},{scale})"
    if data_type == "datetimeoffset":
        # pyodbc can't read datetimeoffset directly (ODBC SQL type -155);
        # it's cast to varchar in the SELECT below, so mirror that here.
        return "varchar(50)"
    return data_type


def build_select_list(columns):
    parts = []
    for name, data_type, *_ in columns:
        if data_type == "datetimeoffset":
            parts.append(f"CONVERT(varchar(50), [{name}], 120) AS [{name}]")
        else:
            parts.append(f"[{name}]")
    return ", ".join(parts)


def extract_one(source_cursor, target_conn, source_view, target_table):
    src_schema, src_name = source_view.split(".")
    tgt_schema, tgt_name = target_table.split(".")

    columns = get_columns(source_cursor, src_schema, src_name)
    col_names = [c[0] for c in columns]

    select_list = build_select_list(columns)
    source_cursor.execute(f"SELECT {select_list} FROM [{src_schema}].[{src_name}]")

    col_decls = ",\n            ".join(
        f"[{name}] {sql_type_decl(data_type, max_len, precision, scale)}"
        for name, data_type, max_len, precision, scale in columns
    )

    target_cursor = target_conn.cursor()
    target_cursor.fast_executemany = True
    target_cursor.execute(
        f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{tgt_schema}') "
        f"EXEC('CREATE SCHEMA [{tgt_schema}]')"
    )
    target_cursor.execute(
        f"IF OBJECT_ID('[{tgt_schema}].[{tgt_name}]', 'U') IS NOT NULL "
        f"DROP TABLE [{tgt_schema}].[{tgt_name}]"
    )
    target_cursor.execute(f"CREATE TABLE [{tgt_schema}].[{tgt_name}] (\n            {col_decls}\n        )")
    target_conn.commit()

    placeholders = ", ".join("?" for _ in col_names)
    insert_sql = (
        f"INSERT INTO [{tgt_schema}].[{tgt_name}] ({', '.join(f'[{c}]' for c in col_names)}) "
        f"VALUES ({placeholders})"
    )

    total = 0
    while True:
        rows = source_cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
        target_cursor.executemany(insert_sql, [tuple(r) for r in rows])
        total += len(rows)
    target_conn.commit()
    return total


def main():
    env = load_env()

    try:
        source_conn = pyodbc.connect(build_connection_string(env))
    except pyodbc.Error as e:
        print(f"Source (MGFO) connection FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        target_conn = pyodbc.connect(build_connection_string(target_env(env)))
    except pyodbc.Error as e:
        print(f"Target (on-prem) connection FAILED: {e}", file=sys.stderr)
        source_conn.close()
        sys.exit(1)

    source_cursor = source_conn.cursor()

    try:
        for source_view, target_table in VIEWS:
            print(f"Extracting {source_view} -> {target_table} ...")
            count = extract_one(source_cursor, target_conn, source_view, target_table)
            print(f"  {count} rows loaded")
    finally:
        source_conn.close()
        target_conn.close()

    print("Done.")


if __name__ == "__main__":
    main()
