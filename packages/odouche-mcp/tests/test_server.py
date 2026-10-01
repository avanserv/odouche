import asyncio

import pytest
from mcp.server import MCPServer

import odouche_mcp
from odouche_mcp.server import create_server, main


def test_server_identifies_itself():
    server = create_server()

    assert server.name == "odouche"
    assert server.version == odouche_mcp.__version__


def test_server_exposes_no_tools_yet():
    assert asyncio.run(create_server().list_tools()) == []


def test_main_serves_over_stdio(monkeypatch: pytest.MonkeyPatch):
    transports: list[str] = []
    monkeypatch.setattr(MCPServer, "run", lambda _self, transport: transports.append(transport))

    main()

    assert transports == ["stdio"]
