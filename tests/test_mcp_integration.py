"""MCP integration tests: start server.server over stdio and call each tool.

No LLM and no API key. The server runs with DEMO_TODAY fixed and ESCALATIONS_PATH
pointing into tmp_path, so real data files are never written.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"  # run on asyncio only (trio is not installed)


@pytest.fixture
def server_params(tmp_path):
    # The v2 SDK does not inherit the environment, so pass what the server needs.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DEMO_TODAY": "2026-11-01",
        "ESCALATIONS_PATH": str(tmp_path / "escalations.json"),
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.server"],
        cwd=REPO_ROOT,
        env=env,
    )


async def call(params, name, arguments):
    """Start the server, call one tool, and return its result as a dict."""
    async with Client(params) as client:
        result = await client.call_tool(name, arguments)
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_lists_exactly_the_registered_tools(server_params):
    async with Client(server_params) as client:
        listing = await client.list_tools()
    assert sorted(tool.name for tool in listing.tools) == [
        "check_request_eligibility",
        "flag_for_human_review",
        "get_employee_info",
        "get_policy_limits",
    ]


async def test_get_employee_info_uses_demo_today(server_params):
    info = await call(server_params, "get_employee_info", {"employee_id": "E001"})
    # 67 completed months on 2026-11-01; the real date would give a different value.
    assert info["tenure"]["tenure_months"] == 67


async def test_get_policy_limits_manager(server_params):
    limits = await call(server_params, "get_policy_limits", {"role": "manager"})
    assert limits["items"]["laptop"]["refresh_months"] == 24


async def test_get_policy_limits_unknown_role(server_params):
    result = await call(server_params, "get_policy_limits", {"role": "intern"})
    assert result["error_code"] == "ROLE_NOT_IN_POLICY"


async def test_check_request_eligibility_borderline(server_params):
    result = await call(
        server_params,
        "check_request_eligibility",
        {"employee_id": "E003", "item": "laptop", "request_type": "replacement"},
    )
    assert result["status"] == "borderline"
    assert result["days_until_eligible"] == 30


async def test_flag_for_human_review_writes_ticket(server_params, tmp_path):
    reason = "BORDERLINE_ELIGIBILITY: eligible on 2026-12-01, 30 days away"
    result = await call(
        server_params,
        "flag_for_human_review",
        {"employee_id": "E003", "request": "My laptop is slow.", "reason": reason},
    )
    assert result == {"status": "pending_review", "ticket_id": "ESC-0001"}

    # server_params points ESCALATIONS_PATH at tmp_path/escalations.json.
    tickets = json.loads((tmp_path / "escalations.json").read_text(encoding="utf-8"))
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == "ESC-0001"
    assert tickets[0]["employee_id"] == "E003"
    assert tickets[0]["reason"] == reason
