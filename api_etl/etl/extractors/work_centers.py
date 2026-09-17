from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first

RPT_COLUMNS = [
    "work_center_id", "code", "name", "work_center_type", "is_active",
    "site_id", "site_code", "site_name", "production_line_id",
    "production_line_code",
]


def _map(item):
    return {
        "work_center_id": first(item, "id", "workCenterId"),
        "code": item.get("code"),
        "name": item.get("name"),
        "work_center_type": item.get("type"),
        "is_active": item.get("isActive"),
        "site_id": get(item, "site", "id"),
        "site_code": get(item, "site", "code"),
        "site_name": get(item, "site", "name"),
        "production_line_id": get(item, "productionLine", "id"),
        "production_line_code": get(item, "productionLine", "code"),
    }


SPEC = ExtractorSpec(
    name="work_centers",
    method="POST",
    path="/api/v1/work-centers/list",
    stg_table="work_centers_raw",
    rpt_table="work_centers",
    rpt_key_column="work_center_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=200,  # documented max for this endpoint
)


def extract_work_centers(client, conn):
    return run_extractor(client, conn, SPEC)
