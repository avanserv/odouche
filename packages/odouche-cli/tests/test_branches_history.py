import json
import re
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import (
    Branch,
    BuildResult,
    BuildStatus,
    PushedCommit,
    Stage,
    TrackedBuild,
    Tracking,
    TrackingKind,
)
from odouche_cli import _time
from odouche_cli.app import app


NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
FIRST = "a" * 40
SECOND = "b" * 40


def commit(hash_: str, message: str) -> PushedCommit:
    return PushedCommit(hash=hash_, message=message, url=f"https://github.com/acme/odoo/commit/{hash_}")


def tracking(
    id_: int,
    kind: TrackingKind,
    age: timedelta,
    *,
    build: TrackedBuild | None = None,
    commits: tuple[PushedCommit, ...] = (),
    pusher: str | None = "octo-dev",
    source: Stage | None = None,
    target: Stage | None = None,
) -> Tracking:
    return Tracking(
        id=id_,
        kind=kind,
        kind_name=kind.value,
        created_at=NOW - age,
        build=build,
        commits=commits,
        pusher=pusher,
        source_stage=source,
        target_stage=target,
    )


REBUILT = tracking(
    5,
    TrackingKind.REBUILD,
    timedelta(minutes=3),
    build=TrackedBuild(103, BuildStatus.PROGRESS, "progress", None, None),
    commits=(commit(FIRST, "Add the report\n\nWith its totals."),),
)
PUSHED = tracking(
    4,
    TrackingKind.PUSH,
    timedelta(hours=5),
    build=TrackedBuild(102, BuildStatus.DROPPED, "dropped", BuildResult.FAILED, "failed"),
    commits=(commit(FIRST, "Add the report\n\nWith its totals."), commit(SECOND, "Fix the tax")),
)
MOVED = tracking(3, TrackingKind.STAGE, timedelta(days=1), pusher=None, source=Stage.DEVELOPMENT, target=Stage.STAGING)
CREATED = tracking(2, TrackingKind.STAGE, timedelta(days=2), pusher=None, target=Stage.DEVELOPMENT)
HISTORY = (REBUILT, PUSHED, MOVED, CREATED)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with a branch and its history, and records the calls."""

    found: tuple[Tracking, ...] = HISTORY
    modes: list[bool]
    calls: list[str]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        self.calls.append("projects")
        return []

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[Branch]:
        self.calls.append(f"branches {project}")
        return [FEATURE]

    def history(self, branch: Branch, *, limit: int = 20, timeout: float) -> list[Tracking]:
        assert timeout > 0
        self.calls.append(f"history {branch.name} {limit}")

        return list(self.found[:limit])


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    monkeypatch.setattr(_time, "_now", lambda: NOW)

    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, ["branches", "history", "--project", "acme", "--branch", "feature-x", *args])


def rows(result: Result) -> list[list[str]]:
    """Split each line into its cells, which two spaces or more separate."""
    return [re.split(r"\s{2,}", line.strip()) for line in result.stdout.splitlines()]


def test_each_event_is_listed_newest_first_with_its_date_and_kind(client: type[StubClient]):
    result = run()

    assert result.exit_code == 0
    assert client.calls == ["branches acme", "history feature-x 10"]
    assert client.modes == [True]
    assert rows(result) == [
        ["When", "Kind", "Build", "Status", "Result", "By", "Change"],
        ["3 minutes ago", "rebuild", "103", "progress", "octo-dev", "aaaaaaa Add the report"],
        ["5 hours ago", "push", "102", "dropped", "failed", "octo-dev", "aaaaaaa Add the report"],
        ["bbbbbbb Fix the tax"],
        ["1 day ago", "stage", "development → staging"],
        ["2 days ago", "stage", "created in development"],
    ]


def test_the_limit_is_passed_to_the_library(client: type[StubClient]):
    result = run("--limit", "1")

    assert result.exit_code == 0
    assert client.calls[-1] == "history feature-x 1"
    assert len(rows(result)) == 2


@pytest.mark.parametrize("limit", ["0", "201"])
def test_a_limit_out_of_range_is_a_usage_error(client: type[StubClient], limit: str):
    result = run("--limit", limit)

    assert result.exit_code == 2
    assert client.calls == []


def test_commits_prints_each_in_full_under_its_event():
    result = run("--commits")

    assert result.exit_code == 0
    assert result.stdout.splitlines()[:16] == [
        "rebuild, 3 minutes ago, by octo-dev, build 103 progress",
        "",
        f"    commit {FIRST}",
        f"    https://github.com/acme/odoo/commit/{FIRST}",
        "",
        "        Add the report",
        "",
        "        With its totals.",
        "",
        "push, 5 hours ago, by octo-dev, build 102 dropped failed",
        "",
        f"    commit {FIRST}",
        f"    https://github.com/acme/odoo/commit/{FIRST}",
        "",
        "        Add the report",
        "",
    ]
    assert result.stdout.splitlines()[-1] == "stage, 2 days ago, created in development"


@pytest.mark.usefixtures("terminal")
def test_a_commit_message_is_printed_without_its_control_characters(client: type[StubClient]):
    escaped = PushedCommit(hash=FIRST, message="Fix\x1b[2J it", url="https://github.com/\x1b[2J")
    client.found = (tracking(1, TrackingKind.PUSH, timedelta(hours=1), commits=(escaped,), pusher="octo\x1b[2J"),)
    table = run()
    full = run("--commits")

    assert "Fix" in table.stdout
    assert "octo" in full.stdout
    assert "\x1b[2J" not in table.stdout
    assert "\x1b[2J" not in full.stdout


def test_as_json_is_the_whole_model_with_iso_times():
    result = runner.invoke(
        app, ["--format", "json", "branches", "history", "--project", "acme", "--branch", "feature-x", "--commits"]
    )

    events = json.loads(result.stdout)
    assert [event["id"] for event in events] == [5, 4, 3, 2]
    assert events[1]["created_at"] == "2026-03-10T07:00:00+00:00"
    assert events[1]["build"] == {
        "id": 102,
        "status": "dropped",
        "status_name": "dropped",
        "result": "failed",
        "result_name": "failed",
    }
    assert [found["hash"] for found in events[1]["commits"]] == [FIRST, SECOND]
    assert (events[2]["source_stage"], events[2]["target_stage"]) == ("development", "staging")


def test_an_unknown_kind_shows_what_odoo_sh_calls_it(client: type[StubClient]):
    client.found = (Tracking(**{**vars_of(PUSHED), "kind": TrackingKind.UNKNOWN, "kind_name": "merge"}),)

    assert rows(run())[1][1] == "merge"


def vars_of(event: Tracking) -> dict[str, object]:
    return {name: getattr(event, name) for name in Tracking.__dataclass_fields__}


@pytest.mark.parametrize("flags", [(), ("--commits",)])
def test_no_history_is_a_line_on_stderr(client: type[StubClient], flags: tuple[str, ...]):
    client.found = ()
    result = run(*flags)

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == "No history.\n"


def test_help_names_the_example():
    result = runner.invoke(app, ["branches", "history", "--help"])

    assert result.exit_code == 0
    assert "Example: osh branches history" in click.unstyle(result.output)
