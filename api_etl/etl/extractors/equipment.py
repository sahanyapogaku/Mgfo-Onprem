from etl.engine import ExtractorSpec, run_extractor
from etl.mapping import first

RPT_COLUMNS = [
    "equipment_id", "external_id", "itag_code", "is_active",
    "calibration_vendor_id", "calibration_vendor_code", "calibration_vendor_name",
    "tolerance_unit_id", "tolerance_unit_code", "tolerance_unit_name",
    "accuracy_unit_id", "accuracy_unit_code", "accuracy_unit_name",
    "range_unit_id", "range_unit_code", "range_unit_name",
]


def _map(item):
    return {
        "equipment_id": first(item, "equipmentId", "id"),
        "external_id": item.get("externalId"),
        "itag_code": item.get("iTagCode"),
        "is_active": item.get("isActive"),
        "calibration_vendor_id": item.get("calibrationVendorId"),
        "calibration_vendor_code": item.get("calibrationVendorCode"),
        "calibration_vendor_name": item.get("calibrationVendorName"),
        "tolerance_unit_id": item.get("toleranceUnitId"),
        "tolerance_unit_code": item.get("toleranceUnitCode"),
        "tolerance_unit_name": item.get("toleranceUnitName"),
        "accuracy_unit_id": item.get("accuracyUnitId"),
        "accuracy_unit_code": item.get("accuracyUnitCode"),
        "accuracy_unit_name": item.get("accuracyUnitName"),
        "range_unit_id": item.get("rangeUnitId"),
        "range_unit_code": item.get("rangeUnitCode"),
        "range_unit_name": item.get("rangeUnitName"),
    }


SPEC = ExtractorSpec(
    name="equipment",
    method="POST",
    path="/equipment/api/public/equipment/filter",
    stg_table="equipment_raw",
    rpt_table="equipment",
    rpt_key_column="equipment_id",
    rpt_columns=RPT_COLUMNS,
    mapper=_map,
    page_size=25,
)


def extract_equipment(client, conn):
    return run_extractor(client, conn, SPEC)
