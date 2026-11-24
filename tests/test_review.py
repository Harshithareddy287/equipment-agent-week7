"""Unit tests for flag_for_human_review (docs/requirements.md section 10).

Every test points ESCALATIONS_PATH into tmp_path (autouse fixture), so the real
data/escalations.json is never touched.
"""

import json
from datetime import datetime

import pytest

from server.tools import flag_for_human_review

FIELDS = {"ticket_id", "employee_id", "request", "reason", "created_at", "status"}


@pytest.fixture(autouse=True)
def escalations_file(tmp_path, monkeypatch):
    path = tmp_path / "escalations.json"
    monkeypatch.setenv("ESCALATIONS_PATH", str(path))
    return path


def read_tickets(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- normal cases --------------------------------------------------------------------

def test_first_call_creates_file_and_returns_first_ticket(escalations_file):
    assert not escalations_file.exists()
    result = flag_for_human_review("E003", "Laptop is slow", "BORDERLINE_ELIGIBILITY: 30 days away")
    assert result == {"status": "pending_review", "ticket_id": "ESC-0001"}
    assert list(result)[0] == "status"
    assert escalations_file.exists()


def test_stored_record_has_exactly_the_six_fields(escalations_file):
    flag_for_human_review(" E003 ", "Laptop is slow", "BORDERLINE_ELIGIBILITY: 30 days away")
    [record] = read_tickets(escalations_file)
    assert set(record) == FIELDS
    assert record["ticket_id"] == "ESC-0001"
    assert record["employee_id"] == "E003"  # whitespace stripped
    assert record["request"] == "Laptop is slow"
    assert record["reason"] == "BORDERLINE_ELIGIBILITY: 30 days away"
    assert record["status"] == "pending_review"
    created = datetime.fromisoformat(record["created_at"])
    assert created.tzinfo is not None  # ISO 8601 with timezone


def test_second_call_gets_next_unique_ticket(escalations_file):
    first = flag_for_human_review("E003", "req 1", "reason 1")
    second = flag_for_human_review("E004", "req 2", "reason 2")
    assert (first["ticket_id"], second["ticket_id"]) == ("ESC-0001", "ESC-0002")
    tickets = read_tickets(escalations_file)
    assert len(tickets) == 2
    assert len({t["ticket_id"] for t in tickets}) == 2


def test_numbering_continues_from_existing_file(escalations_file):
    existing = [
        {"ticket_id": "ESC-0001", "employee_id": "E003", "request": "a", "reason": "x",
         "created_at": "2026-11-01T09:00:00+00:00", "status": "pending_review"},
        {"ticket_id": "ESC-0002", "employee_id": "E004", "request": "b", "reason": "y",
         "created_at": "2026-11-01T09:05:00+00:00", "status": "pending_review"},
    ]
    escalations_file.write_text(json.dumps(existing), encoding="utf-8")
    assert flag_for_human_review("E008", "c", "z")["ticket_id"] == "ESC-0003"
    tickets = read_tickets(escalations_file)
    assert len(tickets) == 3
    assert tickets[:2] == existing  # earlier tickets are kept unchanged


def test_unknown_employee_is_accepted(escalations_file):
    result = flag_for_human_review("E999", "I need a new monitor.", "UNKNOWN_EMPLOYEE: E999 not found")
    assert result["status"] == "pending_review"
    assert read_tickets(escalations_file)[0]["employee_id"] == "E999"


def test_multi_code_reason_stored_unchanged(escalations_file):
    reason = "ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY: standing desk for back injury"
    flag_for_human_review("E004", "I need a standing desk because of a back injury.", reason)
    assert read_tickets(escalations_file)[0]["reason"] == reason


def test_missing_folder_is_created(tmp_path, monkeypatch):
    path = tmp_path / "new" / "nested" / "escalations.json"
    monkeypatch.setenv("ESCALATIONS_PATH", str(path))
    assert flag_for_human_review("E003", "req", "reason")["ticket_id"] == "ESC-0001"
    assert path.exists()


# --- error cases ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_reason", ["", "   ", None])
def test_empty_reason_rejected_and_file_not_created(escalations_file, bad_reason):
    result = flag_for_human_review("E003", "req", bad_reason)
    assert result["status"] == "error"
    assert result["error_code"] == "EMPTY_REASON"
    assert "error" in result
    assert not escalations_file.exists()


def test_empty_reason_leaves_existing_file_unchanged(escalations_file):
    flag_for_human_review("E003", "req", "reason")
    before = escalations_file.read_text(encoding="utf-8")
    assert flag_for_human_review("E004", "req", "  ")["error_code"] == "EMPTY_REASON"
    assert escalations_file.read_text(encoding="utf-8") == before


def test_empty_employee_id_is_accepted(escalations_file):
    result = flag_for_human_review("", "I need a new monitor.", "MISSING_EMPLOYEE_ID: no ID in request")
    assert result["ticket_id"] == "ESC-0001" and read_tickets(escalations_file)[0]["employee_id"] == ""
