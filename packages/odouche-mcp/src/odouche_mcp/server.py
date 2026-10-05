"""The MCP server and its entry point."""

from mcp.server import MCPServer

from odouche_mcp import __version__
from odouche_mcp._contract import add_tool
from odouche_mcp._read import (
    DEFAULT_BUILDS,
    DEFAULT_LISTED,
    MAX_BUILDS,
    MAX_LISTED,
    get_build,
    list_branches,
    list_builds,
    list_projects,
)
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
    listed = f"`limit` items, {DEFAULT_LISTED} by default and {MAX_LISTED} at most"
    add_tool(
        server,
        list_projects,
        returns="the projects, each with its name, repository and address, and `truncated`, true when there are more.",
        bounds=f"one request to Odoo.sh; {listed}.",
    )
    add_tool(
        server,
        list_branches,
        returns="the branches, each with its name and stage, and `truncated`, true when there are more.",
        bounds=f"two requests to Odoo.sh; {listed}.",
    )
    add_tool(
        server,
        list_builds,
        returns="the builds, and `truncated`, true when Odoo.sh answered more than `limit`.",
        bounds=(
            f"three requests to Odoo.sh; `limit` builds, {DEFAULT_BUILDS} by default and {MAX_BUILDS} at most. "
            "Odoo.sh has only been seen to answer 4: older builds are out of reach, whatever `truncated` says."
        ),
    )
    add_tool(
        server,
        get_build,
        returns="the build, with its commit and the address of its database.",
        bounds="three requests to Odoo.sh; a build older than the branch's latest ones is not found.",
    )
    return server


def main() -> None:
    """Run the server over stdio."""
    create_server().run(transport="stdio")
