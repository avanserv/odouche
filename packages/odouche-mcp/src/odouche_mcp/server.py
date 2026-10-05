"""The MCP server and its entry point."""

from mcp.server import MCPServer

from odouche_mcp import __version__


def create_server() -> MCPServer:
    """Build the server. Tools are registered here, through `_contract.add_tool`."""
    return MCPServer(name="odouche", version=__version__)


def main() -> None:
    """Run the server over stdio."""
    create_server().run(transport="stdio")
