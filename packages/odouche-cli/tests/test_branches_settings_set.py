import json
import re
from dataclasses import fields, replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import AiAgent, Branch, BranchSettings, BuildTests, ModuleInstall, PushBehavior, SettingsChange, Stage
from odouche_cli import _terminal
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
MAIN = Branch(id=1, name="main", stage=Stage.PRODUCTION, stage_name="production")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
ESCAPE = "\x1b[2J\x1b]0;owned\x07"
OWN = BranchSettings(
    push_behavior=PushBehavior.NEW_BUILD,
    project_defaults=False,
    module_install=ModuleInstall.REPOSITORY,
    modules=(),
    tests=BuildTests.MODULES,
    test_tags=None,
    demo_data=True,
    ai_agent=AiAgent.CLAUDE,
    odoo_version=None,
    odoo_revision_id=None,
    machine="ubuntu-24.04",
    recommended_machine="ubuntu-24.04",
    next_machine=None,
    domains=(),
    dns_target="acme-feature-x-104.dev.odoo.com",
)
SET = ("branches", "settings", "set", "--project", "acme", "--branch", "feature-x")
LOST = odouche.OutcomeUnknownError(
    "The change of branch 4's settings was sent, and the settings do not show it. Look before trying again.",
    operation="branch settings change",
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: changes settings as the library does, and records the calls."""

    found: BranchSettings = OWN
    on_branch: Branch = FEATURE
    lost: Exception | None = None
    modes: list[bool]
    calls: list[str]
    sent: list[SettingsChange]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        return [ACME]

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[Branch]:
        self.calls.append(f"branches {project}")
        return [MAIN, self.on_branch]

    def branch_settings(self, branch: Branch) -> BranchSettings:
        self.calls.append(f"settings {branch.name}")
        return self.found

    # The library's own, which asks nothing.
    check_settings_change = odouche.Client.check_settings_change

    def change_branch_settings(self, branch: Branch, change: SettingsChange) -> odouche.SettingsOutcome:
        self.calls.append(f"change {branch.name}")
        self.sent.append(change)

        if self.lost is not None:
            raise self.lost

        after = replace(self.found, **change.given())  # pyright: ignore[reportArgumentType]
        moved: tuple[str, ...] = ()

        # As the page says Odoo.sh does: installing every module turns the test suite off.
        if after.module_install is ModuleInstall.ALL and after.tests is not BuildTests.OFF:
            after, moved = replace(after, tests=BuildTests.OFF), ("tests",)

        return odouche.SettingsOutcome(self.found, after, moved)


@pytest.fixture(autouse=True)
def read_only_clients() -> None:
    """Replace the shared check: the command of this file is one that writes."""


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []
        sent: list[SettingsChange] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)

    return Client


def run(*args: str, stdin: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=stdin)


def changes(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith("change")]


def pairs(result: Result) -> dict[str, str]:
    found = [re.split(r"\s{2,}", line.strip(), maxsplit=1) for line in result.stdout.splitlines()]
    return {row[0]: row[1] if len(row) > 1 else "" for row in found}


def test_a_yes_sends_the_change_on_a_client_that_writes_and_prints_the_settings_after(client: type[StubClient]):
    result = run(*SET, "ai_agent=opencode", stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "settings feature-x", "change feature-x"]
    assert client.sent == [SettingsChange(ai_agent=AiAgent.OPENCODE)]
    assert client.modes == [False]
    assert result.stderr.splitlines()[:3] == [
        "Project: acme",
        "Branch: feature-x (development)",
        "ai_agent: claude → opencode",
    ]
    assert result.stderr.splitlines()[-1].endswith("The settings were changed.")
    assert pairs(result)["AI agent"] == "opencode"


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n", "yep\n", ""], ids=repr)
def test_anything_but_a_yes_sends_nothing_and_exits_1(client: type[StubClient], answer: str):
    result = run(*SET, "ai_agent=opencode", stdin=answer)

    assert result.exit_code == 1
    assert changes(client) == []
    assert result.stdout == ""
    assert result.stderr.endswith("Change these settings of this branch? [y/N]: Nothing was sent.\n")


def test_yes_sends_without_asking(client: type[StubClient]):
    result = run(*SET, "--yes", "ai_agent=opencode")

    assert result.exit_code == 0
    assert changes(client) == ["change feature-x"]
    assert "[y/N]" not in result.stderr


@pytest.mark.parametrize("name", ["stdin_is_terminal", "stderr_is_terminal"])
def test_a_run_nobody_attends_is_refused_before_a_client_is_opened(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, name: str
):
    monkeypatch.setattr(_terminal, name, lambda: False)

    result = run(*SET, "ai_agent=opencode", stdin="y\n")

    assert result.exit_code == 2
    assert client.modes == []
    assert "Stdin or stderr is not a terminal" in click.unstyle(result.stderr)
    assert "--yes" in click.unstyle(result.stderr)


@pytest.mark.parametrize("arguments", [(), ("--yes",)], ids=["asked", "yes"])
def test_a_setting_already_at_its_value_sends_nothing_and_asks_nothing(
    client: type[StubClient], arguments: tuple[str, ...]
):
    result = run(*SET, *arguments, "push_behavior=new_build", "test_tags=")

    assert result.exit_code == 0
    assert changes(client) == []
    assert "[y/N]" not in result.stderr
    assert result.stderr.splitlines()[2:] == [
        "push_behavior is already new_build.",
        "test_tags is already none.",
        "Nothing was sent: every setting already has that value.",
    ]
    assert pairs(result)["On new commit"] == "new_build"


def test_a_setting_odoo_sh_moves_along_is_said_and_the_change_succeeds(client: type[StubClient]):
    result = run(*SET, "--yes", "module_install=all")

    assert result.exit_code == 0
    assert result.stderr.splitlines()[-2:] == [
        "The settings were changed.",
        "tests: modules → off, also changed by Odoo.sh.",
    ]
    assert (pairs(result)["Install"], pairs(result)["Tests"]) == ("all", "off")


def test_already_is_what_the_library_leaves_out_and_not_how_a_value_prints(client: type[StubClient]):
    result = run(*SET, "--yes", "test_tags=none", "tests=tags")

    assert result.exit_code == 0
    assert result.stderr.splitlines()[2:4] == ["tests: modules → tags", 'test_tags: none → "none"']
    assert client.sent == [SettingsChange(tests=BuildTests.TAGS, test_tags="none")]


def test_a_mix_says_what_is_already_set_and_sends_the_rest(client: type[StubClient]):
    result = run(
        *SET, "push_behavior=new_build", "demo_data=no", "modules=sale, purchase", "module_install=listed", stdin="y\n"
    )

    assert result.exit_code == 0
    assert client.sent == [
        SettingsChange(module_install=ModuleInstall.LISTED, modules=("sale", "purchase"), demo_data=False)
    ]
    assert result.stderr.splitlines()[2:6] == [
        "push_behavior is already new_build.",
        "module_install: repository → listed",
        "modules: none → sale, purchase",
        "demo_data: yes → no",
    ]


@pytest.mark.parametrize(
    ("given", "said"),
    [
        (("ai_agent",), "is not NAME=VALUE"),
        (("machine=ubuntu-26.04",), "push_behavior, project_defaults"),
        (("ai_agent=claude", "ai_agent=opencode"), "given twice"),
        (("ai_agent=codex",), "claude, opencode"),
        (("push_behavior=new",), "nothing, new_build, update"),
        (("demo_data=maybe",), "yes, no"),
        (("modules=sale;purchase",), "not a module name"),
        (("test_tags=/sale\x1b",), "Test tags hold only"),
        (("test_tags=/sale $(id)",), "Test tags hold only"),
    ],
)
def test_a_value_that_cannot_be_sent_is_a_usage_error_before_any_client(
    client: type[StubClient], given: tuple[str, ...], said: str
):
    result = run(*SET, "--yes", *given)

    assert result.exit_code == 2
    assert client.modes == []
    assert said in " ".join(click.unstyle(result.stderr).split())


@pytest.mark.parametrize("text", ["yes", "YES", "true", "no", "False"])
def test_a_yes_or_no_takes_its_usual_words(client: type[StubClient], text: str):
    client.found = replace(OWN, demo_data=text.lower() not in {"yes", "true"})
    result = run(*SET, "--yes", f"demo_data={text}")

    assert result.exit_code == 0
    assert client.sent == [SettingsChange(demo_data=text.lower() in {"yes", "true"})]


def test_the_project_defaults_left_on_are_a_usage_error_before_the_change(client: type[StubClient]):
    client.found = replace(OWN, project_defaults=True)
    result = run(*SET, "--yes", "ai_agent=opencode")

    assert result.exit_code == 2
    assert changes(client) == []
    assert "project_defaults" in result.stderr


def test_another_value_error_once_sent_is_no_usage_error(client: type[StubClient]):
    client.lost = ValueError("Raised after the change was sent.")
    result = run(*SET, "--yes", "ai_agent=opencode")

    assert result.exit_code == 1
    assert changes(client) == ["change feature-x"]
    assert "Unexpected error (ValueError)" in result.stderr


def test_a_production_branch_exits_9_before_the_question(client: type[StubClient]):
    result = run(
        "branches", "settings", "set", "--project", "acme", "--branch", "main", "push_behavior=update", stdin="y\n"
    )

    assert result.exit_code == 9
    assert changes(client) == []
    assert "[y/N]" not in result.stderr
    assert "production" in result.stderr


def test_an_unknown_outcome_exits_10_and_says_where_to_look(client: type[StubClient]):
    client.lost = LOST
    result = run(*SET, "--yes", "ai_agent=opencode")

    assert result.exit_code == 10
    assert changes(client) == ["change feature-x"]
    assert result.stdout == ""
    assert result.stderr.splitlines()[-2:] == [
        str(LOST),
        (
            "`osh branches settings show` shows whether the settings were changed. Sending the same change again "
            "does no harm."
        ),
    ]


def test_an_escape_sequence_in_the_branch_name_is_not_emitted(client: type[StubClient]):
    client.on_branch = replace(FEATURE, name=f"feature{ESCAPE}")

    result = run(
        "branches",
        "settings",
        "set",
        "--project",
        "acme",
        "--branch",
        f"feature{ESCAPE}",
        "ai_agent=opencode",
        stdin="n\n",
    )

    assert result.exit_code == 1
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", result.stderr)
    assert "Branch: feature[2J]0;owned (development)" in result.stderr


def test_json_is_the_settings_after(client: type[StubClient]):
    result = run("--format", "json", *SET, "--yes", "ai_agent=opencode")
    shown = json.loads(result.stdout)
    assert list(shown) == [field.name for field in fields(BranchSettings)]
    assert shown["ai_agent"] == "opencode"


def test_help_opens_no_client_and_its_first_line_says_it_changes_state(client: type[StubClient]):
    result = run("branches", "settings", "set", "--help")

    assert result.exit_code == 0
    lines = [line.strip() for line in click.unstyle(result.output).splitlines() if line.strip()]
    assert lines[1].startswith("Change state on Odoo.sh:")
    assert client.modes == []
