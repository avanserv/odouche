"""The tool sections of `docs/mcp.md`, held to the server."""

import asyncio
import re
from pathlib import Path

import pytest

from odouche_mcp._logs import DEFAULT_LINES, MAX_BYTES, MAX_LINES
from odouche_mcp._read import DEFAULT_BUILDS, DEFAULT_LISTED, MAX_BUILDS, MAX_LISTED
from odouche_mcp.server import create_server


GUIDE = Path(__file__).resolve().parents[3] / "docs" / "mcp.md"

_SECTION = re.compile(r"^### `(\w+)`\n(.*?)(?=^##)", re.MULTILINE | re.DOTALL)


def sections() -> dict[str, str]:
    """Return the text under each heading of the guide that is a tool's name."""
    return dict(_SECTION.findall(GUIDE.read_text(encoding="utf-8")))


def test_the_guide_has_a_section_for_every_tool_and_no_other():
    registered = [tool.name for tool in asyncio.run(create_server(allow_changes=True).list_tools())]

    assert list(sections()) == registered


@pytest.mark.parametrize(
    ("tool", "default", "most"),
    [
        ("list_projects", DEFAULT_LISTED, MAX_LISTED),
        ("list_branches", DEFAULT_LISTED, MAX_LISTED),
        ("list_builds", DEFAULT_BUILDS, MAX_BUILDS),
    ],
)
def test_the_guide_gives_the_limits_the_tools_have(tool: str, default: int, most: int):
    assert f"`limit`, {default} by default and {most} at most" in " ".join(sections()[tool].split())


def test_the_guide_gives_the_caps_of_a_log():
    section = " ".join(sections()["read_log"].split())

    assert f"`lines`, {DEFAULT_LINES} by default and {MAX_LINES} at most" in section
    assert f"{MAX_BYTES} bytes" in section
