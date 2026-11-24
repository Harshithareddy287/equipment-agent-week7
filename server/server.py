"""MCP server for the IT equipment request handler.

A thin wrapper: each tool calls the plain function in server/tools.py, where the
business logic lives and is unit-tested. Run with:  python -m server.server

"today" is never a tool argument (docs/requirements.md section 10); the plain
functions fall back to config.get_today(), i.e. DEMO_TODAY or the real date.
"""

from mcp.server import MCPServer

from server import tools

mcp = MCPServer("equipment-requests")


@mcp.tool()
def get_employee_info(employee_id: str) -> dict:
    """Look up an employee by ID (e.g. "E001"; case and surrounding spaces are ignored).

    Returns the employee's id, name, role, department, hire_date, tenure
    (tenure_months, years, months) and equipment on file (a list of
    {item, acquired_date, asset_tag}).

    On failure returns {"error": <message>, "error_code": <code>} where code is
    INVALID_EMPLOYEE_ID (empty ID) or EMPLOYEE_NOT_FOUND (no such employee).
    """
    return tools.get_employee_info(employee_id)


@mcp.tool()
def get_policy_limits(role: str) -> dict:
    """Return what a role is eligible for and how often (case and surrounding spaces are ignored).

    Roles in the policy: standard, manager, engineer, contractor. Returns
    {"role": <role>, "items": {<item>: {allowed, max_count, refresh_months}}} for every
    catalog item: laptop, monitor, keyboard, mouse, headset, docking_station.
    allowed=false means the role cannot request that item; refresh_months is how
    many months must pass before an item can be replaced (null when not allowed).

    On failure returns {"error": <message>, "error_code": "ROLE_NOT_IN_POLICY"}
    (unknown or empty role).
    """
    return tools.get_policy_limits(role)


@mcp.tool()
def check_request_eligibility(employee_id: str, item: str, request_type: str | None = None) -> dict:
    """Check whether an employee's equipment request falls within policy. Call this before deciding.

    Args:
        employee_id: e.g. "E001".
        item: the item requested, in plain words (e.g. "monitor", "screens", "headphones").
            It is mapped to a catalog item: laptop, monitor, keyboard, mouse, headset,
            docking_station. Anything else is reported as unknown_item.
        request_type: "additional" when the employee wants one more ("second", "another",
            "extra"); "replacement" when they want to replace one they have ("replace",
            "old", "slow", "broken"). Omit it if the wording is unclear: it is then
            inferred (replacement if they already own the item, otherwise additional).

    Returns {status, reason, item, request_type, ...} where status is one of:
        eligible     - within policy.
        ineligible   - a policy rule says no (role not allowed the item, maximum count
                       reached, or the refresh date is more than 60 days away).
        borderline   - a replacement becomes eligible within 60 days.
        unknown_item - the item is not in the catalog; "catalog" lists what can be requested.
        error        - bad input or data; "error_code" is INVALID_EMPLOYEE_ID,
                       EMPLOYEE_NOT_FOUND, ROLE_NOT_IN_POLICY or INVALID_REQUEST_TYPE.
    Replacement results also include next_eligible_date and days_until_eligible.
    """
    return tools.check_request_eligibility(employee_id, item, request_type)


if __name__ == "__main__":
    mcp.run(transport="stdio")
