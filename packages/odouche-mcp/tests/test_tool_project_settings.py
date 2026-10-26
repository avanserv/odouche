import asyncio
from dataclasses import replace
from ipaddress import ip_address
from typing import Any, ClassVar, Self

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import CallToolResult, Tool, ToolAnnotations

import odouche
from odouche_mcp._contract import add_tool
from odouche_mcp._write import SETTINGS, project_settings_tool
from odouche_mcp.server import create_server


SENTINEL = "sentinel-session-value"
TOOL = "change_project_settings"

OWN = odouche.ProjectSettings(
    name="acme",
    odoo_domain_blocked=False,
    session_lifetime=odouche.SessionLifetime.AUTO,
    public=False,
    commit_statuses_suspended=False,
    deploy_key_writable=False,
    submodules=(),
    hosting=odouche.ProjectHosting(1024, 2048, 1, 1),
    dedicated=False,
    http_timeout_seconds=900,
    cron_timeout_seconds=900,
    module_install=odouche.ModuleInstall.REPOSITORY,
    modules=(),
    tests=odouche.BuildTests.MODULES,
    test_tags=None,
    demo_data=True,
    ai_agent=odouche.AiAgent.CLAUDE,
    ip_allow_list=(ip_address("198.51.100.42"),),
)


class Upstream:
    """A client over one project, `acme`, that narrows and refuses a change as the library does."""

    built: ClassVar[list[bool]] = []
    sent: ClassVar[list[odouche.ProjectSettingsChange]] = []
    found: ClassVar[odouche.ProjectSettings] = OWN
    failure: ClassVar[Exception | None] = None

    def __init__(self, *, read_only: bool) -> None:
        self.read_only = read_only
        self.built.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def project_settings(self, project: str) -> odouche.ProjectSettings:
        if project != "acme":
            msg = f"The session's user can reach no project named {project!r}."
            raise odouche.NotFoundError(msg)

        return self.found

    check_project_settings_change = odouche.Client.check_project_settings_change

    def change_project_settings(
        self, project: str, change: odouche.ProjectSettingsChange
    ) -> odouche.SettingsOutcome[odouche.ProjectSettings]:
        if self.read_only:
            msg = "This client is read-only: it does not send a change_settings."
            raise odouche.ReadOnlyError(msg)

        self.sent.append(change)

        if self.failure:
            raise self.failure

        after = replace(self.found, **change.given())  # pyright: ignore[reportArgumentType]
        moved: tuple[str, ...] = ()

        # As the page says Odoo.sh does: installing every module turns the test suite off.
        if after.module_install is odouche.ModuleInstall.ALL and after.tests is not odouche.BuildTests.OFF:
            after, moved = replace(after, tests=odouche.BuildTests.OFF), ("tests",)

        return odouche.SettingsOutcome(self.found, after, moved)


@pytest.fixture(autouse=True)
def upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(odouche.SESSION_ENV, SENTINEL)
    monkeypatch.setattr(odouche, "Client", Upstream)
    monkeypatch.setattr(Upstream, "built", [])
    monkeypatch.setattr(Upstream, "sent", [])
    monkeypatch.setattr(Upstream, "found", OWN)
    monkeypatch.setattr(Upstream, "failure", None)


def _allowed() -> MCPServer:
    return create_server(allow_changes=True)


def _tools(server: MCPServer) -> dict[str, Tool]:
    async def run() -> dict[str, Tool]:
        async with Client(server) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    return asyncio.run(run())


def _call(server: MCPServer, **arguments: Any) -> CallToolResult:
    async def run() -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(TOOL, arguments)

    return asyncio.run(run())


def _error(server: MCPServer, **arguments: Any) -> str:
    result = _call(server, **arguments)
    assert result.is_error

    return result.model_dump()["content"][0]["text"].removeprefix(f"Error executing tool {TOOL}: ")


def test_the_tool_is_absent_unless_changes_are_allowed():
    assert TOOL not in _tools(create_server())


def test_the_tool_is_listed_as_one_that_changes_state_and_takes_no_access_setting():
    tool = _tools(_allowed())[TOOL]

    assert tool.annotations == ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
    )
    description = tool.description or ""
    assert description.startswith("Change state on Odoo.sh: change settings of a project")
    assert "The IP allow list, public access and session lifetime are not offered" in description
    assert "Never the IP allow list, public access or the session lifetime." in description
    assert tool.input_schema["required"] == ["project"]
    assert tool.input_schema["additionalProperties"] is False
    assert set(tool.input_schema["properties"]) == {
        "project",
        "http_timeout_seconds",
        "cron_timeout_seconds",
        "module_install",
        "modules",
        "tests",
        "test_tags",
        "demo_data",
        "ai_agent",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"ip_whitelist": "192.0.2.7"},
        {"ip_allow_list": ["192.0.2.7"]},
        {"allow_ips": ["192.0.2.7"]},
        {"disallow_ips": ["198.51.100.42"]},
        {"public": True},
        {"session_lifetime": "8d"},
        {"ai_agent": "opencode", "allow_ips": ["192.0.2.7"]},
    ],
    ids=",".join,
)
def test_an_access_setting_is_refused_before_any_client(arguments: dict[str, object]):
    error = _error(_allowed(), project="acme", **arguments)

    assert "Extra inputs are not permitted" in error
    assert Upstream.built == []
    assert Upstream.sent == []


