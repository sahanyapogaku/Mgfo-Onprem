from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first, audit_date

RPT_COLUMNS = [
    "condition_id", "nonconformance_id", "site_id", "sequence_number",
    "summary", "status_id", "status_description", "reject_category_id",
    "reject_category_code", "reject_code_id", "reject_code_code",
    "where_found", "is_further_action_required", "last_modified_on",
    "completed_on",
]


def _map(item):
    return {
        "condition_id": first(item, "id", "conditionId"),
        "nonconformance_id": get(item, "nonconformance", "id"),
        "site_id": item.get("siteId"),
        "sequence_number": item.get("sequenceNumber"),
        "summary": item.get("summary"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "reject_category_id": get(item, "rejectCategory", "id"),
        "reject_category_code": get(item, "rejectCategory", "code"),
        "reject_code_id": get(item, "rejectCode", "id"),
        "reject_code_code": get(item, "rejectCode", "code"),
        "where_found": item.get("whereFound"),
        "is_further_action_required": item.get("isFurtherActionRequired"),
        "last_modified_on": audit_date(get(item, "lastModified", "date")),
        "completed_on": audit_date(item.get("completed")),
    }


SPEC = ExtractorSpec(
    name="conditions",
    method="POST",
    path="/eworkin-plus/nc/api/v2/conditions/filter",
    stg_table="conditions_raw",
    rpt_table="nc_conditions",
    rpt_key_column="condition_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=25,
    incremental_field="lastModifiedOn",
    incremental_field_column="last_modified_on",
)


def extract_conditions(client, conn):
    return run_extractor(client, conn, SPEC)
