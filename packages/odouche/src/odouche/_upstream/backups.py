"""The backups of a project, which one request answers for every stage, and the manual backup of a branch."""

import logging
import time
from collections.abc import Callable, Generator

from odouche._upstream import branches, builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import NotFoundError, StageRefusedError, StreamTimeoutError
from odouche.models import Backup, BackupKind, BackupRequest, Stage


_OPERATION = "backups"
_CREATE = "backup"
_KINDS = {kind.value: kind for kind in BackupKind if kind is not BackupKind.UNKNOWN}
# Seen on a staging branch only. Production is let through unseen.
_BACKED_UP = frozenset({Stage.STAGING, Stage.PRODUCTION})
# Short beside the minute a backup takes to be listed, and well under the rate limit.
_INTERVAL = 5.0

# What the tests replace: the clock and the wait between two requests.
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep

_logger = logging.getLogger("odouche")


def backups(transport: Transport, project: str) -> list[Backup]:
    """List the backups of the project named `project`, newest first."""
    return _listed(transport, _technical_name(transport, project))


@state_changing
def backup(transport: Transport, project: str, branch_id: int, stage: Stage | None, comment: str) -> BackupRequest:
    """Ask for a manual backup of a branch's latest build. `stage` is the one the caller holds, if any."""
    if stage is not None:
        allow(stage)
    entry = builds.entry(transport, branch_id, 1)
    # The caller's branch may have changed stage since it was read.
    allow(branches.stage(entry.child("branch_info").text("stage")))
    latest = max(entry.items("builds"), key=lambda build: build.integer("id"), default=None)
    if latest is None:
        raise NotFoundError(f"Branch {branch_id} has no build to back up.", operation=_CREATE)
    # The wait looks among this project's backups: a branch of another would never be found there.
    if branch_id not in {branch.id for branch in branches.branches(transport, project)}:
        raise NotFoundError(f"Project {project!r} has no branch numbered {branch_id}.", operation=_CREATE)
    build = builds.whole(latest)
    previous = _manual(_listed(transport, _technical_name(transport, project)), build.name)
    transport.change(_CREATE, f"/app/build/{build.id}/dump", {"backup_only": True, "comment": comment})
    return BackupRequest(build=build, previous=previous[0].taken_at if previous else None)


def allow(stage: Stage) -> None:
    """Raise `StageRefusedError` for a stage that is not backed up. Nothing is asked."""
    if stage not in _BACKED_UP:
        raise StageRefusedError(
            f"A branch in the {stage.value} stage is not backed up: only a staging or a production one is.",
            operation=_CREATE,
        )


def wait(transport: Transport, project: str, request: BackupRequest, *, timeout: float) -> Generator[Backup | None]:
    """Yield `None` after each look that does not find the backup asked for, then the backup."""
    if timeout <= 0:
        raise ValueError("A timeout is more than 0")
    deadline = _monotonic() + timeout
    return _wait(transport, _technical_name(transport, project), request, deadline)


def _wait(
    transport: Transport, technical_name: str, request: BackupRequest, deadline: float
) -> Generator[Backup | None]:
    while True:
        found = _manual(_listed(transport, technical_name), request.build.name)
        if found and (request.previous is None or found[0].taken_at > request.previous):
            yield found[0]
            return
        yield None
        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise StreamTimeoutError(
                f"The backup of build {request.build.id} was not listed at the timeout.", operation=_OPERATION
            )
        _sleep(min(_INTERVAL, remaining))


def _manual(listed: list[Backup], build_name: str) -> list[Backup]:
    """Return the manual backups of a build, newest first."""
    return [backup for backup in listed if backup.kind is BackupKind.MANUAL and backup.build_name == build_name]


def _technical_name(transport: Transport, project: str) -> str:
    technical_name = projects.technical_name(transport, project)
    if technical_name is None:
        raise NotFoundError(f"The session's user can reach no project named {project!r}.", operation=_OPERATION)
    return technical_name


def _listed(transport: Transport, technical_name: str) -> list[Backup]:
    path = f"/app/project/{projects.segment(technical_name)}/backups"
    answer = Reader(_OPERATION, transport.call(_OPERATION, path, retry=True))
    listed = [_backup(backup) for backup in answer.items("result")]
    return sorted(listed, key=lambda backup: backup.taken_at, reverse=True)


def _backup(backup: Reader) -> Backup:
    # The `id` of a `remote` backup changes between two answers: the timestamp is what names one.
    name = backup.text("type")
    return Backup(
        kind=_kind(name),
        kind_name=name,
        taken_at=builds.timestamp(backup, "backup_datetime_utc", backup.text("backup_datetime_utc")),
        build_name=backup.text("name"),
        branch_name=backup.text("branch"),
        commit_hash=backup.text("revision"),
        downloadable=backup.boolean("downloadable"),
        size=_size(backup) if backup.has("size_sql_gz") else None,
    )


def _kind(name: str) -> BackupKind:
    known = _KINDS.get(name)
    if known is None:
        _logger.debug("Unknown backup kind: %r", name)
        return BackupKind.UNKNOWN
    return known


def _size(backup: Reader) -> int:
    size = backup.number("size_sql_gz")
    if size < 0 or not size.is_integer():
        raise backup.changed("size_sql_gz")
    return int(size)
