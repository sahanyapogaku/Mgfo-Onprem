from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import first

# Confirmed live: this endpoint returns only {id, code} per item.
RPT_COLUMNS = ["inspection_code_id", "code"]


def _map(item):
    return {
        "inspection_code_id": first(item, "id", "inspectionCodeId"),
        "code": item.get("code"),
    }


SPEC = ExtractorSpec(
    name="inspection_codes",
    method="GET",
    path="/eworkin-plus/masterdata/api/v1/public/inspection-codes",
    stg_table="inspection_codes_raw",
    rpt_table="inspection_codes",
    rpt_key_column="inspection_code_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    paginated=False,  # small dictionary endpoint, returned in a single response
)


def extract_inspection_codes(client, conn):
    return run_extractor(client, conn, SPEC)
