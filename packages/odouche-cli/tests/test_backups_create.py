import json
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Backup, BackupKind, BackupRequest, Branch, Build, BuildStatus, Commit, Stage
from odouche_cli import _terminal
from odouche_cli.app import app


NOW = datetime(2026, 10, 14, 13, 4, 43, tzinfo=UTC)
ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
STAGING = Branch(id=2, name="staging", stage=Stage.STAGING, stage_name="staging")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
CREATE = ("backups", "create")
ESCAPE = "\x1b[2J\x1b]0;owned\x07"
ON_STAGING = ("--project", "acme", "--branch", "staging")

LATEST = Build(
    id=124,
    name="acme-staging-124",
    branch_id=STAGING.id,
    branch_name=STAGING.name,
    commit=Commit(
        hash="4f1c2a9".ljust(40, "a"),
        message="Add the report",
        author="Ann Example",
        timestamp=NOW - timedelta(hours=1),
        url="https://github.com/acme/odoo/commit/4f1c2a9",
    ),
    status=BuildStatus.DONE,
    status_name="done",
    result=None,
    result_name=None,
    status_info="done",
    started_at=NOW - timedelta(hours=1),
    url="https://acme-staging-124.dev.odoo.com",
)
TAKEN = Backup(
    kind=BackupKind.MANUAL,
    kind_name="manual",
    taken_at=datetime(2026, 10, 14, 13, 5, 41, tzinfo=UTC),
    build_name=LATEST.name,
    branch_name=STAGING.name,
    commit_hash=LATEST.commit.hash,
    downloadable=True,
    size=None,
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: takes backups as the library does, and records the calls."""

    on_branch: Branch = STAGING
    latest: Build | None = LATEST
    looks: tuple[Backup | None, ...] = (None, None, TAKEN)
    """What a wait for the backup yields."""
    lost: odouche.OdoucheError | None = None
    """What the creation raises once it is sent."""
    late: odouche.OdoucheError | None = None
    """What the wait raises once it has yielded `looks`."""
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
        return [self.on_branch]

    def latest_build(self, branch: Branch) -> Build | None:
        self.calls.append(f"latest {branch.name}")
        return self.latest

    # The library's own, which asks nothing.
    check_backup = odouche.Client.check_backup

    def create_backup(self, project: str, branch: Branch, *, comment: str = "") -> BackupRequest:
        self.calls.append(f"create {project} {branch.name} {comment!r}")

        if self.lost is not None:
            raise self.lost

        return BackupRequest(build=LATEST, previous=None)

    def wait_for_backup(self, project: str, request: BackupRequest, *, timeout: float) -> Iterator[Backup | None]:
        self.calls.append(f"wait {project} {request.build.id} {timeout:g}")

        yield from self.looks

        if self.late is not None:
            raise self.late


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


def sent(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith("create")]


def test_a_yes_sends_one_backup_on_a_client_that_writes(client: type[StubClient]):
    result = run(*CREATE, *ON_STAGING, stdin="y\n")

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "latest staging", "create acme staging ''"]
    assert client.modes == [False]
    assert result.stdout == ""
    # The line break of the answer is the terminal's to echo.
    assert result.stderr.endswith(
        "[y/N]: A backup of build 124 was asked for.\n"
        "Odoo.sh lists it about a minute later: `osh backups list --branch staging`.\n"
    )


def test_what_is_backed_up_and_for_how_long_is_said_before_the_question(client: type[StubClient]):
    result = run(*CREATE, *ON_STAGING, stdin="n\n")

    assert result.stderr.splitlines()[:5] == [
        "Project: acme",
        "Branch: staging (staging)",
        "Latest build: 124, acme-staging-124",
        "Odoo.sh keeps a manual backup for 3 days.",
        "Take a backup of this build? [y/N]: Nothing was sent.",
    ]


@pytest.mark.parametrize("answer", ["n\n", "\n", "yep\n", ""], ids=repr)
def test_anything_but_a_yes_sends_nothing_and_exits_1(client: type[StubClient], answer: str):
    result = run(*CREATE, *ON_STAGING, stdin=answer)

    assert result.exit_code == 1
    assert sent(client) == []
    assert result.stderr.endswith("Nothing was sent.\n")


def test_yes_sends_without_asking(client: type[StubClient]):
    result = run(*CREATE, *ON_STAGING, "--yes")

    assert result.exit_code == 0
    assert sent(client) == ["create acme staging ''"]
    assert "[y/N]" not in result.stderr


def test_the_comment_is_sent(client: type[StubClient]):
    run(*CREATE, *ON_STAGING, "--yes", "--comment", "before the upgrade")

    assert sent(client) == ["create acme staging 'before the upgrade'"]


@pytest.mark.parametrize("closed", ["stdin_is_terminal", "stderr_is_terminal"])
def test_a_run_nobody_attends_is_refused_before_a_client_is_opened(
    client: type[StubClient], monkeypatch: pytest.MonkeyPatch, closed: str
):
    monkeypatch.setattr(_terminal, closed, lambda: False)

    refused = run(*CREATE, *ON_STAGING, stdin="y\n")
    accepted = run(*CREATE, *ON_STAGING, "-y")

    assert refused.exit_code == 2
    assert "--yes" in click.unstyle(refused.stderr)
    assert accepted.exit_code == 0
    assert client.modes == [False]


@pytest.mark.parametrize("arguments", [(), ("--yes",)], ids=["asked", "yes"])
def test_a_development_branch_is_refused_before_anything_is_sent(client: type[StubClient], arguments: tuple[str, ...]):
    client.on_branch = FEATURE
    result = run(*CREATE, "--project", "acme", "--branch", "feature-x", *arguments, stdin="y\n")

    assert result.exit_code == 9
    assert client.calls == ["branches acme"]
    assert (
        result.stderr == "A branch in the development stage is not backed up: only a staging or a production one is.\n"
    )


def test_a_branch_with_no_build_exits_4_before_the_question(client: type[StubClient]):
    client.latest = None
    result = run(*CREATE, *ON_STAGING, stdin="y\n")

    assert result.exit_code == 4
    assert sent(client) == []
    assert "[y/N]" not in result.stderr
    assert result.stderr == "Branch staging of acme has no build to back up.\n"


def test_an_escape_sequence_in_a_name_is_not_emitted(client: type[StubClient]):
    client.latest = replace(LATEST, name=f"acme{ESCAPE}-staging\x9b31m")
    result = run(*CREATE, *ON_STAGING, stdin="n\n")

    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", result.output)
    assert "Latest build: 124, acme[2J]0;owned-staging31m" in result.stderr


def test_a_production_branch_is_backed_up(client: type[StubClient]):
    client.on_branch = replace(STAGING, name="main", stage=Stage.PRODUCTION, stage_name="production")
    result = run(*CREATE, "--project", "acme", "--branch", "main", "--yes")

    assert result.exit_code == 0
    assert sent(client) == ["create acme main ''"]


def test_wait_shows_the_backup_once_it_is_listed(client: type[StubClient]):
    result = run(*CREATE, *ON_STAGING, "--yes", "--wait")

    assert result.exit_code == 0
    assert client.calls[-1] == "wait acme 124 600"
    shown = dict(line.split(maxsplit=1) for line in result.stdout.splitlines() if len(line.split()) > 1)
    assert shown["Kind"] == "manual"
    assert shown["Build"] == "acme-staging-124"
    assert result.stderr.splitlines()[-1] == "Waiting for Odoo.sh to finish it."


def test_wait_as_json_is_the_backup(client: type[StubClient]):
    result = run("--format", "json", *CREATE, *ON_STAGING, "--yes", "--wait", "--timeout", "90")

    assert json.loads(result.stdout)["taken_at"] == "2026-10-14T13:05:41+00:00"
    assert client.calls[-1] == "wait acme 124 90"


def test_a_wait_that_times_out_exits_8_and_says_where_to_look(client: type[StubClient]):
    client.looks = (None,)
    client.late = odouche.StreamTimeoutError("The backup of build 124 was not finished at the timeout.")
    result = run(*CREATE, *ON_STAGING, "--yes", "--wait")

    assert result.exit_code == 8
    assert result.stdout == ""
    assert result.stderr.splitlines()[-2:] == [
        "The backup may still be coming. Look with `osh backups list --branch staging`.",
        "The backup of build 124 was not finished at the timeout.",
    ]


def test_timeout_without_wait_is_a_usage_error(client: type[StubClient]):
    result = run(*CREATE, *ON_STAGING, "--yes", "--timeout", "60")

    assert result.exit_code == 2
    assert "--wait" in click.unstyle(result.stderr)
    assert client.modes == []


def test_an_unknown_outcome_exits_10_and_names_the_backups_to_check(client: type[StubClient]):
    client.lost = odouche.OutcomeUnknownError(
        "Odoo.sh did not confirm the backup, which may have been done. Look before trying again.", operation="backup"
    )

    result = run(*CREATE, *ON_STAGING, "--yes", "--wait")

    assert result.exit_code == 10
    assert result.stderr.splitlines()[-1] == "`osh backups list` shows whether the backup was taken."
    assert not any(call.startswith("wait") for call in client.calls)


def test_the_help_says_it_changes_state(client: type[StubClient]):
    result = run("backups", "--help")
    listed = [line for line in click.unstyle(result.output).splitlines() if " create " in line]
    assert len(listed) == 1
    assert "Change state on Odoo.sh" in listed[0]
    assert client.modes == []
