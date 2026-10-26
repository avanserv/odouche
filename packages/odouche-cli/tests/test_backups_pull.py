import ipaddress
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Backup, BackupKind, Branch, Build, BuildStatus, Commit, SshTarget, Stage
from odouche_cli import _terminal, backups, ssh
from odouche_cli.app import app


ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
MAIN = Branch(id=1, name="main", stage=Stage.PRODUCTION, stage_name="production")
STAGING = Branch(id=2, name="staging", stage=Stage.STAGING, stage_name="staging")
BUILD = Build(
    id=101,
    name="acme-main-101",
    branch_id=MAIN.id,
    branch_name=MAIN.name,
    commit=Commit(hash="a" * 40, message="Start", author="Ann Example", timestamp=None, url=""),  # pyright: ignore[reportArgumentType]
    status=BuildStatus.DONE,
    status_name="done",
    result=None,
    result_name=None,
    status_info=None,
    started_at=None,
    url="https://acme.odoo.com",
)
HOST = "acme.odoo.com"
DAILY = Backup(
    kind=BackupKind.DAILY,
    kind_name="daily",
    taken_at=datetime(2026, 10, 14, 3, 12, 5, tzinfo=UTC),
    # Not the latest build: the file is named after the build the backup was taken from.
    build_name="acme-main-99",
    branch_name=MAIN.name,
    commit_hash="b" * 40,
    downloadable=True,
    size=None,
)
REMOTE = replace(DAILY, kind=BackupKind.REMOTE, kind_name="remote", downloadable=False, size=7)
MANUAL = replace(
    DAILY,
    kind=BackupKind.MANUAL,
    kind_name="manual",
    taken_at=datetime(2026, 10, 14, 12, 48, 50, tzinfo=UTC),
    build_name="acme-staging-124",
    branch_name=STAGING.name,
)
SSH = "/usr/bin/ssh"
RSYNC = "/usr/bin/rsync"
SCP = "/usr/bin/scp"
SESSION = "s3ss10n-v4lu3"
REFUSED = f"ssh: connect to host {HOST} port 22: Connection refused\n"

runner = CliRunner()


class StubClient:
    """Stands in for `odouche.Client`: a project with a production and a staging branch, and its backups."""

    branches_: tuple[Branch, ...] = (STAGING, MAIN)
    listed: tuple[Backup, ...] = (REMOTE, DAILY, MANUAL)
    modes: list[bool]
    events: list[object]

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.events.append("closed")

    def projects(self) -> list[odouche.Project]:
        return [ACME]

    # The library's own, over `branches`.
    branch = odouche.Client.branch

    def branches(self, project: str) -> list[Branch]:
        assert project == ACME.name
        return list(self.branches_)

    def backups(self, project: str) -> list[Backup]:
        assert project == ACME.name
        return list(self.listed)

    def latest_build(self, branch: Branch) -> Build | None:
        assert branch == MAIN
        return BUILD

    def ssh_target(self, build: Build) -> SshTarget:
        assert build == BUILD
        return SshTarget(user=str(build.id), host=HOST)

    def allow_ip(self, branch: Branch) -> ipaddress.IPv4Address:
        assert branch == MAIN
        assert self.modes[-1] is False
        self.events.append("allowed")
        return ipaddress.IPv4Address("203.0.113.7")


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    made = type("Made", (StubClient,), {"modes": [], "events": []})
    monkeypatch.setattr(odouche, "Client", made)
    return made


@pytest.fixture(autouse=True)
def read_only_clients(unreached: object, client: type[StubClient]) -> Iterator[None]:
    """Replace the shared check: a client that writes is built only for a build that did not let this machine in."""
    yield
    assert all(client.modes) or "allowed" in client.events, "A client that writes was built and nothing was allowed."


@pytest.fixture(autouse=True)
def tries(monkeypatch: pytest.MonkeyPatch, client: type[StubClient]) -> list[str | None]:
    """What each try of `ssh` prints when it fails, or `None` when it gets in. The last stands for every try after it."""
    outcomes: list[str | None] = [None]
    now = [0.0]

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert command == [SSH, *ssh._TRY, "-l", "101", HOST, "true"]
        client.events.append(("tried", os.environ.get(odouche.SESSION_ENV)))
        said = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        return subprocess.CompletedProcess(command, 255 if said is not None else 0, stderr=said or "")

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(ssh, "_run", run)
    monkeypatch.setattr(ssh, "_monotonic", lambda: now[0])
    monkeypatch.setattr(ssh, "_sleep", sleep)
    return outcomes


