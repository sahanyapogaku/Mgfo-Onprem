"""Process plans extractor — a plan can reference multiple products
(item.products[]), so this fans into rpt.process_plans + rpt.process_plan_products
and drives db.merge_upsert directly, like etl/extractors/products.py.
"""
import logging

from etl import db
from etl.engine import ExtractorSpec, ExtractorResult, fetch_pages
from etl.mapping import get, first, audit_date

logger = logging.getLogger("etl.extractors.process_plans")

PLAN_COLUMNS = [
    "process_plan_id", "name", "revision", "is_latest", "type_id",
    "type_description", "status_id", "status_description", "bom_id",
    "bom_name", "bom_revision", "pedigree_id", "pedigree_description",
    "process_family_id", "process_family_number", "created_on", "updated_on",
    "released_on",
]
PRODUCT_COLUMNS = [
    "process_plan_product_key", "process_plan_id", "product_guid",
    "product_code", "product_revision", "product_description",
]


def _map_plan(item):
    return {
        "process_plan_id": first(item, "id", "processPlanId"),
        "name": item.get("name"),
        "revision": item.get("revision"),
        "is_latest": item.get("isLatest"),
        "type_id": get(item, "type", "id"),
        "type_description": get(item, "type", "description"),
        "status_id": get(item, "status", "id"),
        "status_description": get(item, "status", "description"),
        "bom_id": get(item, "bom", "id"),
        "bom_name": get(item, "bom", "name"),
        "bom_revision": get(item, "bom", "revision"),
        "pedigree_id": get(item, "pedigree", "id"),
        "pedigree_description": get(item, "pedigree", "description"),
        "process_family_id": get(item, "processFamily", "id"),
        "process_family_number": get(item, "processFamily", "number"),
        "created_on": audit_date(item.get("createdOn")),
        "updated_on": audit_date(item.get("updatedOn")),
        "released_on": audit_date(item.get("releasedOn")),
    }


def _map_products(item):
    plan_id = first(item, "id", "processPlanId")
    rows = []
    for prod in item.get("products") or []:
        guid = prod.get("guid") or prod.get("id")
        rows.append({
            "process_plan_product_key": f"{plan_id}:{guid}",
            "process_plan_id": plan_id,
            "product_guid": guid,
            "product_code": prod.get("code"),
            "product_revision": prod.get("revision"),
            "product_description": prod.get("description"),
        })
    return rows


SPEC = ExtractorSpec(
    name="process_plans",
    method="POST",
    path="/eworkin-plus/planning/api/v2/process-plans/filter",
    stg_table="process_plans_raw",
    rpt_table="process_plans",
    rpt_key_column="process_plan_id",
    rpt_columns=PLAN_COLUMNS,
    mapper=_map_plan,
    page_size=10,  # API rejects limit > 10 with HTTP 400 (confirmed live)
    # No server-side modified-date filter is documented for this endpoint —
    # full pull each run, but `updated_on` is retained so downstream consumers
    # can diff client-side if needed.
)


def extract_process_plans(client, conn):
    logger.info("Starting extractor: %s", SPEC.name)
    try:
        raw_items = list(fetch_pages(client, SPEC))
    except Exception as exc:
        logger.exception("Extraction failed for %s", SPEC.name)
        return ExtractorResult(SPEC.name, "failed", 0, 0, str(exc))

    rows_pulled = len(raw_items)
    logger.info("%s: pulled %d rows", SPEC.name, rows_pulled)

    try:
        db.insert_staging(conn, SPEC.stg_table, raw_items, SPEC.path)

        plan_rows = [_map_plan(item) for item in raw_items]
        product_rows = [row for item in raw_items for row in _map_products(item)]

        upserted = db.merge_upsert(
            conn, "process_plans", "process_plan_id", PLAN_COLUMNS, plan_rows
        )
        upserted += db.merge_upsert(
            conn, "process_plan_products", "process_plan_product_key",
            PRODUCT_COLUMNS, product_rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Load failed for %s", SPEC.name)
        return ExtractorResult(SPEC.name, "failed", rows_pulled, 0, str(exc))

    logger.info("%s: upserted %d rows", SPEC.name, upserted)
    return ExtractorResult(SPEC.name, "success", rows_pulled, upserted)
