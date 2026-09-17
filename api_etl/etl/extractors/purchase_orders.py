"""Purchase orders extractor — hybrid, two-source design.

Manufacturo's public API cannot bulk-list purchase orders. Confirmed live:
GET /eworkin-plus/inventory/api/integrations/orders/purchase-orders requires
an exact OrderNumber (calling with only SiteCode returns HTTP 400 "Order
number is missing"). There is no list/filter variant of this endpoint.

So order numbers have to come from somewhere else first:

  Step A (order-number discovery, optional per run): the internal
  "purchase order cockpit" endpoint used by Manufacturo's own web UI
  (NOT part of the public API/ALLOWLIST — found via browser DevTools, not
  documented). It bulk-lists orders per site, but only accepts an
  interactive-login Bearer token (~5 min lifetime) — there is no
  service-account/API-key variant confirmed for it. This code never
  attempts to obtain that token itself; it must be pasted into
  MANUFACTURO_BEARER_TOKEN before a run that needs to discover orders this
  pipeline hasn't seen before. If the token is absent or expired, this step
  is skipped (not fatal) and the run falls back to whatever order numbers
  are already known in rpt.purchase_orders from a previous run.

  Step B (detail pull, uses MNFO_API_KEY like everything else in this
  pipeline): for every order number known (freshly discovered in Step A,
  plus whatever was already in rpt.purchase_orders), call the public
  per-order endpoint above and land/map its header + orderLines[] as
  usual. This is the only call whose response shape is fully verified
  against this project's documented schema, so it's used for all
  header/line data even when Step A also returned order data — Step A's
  own item shape (beyond orderNumber/guid/status) isn't confirmed, so its
  raw response is landed to staging for audit only, not mapped to rpt.

Known live blocker (as of this writing): MNFO_API_KEY does not have the
"Purchase Order read" privilege granted yet — Step B calls fail with
{"statusCode":401,"message":"Authentication failure: ApiKey unauthorized"}
even for a real, existing order number. This must be granted on the
Manufacturo side (see README) before Step B can succeed at all.
"""
import logging

import requests

from etl import config, db
from etl.engine import ExtractorResult
from etl.http_client import ManufacturoApiError
from etl.mapping import get, parse_dt

logger = logging.getLogger("etl.extractors.purchase_orders")

PATH = "/eworkin-plus/inventory/api/integrations/orders/purchase-orders"

# Internal, undocumented endpoint — NOT in http_client.ALLOWLIST. Uses a
# human Bearer token instead of X-Api-Key, so it deliberately bypasses
# ManufacturoClient rather than being folded into that abstraction.
COCKPIT_PATH = "/eworkin-plus/inventory/api/purchaseOrderCockpit/purchase-orders/list"
COCKPIT_PAGE_SIZE = 15

HEADER_COLUMNS = [
    "purchase_order_id", "order_number", "site_code", "transit_site_code",
    "partner_code", "partner_name", "area_code",
]
LINE_COLUMNS = [
    "line_id", "purchase_order_id", "order_detail_number", "product_id",
    "product_code", "product_description", "product_revision",
    "product_uom_code", "quantity_ordered", "quantity_completed", "uom_code",
    "due_date", "delivery_date", "status_id", "status_description", "comment",
    "pedigree_code", "project_code", "inspection_code", "inventory_status_id",
    "inventory_status_description", "under_tolerance", "over_tolerance",
    "unit_cost", "currency_code", "line_amount",
]


class CockpitAuthError(Exception):
    """MANUFACTURO_BEARER_TOKEN missing/expired/rejected. Never auto-retried
    or worked around — a human has to paste a fresh token."""


def _site_directory(conn):
    """(site_code, site_id) pairs already known from the work_centers pull."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT site_code, site_id FROM rpt.work_centers "
        "WHERE site_code IS NOT NULL AND site_id IS NOT NULL"
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]


def _known_order_numbers(conn):
    """(site_code, order_number) pairs already landed in a previous run."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT site_code, order_number FROM rpt.purchase_orders "
        "WHERE site_code IS NOT NULL AND order_number IS NOT NULL"
    )
    return {(row[0], row[1]) for row in cursor.fetchall()}


