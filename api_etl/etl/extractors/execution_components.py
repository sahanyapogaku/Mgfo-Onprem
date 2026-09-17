"""Execution components extractor — each component can carry multiple
consumption records (item.records[]), so this fans into
rpt.execution_components + rpt.execution_component_records, driving
db.merge_upsert directly like etl/extractors/products.py.
"""
import logging

from etl import db
from etl.engine import ExtractorSpec, ExtractorResult, fetch_pages
from etl.mapping import get, first

logger = logging.getLogger("etl.extractors.execution_components")

COMPONENT_COLUMNS = [
    "component_id", "step_id", "planned_quantity", "activity_type_code",
    "consumption_type_code", "product_id", "product_code", "product_name",
    "product_revision_id", "product_revision_code",
]
RECORD_COLUMNS = [
    "record_id", "component_id", "quantity", "removed_quantity",
    "reference_designator",
]


def _map_component(item):
    return {
        "component_id": first(item, "id", "componentId"),
        "step_id": get(item, "step", "id"),
        "planned_quantity": item.get("plannedQuantity"),
        "activity_type_code": item.get("activityTypeCode"),
        "consumption_type_code": item.get("consumptionTypeCode"),
        "product_id": get(item, "plannedProductRevision", "productId"),
        "product_code": get(item, "plannedProductRevision", "productCode"),
        "product_name": get(item, "plannedProductRevision", "productName"),
        "product_revision_id": get(item, "plannedProductRevision", "id"),
        "product_revision_code": get(item, "plannedProductRevision", "revisionCode"),
    }


def _map_records(item):
    component_id = first(item, "id", "componentId")
    rows = []
    for rec in item.get("records") or []:
        rows.append({
            "record_id": rec.get("id"),
            "component_id": component_id,
            "quantity": rec.get("quantity"),
            "removed_quantity": rec.get("removedQuantity"),
            "reference_designator": rec.get("referenceDesignator"),
        })
    return rows


SPEC = ExtractorSpec(
    name="execution_components",
    method="POST",
    path="/eworkin-plus/execution/api/v1/components/filter",
    stg_table="execution_components_raw",
    rpt_table="execution_components",
    rpt_key_column="component_id",
    rpt_columns=COMPONENT_COLUMNS,
    mapper=_map_component,
    page_size=50,
)


def extract_execution_components(client, conn):
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

        component_rows = [_map_component(item) for item in raw_items]
        record_rows = [row for item in raw_items for row in _map_records(item)]

        upserted = db.merge_upsert(
            conn, "execution_components", "component_id", COMPONENT_COLUMNS,
            component_rows,
        )
        upserted += db.merge_upsert(
            conn, "execution_component_records", "record_id", RECORD_COLUMNS,
            record_rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Load failed for %s", SPEC.name)
        return ExtractorResult(SPEC.name, "failed", rows_pulled, 0, str(exc))

    logger.info("%s: upserted %d rows", SPEC.name, upserted)
    return ExtractorResult(SPEC.name, "success", rows_pulled, upserted)
