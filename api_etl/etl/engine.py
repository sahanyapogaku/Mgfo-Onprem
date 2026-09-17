"""Generic extraction engine shared by every endpoint's extractor function.

Each extractor module (etl/extractors/*.py) declares an ExtractorSpec describing
its endpoint, pagination, optional incremental filter, and how to map a raw JSON
item onto reporting-table columns. run_extractor() does the actual work: page
through the API, land raw JSON to staging, map + MERGE into the reporting table,
and advance the watermark only after a fully successful run.
"""
import logging
from dataclasses import dataclass, field
from datetime import timezone

from etl import db

logger = logging.getLogger("etl.engine")


@dataclass
class ExtractorSpec:
    name: str                      # endpoint_name key used for watermark/run_log/stg table
    method: str                    # "GET" or "POST"
    path: str
    stg_table: str
    rpt_table: str
    rpt_key_column: str
    rpt_columns: list
    mapper: callable                # raw_item(dict) -> rpt row dict
    page_size: int = 25
    paginated: bool = True
    incremental_field: str = None   # e.g. "lastModifiedOn"; None = full pull every run
    incremental_field_column: str = None  # rpt column holding that value, e.g. "last_modified_on"
    items_key: str = "items"
    extra_filter: dict = field(default_factory=dict)
    pagination_style: str = "nested"  # "nested" -> {"pagination": {"limit","offset"}}
                                       # "flat" -> top-level {"limit","offset"}
                                       # (confirmed live: /api/v1/persons/list only
                                       # honors flat; nested silently ignores offset)


@dataclass
class ExtractorResult:
    name: str
    status: str
    rows_pulled: int
    rows_upserted: int
    error_message: str = None


def _extract_items(body, items_key):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get(items_key, [])
    return []


def _has_next(body):
    """`hasNext` is returned as a top-level sibling of `items`/`pagination`,
    not nested inside `pagination` — confirmed against the live API."""
    if not isinstance(body, dict):
        return False
    if "hasNext" in body:
        return bool(body.get("hasNext"))
    pagination = body.get("pagination") or {}
    return bool(pagination.get("hasNext", False))


def fetch_pages(client, spec, watermark=None):
    """Yield raw item dicts across all pages for this endpoint.

    Exposed publicly (not just used by run_extractor) so extractors that need
    custom multi-table load logic — e.g. products + product_revisions — can
    still reuse the shared pagination behavior.
    """
    if not spec.paginated:
        if spec.method == "GET":
            body = client.get(spec.path)
        else:
            body = client.post_filter(spec.path, dict(spec.extra_filter))
        for item in _extract_items(body, spec.items_key):
            yield item
        return

    offset = 0
    while True:
        filter_body = dict(spec.extra_filter)
        if spec.pagination_style == "flat":
            filter_body["limit"] = spec.page_size
            filter_body["offset"] = offset
        else:
            filter_body["pagination"] = {"limit": spec.page_size, "offset": offset}
        if spec.incremental_field and watermark is not None:
            filter_body[spec.incremental_field] = {"gte": _iso(watermark)}

        body = client.post_filter(spec.path, filter_body)
        items = _extract_items(body, spec.items_key)
        for item in items:
            yield item

        if not items or not _has_next(body):
            break
        if len(items) < spec.page_size:
            # Defensive: a short page implies this was the last one even if
            # hasNext was (incorrectly) still true — avoids looping forever
            # on a server-side pagination bug.
            logger.warning(
                "%s: page at offset %d returned %d/%d items but hasNext=true; "
                "stopping pagination defensively",
                spec.name, offset, len(items), spec.page_size,
            )
            break
        offset += spec.page_size


def _iso(dt):
    """Format a watermark for the API's `{gte: <iso>}` filter.

    Watermarks are always stored/compared as UTC. Naive datetimes (as returned
    by pyodbc for DATETIME2 columns) are assumed to already be UTC rather than
    converted via the host's local timezone.
    """
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(timezone.utc).isoformat()


def run_extractor(client, conn, spec: ExtractorSpec) -> ExtractorResult:
    logger.info("Starting extractor: %s", spec.name)
    watermark = db.get_watermark(conn, spec.name) if spec.incremental_field else None

    raw_items = []
    try:
        for item in fetch_pages(client, spec, watermark):
            raw_items.append(item)
    except Exception as exc:
        logger.exception("Extraction failed for %s", spec.name)
        return ExtractorResult(spec.name, "failed", len(raw_items), 0, str(exc))

    rows_pulled = len(raw_items)
    logger.info("%s: pulled %d rows", spec.name, rows_pulled)

    try:
        db.insert_staging(conn, spec.stg_table, raw_items, spec.path)

        mapped_rows = [spec.mapper(item) for item in raw_items]
        rows_upserted = db.merge_upsert(
            conn, spec.rpt_table, spec.rpt_key_column, spec.rpt_columns, mapped_rows
        )

        new_watermark = None
        if spec.incremental_field:
            values = [
                row.get(spec.incremental_field_column)
                for row in mapped_rows
                if row.get(spec.incremental_field_column)
            ]
            if values:
                new_watermark = max(values)

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Load failed for %s", spec.name)
        return ExtractorResult(spec.name, "failed", rows_pulled, 0, str(exc))

    if spec.incremental_field and new_watermark:
        db.set_watermark(conn, spec.name, new_watermark, "success")
        conn.commit()
    elif spec.incremental_field:
        db.set_watermark(conn, spec.name, watermark, "success")
        conn.commit()

    logger.info("%s: upserted %d rows", spec.name, rows_upserted)
    return ExtractorResult(spec.name, "success", rows_pulled, rows_upserted)
