"""The MCP server and its entry point."""

from mcp.server import MCPServer

from odouche_mcp import __version__
from odouche_mcp._contract import add_tool
from odouche_mcp._session import get_session


def create_server() -> MCPServer:
    """Build the server. Tools are registered here, through `_contract.add_tool`."""
    server = MCPServer(name="odouche", version=__version__)
    add_tool(
        server,
        get_session,
        returns="whether a session is available, its source, its user and the seconds left before its max age.",
        bounds="one request to Odoo.sh, none when there is no session.",
    )
    return server


def main() -> None:
    """Run the server over stdio."""
    create_server().run(transport="stdio")
