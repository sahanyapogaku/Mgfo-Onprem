"""Single entrypoint that runs all (or a subset of) the Manufacturo extractors.

Usage:
    python -m etl.run_all                 # run every extractor
    python -m etl.run_all --group fast     # nonconformances + conditions only
    python -m etl.run_all --group slow     # everything else (full-pull endpoints)
    python -m etl.run_all --only equipment,products

Each extractor runs independently: one endpoint's failure is logged and
recorded in etl.run_log, but does not stop the others from running.
"""
import argparse
import logging
import sys
from datetime import datetime, timezone

from etl import config, db
from etl.http_client import ManufacturoClient
from etl.logging_config import setup_logging

from etl.extractors.nonconformances import extract_nonconformances
from etl.extractors.conditions import extract_conditions
from etl.extractors.dispositions import extract_dispositions
from etl.extractors.equipment import extract_equipment
from etl.extractors.process_plans import extract_process_plans
from etl.extractors.execution_operations import extract_execution_operations
from etl.extractors.execution_components import extract_execution_components
from etl.extractors.wip_traces import extract_wip_traces
from etl.extractors.users import extract_users
from etl.extractors.skills import extract_skills
from etl.extractors.work_centers import extract_work_centers
from etl.extractors.products import extract_products
from etl.extractors.inspection_codes import extract_inspection_codes
from etl.extractors.purchase_orders import extract_purchase_orders

logger = logging.getLogger("etl.run_all")

# "fast" = cheap incremental pulls suitable for a 15-60 min schedule.
# "slow" = full-pull-only endpoints; run every few hours to limit API load.
GROUPS = {
    "fast": [
        ("nonconformances", extract_nonconformances),
        ("conditions", extract_conditions),
    ],
    "slow": [
        ("dispositions", extract_dispositions),
        ("equipment", extract_equipment),
        ("process_plans", extract_process_plans),
        ("execution_operations", extract_execution_operations),
        ("execution_components", extract_execution_components),
        ("wip_traces", extract_wip_traces),
        ("users", extract_users),
        ("skills", extract_skills),
        ("work_centers", extract_work_centers),
        ("products", extract_products),
        ("inspection_codes", extract_inspection_codes),
        ("purchase_orders", extract_purchase_orders),
    ],
}
ALL_EXTRACTORS = GROUPS["fast"] + GROUPS["slow"]


def _select_extractors(args):
    if args.only:
        wanted = set(name.strip() for name in args.only.split(","))
        selected = [(n, f) for n, f in ALL_EXTRACTORS if n in wanted]
        missing = wanted - {n for n, _ in selected}
        if missing:
            raise SystemExit(f"Unknown extractor name(s): {', '.join(sorted(missing))}")
        return selected
    if args.group == "all":
        return ALL_EXTRACTORS
    return GROUPS[args.group]


def run_one(client, conn, name, extract_fn):
    started_at = datetime.now(timezone.utc)
    logger.info("=== %s: starting ===", name)
    try:
        result = extract_fn(client, conn)
    except Exception as exc:
        # Defense in depth: extract_fn should already catch and return a
        # failed ExtractorResult, but never let one endpoint's bug crash the run.
        logger.exception("%s: unhandled exception", name)
        conn.rollback()
        ended_at = datetime.now(timezone.utc)
        db.write_run_log(conn, name, started_at, ended_at, 0, 0, "failed", str(exc))
        conn.commit()
        return False

    ended_at = datetime.now(timezone.utc)
    db.write_run_log(
        conn, name, started_at, ended_at,
        result.rows_pulled, result.rows_upserted, result.status, result.error_message,
    )
    conn.commit()

    if result.status == "success":
        logger.info(
            "=== %s: done — pulled %d, upserted %d ===",
            name, result.rows_pulled, result.rows_upserted,
        )
        return True

    logger.error("=== %s: FAILED — %s ===", name, result.error_message)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group", choices=["all", "fast", "slow"], default="all",
        help="Which set of extractors to run (default: all)",
    )
    parser.add_argument(
        "--only", default=None,
        help="Comma-separated extractor names to run, overrides --group",
    )
    args = parser.parse_args()

    setup_logging()
    extractors = _select_extractors(args)

    client = ManufacturoClient()
    conn = db.get_connection()

    failures = 0
    try:
        for name, extract_fn in extractors:
            ok = run_one(client, conn, name, extract_fn)
            if not ok:
                failures += 1
    finally:
        conn.close()

    logger.info(
        "Run complete: %d/%d extractors succeeded",
        len(extractors) - failures, len(extractors),
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
