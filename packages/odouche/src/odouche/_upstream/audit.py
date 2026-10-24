"""The audit log of a project, which Odoo.sh answers whole: the last 30 days in one answer, with no paging."""

import logging
import time
from collections.abc import Callable, Generator
from datetime import datetime

from odouche._upstream import branches, builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import TooLargeError, Transport
from odouche.errors import OdoucheError, PermissionDeniedError, StreamTimeoutError, UpstreamUnavailableError
from odouche.models import AuditEntry, AuditKind


# The page's rows a screen.
DEFAULT_LIMIT = 25
MAX_ANSWER = 16777216
"""The bytes of the answer read before it is given up on: room for the 30 days of a busy project."""

_OPERATION = "audit log"
# The page shows the label Odoo.sh sends: the last three were seen in the CSV export only.
_KINDS = {
    "Allow IP": AuditKind.ALLOW_IP,
    "Connect as user": AuditKind.CONNECT_AS_USER,
    "Download database": AuditKind.DOWNLOAD_DATABASE,
    "Manage collaborators": AuditKind.MANAGE_COLLABORATORS,
    "Open Editor": AuditKind.OPEN_EDITOR,
    "Open Shell": AuditKind.OPEN_SHELL,
    "Open Webmail": AuditKind.OPEN_WEBMAIL,
    "Open database logs": AuditKind.OPEN_DATABASE_LOGS,
    "Change branch stage": AuditKind.CHANGE_BRANCH_STAGE,
    "Add domain name": AuditKind.ADD_DOMAIN_NAME,
    "Manage settings": AuditKind.MANAGE_SETTINGS,
}
_KIND_NAME = 64

# What the tests replace: the clock.
_monotonic: Callable[[], float] = time.monotonic

_logger = logging.getLogger("odouche")


def audit_log(transport: Transport, name: str, *, limit: int, timeout: float) -> Generator[AuditEntry]:
    """Yield the entries of the audit log of the project named `name`, newest first and at most `limit` of them."""
    if builds.number("limit", limit) < 1:
        raise ValueError("A limit is at least 1")
    if timeout <= 0:
        raise ValueError("A timeout is more than 0")
    return _audit_log(transport, name, limit, _monotonic() + timeout)


def _audit_log(transport: Transport, name: str, limit: int, deadline: float) -> Generator[AuditEntry]:
    rows = _answered(transport, name, deadline)
    # Stable: entries of the same second keep the answer's order. The page sorts them itself.
    rows.sort(key=lambda row: row[0], reverse=True)
    for logged_at, row in rows[:limit]:
        yield _entry(row, logged_at)


def _answered(transport: Transport, name: str, deadline: float) -> list[tuple[datetime, Reader]]:
    try:
        return _rows(transport, name, deadline)
    except UpstreamUnavailableError as error:
        failed = error
    # Out of the handler, as the timeout is raised from no other error. A request the deadline cut
    # short is the timeout, which `_remaining` raises.
    _remaining(deadline, name)
    raise failed


def _rows(transport: Transport, name: str, deadline: float) -> list[tuple[datetime, Reader]]:
    info = projects.info(transport, name, within=_remaining(deadline, name))
    # The page's own test: what Odoo.sh answers anyone else was never seen.
    if not projects.is_admin(info):
        raise PermissionDeniedError("Odoo.sh shows a project's audit log to its admins only.", operation=_OPERATION)
    technical_name = info.child("active_repo").text("technical_name")
    try:
        body = transport.call(
            _OPERATION,
            f"/app/project/{projects.segment(technical_name)}/audit_logs",
            retry=True,
            within=_remaining(deadline, name),
            limit=MAX_ANSWER,
        )
    except TooLargeError:
        msg = f"The audit log of {name!r} is over {MAX_ANSWER // 1048576} MiB as Odoo.sh answers it, which the library does not read."
        raise OdoucheError(msg, operation=_OPERATION) from None
    return [(builds.timestamp(row, "date", row.text("date")), row) for row in Reader(_OPERATION, body).items("result")]


def _entry(row: Reader, logged_at: datetime) -> AuditEntry:
    action = row.text("action")
    stage = row.text("stage")
    return AuditEntry(
        logged_at=logged_at,
        author=row.text("user"),
        kind=_kind(action),
        kind_name=action[:_KIND_NAME],
        stage=branches.stage(stage) if stage else None,
        details=row.text("message"),
        succeeded=row.boolean("successful"),
    )


def _kind(action: str) -> AuditKind:
    known = _KINDS.get(action)
    if known is None:
        _logger.debug("Unknown audit log action: %r", action[:_KIND_NAME])
        return AuditKind.UNKNOWN
    return known


def _remaining(deadline: float, name: str) -> float:
    remaining = deadline - _monotonic()
    if remaining <= 0:
        raise StreamTimeoutError(
            f"The audit log of {name!r} was still being read at the timeout.", operation=_OPERATION
        )
    return remaining
