"""Minimal MCP client (Step 1): connect to hello_server, list its tools, call ping.

Run from the repo root:  python client_hello.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parent

# Launch the server as a subprocess with the same Python interpreter (same venv),
# from the repo root so "-m server.hello_server" resolves.
SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "server.hello_server"],
    cwd=REPO_ROOT,
)


async def main() -> None:
    # Entering the context starts the subprocess and performs the MCP handshake.
    async with Client(SERVER) as client:
        listing = await client.list_tools()
        print("Registered tools:", [tool.name for tool in listing.tools])

        result = await client.call_tool("ping", {})
        # Tool output comes back as a list of content blocks; ping returns one text block.
        print("ping ->", result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
