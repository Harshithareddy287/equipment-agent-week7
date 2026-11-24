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


if __name__ == "__main__":
    mcp.run(transport="stdio")
