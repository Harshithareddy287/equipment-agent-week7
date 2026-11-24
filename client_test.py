"""MCP client check for the real server: list tools, call get_employee_info.

Run from the repo root:  DEMO_TODAY=2026-11-01 python client_test.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parent

# The v2 SDK starts the server with a minimal default environment, so pass on
# PATH plus our own settings explicitly (each only if it is set).
PASS_THROUGH = ["PATH", "DEMO_TODAY", "EMPLOYEES_PATH", "POLICIES_PATH", "ESCALATIONS_PATH"]
SERVER_ENV = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}

SERVER = StdioServerParameters(
    command=sys.executable,  # same interpreter / venv as this script
    args=["-m", "server.server"],
    cwd=REPO_ROOT,
    env=SERVER_ENV,
)


def result_as_json(result) -> dict:
    """Prefer the tool's structured output; fall back to parsing its text block."""
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


async def main() -> None:
    async with Client(SERVER) as client:
        listing = await client.list_tools()
        print("Registered tools:", [tool.name for tool in listing.tools])

        for employee_id in ["E001", "E999"]:
            result = await client.call_tool("get_employee_info", {"employee_id": employee_id})
            print(f"\nget_employee_info({employee_id!r}) ->")
            print(json.dumps(result_as_json(result), indent=2))

        for role in ["manager", "intern"]:
            result = await client.call_tool("get_policy_limits", {"role": role})
            print(f"\nget_policy_limits({role!r}) ->")
            print(json.dumps(result_as_json(result), indent=2))

        eligibility_checks = [
            {"employee_id": "E001", "item": "monitor", "request_type": "replacement"},
            {"employee_id": "E003", "item": "laptop", "request_type": "replacement"},
            {"employee_id": "E004", "item": "standing desk"},
        ]
        for args in eligibility_checks:
            result = await client.call_tool("check_request_eligibility", args)
            print(f"\ncheck_request_eligibility({args}) ->")
            print(json.dumps(result_as_json(result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
