"""Unit tests for check_request_eligibility and normalize_item (requirements sections 4, 5, 7, 11)."""

import json
from datetime import date

import pytest

from server.tools import check_request_eligibility, normalize_item

TODAY = date(2026, 11, 1)  # DEMO_TODAY


def check(employee_id, item, request_type=None, today=TODAY):
    return check_request_eligibility(employee_id, item, request_type, today=today)


# --- Section 11 cases ------------------------------------------------------------------

def test_e001_monitor_replacement_eligible():
    r = check("E001", "monitor", "replacement")
    assert r["status"] == "eligible"
    assert r["next_eligible_date"] == "2025-09-01"
    assert r["days_until_eligible"] == 0


def test_e002_contractor_laptop_ineligible():
    r = check("E002", "laptop")
    assert r["status"] == "ineligible"
    assert "not allowed" in r["reason"]


def test_e003_laptop_replacement_borderline():
    r = check("E003", "laptop", "replacement")
    assert r["status"] == "borderline"
    assert r["days_until_eligible"] == 30
    assert r["next_eligible_date"] == "2026-12-01"


def test_e004_standing_desk_unknown_item():
    r = check("E004", "standing desk")
    assert r["status"] == "unknown_item"
    assert r["item"] == "standing desk"
    assert set(r["catalog"]) == {"laptop", "monitor", "keyboard", "mouse", "headset", "docking_station"}


def test_e005_laptop_replacement_eligible():
    r = check("E005", "laptop", "replacement")
    assert r["status"] == "eligible"
    assert r["next_eligible_date"] == "2026-06-15"


def test_e006_monitor_replacement_inside_refresh_window():
    r = check("E006", "monitor", "replacement")
    assert r["status"] == "ineligible"
    assert r["next_eligible_date"] == "2028-11-15"


def test_e007_additional_monitor_max_count_reached():
    r = check("E007", "monitor", "additional")
    assert r["status"] == "ineligible"
    assert "maximum is 3" in r["reason"]


def test_e007_monitor_replacement_still_ineligible():
    # Robustness: even if the agent picks the wrong type, the answer is still no.
    assert check("E007", "monitor", "replacement")["status"] == "ineligible"


def test_e008_laptop_replacement_ineligible():
    r = check("E008", "laptop", "replacement")
    assert r["status"] == "ineligible"
    assert r["next_eligible_date"] == "2027-08-01"


@pytest.mark.parametrize(
    "employee_id, item, code",
    [
        ("E009", "headset", "ROLE_NOT_IN_POLICY"),
        ("E999", "monitor", "EMPLOYEE_NOT_FOUND"),
        ("", "monitor", "INVALID_EMPLOYEE_ID"),
    ],
)
def test_error_cases(employee_id, item, code):
    r = check(employee_id, item)
    assert r["status"] == "error"
    assert r["error_code"] == code
    assert r["reason"]


# --- Request types ---------------------------------------------------------------------

def test_invalid_request_type():
    r = check("E001", "monitor", "upgrade")
    assert r["status"] == "error"
    assert r["error_code"] == "INVALID_REQUEST_TYPE"


def test_request_type_inferred_as_replacement_when_owned():
    r = check("E001", "monitor")
    assert r["request_type"] == "replacement"
    assert r["status"] == "eligible"


def test_second_monitor_additional_within_max_count():
    r = check("E001", "monitor", "additional")  # has 1 of 2
    assert r["status"] == "eligible"
    assert r["request_type"] == "additional"


def test_replacement_of_unowned_item_treated_as_additional():
    r = check("E004", "keyboard", "replacement")  # owns no keyboard
    assert r["request_type"] == "additional"
    assert r["status"] == "eligible"


# --- Boundaries (E003 laptop, eligible on 2026-12-01) ----------------------------------

@pytest.mark.parametrize(
    "today, status, days",
    [
        (date(2026, 12, 1), "eligible", 0),     # exactly on the date
        (date(2026, 10, 2), "borderline", 60),  # exactly 60 days away
        (date(2026, 10, 1), "ineligible", 61),  # 61 days away
    ],
)
def test_borderline_boundaries(today, status, days):
    r = check("E003", "laptop", "replacement", today=today)
    assert r["status"] == status
    assert r["days_until_eligible"] == days


# --- Normalization ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Screens", "monitor"),
        ("headphones", "headset"),
        ("docking stations", "docking_station"),
        ("mice", "mouse"),
        (" LAPTOP ", "laptop"),
    ],
)
def test_normalize_item(text, expected):
    assert normalize_item(text) == expected


def test_normalize_item_not_in_catalog():
    assert normalize_item("chair") is None


# --- Oldest acquisition ----------------------------------------------------------------

def test_replacement_measured_from_oldest_unit(tmp_path, monkeypatch):
    employees = {
        "T200": {
            "name": "Two Monitors",
            "role": "standard",
            "department": "QA",
            "hire_date": "2019-01-01",
            "equipment": [
                {"item": "monitor", "acquired_date": "2025-06-01", "asset_tag": "MN-9002"},
                {"item": "monitor", "acquired_date": "2020-01-01", "asset_tag": "MN-9001"},
            ],
        }
    }
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(employees), encoding="utf-8")
    monkeypatch.setenv("EMPLOYEES_PATH", str(path))

    r = check("T200", "monitor", "replacement")
    # Oldest (2020-01-01) + 36 months = 2023-01-01 -> eligible. The newest would give 2028.
    assert r["status"] == "eligible"
    assert r["next_eligible_date"] == "2023-01-01"


# --- Result shape ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "employee_id, item, request_type",
    [
        ("E001", "monitor", "replacement"),  # eligible
        ("E002", "laptop", None),            # ineligible
        ("E003", "laptop", "replacement"),   # borderline
        ("E004", "standing desk", None),     # unknown_item
        ("E999", "monitor", None),           # error
    ],
)
def test_status_and_reason_are_first_keys(employee_id, item, request_type):
    assert list(check(employee_id, item, request_type))[:2] == ["status", "reason"]


def test_request_type_case_insensitive_and_empty_means_not_given():
    assert check("E001", "monitor", "Replacement")["request_type"] == "replacement"
    assert check("E001", "monitor", "  ")["request_type"] == "replacement"  # inferred
