from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import get, first, audit_date

RPT_COLUMNS = [
    "disposition_id", "nonconformance_id", "sequence_number", "type_id",
    "type_code", "type_description", "status_id", "status_description",
    "assignee_id", "instruction", "execution_note", "verification_note",
    "rationale", "summary", "require_verification", "is_repair",
    "is_customer_approval_required", "is_flexible", "last_modified_on",
]


def _map(item):
    return {
        "disposition_id": first(item, "id", "dispositionId"),
        "nonconformance_id": get(item, "nonconformance", "id"),
        "sequence_number": item.get("sequenceNumber"),
        "type_id": get(item, "type", "id"),
        "type_code": get(item, "type", "code"),
        "type_description": get(item, "type", "description"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "assignee_id": get(item, "assignee", "id"),
        "instruction": item.get("instruction"),
        "execution_note": item.get("executionNote"),
        "verification_note": item.get("verificationNote"),
        "rationale": item.get("rationale"),
        "summary": item.get("summary"),
        "require_verification": item.get("requireVerification"),
        "is_repair": item.get("isRepair"),
        "is_customer_approval_required": item.get("isCustomerApprovalRequired"),
        "is_flexible": item.get("isFlexible"),
        "last_modified_on": audit_date(get(item, "lastModified", "date")),
    }


SPEC = ExtractorSpec(
    name="dispositions",
    method="POST",
    path="/eworkin-plus/nc/api/v2/dispositions/filter",
    stg_table="dispositions_raw",
    rpt_table="nc_dispositions",
    rpt_key_column="disposition_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=25,
)


def extract_dispositions(client, conn):
    return run_extractor(client, conn, SPEC)
