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


# --- check_request_eligibility (docs/requirements.md sections 4, 5 and 7) ------------

REQUEST_TYPES = ("replacement", "additional")
KEY_ORDER = ("status", "reason")  # always first in eligibility results


def normalize_item(text: str | None, policies: dict | None = None) -> str | None:
    """Map free text to a catalog item (section 4), or None if it is not in the catalog.

    Lowercase + strip, look up catalog items and synonyms, then retry once without a
    trailing "s" ("Screens" -> "screen" -> monitor).
    """
    policies = policies or _load_policies()
    catalog = set(policies["catalog"])
    synonyms = policies["synonyms"]

    def lookup(word: str) -> str | None:
        if word in catalog:
            return word
        return synonyms.get(word)

    word = (text or "").strip().lower()
    if not word:
        return None
    found = lookup(word)
    if found is None and word.endswith("s"):
        found = lookup(word[:-1])
    return found


def _check_request_eligibility(
    employee_id: str | None,
    item: str | None,
    request_type: str | None = None,
    today: date | None = None,
) -> dict:
    """Decide whether a request falls within policy (section 7 rules, first match wins).

    Returns status: eligible | ineligible | borderline | unknown_item | error, plus a
    human-readable reason, the normalized item and the request_type used. Date rules add
    next_eligible_date and days_until_eligible; unknown_item adds catalog; error adds
    error_code. An empty request_type counts as not given.
    """
    today = today or config.get_today()
    given_type = (request_type or "").strip().lower() or None

    def error(message: str, code: str) -> dict:
        return {
            "status": "error",
            "error_code": code,
            "reason": message,
            "item": item,
            "request_type": given_type,
        }

    # Rules 1a-1c: employee and role must be valid (reuse the other tools' errors).
    employee = get_employee_info(employee_id, today=today)
    if "error_code" in employee:
        return error(employee["error"], employee["error_code"])
    limits = get_policy_limits(employee["role"])
    if "error_code" in limits:
        return error(limits["error"], limits["error_code"])

    # Rule 1d: request_type, if given, must be one of the two known types.
    if given_type is not None and given_type not in REQUEST_TYPES:
        return error(
            f"request_type {request_type!r} is invalid; use 'replacement' or 'additional'",
            "INVALID_REQUEST_TYPE",
        )

    # Rule 2: item must be in the catalog after normalization.
    policies = _load_policies()
    catalog_item = normalize_item(item, policies)
    if catalog_item is None:
        return {
            "status": "unknown_item",
            "reason": f"{item!r} is not in the equipment catalog",
            "item": item,
            "request_type": given_type or "additional",
            "catalog": list(policies["catalog"]),
        }

    # Section 5: infer the type; replacing something you don't own is an additional request.
    owned = sorted(
        date.fromisoformat(e["acquired_date"])
        for e in employee["equipment"]
        if e["item"] == catalog_item
    )
    used_type = given_type or ("replacement" if owned else "additional")
    if used_type == "replacement" and not owned:
        used_type = "additional"

    result = {"item": catalog_item, "request_type": used_type}
    limit = limits["items"][catalog_item]
    role = employee["role"]

    # Rule 3: role must be allowed the item.
    if not limit["allowed"]:
        return {**result, "status": "ineligible", "reason": f"role {role} is not allowed a {catalog_item}"}

    # Rules 4-5: additional requests are checked against max_count.
    if used_type == "additional":
        count, max_count = len(owned), limit["max_count"]
        if count >= max_count:
            return {
                **result,
                "status": "ineligible",
                "reason": f"already has {count} {catalog_item}(s); the {role} maximum is {max_count}",
            }
        return {
            **result,
            "status": "eligible",
            "reason": f"has {count} {catalog_item}(s); the {role} maximum is {max_count}",
        }

    # Rules 6-8: replacements are checked against refresh_months from the OLDEST unit.
    oldest = owned[0]
    next_date = config.add_months(oldest, limit["refresh_months"])
    days = (next_date - today).days
    window = policies["borderline_window_days"]
    dates = {"next_eligible_date": next_date.isoformat(), "days_until_eligible": max(days, 0)}
    basis = (
        f"oldest {catalog_item} acquired {oldest.isoformat()}; "
        f"{role} refresh period is {limit['refresh_months']} months"
    )

    if days <= 0:
        return {**result, **dates, "status": "eligible",
                "reason": f"{basis}; eligible since {next_date.isoformat()}"}
    if days <= window:
        return {**result, **dates, "status": "borderline",
                "reason": f"{basis}; eligible on {next_date.isoformat()}, {days} days away "
                          f"(within the {window}-day borderline window)"}
    return {**result, **dates, "status": "ineligible",
            "reason": f"{basis}; not eligible until {next_date.isoformat()}, {days} days away"}


def check_request_eligibility(
    employee_id: str | None,
    item: str | None,
    request_type: str | None = None,
    today: date | None = None,
) -> dict:
    """Public entry point: the section 7 check, with status and reason as the first keys."""
    result = _check_request_eligibility(employee_id, item, request_type, today)
    first = {key: result[key] for key in KEY_ORDER}
    return {**first, **{k: v for k, v in result.items() if k not in KEY_ORDER}}
