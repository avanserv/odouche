"""The backups request, which belongs to the project and answers every stage's backups."""

import logging

from odouche._upstream import builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import NotFoundError
from odouche.models import Backup, BackupKind


_OPERATION = "backups"
_KINDS = {kind.value: kind for kind in BackupKind if kind is not BackupKind.UNKNOWN}

_logger = logging.getLogger("odouche")


def backups(transport: Transport, project: str) -> list[Backup]:
    """List the backups of the project named `project`, newest first."""
    technical_name = projects.technical_name(transport, project)
    if technical_name is None:
        raise NotFoundError(f"The session's user can reach no project named {project!r}.", operation=_OPERATION)
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
