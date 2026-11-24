"""MCP client side: how the agent starts and talks to server.server over stdio."""

import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parent.parent

# The v2 SDK starts the server with a minimal default environment, so pass on
# PATH plus our own settings explicitly (each only if it is set).
PASS_THROUGH = ["PATH", "DEMO_TODAY", "EMPLOYEES_PATH", "POLICIES_PATH", "ESCALATIONS_PATH"]


def server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,  # same interpreter / venv as the agent
        args=["-m", "server.server"],
        cwd=REPO_ROOT,
        env={name: os.environ[name] for name in PASS_THROUGH if name in os.environ},
    )


def connect() -> Client:
    """An MCP client for our server; use as `async with connect() as mcp:`."""
    return Client(server_params())


def mcp_tools_to_claude(mcp_tools) -> list[dict]:
    """Convert MCP tool listings to Claude's tool format; nothing is hardcoded."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
        }
        for tool in mcp_tools
    ]


def result_as_json(result):
    """Prefer the tool's structured output; fall back to its text block."""
    if result.structured_content is not None:
        return result.structured_content
    text = result.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
