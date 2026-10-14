import json
from datetime import UTC, datetime
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Backup, BackupKind
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
COMMIT = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a09"


def backup(kind: BackupKind, taken_at: datetime, branch: str, size: int | None = None) -> Backup:
    return Backup(
        kind=kind,
        kind_name=kind.value,
        taken_at=taken_at,
        build_name=f"acme-{branch}-1",
        branch_name=branch,
        commit_hash=COMMIT,
        downloadable=kind is not BackupKind.REMOTE,
        size=size,
    )


BACKUPS = (
    backup(BackupKind.MANUAL, datetime(2026, 10, 14, 12, 48, 50, tzinfo=UTC), "staging"),
    backup(BackupKind.DAILY, datetime(2026, 10, 13, 18, 9, 37, tzinfo=UTC), "main"),
    backup(BackupKind.REMOTE, datetime(2026, 10, 13, 18, 9, 37, tzinfo=UTC), "main", 1150662),
)

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: answers with backups, and records the calls."""

    found: tuple[Backup, ...] = BACKUPS
    modes: list[bool]
    """The `read_only` each client was built with."""
    calls: list[str]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def projects(self) -> list[odouche.Project]:
        self.calls.append("projects")
        return [ACME]

    def backups(self, project: str) -> list[Backup]:
        self.calls.append(f"backups {project}")
        return list(self.found)


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []
        calls: list[str] = []

    monkeypatch.setattr(odouche, "Client", Client)
    return Client


def run(*args: str) -> Result:
    return runner.invoke(app, list(args))


def rows(result: Result) -> list[list[str]]:
    return [line.split() for line in result.stdout.splitlines()]


def test_lists_every_branch_with_the_time_in_utc_and_whether_it_downloads(client: type[StubClient]):
    result = run("backups", "list", "--project", "acme")

    assert result.exit_code == 0
    assert client.calls == ["backups acme"]
    assert client.modes == [True]
    assert rows(result) == [
        ["Taken", "(UTC)", "Kind", "Branch", "Build", "Commit", "Size", "Downloadable"],
        ["2026-10-14", "12:48:50", "manual", "staging", "acme-staging-1", "9a8b7c6", "yes"],
        ["2026-10-13", "18:09:37", "daily", "main", "acme-main-1", "9a8b7c6", "yes"],
        ["2026-10-13", "18:09:37", "remote", "main", "acme-main-1", "9a8b7c6", "1.1", "MiB", "no"],
    ]


def test_as_json_is_the_whole_model():
    result = run("--format", "json", "backups", "list", "--project", "acme")

    assert json.loads(result.stdout)[2] == {
        "kind": "remote",
        "kind_name": "remote",
        "taken_at": "2026-10-13T18:09:37+00:00",
        "build_name": "acme-main-1",
        "branch_name": "main",
        "commit_hash": COMMIT,
        "downloadable": False,
        "size": 1150662,
    }


def test_a_branch_keeps_its_backups_only():
    result = run("backups", "list", "--project", "acme", "--branch", "main")

    assert [row[2] for row in rows(result)[1:]] == ["daily", "remote"]


def test_the_branch_is_not_the_checkouts_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OSH_BRANCH", "staging")

    result = run("backups", "list", "--project", "acme")

    assert len(rows(result)) == 4


def test_an_empty_branch_is_a_usage_error(client: type[StubClient]):
    result = run("backups", "list", "--project", "acme", "--branch", "")

    assert result.exit_code == 2
    assert "A branch is not empty." in click.unstyle(result.stderr)
    assert client.calls == []


@pytest.mark.parametrize(
    ("size", "shown"), [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (5 * 1024**4, "5120.0 GiB")]
)
def test_a_size_is_in_binary_units(client: type[StubClient], size: int, shown: str):
    client.found = (backup(BackupKind.REMOTE, datetime(2026, 10, 1, tzinfo=UTC), "main", size),)

    result = run("backups", "list", "--project", "acme")

    assert " ".join(rows(result)[1][-3:-1]) == shown


@pytest.mark.parametrize(("found", "args"), [((), ()), (BACKUPS, ("--branch", "nope"))])
def test_none_is_a_line_on_stderr(client: type[StubClient], found: tuple[Backup, ...], args: tuple[str, ...]):
    client.found = found

    result = run("backups", "list", "--project", "acme", *args)

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "No backups." in result.stderr


def test_none_as_json_is_an_empty_list(client: type[StubClient]):
    client.found = ()

    result = run("--format", "json", "backups", "list", "--project", "acme")

    assert json.loads(result.stdout) == []
