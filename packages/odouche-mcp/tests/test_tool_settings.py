import asyncio
import io
from dataclasses import replace
from typing import Any, ClassVar, Self

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import CallToolResult, Tool, ToolAnnotations

import odouche
from odouche_mcp._contract import add_tool
from odouche_mcp._write import SETTINGS, settings_tool
from odouche_mcp.server import create_server


SENTINEL = "sentinel-session-value"
TOOL = "change_branch_settings"

MAIN = odouche.Branch(id=3, name="main", stage=odouche.Stage.PRODUCTION, stage_name="production")
FEATURE = odouche.Branch(id=4, name="feature-x", stage=odouche.Stage.DEVELOPMENT, stage_name="dev")
ODD = odouche.Branch(id=5, name="odd\x1b[2J\nname", stage=odouche.Stage.DEVELOPMENT, stage_name="dev")
OWN = odouche.BranchSettings(
    push_behavior=odouche.PushBehavior.NEW_BUILD,
    project_defaults=False,
    module_install=odouche.ModuleInstall.REPOSITORY,
    modules=(),
    tests=odouche.BuildTests.MODULES,
    test_tags=None,
    demo_data=True,
    ai_agent=odouche.AiAgent.CLAUDE,
    odoo_version=None,
    odoo_revision_id=None,
    machine="ubuntu-24.04",
    recommended_machine="ubuntu-24.04",
    next_machine=None,
    domains=(),
    dns_target=None,
)


class Upstream:
    """A client over one project, `acme`, that narrows and refuses a change as the library does."""

    modes: ClassVar[list[bool]] = []
    sent: ClassVar[list[odouche.SettingsChange]] = []
    found: ClassVar[odouche.BranchSettings] = OWN
    failure: ClassVar[Exception | None] = None

    def __init__(self, *, read_only: bool) -> None:
        self.read_only = read_only
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[odouche.Branch]:
        if project != "acme":
            msg = f"No project {project} among those you can reach."
            raise odouche.NotFoundError(msg)
        return [MAIN, FEATURE, ODD]

    def branch_settings(self, branch: odouche.Branch) -> odouche.BranchSettings:
        return self.found

    check_settings_change = odouche.Client.check_settings_change

    def change_branch_settings(self, branch: odouche.Branch, change: odouche.SettingsChange) -> odouche.SettingsOutcome:
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
    monkeypatch.setattr(Upstream, "modes", [])
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


def test_the_tool_is_listed_as_one_that_changes_state():
    tool = _tools(_allowed())[TOOL]

    assert tool.annotations == ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
    )
    assert (tool.description or "").startswith("Change state on Odoo.sh: change settings of a branch")
    assert "Touches: the settings given of the branch" in (tool.description or "")
    assert set(tool.input_schema["required"]) == {"project", "branch"}
    assert set(tool.input_schema["properties"]) == {
        "project",
        "branch",
        "push_behavior",
        "project_defaults",
        "module_install",
        "modules",
        "tests",
        "test_tags",
        "demo_data",
        "ai_agent",
    }


def test_only_the_settings_given_reach_the_change_on_a_client_that_writes():
    result = _call(_allowed(), project="acme", branch="feature-x", ai_agent="opencode", push_behavior="new_build")

    assert not result.is_error
    assert Upstream.sent == [odouche.SettingsChange(ai_agent=odouche.AiAgent.OPENCODE)]
    assert Upstream.modes == [False]
    content = result.structured_content
    assert content is not None
    assert content["branch"]["name"] == "feature-x"
    assert (content["changed"], content["unchanged"], content["moved"]) == (["ai_agent"], ["push_behavior"], [])
    assert content["settings"]["ai_agent"] == "opencode"


def test_a_setting_odoo_sh_moves_along_is_returned_with_its_values():
    result = _call(_allowed(), project="acme", branch="feature-x", module_install="all")

    assert not result.is_error
    content = result.structured_content
    assert content is not None
    assert content["changed"] == ["module_install"]
    assert content["moved"] == [{"name": "tests", "before": "modules", "after": "off"}]
    assert content["settings"]["tests"] == "off"


def test_modules_are_names_separated_by_commas():
    _call(_allowed(), project="acme", branch="feature-x", module_install="listed", modules="sale, purchase,")

    assert Upstream.sent == [
        odouche.SettingsChange(module_install=odouche.ModuleInstall.LISTED, modules=("sale", "purchase"))
    ]


def test_settings_already_at_their_value_send_nothing():
    result = _call(_allowed(), project="acme", branch="feature-x", ai_agent="claude", test_tags="")

    assert not result.is_error
    assert Upstream.sent == []
    content = result.structured_content
    assert content is not None
    assert (content["changed"], content["unchanged"]) == ([], ["test_tags", "ai_agent"])


