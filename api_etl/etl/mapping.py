"""Small helpers shared by the per-endpoint mapper functions.

Field names below follow Manufacturo's documented response shapes as described
in this project's build spec. If a live sample payload uses different casing or
nesting than assumed here, adjust the relevant mapper function only — the
staging tables already capture the untouched raw JSON, so reporting-table
mappings can be revised at any time without re-pulling from the API.
"""
from datetime import datetime


def parse_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def get(item, *path, default=None):
    """Nested dict lookup, e.g. get(item, 'status', 'description')."""
    cur = item
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def audit_date(value):
    """Several endpoints wrap timestamps as {personId, date} audit objects
    (createdOn/updatedOn/lastModified/reported/completed); others return a
    plain ISO string for the same-named field. Handle both."""
    if isinstance(value, dict):
        return parse_dt(value.get("date"))
    return parse_dt(value)


def first(item, *keys, default=None):
    """Return the first present top-level key — useful when a field name isn't
    confirmed yet (e.g. 'id' vs 'nonconformanceId')."""
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return default
