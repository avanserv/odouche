import errno
import os
import re
import stat
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

import click
import pytest
from typer.testing import CliRunner, Result

import odouche
from odouche import Backup, BackupFile, BackupKind, BackupRequest, Branch, Build, BuildStatus, Commit, Stage
from odouche_cli import _terminal
from odouche_cli.app import app


NOW = datetime(2026, 10, 14, 13, 4, 43, tzinfo=UTC)
ACME = odouche.Project(id=1, name="acme", repository="acme/odoo", url="https://www.odoo.sh/project/acme")
STAGING = Branch(id=2, name="staging", stage=Stage.STAGING, stage_name="staging")
FEATURE = Branch(id=4, name="feature-x", stage=Stage.DEVELOPMENT, stage_name="dev")
DOWNLOAD = ("backups", "download")
ON_STAGING = ("--project", "acme", "--branch", "staging")
CONTENT = b"PK\x03\x04 a zip"
WORKER = "https://eupd00.odoo.com"

BUILD = Build(
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
OLDER = Backup(
    kind=BackupKind.MANUAL,
    kind_name="manual",
    taken_at=datetime(2026, 10, 14, 9, 0, 0, tzinfo=UTC),
    build_name=BUILD.name,
    branch_name=STAGING.name,
    commit_hash=BUILD.commit.hash,
    downloadable=True,
    size=None,
)
NEWER = replace(OLDER, taken_at=datetime(2026, 10, 14, 12, 48, 50, tzinfo=UTC))
REMOTE = replace(OLDER, kind=BackupKind.REMOTE, kind_name="remote", taken_at=NEWER.taken_at, downloadable=False)
TAKEN = replace(NEWER, taken_at=datetime(2026, 10, 14, 13, 5, 41, tzinfo=UTC))
ELSEWHERE = replace(NEWER, branch_name="19.0", taken_at=datetime(2026, 10, 14, 13, 0, 0, tzinfo=UTC))

runner = CliRunner()


class Cut(odouche.UpstreamUnavailableError):
    pass


def prepared(backup: Backup, *, neutralized: bool, filestore: bool) -> odouche.PreparedDownload:
    return odouche.PreparedDownload(
        backup=backup,
        build=BUILD,
        worker_url=WORKER,
        neutralized=neutralized,
        filestore=filestore,
        link=f"{WORKER}/paas/build/124/download/dump?backup_datetime_utc=x&test_dump=1&filestore=1",
        previous=0,
    )


class StubClient:
    """Stands in for `odouche.Client`: prepares and downloads as the library does, and records the calls."""

    branch: Branch = STAGING
    listed: tuple[Backup, ...] = (ELSEWHERE, REMOTE, NEWER, OLDER)
    content: tuple[bytes, ...] = (CONTENT[:4], CONTENT[4:])
    size: int | None = len(CONTENT)
    cut: bool = False
    """Whether the connection drops after the first chunk."""
    late: odouche.OdoucheError | None = None
    """What the wait for the file raises."""
    held: bool = False
    """Whether Odoo.sh already holds the file."""
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

    def branches(self, project: str) -> list[Branch]:
        self.calls.append(f"branches {project}")
        return [self.branch]

    def backups(self, project: str) -> list[Backup]:
        self.calls.append(f"backups {project}")
        return list(self.listed)

    def latest_build(self, branch: Branch) -> Build | None:
        self.calls.append(f"latest {branch.name}")
        return BUILD

    check_backup = odouche.Client.check_backup

    def create_backup(self, project: str, branch: Branch, *, comment: str = "") -> BackupRequest:
        self.calls.append(f"create {project} {branch.name} {comment!r}")
        return BackupRequest(build=BUILD, previous=None)

    def wait_for_backup(self, project: str, request: BackupRequest, *, timeout: float) -> Iterator[Backup | None]:
        self.calls.append(f"wait backup {project} {request.build.id} {timeout:g}")
        yield None
        yield TAKEN

    def prepare_download(
        self, project: str, backup: Backup, *, neutralized: bool = True, filestore: bool = True
    ) -> odouche.PreparedDownload:
        self.calls.append(f"prepare {project} {backup.taken_at:%H:%M:%S} {neutralized} {filestore}")
        return prepared(backup, neutralized=neutralized, filestore=filestore)

    def find_download(
        self, project: str, backup: Backup, *, neutralized: bool = True, filestore: bool = True
    ) -> odouche.PreparedDownload | None:
        self.calls.append(f"find {project} {backup.taken_at:%H:%M:%S} {neutralized} {filestore}")
        if not self.held:
            return None
        return prepared(backup, neutralized=neutralized, filestore=filestore)

    def wait_for_download(self, project: str, prepared: odouche.PreparedDownload, *, timeout: float) -> Iterator[None]:
        self.calls.append(f"wait file {project} {timeout:g}")
        yield None
        if self.late is not None:
            raise self.late

    @contextmanager
    def download(self, prepared: odouche.PreparedDownload) -> Generator[BackupFile]:
        self.calls.append(f"download {prepared.backup.taken_at:%H:%M:%S}")
        yield BackupFile(size=self.size, chunks=self._chunks())

    def _chunks(self) -> Iterator[bytes]:
        for index, chunk in enumerate(self.content):
            if self.cut and index:
                msg = "Odoo.sh could not be reached (ReadError)."
                raise Cut(msg)
            yield chunk


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


def said(result: Result) -> str:
    """Return stderr as one line, out of the box a usage error is drawn in."""
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", click.unstyle(result.stderr)).split())


def changes(client: type[StubClient]) -> list[str]:
    return [call for call in client.calls if call.startswith(("create", "prepare"))]


def test_writes_the_latest_backup_to_a_file_only_its_owner_reads(client: type[StubClient], tmp_path: Path):
    target = tmp_path / "staging.zip"

    result = run(*DOWNLOAD, *ON_STAGING, "--output", str(target), stdin="y\n")

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == CONTENT
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert client.modes == [False]
    assert client.calls == [
        "branches acme",
        "backups acme",
        "find acme 12:48:50 True True",
        "prepare acme 12:48:50 True True",
        "wait file acme 600",
        "download 12:48:50",
    ]
    assert result.stdout == ""
    for line in (
        "Project: acme",
        "Branch: staging (staging)",
        "Backup: 2026-10-14 12:48:50 UTC, manual, of build acme-staging-124",
        "Database: neutralized, with the filestore",
        f"To: {target}",
        "Prepare the file of this backup? [y/N]",
        "delete it once you are done with it",
    ):
        assert line in result.stderr


def test_the_file_is_private_whatever_the_umask(tmp_path: Path):
    target = tmp_path / "staging.zip"
    previous = os.umask(0)
    try:
        result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")
    finally:
        os.umask(previous)

    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ((), "True True"),
        (("--exact",), "False True"),
        (("--no-filestore",), "True False"),
        (("--exact", "--no-filestore"), "False False"),
    ],
)
def test_asks_for_the_database_and_filestore_chosen(
    client: type[StubClient], tmp_path: Path, flags: tuple[str, ...], expected: str
):
    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes", *flags)

    assert result.exit_code == 0, result.output
    assert changes(client) == [f"prepare acme 12:48:50 {expected}"]


