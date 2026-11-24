"""Unit tests for get_employee_info and the date/config helpers it relies on."""

import json
from datetime import date

import pytest

from server import config
from server.tools import get_employee_info

DEMO_TODAY = date(2026, 11, 1)


# --- get_employee_info: normal cases -------------------------------------------------

def test_known_employee_returns_profile():
    info = get_employee_info("E001", today=DEMO_TODAY)
    assert info["id"] == "E001"
    assert info["name"] == "Priya Shah"
    assert info["role"] == "standard"
    assert len(info["equipment"]) == 2


def test_id_is_stripped_and_uppercased():
    assert get_employee_info(" e001 ", today=DEMO_TODAY) == get_employee_info("E001", today=DEMO_TODAY)


def test_tenure_from_fixed_date():
    # Hired 2021-03-15, today 2026-11-01 -> 67 completed months = 5 years 7 months.
    tenure = get_employee_info("E001", today=DEMO_TODAY)["tenure"]
    assert tenure == {"tenure_months": 67, "years": 5, "months": 7}


# --- get_employee_info: error cases --------------------------------------------------

def test_unknown_employee():
    result = get_employee_info("E999", today=DEMO_TODAY)
    assert result["error_code"] == "EMPLOYEE_NOT_FOUND"
    assert "error" in result


@pytest.mark.parametrize("bad_id", ["", "   ", None])
def test_empty_or_whitespace_id(bad_id):
    result = get_employee_info(bad_id, today=DEMO_TODAY)
    assert result["error_code"] == "INVALID_EMPLOYEE_ID"
    assert "error" in result


# --- date helpers --------------------------------------------------------------------

@pytest.mark.parametrize(
    "start, n, expected",
    [
        (date(2024, 1, 31), 1, date(2024, 2, 29)),   # clamped to last day (leap year)
        (date(2023, 6, 15), 36, date(2026, 6, 15)),  # plain multi-year add
    ],
)
def test_add_months(start, n, expected):
    assert config.add_months(start, n) == expected


@pytest.mark.parametrize(
    "start, end, expected",
    [
        (date(2021, 3, 15), date(2026, 11, 1), 67),
        (date(2021, 3, 15), date(2026, 11, 15), 68),  # boundary: anniversary day reached
    ],
)
def test_completed_months(start, end, expected):
    assert config.completed_months(start, end) == expected


def test_get_today_reads_demo_today(monkeypatch):
    monkeypatch.setenv("DEMO_TODAY", "2026-11-01")
    assert config.get_today() == DEMO_TODAY


# --- data path override --------------------------------------------------------------

def test_employees_path_override(tmp_path, monkeypatch):
    employees = {
        "T100": {
            "name": "Test Person",
            "role": "engineer",
            "department": "QA",
            "hire_date": "2025-11-01",
            "equipment": [],
        }
    }
    path = tmp_path / "employees.json"
    path.write_text(json.dumps(employees), encoding="utf-8")
    monkeypatch.setenv("EMPLOYEES_PATH", str(path))

    info = get_employee_info("T100", today=DEMO_TODAY)
    assert info["name"] == "Test Person"
    assert info["tenure"]["tenure_months"] == 12
    # The real data file is no longer used, so E001 is not found.
    assert get_employee_info("E001", today=DEMO_TODAY)["error_code"] == "EMPLOYEE_NOT_FOUND"
