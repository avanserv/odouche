"""The backups of a project, which one request answers for every stage, the manual backup of a branch, and its download."""

import logging
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from urllib.parse import urlencode

import httpx2

from odouche._upstream import branches, builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import NotFoundError, StageRefusedError, StreamTimeoutError, UpstreamUnavailableError
from odouche.models import Backup, BackupFile, BackupKind, BackupRequest, Build, PreparedDownload, Stage


_OPERATION = "backups"
_CREATE = "backup"
_PREPARE = "download preparation"
_FIND = "download lookup"
_DOWNLOAD = "download"
_INFO = "project"
_TAKEN = "%Y-%m-%d %H:%M:%S"
_READY = "dump"
_LINK = "download"
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
    """Yield `None` after each look that does not find the backup asked for finished, then the backup."""
    if timeout <= 0:
        raise ValueError("A timeout is more than 0")

    deadline = _monotonic() + timeout

    return _wait(transport, project, _technical_name(transport, project), request, deadline)


def _wait(
    transport: Transport, project: str, technical_name: str, request: BackupRequest, deadline: float
) -> Generator[Backup | None]:
    while True:
        found = _manual(_listed(transport, technical_name), request.build.name)

        # Listed some 20 seconds before it is finished, and Odoo.sh refuses a file of it until then.
        if (
            found
            and (request.previous is None or found[0].taken_at > request.previous)
            and not _dumping(transport, project)
        ):
            yield found[0]
            return

        yield None
        remaining = deadline - _monotonic()

        if remaining <= 0:
            raise StreamTimeoutError(
                f"The backup of build {request.build.id} was not finished at the timeout.", operation=_OPERATION
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


@state_changing
def prepare(
    transport: Transport, project: str, backup: Backup, *, neutralized: bool, filestore: bool
) -> PreparedDownload:
    """Ask Odoo.sh to prepare the file of a backup, on the build it was taken from."""
    build, worker = _located(transport, project, backup, _PREPARE)
    previous = max((item.integer("id") for item in _notifications(transport, project)), default=0)
    transport.change(
        _PREPARE,
        f"/app/build/{build.id}/dump",
        {"test_dump": neutralized, "filestore": filestore, "backup_datetime_utc": backup.taken_at.strftime(_TAKEN)},
    )

    return _prepared(backup, build, worker, neutralized=neutralized, filestore=filestore, previous=previous)


def find(
    transport: Transport, project: str, backup: Backup, *, neutralized: bool, filestore: bool
) -> PreparedDownload | None:
    """Return the file of a backup that Odoo.sh already holds, or `None`. Nothing changes on Odoo.sh."""
    build, worker = _located(transport, project, backup, _FIND)
    candidate = _prepared(backup, build, worker, neutralized=neutralized, filestore=filestore, previous=0)
    announced = [item.integer("id") for item in _notifications(transport, project) if _announces(item, candidate)]

    if not announced:
        return None

    # Only the worker tells whether the file outlived the notification.
    try:
        with download(transport, candidate):
            pass
    except NotFoundError:
        return None

    return replace(candidate, previous=max(announced))


def _located(transport: Transport, project: str, backup: Backup, operation: str) -> tuple[Build, str]:
    """Return the build a backup was taken from, and the address of the worker that holds it."""
    if not backup.downloadable:
        raise ValueError(f"Odoo.sh does not let a {backup.kind_name} backup be downloaded")

    branch = next((found for found in branches.branches(transport, project) if found.name == backup.branch_name), None)

    if branch is None:
        raise NotFoundError(f"Project {project!r} has no branch named {backup.branch_name!r}.", operation=operation)

    entry = builds.entry(transport, branch.id, builds.DEFAULT_LIMIT)
    listed = next((found for found in entry.items("builds") if found.text("name") == backup.build_name), None)

    if listed is None:
        raise NotFoundError(
            f"Build {backup.build_name} is no longer among the latest builds of branch {branch.name}, "
            "so its backups cannot be downloaded.",
            operation=operation,
        )

    worker = listed.optional_text("worker_url")

    if worker is None:
        raise NotFoundError(f"Build {backup.build_name} has no worker to hold the file.", operation=operation)

    return builds.whole(listed), worker


def _prepared(
    backup: Backup, build: Build, worker: str, *, neutralized: bool, filestore: bool, previous: int
) -> PreparedDownload:
    query = urlencode(_query(backup, neutralized=neutralized, filestore=filestore))
    return PreparedDownload(
        backup=backup,
        build=build,
        worker_url=worker,
        neutralized=neutralized,
        filestore=filestore,
        link=f"{worker}{_path(build.id)}?{query}",
        previous=previous,
    )


def wait_download(transport: Transport, project: str, prepared: PreparedDownload, *, timeout: float) -> Generator[None]:
    """Yield `None` after each look that does not find the file ready, and end once it is."""
    if timeout <= 0:
        raise ValueError("A timeout is more than 0")

    deadline = _monotonic() + timeout

    return _wait_download(transport, project, prepared, deadline)


def _wait_download(transport: Transport, project: str, prepared: PreparedDownload, deadline: float) -> Generator[None]:
    while True:
        if any(_announces(item, prepared) for item in _notifications(transport, project)):
            return

        yield None
        remaining = deadline - _monotonic()

        if remaining <= 0:
            raise StreamTimeoutError(
                f"The file of backup {prepared.backup.taken_at:{_TAKEN}} was not ready at the timeout.",
                operation=_PREPARE,
            )

        _sleep(min(_INTERVAL, remaining))


@contextmanager
def download(transport: Transport, prepared: PreparedDownload) -> Generator[BackupFile]:
    """Open the prepared file, which Odoo.sh hands over a token for."""
    build_id = builds.number("build", prepared.build.id)
    query = _query(prepared.backup, neutralized=prepared.neutralized, filestore=prepared.filestore)

    with ExitStack() as stack:
        try:
            body = stack.enter_context(
                transport.worker_download(
                    _DOWNLOAD, prepared.worker_url, f"/paas/build/{build_id}/token", _path(build_id), query
                )
            )
        except NotFoundError:
            body = None

        # Raised out of the handler, as the transport's are.
        if body is None:
            raise NotFoundError(
                f"The file of backup {prepared.backup.taken_at:{_TAKEN}} is not ready, or Odoo.sh no longer keeps it.",
                operation=_DOWNLOAD,
            )

        yield BackupFile(size=body.size, chunks=_whole(body.size, body.chunks))


def _whole(size: int | None, chunks: Iterator[bytes]) -> Iterator[bytes]:
    received = 0

    for chunk in chunks:
        received += len(chunk)
        yield chunk

    if size is not None and received != size:
        raise UpstreamUnavailableError(f"The file ended after {received} of its {size} bytes.", operation=_DOWNLOAD)


def _path(build_id: int) -> str:
    return f"/paas/build/{build_id}/download/dump"


def _query(backup: Backup, *, neutralized: bool, filestore: bool) -> dict[str, str]:
    """Return the query of the page's link, which carries the values of the preparation."""
    return {
        "backup_datetime_utc": backup.taken_at.strftime(_TAKEN),
        "test_dump": "1" if neutralized else "0",
        "filestore": "1" if filestore else "0",
    }


def _announces(item: Reader, prepared: PreparedDownload) -> bool:
    """Tell whether a notification says the file is ready: its button is the page's link to it."""
    if item.integer("id") <= prepared.previous or item.text("notif_type") != _READY:
        return False

    return any(
        button.text("type") == _LINK and button.has("url") and _same(button.text("url"), prepared.link)
        for button in item.items("buttons")
    )


def _same(url: str, link: str) -> bool:
    """Compare two addresses as the worker reads them, so the order and encoding of the query do not count."""
    try:
        return _parts(httpx2.URL(url)) == _parts(httpx2.URL(link))
    except httpx2.InvalidURL:
        return False


def _parts(url: httpx2.URL) -> tuple[object, ...]:
    return url.scheme, url.host, url.port, url.path, sorted(url.params.multi_items())


def _notifications(transport: Transport, project: str) -> list[Reader]:
    """Return the project's notifications, which `get_info` gives under the project's number."""
    result = _info(transport, project)
    key = str(result.child("active_repo").integer("id"))
    notifications = result.child("notifications")

    return notifications.child(key).items("items") if notifications.has(key) else []


def _dumping(transport: Transport, project: str) -> bool:
    """Tell whether Odoo.sh is still making a backup or a file of the project."""
    return _info(transport, project).child("active_repo").boolean("dump_in_progress")


def _info(transport: Transport, project: str) -> Reader:
    answer = Reader(
        _INFO,
        transport.call(
            _INFO,
            f"/app/project/{projects.segment(project)}/get_info",
            retry=True,
            not_found=f"The session's user can reach no project named {project!r}.",
        ),
    )
    return answer.child("result")
