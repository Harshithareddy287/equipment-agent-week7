"""Business logic for the equipment request handler, as plain Python functions.

These are tested directly (tests/) and later wrapped as MCP tools in server/server.py.
See docs/requirements.md section 10 for the contracts.
"""

import json
from datetime import date

from server import config


def _error(message: str, code: str) -> dict:
    """Error shape shared by all tools: {"error": ..., "error_code": ...}."""
    return {"error": message, "error_code": code}


def _load_employees() -> dict:
    with open(config.employees_path(), encoding="utf-8") as f:
        return json.load(f)


def _load_policies() -> dict:
    with open(config.policies_path(), encoding="utf-8") as f:
        return json.load(f)


def get_policy_limits(role: str | None) -> dict:
    """Return what a role may request: per-item allowed, max_count, refresh_months.

    Role matching ignores case and surrounding spaces, so " Manager " finds manager.
    Every catalog item is listed; an item missing from the role's policy is not allowed.
    Errors: ROLE_NOT_IN_POLICY (unknown, empty or None role).
    """
    role_key = (role or "").strip().lower()
    policies = _load_policies()
    role_policy = policies["roles"].get(role_key) if role_key else None
    if role_policy is None:
        return _error(f"role {role_key or '<empty>'!s} is not in the policy", "ROLE_NOT_IN_POLICY")

    not_allowed = {"allowed": False, "max_count": 0, "refresh_months": None}
    items = {item: dict(role_policy.get(item, not_allowed)) for item in policies["catalog"]}
    return {"role": role_key, "items": items}


def get_employee_info(employee_id: str | None, today: date | None = None) -> dict:
    """Return an employee's role, tenure and equipment on file.

    The ID is stripped and uppercased, so " e001 " finds E001.
    Errors: INVALID_EMPLOYEE_ID (empty/whitespace/None), EMPLOYEE_NOT_FOUND.
    """
    emp_id = (employee_id or "").strip().upper()
    if not emp_id:
        return _error("employee_id is empty", "INVALID_EMPLOYEE_ID")

    record = _load_employees().get(emp_id)
    if record is None:
        return _error(f"employee {emp_id} not found", "EMPLOYEE_NOT_FOUND")

    today = today or config.get_today()
    hire_date = date.fromisoformat(record["hire_date"])
    tenure_months = config.completed_months(hire_date, today)

    return {
        "id": emp_id,
        "name": record["name"],
        "role": record["role"],
        "department": record["department"],
        "hire_date": record["hire_date"],
        "tenure": {
            "tenure_months": tenure_months,
            "years": tenure_months // 12,
            "months": tenure_months % 12,
        },
        "equipment": [dict(item) for item in record["equipment"]],
    }