def test_a_backup_is_named_by_its_time(client: type[StubClient], tmp_path: Path):
    result = run(*DOWNLOAD, "2026-10-14 09:00:00", *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes")

    assert result.exit_code == 0, result.output
    assert changes(client) == ["prepare acme 09:00:00 True True"]


def test_a_time_shared_with_a_remote_copy_downloads_the_backup_that_can_be(client: type[StubClient], tmp_path: Path):
    result = run(*DOWNLOAD, "2026-10-14 12:48:50", *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes")

    assert result.exit_code == 0, result.output
    assert changes(client) == ["prepare acme 12:48:50 True True"]


def test_a_remote_backup_is_refused_before_any_change(client: type[StubClient], tmp_path: Path):
    client.listed = (REMOTE,)

    result = run(*DOWNLOAD, "2026-10-14 12:48:50", *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes")

    assert result.exit_code == 4
    assert "is remote: Odoo.sh does not let it be downloaded" in result.stderr
    assert changes(client) == []


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("2026-10-14 10:00:00",), "no backup taken at 2026-10-14 10:00:00 UTC"),
        ((), "no backup that can be downloaded"),
    ],
)
def test_a_backup_that_is_not_there_is_not_found(
    client: type[StubClient], tmp_path: Path, args: tuple[str, ...], message: str
):
    client.listed = (ELSEWHERE,)

    result = run(*DOWNLOAD, *args, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes")

    assert result.exit_code == 4
    assert message in result.stderr
    assert changes(client) == []
    assert not (tmp_path / "f.zip").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "Give --output PATH"),
        (("--link", "-o", "f.zip"), "do not go together"),
        (("-o", "f.zip", "--new", "latest"), "BACKUP and --new do not go together"),
        (("-o", "f.zip", "yesterday"), "A backup is named by its time"),
        (("-o", "missing/f.zip"), "is not a directory"),
    ],
)
def test_a_usage_error_opens_no_client(client: type[StubClient], args: tuple[str, ...], message: str):
    result = run(*DOWNLOAD, *ON_STAGING, "--yes", *args)

    assert result.exit_code == 2
    assert message in said(result)
    assert client.modes == []


