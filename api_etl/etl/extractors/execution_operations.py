from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first, audit_date

RPT_COLUMNS = [
    "operation_id", "wip_trace_id", "wip_order_operation_id", "code_number",
    "priority", "serial_number", "lot_number", "description", "status_id",
    "status_description", "redline_status_id", "redline_status_description",
    "work_center_id", "work_center_code", "order_id", "order_number",
    "product_id", "product_code", "product_revision", "created_on",
    "updated_on",
]


def _map(item):
    return {
        "operation_id": first(item, "id", "operationId"),
        "wip_trace_id": item.get("wipTraceId"),
        "wip_order_operation_id": item.get("wipOrderOperationId"),
        "code_number": item.get("codeNumber"),
        "priority": item.get("priority"),
        "serial_number": item.get("serialNumber"),
        "lot_number": item.get("lotNumber"),
        "description": item.get("description"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "redline_status_id": get(item, "redlineStatus", "id"),
        "redline_status_description": get(item, "redlineStatus", "description"),
        "work_center_id": get(item, "workCenter", "id"),
        "work_center_code": get(item, "workCenter", "code"),
        "order_id": get(item, "wipOrder", "id"),
        "order_number": get(item, "wipOrder", "orderNumber"),
        "product_id": get(item, "product", "id"),
        "product_code": get(item, "product", "code"),
        "product_revision": get(item, "product", "revision"),
        "created_on": audit_date(item.get("createdOn")),
        "updated_on": audit_date(item.get("updatedOn")),
    }


SPEC = ExtractorSpec(
    name="execution_operations",
    method="POST",
    path="/eworkin-plus/execution/api/v1/operations/filter",
    stg_table="execution_operations_raw",
    rpt_table="execution_operations",
    rpt_key_column="operation_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=50,  # documented max for this endpoint
)


def extract_execution_operations(client, conn):
    return run_extractor(client, conn, SPEC)
