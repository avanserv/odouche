import json
import re
from dataclasses import replace
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Branch, Stage
from odouche_cli import _terminal
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
MAIN = Branch(id=1, name="main", stage=Stage.PRODUCTION, stage_name="production")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
TRIAL = Branch(id=7, name="trial", stage=Stage.STAGING, stage_name="staging")
ESCAPE = "\x1b[2J\x1b]0;owned\x07"
MOVE = ("branches", "move", "--project", "acme")
LOST = odouche.OutcomeUnknownError(
    "The move of branch 4 to staging was sent, and the branch could not be read back. Look before trying again.",
    operation="branch stage move",
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: moves a branch as the library does, and records the calls."""

    listed: tuple[Branch, ...] = (MAIN, FEATURE, TRIAL)
    lost: Exception | None = None
    modes: list[bool]
    calls: list[str]

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
        return list(self.listed)

    # The library's own, which asks nothing.
    check_move = odouche.Client.check_move

    def move_branch(self, branch: Branch, to: Stage) -> Branch:
        self.calls.append(f"move {branch.name} {to.value}")
        if self.lost is not None:
            raise self.lost
        return replace(branch, stage=to, stage_name="dev" if to is Stage.DEVELOPMENT else to.value)


@pytest.fixture(autouse=True)
def read_only_clients() -> None:
    """Replace the shared check: the command of this file is one that writes."""


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)
    return Client


def run(*args: str, stdin: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=stdin)


def moves(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith("move")]


def test_a_yes_moves_a_development_branch_to_staging_once_and_prints_it(client: type[StubClient]):
    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "move feature-x staging"]
    assert client.modes == [False]
    assert result.stderr.splitlines() == [
        "Project: acme",
        "Branch: feature-x (development)",
        "Move: development → staging",
        (
            "Odoo.sh starts a new build of the branch on a copy of production's data, with outgoing mails caught and "
            "scheduled actions turned off, and builds its next commits the same way."
        ),
        (
            "Move this branch to staging? [y/N]: Branch feature-x is now in staging. Follow its new build with "
            "`osh builds watch --branch feature-x`."
        ),
    ]
    assert re.split(r"\s{2,}", result.stdout.splitlines()[1].strip()) == ["Stage", "staging"]


def test_a_yes_moves_a_staging_branch_to_development_and_says_what_is_dropped(client: type[StubClient]):
    result = run(*MOVE, "--branch", "trial", "--to", "development", stdin="yes\n")

    assert result.exit_code == 0
    assert moves(client) == ["move trial development"]
    assert result.stderr.splitlines()[2:] == [
        "Move: staging → development",
        (
            "Odoo.sh drops the branch's staging builds, which are not backed up and are lost for good. Its next "
            "builds start from a fresh database with demonstration data."
        ),
        "Move this branch to development? [y/N]: Branch trial is now in development.",
    ]


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n", "yep\n", ""], ids=repr)
def test_anything_but_a_yes_sends_nothing_and_exits_1(client: type[StubClient], answer: str):
    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", stdin=answer)

    assert result.exit_code == 1
    assert moves(client) == []
    assert result.stdout == ""
    assert result.stderr.endswith("Move this branch to staging? [y/N]: Nothing was sent.\n")


def test_yes_sends_without_asking(client: type[StubClient]):
    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", "--yes")

    assert result.exit_code == 0
    assert moves(client) == ["move feature-x staging"]
    assert "[y/N]" not in result.stderr


def test_the_branch_defaults_to_the_checkout(client: type[StubClient], checkout):
    checkout("feature-x")

    result = run(*MOVE, "--to", "staging", "--yes")

    assert result.exit_code == 0
    assert moves(client) == ["move feature-x staging"]


@pytest.mark.parametrize("name", ["stdin_is_terminal", "stderr_is_terminal"])
def test_a_run_nobody_attends_is_refused_before_a_client_is_opened(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, name: str
):
    monkeypatch.setattr(_terminal, name, lambda: False)

    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", stdin="y\n")

    assert result.exit_code == 2
    assert client.modes == []
    assert "Stdin or stderr is not a terminal" in click.unstyle(result.stderr)


@pytest.mark.parametrize("to", ["production", "dev", "unknown", ""])
def test_a_target_other_than_staging_or_development_is_a_usage_error_before_any_client(
    client: type[StubClient], to: str
):
    result = run(*MOVE, "--branch", "feature-x", "--to", to, "--yes")

    assert result.exit_code == 2
    assert client.modes == []
    assert "staging" in click.unstyle(result.stderr)


def test_a_missing_target_is_a_usage_error(client: type[StubClient]):
    result = run(*MOVE, "--branch", "feature-x", "--yes")

    assert result.exit_code == 2
    assert client.modes == []


@pytest.mark.parametrize(
    ("branch", "to", "said"),
    [
        ("main", "staging", "production stage is not moved"),
        ("main", "development", "production stage is not moved"),
        ("feature-x", "development", "Branch 4 is already in development."),
        ("trial", "staging", "Branch 7 is already in staging."),
    ],
)
def test_a_move_the_library_refuses_exits_9_before_the_question(
    client: type[StubClient], branch: str, to: str, said: str
):
    result = run(*MOVE, "--branch", branch, "--to", to, stdin="y\n")

    assert result.exit_code == 9
    assert moves(client) == []
    assert "[y/N]" not in result.stderr
    assert said in result.stderr


def test_an_unknown_outcome_exits_10_and_says_where_to_look(client: type[StubClient]):
    client.lost = LOST

    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", "--yes")

    assert result.exit_code == 10
    assert moves(client) == ["move feature-x staging"]
    assert result.stdout == ""
    assert result.stderr.splitlines()[-2:] == [
        str(LOST),
        "`osh branches list` shows the branch's stage. Running the move again is refused once the branch is there.",
    ]


def test_a_refusal_after_the_question_exits_9_and_says_nothing_was_moved(client: type[StubClient]):
    # The stage read again just before the move is not the one listed.
    client.lost = odouche.StageRefusedError(
        "A branch in the production stage is not moved: changing the production branch changes what customers run, "
        "and is done in the Odoo.sh page.",
        operation="branch stage move",
    )

    result = run(*MOVE, "--branch", "feature-x", "--to", "staging", stdin="y\n")

    assert result.exit_code == 9
    assert moves(client) == ["move feature-x staging"]
    assert result.stdout == ""
    assert "[y/N]" in result.stderr
    assert "is now in" not in result.stderr
    assert "production stage is not moved" in result.stderr


def test_an_escape_sequence_in_the_branch_name_is_not_emitted(client: type[StubClient]):
    client.listed = (MAIN, replace(FEATURE, name=f"feature{ESCAPE}"))

    result = run(*MOVE, "--branch", f"feature{ESCAPE}", "--to", "staging", stdin="y\n")

    assert result.exit_code == 0
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", result.stderr)
    assert "Branch: feature[2J]0;owned (development)" in result.stderr
    assert "Branch feature[2J]0;owned is now in staging." in result.stderr


def test_json_is_the_branch(client: type[StubClient]):
    result = run("--format", "json", *MOVE, "--branch", "feature-x", "--to", "staging", "--yes")

    assert json.loads(result.stdout) == {"id": 4, "name": "feature-x", "stage": "staging", "stage_name": "staging"}


def test_help_opens_no_client_and_its_first_line_says_it_changes_state(client: type[StubClient]):
    result = run("branches", "move", "--help")

    assert result.exit_code == 0
    lines = [line.strip() for line in click.unstyle(result.output).splitlines() if line.strip()]
    assert lines[1].startswith("Change state on Odoo.sh:")
    assert "production" in click.unstyle(result.output)
    assert client.modes == []