def _fetch_cockpit_orders(site_code, site_guid, bearer_token):
    """Paginate the cockpit list for one site. Returns raw item dicts.

    Only order_number/guid/status are treated as confirmed fields on these
    items (per the captured example) — callers should not assume anything
    else about item shape from this function.
    """
    url = f"{config.MNFO_BASE_URL}{COCKPIT_PATH}"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    session = requests.Session()
    items = []
    offset = 0
    total_items = None

    while total_items is None or offset < total_items:
        body = {
            "filters": {},
            "sorting": {},
            "offset": offset,
            "limit": COCKPIT_PAGE_SIZE,
            "siteGuid": str(site_guid),
        }
        resp = session.post(url, headers=headers, json=body, timeout=config.HTTP_TIMEOUT_SECONDS)

        if resp.status_code == 401:
            raise CockpitAuthError(
                f"Manufacturo cockpit token rejected (401) for site {site_code}. "
                "MANUFACTURO_BEARER_TOKEN is missing, expired (~5 min lifetime), "
                "or invalid. Log into Manufacturo in a browser, capture a fresh "
                "Bearer token from DevTools (Network tab, Purchase Orders screen), "
                "set MANUFACTURO_BEARER_TOKEN, and re-run this extractor."
            )
        if not resp.ok:
            raise ManufacturoApiError(
                f"POST {COCKPIT_PATH} returned HTTP {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        page_items = data.get("items", [])
        items.extend(page_items)
        total_items = data.get("totalItems", len(items))

        if not page_items:
            break
        offset += COCKPIT_PAGE_SIZE

    return items


def _normalize_response(body):
    """Handle a single PO dict, a bare list, or an {items: [...]} envelope —
    whichever shape the live per-order API turns out to use."""
    if isinstance(body, dict) and "guid" in body:
        return [body]
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("items", [])
    return []


def _map_header(item):
    return {
        "purchase_order_id": item.get("guid"),
        "order_number": item.get("orderNumber"),
        "site_code": item.get("siteCode"),
        "transit_site_code": item.get("transitSiteCode"),
        "partner_code": get(item, "partner", "code"),
        "partner_name": get(item, "partner", "name"),
        "area_code": item.get("areaCode"),
    }


def _map_lines(item):
    po_id = item.get("guid")
    rows = []
    for line in item.get("orderLines") or []:
        quantity_ordered = line.get("quantityOrdered")
        unit_cost = line.get("unitCost")
        line_amount = (
            quantity_ordered * unit_cost
            if quantity_ordered is not None and unit_cost is not None
            else None
        )
        rows.append({
            "line_id": line.get("guid"),
            "purchase_order_id": po_id,
            "order_detail_number": line.get("orderDetailNumber"),
            "product_id": get(line, "product", "guid"),
            "product_code": get(line, "product", "code"),
            "product_description": get(line, "product", "description"),
            "product_revision": get(line, "product", "revision"),
            "product_uom_code": get(line, "product", "uomCode"),
            "quantity_ordered": quantity_ordered,
            "quantity_completed": line.get("quantityCompleted"),
            "uom_code": line.get("uomCode"),
            "due_date": parse_dt(line.get("dueDate")),
            "delivery_date": parse_dt(line.get("deliveryDate")),
            "status_id": get(line, "status", "id"),
            "status_description": get(line, "status", "description"),
            "comment": line.get("comment"),
            "pedigree_code": line.get("pedigreeCode"),
            "project_code": line.get("projectCode"),
            "inspection_code": line.get("inspectionCode"),
            "inventory_status_id": get(line, "inventoryStatus", "id"),
            "inventory_status_description": get(line, "inventoryStatus", "description"),
            "under_tolerance": line.get("underTolerance"),
            "over_tolerance": line.get("overTolerance"),
            "unit_cost": unit_cost,
            "currency_code": line.get("currencyAlphabeticCode"),
            "line_amount": line_amount,
        })
    return rows


def extract_purchase_orders(client, conn):
    logger.info("Starting extractor: purchase_orders")

    try:
        sites = _site_directory(conn)
    except Exception as exc:
        logger.exception("Failed to load site directory for purchase_orders")
        return ExtractorResult("purchase_orders", "failed", 0, 0, str(exc))

    if not sites:
        msg = (
            "No sites known from rpt.work_centers — run the work_centers "
            "extractor first so purchase_orders has a site directory to work from."
        )
        logger.error(msg)
        return ExtractorResult("purchase_orders", "failed", 0, 0, msg)

    # --- Step A: discover order numbers (optional; needs a human token) ---
    pull_set = set(_known_order_numbers(conn))
    cockpit_raw_items = []

    if config.MANUFACTURO_BEARER_TOKEN:
        try:
            for site_code, site_guid in sites:
                site_items = _fetch_cockpit_orders(site_code, site_guid, config.MANUFACTURO_BEARER_TOKEN)
                cockpit_raw_items.extend(site_items)
                for item in site_items:
                    order_number = item.get("orderNumber")
                    if order_number:
                        pull_set.add((site_code, order_number))
        except CockpitAuthError as exc:
            logger.error(str(exc))
            return ExtractorResult("purchase_orders", "failed", 0, 0, str(exc))
        except Exception as exc:
            logger.exception("Cockpit order-number discovery failed")
            return ExtractorResult("purchase_orders", "failed", 0, 0, str(exc))
    else:
        logger.info(
            "MANUFACTURO_BEARER_TOKEN not set — skipping order-number discovery, "
            "using %d previously known order number(s) only.",
            len(pull_set),
        )

    if not pull_set:
        msg = (
            "No purchase order numbers known and MANUFACTURO_BEARER_TOKEN is not "
            "set — this is a first-ever run with nothing to bootstrap from. Log "
            "into Manufacturo, capture a fresh Bearer token via browser DevTools "
            "(Purchase Orders screen, Network tab), set MANUFACTURO_BEARER_TOKEN, "
            "and re-run."
        )
        logger.error(msg)
        return ExtractorResult("purchase_orders", "failed", 0, 0, msg)

    # Cockpit items are landed for audit only — their shape beyond
    # orderNumber/guid/status isn't confirmed, so they're never mapped to rpt.
    if cockpit_raw_items:
        try:
            db.insert_staging(conn, "purchase_orders_raw", cockpit_raw_items, COCKPIT_PATH)
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to stage cockpit raw items (non-fatal, continuing)")

    # --- Step B: per-order detail pull via the public API (MNFO_API_KEY) ---
    raw_items = []
    try:
        for site_code, order_number in sorted(pull_set):
            body = client.get(PATH, params={"SiteCode": site_code, "OrderNumber": order_number})
            raw_items.extend(_normalize_response(body))
    except Exception as exc:
        logger.exception("Extraction failed for purchase_orders")
        return ExtractorResult("purchase_orders", "failed", len(raw_items), 0, str(exc))

    rows_pulled = len(raw_items)
    logger.info("purchase_orders: pulled %d rows", rows_pulled)

    try:
        db.insert_staging(conn, "purchase_orders_raw", raw_items, PATH)

        header_rows = [_map_header(item) for item in raw_items]
        line_rows = [row for item in raw_items for row in _map_lines(item)]

        upserted = db.merge_upsert(
            conn, "purchase_orders", "purchase_order_id", HEADER_COLUMNS, header_rows
        )
        upserted += db.merge_upsert(
            conn, "purchase_order_lines", "line_id", LINE_COLUMNS, line_rows
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Load failed for purchase_orders")
        return ExtractorResult("purchase_orders", "failed", rows_pulled, 0, str(exc))

    logger.info("purchase_orders: upserted %d rows", upserted)
    return ExtractorResult("purchase_orders", "success", rows_pulled, upserted)
