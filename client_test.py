"""MCP client check for the real server: list the tools and call each one.

Run from the repo root:  DEMO_TODAY=2026-11-01 python client_test.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parent

# The v2 SDK starts the server with a minimal default environment, so pass on
# PATH plus our own settings explicitly (each only if it is set).
# flag_for_human_review writes tickets; unless told otherwise, send them to a
# throwaway file so this demo client never writes to data/escalations.json.
if "ESCALATIONS_PATH" not in os.environ:
    os.environ["ESCALATIONS_PATH"] = str(Path(tempfile.mkdtemp()) / "escalations.json")

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

        review_args = {
            "employee_id": "E003",
            "request": "My laptop is slow. Can I get a new one?",
            "reason": "BORDERLINE_ELIGIBILITY: eligible on 2026-12-01, 30 days away",
        }
        result = await client.call_tool("flag_for_human_review", review_args)
        print(f"\nflag_for_human_review({review_args}) ->")
        print(json.dumps(result_as_json(result), indent=2))
        print(f"(ticket written to {os.environ['ESCALATIONS_PATH']})")


if __name__ == "__main__":
    asyncio.run(main())
