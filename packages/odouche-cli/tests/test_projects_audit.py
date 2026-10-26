import json
import re
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import AuditEntry, AuditKind, Stage
from odouche_cli.app import app


NEWEST = datetime(2026, 10, 23, 20, 21, 27, tzinfo=UTC)


def entry(
    age: timedelta,
    kind: AuditKind = AuditKind.OPEN_SHELL,
    *,
    stage: Stage | None = Stage.PRODUCTION,
    details: str = "",
    kind_name: str = "Open Shell",
    succeeded: bool = True,
) -> AuditEntry:
    return AuditEntry(
        logged_at=NEWEST - age,
        author="octo-dev",
        kind=kind,
        kind_name=kind_name,
        stage=stage,
        details=details,
        succeeded=succeeded,
    )


LOG = (
    entry(
        timedelta(0),
        AuditKind.MANAGE_COLLABORATORS,
        kind_name="Manage collaborators",
        stage=None,
        details="Change access rights of user `jane-doe`",
    ),
    entry(timedelta(days=6, hours=9)),
    entry(timedelta(days=7), AuditKind.ALLOW_IP, stage=None, details="Allow IP `203.0.113.7`"),
    entry(timedelta(days=9), AuditKind.OPEN_WEBMAIL, stage=Stage.STAGING),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: yields an audit log, counting the entries drawn from it, or raises."""

    found: tuple[AuditEntry, ...] = LOG
    error: odouche.OdoucheError | None = None
    modes: list[bool]
    calls: list[str]
    drawn: list[int]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        self.calls.append("projects")
        return []

    def audit_log(self, project: str, *, limit: int = 25, timeout: float) -> Generator[AuditEntry]:
        assert timeout > 0
        self.calls.append(f"audit_log {project} {limit}")

        return self._entries(limit)

    def _entries(self, limit: int) -> Generator[AuditEntry]:
        if self.error is not None:
            raise self.error

        for found in self.found[:limit]:
            self.drawn[0] += 1
            yield found


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []
        drawn: list[int] = [0]

    monkeypatch.setattr(odouche, "Client", Client)

    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, ["projects", "audit", "--project", "acme", *args])


def rows(result: Result) -> list[list[str]]:
    """Split each line into its cells, which two spaces or more separate."""
    return [re.split(r"\s{2,}", line.strip()) for line in result.stdout.splitlines()]


def test_lists_the_entries_newest_first_with_their_date_in_utc(client: type[StubClient]):
    result = run()

    assert result.exit_code == 0
    assert client.calls == ["audit_log acme 20"]
    assert client.modes == [True]
    assert rows(result) == [
        ["Date (UTC)", "By", "Stage", "Action", "Details"],
        [
            "2026-10-23 20:21:27",
            "octo-dev",
            "project",
            "manage_collaborators",
            "Change access rights of user `jane-doe`",
        ],
        ["2026-10-17 11:21:27", "octo-dev", "production", "open_shell"],
        ["2026-10-16 20:21:27", "octo-dev", "project", "allow_ip", "Allow IP `203.0.113.7`"],
        ["2026-10-14 20:21:27", "octo-dev", "staging", "open_webmail"],
    ]


def test_the_limit_is_passed_and_bounds_what_is_printed(client: type[StubClient]):
    client.found = tuple(entry(timedelta(minutes=minutes)) for minutes in range(200))
    result = run("--limit", "10")

    assert result.exit_code == 0
    assert client.calls == ["audit_log acme 10"]
    assert len(rows(result)) == 11
    assert client.drawn == [10]


@pytest.mark.parametrize("limit", ["0", "201", "ten"])
def test_a_limit_out_of_range_is_a_usage_error(client: type[StubClient], limit: str):
    result = run("--limit", limit)

    assert result.exit_code == 2
    assert client.calls == []


def test_since_prints_only_what_is_newer_and_reads_one_entry_past_it(client: type[StubClient]):
    result = run("--since", "2026-10-17")

    assert result.exit_code == 0
    assert [row[0] for row in rows(result)[1:]] == ["2026-10-23 20:21:27", "2026-10-17 11:21:27"]
    assert client.drawn == [3]
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("args", "hint"), [((), "raise --limit, up to 200"), (("--limit", "200"), "give a later --since")]
)
def test_since_cut_by_the_limit_says_so_on_stderr(client: type[StubClient], args: tuple[str, ...], hint: str):
    client.found = tuple(entry(timedelta(minutes=minutes)) for minutes in range(300))
    result = run("--since", "2026-10-01", *args)
    shown = 200 if args else 20
    assert result.exit_code == 0
    assert client.calls == [f"audit_log acme {shown + 1}"]
    assert len(rows(result)) == shown + 1
    assert " ".join(click.unstyle(result.stderr).split()) == (
        f"Showing the newest {shown} entries: older ones since 2026-10-01 00:00:00 UTC were left out. "
        f"To see them, {hint}."
    )


def test_since_that_the_limit_reaches_exactly_says_nothing(client: type[StubClient]):
    result = run("--since", "2026-10-17", "--limit", "2")

    assert result.exit_code == 0
    assert len(rows(result)) == 3
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("since", "printed"),
    [("2026-10-17T11:21:27", 2), ("2026-10-17 11:21:28", 1), ("2026-10-01", 4), ("2026-10-24", 0)],
)
def test_since_takes_a_time_and_includes_its_own_second(client: type[StubClient], since: str, printed: int):
    result = run_json("--since", since)

    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == printed


def run_json(*args: str) -> Result:
    return runner.invoke(app, ["--format", "json", "projects", "audit", "--project", "acme", *args])


@pytest.mark.parametrize("since", ["17/10/2026", "2026-10-17T11", "yesterday"])
def test_a_date_it_cannot_read_is_a_usage_error(client: type[StubClient], since: str):
    result = run("--since", since)

    assert result.exit_code == 2
    assert client.calls == []


def test_as_json_is_the_list_of_entries_with_iso_dates():
    result = run_json()
    read = json.loads(result.stdout)
    assert read[0] == {
        "logged_at": "2026-10-23T20:21:27+00:00",
        "author": "octo-dev",
        "kind": "manage_collaborators",
        "kind_name": "Manage collaborators",
        "stage": None,
        "details": "Change access rights of user `jane-doe`",
        "succeeded": True,
    }
    assert read[3]["stage"] == "staging"


@pytest.mark.parametrize(("args", "stdout", "stderr"), [((), "", "No audit log entries.\n"), (("json",), "[]\n", "")])
def test_no_entry_is_a_line_on_stderr_or_an_empty_list(
    client: type[StubClient], args: tuple[str, ...], stdout: str, stderr: str
):
    client.found = ()
    result = run_json() if args else run()

    assert result.exit_code == 0
    assert (result.stdout, result.stderr) == (stdout, stderr)


def test_an_unknown_action_shows_what_odoo_sh_calls_it_and_a_failure_says_so(client: type[StubClient]):
    client.found = (entry(timedelta(0), AuditKind.UNKNOWN, kind_name="Restore\x1b[2J backup", succeeded=False),)

    assert rows(run())[1][3] == "Restore backup (failed)"


def test_text_others_wrote_is_printed_without_its_control_characters(client: type[StubClient]):
    client.found = (
        entry(timedelta(0), details="Open shell\x1b]8;;https://example.com\x07 using \u202eSSH\nclient\x1b[2J"),
    )

    result = run()

    assert "Open shell using SSH client" in result.stdout

    for control in ("\x1b", "\u202e", "]8;;", "[2J"):
        assert control not in result.stdout


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (odouche.StreamTimeoutError("The audit log of 'acme' was still being read at the timeout."), 8),
        (odouche.PermissionDeniedError("Odoo.sh shows a project's audit log to its admins only."), 5),
    ],
)
def test_an_error_exits_with_its_code_and_message(client: type[StubClient], error: odouche.OdoucheError, code: int):
    client.error = error
    result = run()

    assert result.exit_code == code
    assert str(error) in " ".join(click.unstyle(result.stderr).split())
    assert result.stdout == ""


def test_help_names_the_example():
    result = runner.invoke(app, ["projects", "audit", "--help"])

    assert result.exit_code == 0
    assert "Example: osh projects audit --limit 10" in click.unstyle(result.output)