def test_an_existing_file_is_never_written_over(client: type[StubClient], tmp_path: Path):
    target = tmp_path / "f.zip"
    target.write_bytes(b"mine")

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code == 2
    assert "already exists" in said(result)
    assert target.read_bytes() == b"mine"
    assert client.modes == []


def test_a_link_in_the_place_of_the_file_is_never_followed(client: type[StubClient], tmp_path: Path):
    target = tmp_path / "f.zip"
    target.symlink_to(tmp_path / "elsewhere.zip")

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code == 2
    assert not (tmp_path / "elsewhere.zip").exists()


def test_a_file_that_appears_meanwhile_is_not_written_over(
    client: type[StubClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "f.zip"

    def racing(*_: object, **__: object) -> Iterator[None]:
        target.write_bytes(b"mine")
        yield None

    monkeypatch.setattr(client, "wait_for_download", racing)

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code == 2, result.stderr
    assert target.read_bytes() == b"mine"


@pytest.mark.parametrize("debug", [(), ("--debug",)])
def test_a_cut_connection_leaves_no_partial_file(client: type[StubClient], tmp_path: Path, debug: tuple[str, ...]):
    client.cut = True
    target = tmp_path / "f.zip"

    result = run(*debug, *DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code == 7
    assert not target.exists()


def test_an_interrupt_leaves_no_partial_file(client: type[StubClient], tmp_path: Path):
    target = tmp_path / "f.zip"

    def interrupted() -> Iterator[bytes]:
        yield CONTENT
        raise KeyboardInterrupt

    client._chunks = lambda _: interrupted()  # pyright: ignore[reportAttributeAccessIssue]

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code != 0
    assert not target.exists()


def test_a_file_not_ready_in_time_is_a_timeout(client: type[StubClient], tmp_path: Path):
    client.late = odouche.StreamTimeoutError("The file of backup 2026-10-14 12:48:50 was not ready at the timeout.")

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes", "--timeout", "30")

    assert result.exit_code == 8
    assert "wait file acme 30" in client.calls
    assert not (tmp_path / "f.zip").exists()


def test_the_link_is_printed_without_downloading(client: type[StubClient]):
    result = run(*DOWNLOAD, *ON_STAGING, "--link", "--yes")

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{WORKER}/paas/build/124/download/dump?backup_datetime_utc=x&test_dump=1&filestore=1\n"
    assert "token" not in result.stdout
    assert not any(call.startswith("download") for call in client.calls)


def test_a_declined_question_sends_nothing(client: type[StubClient], tmp_path: Path):
    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), stdin="n\n")

    assert result.exit_code == 1
    assert "Nothing was sent." in result.stderr
    assert changes(client) == []
    assert not (tmp_path / "f.zip").exists()


def test_with_no_terminal_it_needs_yes(client: type[StubClient], monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(_terminal, "stdin_is_terminal", lambda: False)

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"))

    assert result.exit_code == 2
    assert "Give --yes" in said(result)
    assert client.modes == []


def test_new_takes_a_backup_waits_for_it_and_downloads_it(client: type[StubClient], tmp_path: Path):
    target = tmp_path / "f.zip"

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--new", stdin="y\n")

    assert result.exit_code == 0, result.output
    assert result.stderr.count("[y/N]") == 1
    assert "Take a backup and prepare its file?" in result.stderr
    assert "Backup: a new one of build 124, acme-staging-124" in result.stderr
    assert client.calls == [
        "branches acme",
        "latest staging",
        "create acme staging ''",
        "wait backup acme 124 600",
        "prepare acme 13:05:41 True True",
        "wait file acme 600",
        "download 13:05:41",
    ]
    assert target.read_bytes() == CONTENT


def test_new_on_a_development_branch_is_refused_before_any_question(client: type[StubClient], tmp_path: Path):
    client.branch = FEATURE

    result = run(*DOWNLOAD, "--project", "acme", "--branch", "feature-x", "-o", str(tmp_path / "f.zip"), "--new")

    assert result.exit_code == 9
    assert "[y/N]" not in result.stderr
    assert changes(client) == []


def test_an_unconfirmed_preparation_says_it_can_be_sent_again(
    client: type[StubClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def lost(*_: object, **__: object) -> None:
        msg = "Odoo.sh did not confirm the download preparation, which may have been done."
        raise odouche.OutcomeUnknownError(msg, operation="download preparation")

    monkeypatch.setattr(client, "prepare_download", lost)

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes")

    assert result.exit_code == 10
    assert "Preparing the file again does no harm" in result.stderr


def test_a_file_odoo_sh_holds_is_written_with_no_question_and_no_preparation(client: type[StubClient], tmp_path: Path):
    client.held = True
    target = tmp_path / "f.zip"

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target))

    assert result.exit_code == 0, result.output
    assert "Odoo.sh already holds this file: nothing is prepared." in result.stderr
    assert "[y/N]" not in result.stderr
    assert "Waiting" not in result.stderr
    assert client.calls == ["branches acme", "backups acme", "find acme 12:48:50 True True", "download 12:48:50"]
    assert target.read_bytes() == CONTENT


def test_the_link_of_a_file_odoo_sh_holds_is_printed_with_no_question(client: type[StubClient]):
    client.held = True

    result = run(*DOWNLOAD, *ON_STAGING, "--link", "--exact")

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(WORKER)
    assert changes(client) == []
    assert "find acme 12:48:50 False True" in client.calls


def test_new_never_looks_for_a_file_odoo_sh_holds(client: type[StubClient], tmp_path: Path):
    client.held = True

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--new", "--yes")

    assert result.exit_code == 0, result.output
    assert not any(call.startswith("find") for call in client.calls)


def test_a_directory_you_cannot_write_to_is_refused_before_any_change(client: type[StubClient], tmp_path: Path):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(locked / "f.zip"), "--yes")

    assert result.exit_code == 2
    assert "You cannot write to" in said(result)
    assert client.modes == []


def test_a_full_disk_leaves_no_partial_file(client: type[StubClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "f.zip"

    def full() -> Iterator[bytes]:
        yield CONTENT
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(client, "_chunks", lambda _: full())

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(target), "--yes")

    assert result.exit_code == 15
    assert "could not be written: No space left on device. Nothing of it is left." in result.stderr
    assert not target.exists()


def test_an_unconfirmed_preparation_after_new_says_not_to_take_another_backup(
    client: type[StubClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def lost(*_: object, **__: object) -> None:
        msg = "Odoo.sh did not confirm the download preparation, which may have been done."
        raise odouche.OutcomeUnknownError(msg, operation="download preparation")

    monkeypatch.setattr(client, "prepare_download", lost)

    result = run(*DOWNLOAD, *ON_STAGING, "-o", str(tmp_path / "f.zip"), "--yes", "--new")

    assert result.exit_code == 10
    assert "naming the backup rather than giving --new" in result.stderr