def test_an_access_setting_writes_no_audit_line(capsys: pytest.CaptureFixture[str]):
    _error(_allowed(), project="acme", allow_ips=["192.0.2.7"])

    assert capsys.readouterr().err == ""


def test_only_the_settings_given_reach_the_change_on_a_client_that_writes():
    result = _call(_allowed(), project="acme", ai_agent="opencode", demo_data=True)

    assert not result.is_error
    assert Upstream.sent == [odouche.ProjectSettingsChange(ai_agent=odouche.AiAgent.OPENCODE)]
    assert Upstream.built == [False]
    content = result.structured_content
    assert content is not None
    assert content["project"] == "acme"
    assert (content["changed"], content["unchanged"], content["moved"]) == (["ai_agent"], ["demo_data"], [])
    assert content["settings"]["ai_agent"] == "opencode"
    assert content["settings"]["ip_allow_list"] == ["198.51.100.42"]


def test_a_setting_odoo_sh_moves_along_is_returned_with_its_values():
    content = _call(_allowed(), project="acme", module_install="all").structured_content

    assert content is not None
    assert content["moved"] == [{"name": "tests", "before": "modules", "after": "off"}]


def test_a_timeout_on_a_dedicated_server_is_sent_in_seconds():
    Upstream.found = replace(OWN, dedicated=True)
    content = _call(_allowed(), project="acme", http_timeout_seconds=1800).structured_content

    assert Upstream.sent == [odouche.ProjectSettingsChange(http_timeout_seconds=1800)]
    assert content is not None
    assert content["settings"]["http_timeout_seconds"] == 1800


def test_a_timeout_without_a_dedicated_server_is_a_tool_error_with_the_message_of_the_library():
    assert "dedicated server only" in _error(_allowed(), project="acme", cron_timeout_seconds=1800)
    assert Upstream.sent == []


def test_settings_already_at_their_value_send_nothing():
    content = _call(_allowed(), project="acme", ai_agent="claude", test_tags="").structured_content

    assert Upstream.sent == []
    assert content is not None
    assert (content["changed"], content["unchanged"]) == ([], ["test_tags", "ai_agent"])


@pytest.mark.parametrize(
    ("arguments", "said"),
    [
        ({}, "at least one setting"),
        ({"http_timeout_seconds": 0}, "over 0"),
        ({"modules": "sale;purchase"}, "not a module name"),
        ({"test_tags": "/sale $(id)"}, "Test tags hold only"),
    ],
)
def test_a_change_that_cannot_be_sent_is_a_tool_error_before_any_client(arguments: dict[str, object], said: str):
    assert said in _error(_allowed(), project="acme", **arguments)
    assert Upstream.built == []


def test_the_tool_built_without_the_switch_has_a_read_only_client():
    server = MCPServer(name="scratch")
    add_tool(
        server,
        project_settings_tool(allow_changes=False),
        returns="the settings after.",
        touches="the settings given.",
        bounds="six requests.",
        annotations=SETTINGS,
    )

    error = _error(server, project="acme", ai_agent="opencode")

    assert error == "This client is read-only: it does not send a change_settings."
    assert Upstream.built == [True]


def test_an_unknown_outcome_says_to_read_the_settings_before_trying_again():
    Upstream.failure = odouche.OutcomeUnknownError(
        "The change of project acme's settings was sent, and the settings could not be read back.",
        operation="project settings change",
    )

    error = _error(_allowed(), project="acme", ai_agent="opencode")

    assert error.endswith("Read the project's settings with get_project_settings before trying again.")
    assert len(Upstream.sent) == 1


def test_a_change_writes_one_line_with_the_names_and_no_value(capsys: pytest.CaptureFixture[str]):
    _call(_allowed(), project="acme", tests="tags", test_tags="/secret_tag")

    captured = capsys.readouterr()
    assert captured.err == "odouche-mcp: change_project_settings project='acme': changed tests, test_tags\n"
    assert captured.out == ""


@pytest.mark.parametrize(
    ("project", "arguments", "outcome"),
    [("nope", {"ai_agent": "opencode"}, "NotFoundError"), ("acme", {}, "ToolError")],
)
def test_a_change_that_fails_writes_one_line_with_the_kind_of_error(
    capsys: pytest.CaptureFixture[str], project: str, arguments: dict[str, str], outcome: str
):
    _error(_allowed(), project=project, **arguments)

    err = capsys.readouterr().err
    assert err == f"odouche-mcp: change_project_settings project='{project}': {outcome}\n"
    assert SENTINEL not in err