def test_the_tool_built_without_the_switch_has_a_read_only_client():
    server = MCPServer(name="scratch")
    add_tool(
        server,
        settings_tool(allow_changes=False),
        returns="the settings after.",
        touches="the settings given.",
        bounds="seven requests.",
        annotations=SETTINGS,
    )

    error = _error(server, project="acme", branch="feature-x", ai_agent="opencode")

    assert error == "This client is read-only: it does not send a change_settings."
    assert Upstream.modes == [True]
    assert Upstream.sent == []


def test_a_value_that_is_no_choice_is_refused_by_the_schema_before_any_client():
    result = _call(_allowed(), project="acme", branch="feature-x", ai_agent="opencod")

    assert result.is_error
    assert Upstream.modes == []


@pytest.mark.parametrize(
    ("arguments", "said"),
    [
        ({}, "at least one setting"),
        ({"modules": "sale;purchase"}, "not a module name"),
        ({"test_tags": "/sale\n/purchase"}, "Test tags hold only"),
        ({"test_tags": "/sale $(id)"}, "Test tags hold only"),
    ],
)
def test_a_change_that_cannot_be_sent_is_a_tool_error_before_any_client(arguments: dict[str, str], said: str):
    assert said in _error(_allowed(), project="acme", branch="feature-x", **arguments)
    assert Upstream.modes == []


def test_a_rule_of_the_tab_is_a_tool_error_with_the_message_of_the_library():
    Upstream.found = replace(OWN, project_defaults=True)

    assert "turn `project_defaults` off" in _error(_allowed(), project="acme", branch="feature-x", ai_agent="opencode")
    assert Upstream.sent == []


def test_another_value_error_once_sent_is_no_refusal_of_the_arguments(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Upstream, "failure", ValueError("Raised after the change was sent."))

    result = _call(_allowed(), project="acme", branch="feature-x", ai_agent="opencode")

    assert result.is_error
    assert "Raised after the change was sent." not in result.model_dump()["content"][0]["text"]
    assert len(Upstream.sent) == 1


def test_a_production_branch_is_refused():
    assert "production" in _error(_allowed(), project="acme", branch="main", push_behavior="update")
    assert Upstream.sent == []


def test_an_unknown_outcome_says_to_read_the_settings_before_trying_again():
    Upstream.failure = odouche.OutcomeUnknownError(
        "The change of branch 4's settings was sent, and the settings do not show it.",
        operation="branch settings change",
    )

    error = _error(_allowed(), project="acme", branch="feature-x", ai_agent="opencode")

    assert error.endswith("Read the branch's settings with get_branch_settings before trying again.")
    assert Upstream.sent == [odouche.SettingsChange(ai_agent=odouche.AiAgent.OPENCODE)]


def test_a_change_writes_one_line_with_the_names_and_no_value(capsys: pytest.CaptureFixture[str]):
    _call(_allowed(), project="acme", branch="feature-x", ai_agent="opencode", tests="tags", test_tags="/secret_tag")

    captured = capsys.readouterr()
    assert captured.err == (
        "odouche-mcp: change_branch_settings project='acme' branch='feature-x': changed tests, test_tags, ai_agent\n"
    )
    assert "secret_tag" not in captured.err
    assert captured.out == ""


def test_a_change_with_nothing_new_writes_that_nothing_changed(capsys: pytest.CaptureFixture[str]):
    _call(_allowed(), project="acme", branch="feature-x", ai_agent="claude")

    assert capsys.readouterr().err == (
        "odouche-mcp: change_branch_settings project='acme' branch='feature-x': changed nothing\n"
    )


@pytest.mark.parametrize(
    ("branch", "arguments", "outcome"),
    [
        ("main", {"push_behavior": "update"}, "StageRefusedError"),
        ("nope", {"ai_agent": "opencode"}, "NotFoundError"),
        ("feature-x", {}, "ToolError"),
    ],
)
def test_a_change_that_fails_writes_one_line_with_the_kind_of_error(
    capsys: pytest.CaptureFixture[str], branch: str, arguments: dict[str, str], outcome: str
):
    _error(_allowed(), project="acme", branch=branch, **arguments)

    err = capsys.readouterr().err
    assert err == f"odouche-mcp: change_branch_settings project='acme' branch='{branch}': {outcome}\n"
    assert SENTINEL not in err


def test_the_line_escapes_the_control_characters_of_a_name(capsys: pytest.CaptureFixture[str]):
    _call(_allowed(), project="acme", branch=ODD.name, ai_agent="opencode")

    err = capsys.readouterr().err
    assert err == ("odouche-mcp: change_branch_settings project='acme' branch='odd\\x1b[2J\\nname': changed ai_agent\n")


def test_a_stderr_that_is_closed_does_not_fail_a_change_that_was_sent(monkeypatch: pytest.MonkeyPatch):
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr("sys.stderr", closed)

    result = _call(_allowed(), project="acme", branch="feature-x", ai_agent="opencode")

    assert not result.is_error
    assert len(Upstream.sent) == 1
