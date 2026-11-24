"""Minimal MCP server (Step 1): one trivial tool, no business logic.

Run directly with:  python -m server.hello_server
It speaks MCP over stdio, so it is normally launched by a client (see client_hello.py).
"""

from mcp.server import MCPServer  # SDK v2 name for what v1 called FastMCP

# Create the server; the name is what clients see during the handshake.
mcp = MCPServer("hello-server")


@mcp.tool()
def ping() -> str:
    """Health check: always returns 'pong'."""
    return "pong"


if __name__ == "__main__":
    # stdio is the default transport: read requests on stdin, write responses on stdout.
    mcp.run(transport="stdio")
