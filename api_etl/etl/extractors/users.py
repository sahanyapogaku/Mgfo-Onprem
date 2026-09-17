from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import first

RPT_COLUMNS = ["user_id", "code", "login", "first_name", "last_name", "is_active"]


def _map(item):
    return {
        "user_id": first(item, "id", "personId", "userId"),
        "code": item.get("code"),
        "login": item.get("login"),
        "first_name": item.get("firstName"),
        "last_name": item.get("lastName"),
        "is_active": item.get("active"),
    }


SPEC = ExtractorSpec(
    name="users",
    method="POST",
    path="/api/v1/persons/list",
    stg_table="users_raw",
    rpt_table="users",
    rpt_key_column="user_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=50,
    pagination_style="flat",  # confirmed live: nested `pagination.offset` is ignored here
)


def extract_users(client, conn):
    return run_extractor(client, conn, SPEC)
