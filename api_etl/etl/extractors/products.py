"""Products extractor — the only endpoint that fans out into two reporting
tables (rpt.products and rpt.product_revisions), so it drives db.merge_upsert
directly instead of going through engine.run_extractor's single-table path.
"""
import logging

from etl import db
from etl.engine import ExtractorSpec, ExtractorResult, fetch_pages
from etl.mapping import get, first, parse_dt

logger = logging.getLogger("etl.extractors.products")

PRODUCT_COLUMNS = [
    "product_id", "site_id", "part_number", "description", "is_active",
    "product_type", "uom_code", "tracking", "is_equipment", "created_on",
    "updated_on",
]
REVISION_COLUMNS = [
    "product_revision_id", "product_id", "code", "is_active", "is_default",
    "inspection_code_id", "status", "created_on", "updated_on",
]


def _map_product(item):
    return {
        "product_id": first(item, "id", "productId"),
        "site_id": get(item, "site", "id"),
        "part_number": get(item, "details", "code"),
        "description": get(item, "details", "name"),
        "is_active": get(item, "details", "active"),
        "product_type": get(item, "details", "type"),
        "uom_code": get(item, "details", "defaultUom", "code"),
        "tracking": get(item, "details", "tracking"),
        "is_equipment": get(item, "details", "isEquipment"),
        "created_on": parse_dt(item.get("createdOn")),
        "updated_on": parse_dt(item.get("updatedOn")),
    }


def _map_revisions(item):
    product_id = first(item, "id", "productId")
    revisions = get(item, "revisions", "items") or []
    rows = []
    for rev in revisions:
        rows.append({
            "product_revision_id": rev.get("id"),
            "product_id": product_id,
            "code": rev.get("code"),
            "is_active": rev.get("active"),
            "is_default": rev.get("isDefault"),
            "inspection_code_id": rev.get("inspectionCodeId"),
            "status": get(rev, "customAttributes", "values", "status"),
            "created_on": parse_dt(rev.get("createdOn")),
            "updated_on": parse_dt(rev.get("updatedOn")),
        })
    return rows


SPEC = ExtractorSpec(
    name="products",
    method="POST",
    path="/eworkin-plus/masterdata/api/public/products/filter",
    stg_table="products_raw",
    rpt_table="products",
    rpt_key_column="product_id",
    rpt_columns=PRODUCT_COLUMNS,
    mapper=_map_product,
    page_size=25,
)


def extract_products(client, conn):
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

        product_rows = [_map_product(item) for item in raw_items]
        revision_rows = [row for item in raw_items for row in _map_revisions(item)]

        upserted = db.merge_upsert(
            conn, "products", "product_id", PRODUCT_COLUMNS, product_rows
        )
        upserted += db.merge_upsert(
            conn, "product_revisions", "product_revision_id", REVISION_COLUMNS,
            revision_rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Load failed for %s", SPEC.name)
        return ExtractorResult(SPEC.name, "failed", rows_pulled, 0, str(exc))

    logger.info("%s: upserted %d rows", SPEC.name, upserted)
    return ExtractorResult(SPEC.name, "success", rows_pulled, upserted)
