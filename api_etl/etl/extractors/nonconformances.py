from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first, audit_date

RPT_COLUMNS = [
    "nonconformance_id", "number", "site_id", "status_id", "status_description",
    "assignee_id", "assignee_login", "owner_id", "owner_login", "reported_on",
    "last_modified_on", "completed_on",
]


def _map(item):
    return {
        "nonconformance_id": first(item, "id", "nonconformanceId"),
        "number": item.get("number"),
        "site_id": item.get("siteId"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "assignee_id": get(item, "assignee", "id"),
        "assignee_login": get(item, "assignee", "login"),
        "owner_id": get(item, "owner", "id"),
        "owner_login": get(item, "owner", "login"),
        "reported_on": audit_date(get(item, "reported", "date")),
        "last_modified_on": audit_date(get(item, "lastModified", "date")),
        "completed_on": audit_date(item.get("completed")),
    }


SPEC = ExtractorSpec(
    name="nonconformances",
    method="POST",
    path="/eworkin-plus/nc/api/v2/nonconformances/filter",
    stg_table="nonconformances_raw",
    rpt_table="nonconformances",
    rpt_key_column="nonconformance_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=25,
    incremental_field="lastModifiedOn",
    incremental_field_column="last_modified_on",
)


def extract_nonconformances(client, conn):
    return run_extractor(client, conn, SPEC)