@pytest.fixture(autouse=True)
def executed(monkeypatch: pytest.MonkeyPatch, client: type[StubClient]) -> list[object]:
    """Stand in for the umask and the exec, and return the client's events, where each exec keeps the session it saw."""

    def record(program: str, command: list[str]) -> None:
        client.events.append((program, command, os.environ.get(odouche.SESSION_ENV)))

    def umask(mask: int) -> int:
        client.events.append(("umask", mask))
        return 0o022

    monkeypatch.setattr(ssh, "_exec", record)
    monkeypatch.setattr(backups, "_umask", umask)
    monkeypatch.setattr(_terminal, "stdout_is_terminal", lambda: False)
    programs = {"ssh": SSH, "rsync": RSYNC, "scp": SCP}
    monkeypatch.setattr(shutil, "which", programs.get)
    return client.events


def unboxed(text: str) -> str:
    """Return a usage error's words on one line: it is boxed and wrapped to the terminal's width."""
    return " ".join(word for word in click.unstyle(text).split() if word not in {"│", "╰", "╭"})


def run(*args: str, output: str | None = "daily.sql.gz", input: str | None = None) -> Result:  # noqa: A002
    out = () if output is None else ("--output", output)
    return runner.invoke(app, ["backups", "pull", "--project", "acme", *out, *args], input=input)


def copied(program: str, path: str, output: str = "daily.sql.gz", *flags: str) -> tuple[str, list[str], None]:
    name = Path(program).name
    return (program, [name, *flags, "--", f"101@{HOST}:backup.daily/{path}", str(Path(output).absolute())], None)


def test_the_daily_backup_is_copied_with_rsync_under_a_private_umask(client: type[StubClient], executed: list[object]):
    result = run()

    assert result.exit_code == 0, result.output
    assert client.modes == [True]
    assert executed == [
        "closed",
        ("tried", None),
        ("umask", 0o077),
        copied(RSYNC, "acme-main-99_daily.sql.gz"),
    ]
    assert "It holds customer data" in result.stderr
    assert result.stdout == ""


