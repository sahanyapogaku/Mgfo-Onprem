from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import first

RPT_COLUMNS = ["skill_id", "code", "name", "is_active", "site_id", "expiration_date_tracked"]


def _map(item):
    return {
        "skill_id": first(item, "id", "skillId"),
        "code": item.get("code"),
        "name": item.get("name"),
        "is_active": item.get("active"),
        "site_id": item.get("siteId"),
        "expiration_date_tracked": item.get("expirationDateTracked"),
    }


SPEC = ExtractorSpec(
    name="skills",
    method="POST",
    path="/api/v1/skills/list",
    stg_table="skills_raw",
    rpt_table="skills",
    rpt_key_column="skill_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=50,
)


def extract_skills(client, conn):
    return run_extractor(client, conn, SPEC)
