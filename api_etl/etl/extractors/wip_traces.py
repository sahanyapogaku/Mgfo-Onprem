from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first, audit_date

RPT_COLUMNS = [
    "wip_trace_id", "serial_number", "lot_number", "status_id",
    "status_description", "redline_status_id", "redline_status_description",
    "order_id", "order_number", "product_id", "product_code",
    "product_revision", "created_on", "updated_on",
]


def _map(item):
    return {
        "wip_trace_id": first(item, "id", "wipTraceId"),
        "serial_number": item.get("serialNumber"),
        "lot_number": item.get("lotNumber"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "redline_status_id": get(item, "redlineStatus", "id"),
        "redline_status_description": get(item, "redlineStatus", "description"),
        "order_id": get(item, "wipOrder", "id"),
        "order_number": get(item, "wipOrder", "orderNumber"),
        "product_id": get(item, "product", "id"),
        "product_code": get(item, "product", "code"),
        "product_revision": get(item, "product", "revision"),
        "created_on": audit_date(item.get("createdOn")),
        "updated_on": audit_date(item.get("updatedOn")),
    }


SPEC = ExtractorSpec(
    name="wip_traces",
    method="POST",
    path="/eworkin-plus/execution/api/v1/wip-traces/filter",
    stg_table="wip_traces_raw",
    rpt_table="wip_traces",
    rpt_key_column="wip_trace_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=50,
)


def extract_wip_traces(client, conn):
    return run_extractor(client, conn, SPEC)