def test_rsync_shows_its_progress_on_a_terminal(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setattr(_terminal, "stdout_is_terminal", lambda: True)

    result = run()

    assert result.exit_code == 0, result.output
    assert executed[-1] == copied(RSYNC, "acme-main-99_daily.sql.gz", "daily.sql.gz", "--progress")


def test_without_rsync_scp_copies_it(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setattr(shutil, "which", {"ssh": SSH, "scp": SCP}.get)

    result = run()

    assert result.exit_code == 0, result.output
    assert executed[-1] == copied(SCP, "acme-main-99_daily.sql.gz")


@pytest.mark.parametrize("program", [RSYNC, SCP])
def test_no_flag_keeps_the_remote_mode(monkeypatch: pytest.MonkeyPatch, executed: list[object], program: str):
    monkeypatch.setattr(shutil, "which", {"ssh": SSH, Path(program).name: program}.get)
    monkeypatch.setattr(_terminal, "stdout_is_terminal", lambda: True)

    run()

    _, command, _ = executed[-1]  # pyright: ignore[reportGeneralTypeIssues]
    assert not {"-p", "-a", "--perms", "--archive"} & set(command)  # pyright: ignore[reportUnknownArgumentType]


def test_a_manual_backup_of_any_stage_is_copied_from_the_production_build(executed: list[object]):
    result = run("--manual", "2026-10-14 12:48:50")

    assert result.exit_code == 0, result.output
    assert executed[-1] == copied(RSYNC, "2026-10-14_124850-acme-staging-124_manual.sql.gz")


def test_a_path_with_a_colon_is_never_read_as_a_host(executed: list[object]):
    result = run(output="host:file.sql.gz")

    assert result.exit_code == 0, result.output
    _, command, _ = executed[-1]  # pyright: ignore[reportGeneralTypeIssues]
    assert command[-1].startswith("/")  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize("name", ["Acme-main-99", "../../etc", "acme main", "acme;rm", "acme$(id)", ""])
def test_a_build_name_that_is_not_lower_case_letters_digits_and_dashes_executes_nothing(
    client: type[StubClient], executed: list[object], name: str
):
    client.listed = (replace(DAILY, build_name=name),)

    result = run()

    assert result.exit_code == 6
    assert "Unexpected answer from Odoo.sh for backups, at build_name." in unboxed(result.output)
    assert executed == ["closed"]


@pytest.mark.parametrize("branch", ["main", "staging"])
def test_the_branch_is_production_whatever_is_given_or_checked_out(checkout, executed: list[object], branch: str):
    checkout("staging")

    result = run("--branch", "main") if branch == "main" else run()

    assert result.exit_code == 0, result.output
    assert executed[-1] == copied(RSYNC, "acme-main-99_daily.sql.gz")


def test_the_branch_variable_is_not_read(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setenv("OSH_BRANCH", "staging")

    result = run()

    assert result.exit_code == 0, result.output


def test_another_stage_is_refused_before_ssh_is_tried(executed: list[object]):
    result = run("--branch", "staging")

    assert result.exit_code == 2
    assert "Branch staging is staging: the backups are copied from the production build." in unboxed(result.output)
    assert executed == ["closed"]


@pytest.mark.parametrize(
    ("args", "listed", "said"),
    [
        (("--branch", "nope"), (DAILY,), "Project acme has no branch nope."),
        ((), (REMOTE, MANUAL), "Odoo.sh lists no daily backup."),
        (("--manual", "2026-10-14 12:00:00"), (DAILY,), "No manual backup was taken at 2026-10-14 12:00:00 UTC."),
        (("--manual", "2026-10-14 03:12:05"), (DAILY,), "is the daily one: leave --manual out to copy it."),
    ],
)
def test_what_is_not_there_executes_nothing(
    client: type[StubClient], executed: list[object], args: tuple[str, ...], listed: tuple[Backup, ...], said: str
):
    client.listed = listed

    result = run(*args)

    assert result.exit_code == 4
    assert said in result.output
    assert executed == ["closed"]


def test_a_project_with_no_production_branch_executes_nothing(client: type[StubClient], executed: list[object]):
    client.branches_ = (STAGING,)

    result = run()

    assert result.exit_code == 4
    assert "Project acme has no production branch." in result.output
    assert executed == ["closed"]


def test_without_output_nothing_is_asked(client: type[StubClient]):
    result = run(output=None)

    assert result.exit_code == 2
    assert "Give --output PATH" in unboxed(result.output)
    assert client.modes == []


@pytest.mark.parametrize(
    ("output", "said"), [("here.sql.gz", "already exists"), ("nowhere/x.sql.gz", "not a directory")]
)
def test_an_output_that_cannot_be_created_asks_nothing(client: type[StubClient], output: str, said: str):
    Path("here.sql.gz").write_bytes(b"mine")

    result = run(output=output)

    assert result.exit_code == 2
    assert said in unboxed(result.output)
    assert client.modes == []
    assert Path("here.sql.gz").read_bytes() == b"mine"


def test_a_manual_time_that_is_no_time_asks_nothing(client: type[StubClient]):
    result = run("--manual", "yesterday")

    assert result.exit_code == 2
    assert "such as '2026-10-14 12:48:50'." in unboxed(result.output)
    assert client.modes == []


@pytest.mark.parametrize(
    ("found", "said"),
    [
        ({"ssh": SSH}, "No `rsync` or `scp` to hand over to. Run it yourself: scp --"),
        ({"rsync": RSYNC}, "No `ssh` to connect with. Run it yourself: rsync --"),
    ],
)
def test_without_a_program_the_command_to_run_is_shown_and_nothing_is_executed(
    monkeypatch: pytest.MonkeyPatch, executed: list[object], found: dict[str, str], said: str
):
    monkeypatch.setattr(shutil, "which", found.get)

    result = run()

    assert result.exit_code == 14
    assert said in result.output
    assert executed == ["closed"]


def test_on_windows_the_command_to_run_is_shown_and_nothing_is_executed(
    monkeypatch: pytest.MonkeyPatch, executed: list[object]
):
    monkeypatch.setattr(sys, "platform", "win32")

    result = run()

    assert result.exit_code == 14
    assert (
        f"hand over to `rsync` on Windows. Run it yourself: rsync -- 101@{HOST}:backup.daily/acme-main-99_daily.sql.gz"
        in result.output
    )
    assert executed == ["closed"]


def test_the_session_is_left_to_no_program(monkeypatch: pytest.MonkeyPatch, executed: list[object]):
    monkeypatch.setenv(odouche.SESSION_ENV, SESSION)

    result = run()

    assert result.exit_code == 0, result.output
    assert ("tried", None) in executed
    assert executed[-1] == copied(RSYNC, "acme-main-99_daily.sql.gz")
    assert SESSION not in result.output


@pytest.fixture
def blocked(tries: list[str | None], monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The address keeps `ssh` out until a rule is added, asked from a terminal."""
    tries[:] = [REFUSED, None]
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(_terminal, "stderr_is_terminal", lambda: True)
    return tries


@pytest.mark.usefixtures("blocked")
def test_an_address_kept_out_is_allowed_on_the_production_branch_once_agreed(
    client: type[StubClient], executed: list[object]
):
    result = run(input="y\n")

    assert result.exit_code == 0, result.output
    assert client.modes == [True, False]
    assert executed[2:5] == ["allowed", "closed", ("tried", None)]
    assert executed[-1] == copied(RSYNC, "acme-main-99_daily.sql.gz")
    assert "on branch main, for one hour.\nAllow it? [y/N]: " in result.stderr


@pytest.mark.usefixtures("blocked")
def test_a_declined_address_copies_nothing(client: type[StubClient], executed: list[object]):
    result = run(input="n\n")

    assert result.exit_code == 1
    assert client.modes == [True]
    assert executed == ["closed", ("tried", None)]


@pytest.mark.usefixtures("blocked")
def test_yes_allows_without_asking(executed: list[object]):
    result = run("--yes")

    assert result.exit_code == 0, result.output
    assert "Allow it?" not in result.stderr
    assert executed.count("allowed") == 1
