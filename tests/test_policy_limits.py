"""Unit tests for get_policy_limits (docs/requirements.md sections 6 and 10)."""

import json

import pytest

from server.tools import get_policy_limits

CATALOG = {"laptop", "monitor", "keyboard", "mouse", "headset", "docking_station"}


# --- normal cases --------------------------------------------------------------------

def test_standard_limits():
    result = get_policy_limits("standard")
    assert result["role"] == "standard"
    assert set(result["items"]) == CATALOG
    laptop = result["items"]["laptop"]
    assert (laptop["allowed"], laptop["max_count"], laptop["refresh_months"]) == (True, 1, 48)
    assert result["items"]["docking_station"]["allowed"] is False


def test_manager_laptop_refresh():
    assert get_policy_limits("manager")["items"]["laptop"]["refresh_months"] == 24


def test_engineer_monitor_max_count():
    assert get_policy_limits("engineer")["items"]["monitor"]["max_count"] == 3


def test_contractor_nothing_allowed():
    items = get_policy_limits("contractor")["items"]
    assert set(items) == CATALOG
    assert all(limit["allowed"] is False for limit in items.values())


@pytest.mark.parametrize("variant", ["Manager", " manager ", "MANAGER"])
def test_role_matching_ignores_case_and_spaces(variant):
    assert get_policy_limits(variant) == get_policy_limits("manager")


# --- error cases ---------------------------------------------------------------------

def test_unknown_role():
    result = get_policy_limits("intern")
    assert result["error_code"] == "ROLE_NOT_IN_POLICY"
    assert "error" in result


@pytest.mark.parametrize("bad_role", ["", "   ", None])
def test_empty_role(bad_role):
    result = get_policy_limits(bad_role)
    assert result["error_code"] == "ROLE_NOT_IN_POLICY"
    assert "error" in result


# --- data path override --------------------------------------------------------------

def test_policies_path_override(tmp_path, monkeypatch):
    policies = {
        "catalog": ["laptop", "monitor"],
        "synonyms": {},
        "borderline_window_days": 60,
        "roles": {
            "tester": {"laptop": {"allowed": True, "max_count": 2, "refresh_months": 6}},
        },
    }
    path = tmp_path / "policies.json"
    path.write_text(json.dumps(policies), encoding="utf-8")
    monkeypatch.setenv("POLICIES_PATH", str(path))

    result = get_policy_limits("tester")
    assert result["items"]["laptop"] == {"allowed": True, "max_count": 2, "refresh_months": 6}
    # Catalog item missing from the role's policy is reported as not allowed.
    assert result["items"]["monitor"]["allowed"] is False
    # The real policy file is no longer used.
    assert get_policy_limits("standard")["error_code"] == "ROLE_NOT_IN_POLICY"
