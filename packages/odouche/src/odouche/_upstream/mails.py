"""The mails a build caught instead of sending them, which a worker keeps and the project's token opens.

Nothing of a mail goes to the library's logger, and the worker's address of a mail's HTML is never
asked: it carries the token.
"""

import email.utils
from dataclasses import dataclass
from datetime import UTC, datetime

from odouche import _mime
from odouche._upstream import builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import TooLargeError, Transport
from odouche.errors import NotFoundError, OdoucheError
from odouche.models import Branch, Build, Mail, MailContent, Stage
from odouche.secret import Secret


DEFAULT_LIMIT = 20
MAX_MESSAGE = 16777216
"""The bytes of one answer of a worker read before it is given up on: a mail's source holds its attachments."""

_OPERATION = "mails"
# The stages the page has the Mail tab on.
_STAGES = frozenset({Stage.DEVELOPMENT, Stage.STAGING})
_STAMP = "%Y-%m-%d %H:%M:%S"
_UNDATED = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Mailbox:
    """Where the mails of one build are asked for, and with what."""

    worker: str
    token: Secret
    build_id: int

    def path(self, action: str) -> str:
        return f"/paas/{self.build_id}/mail/json/{action}"


def mails(transport: Transport, project: str, branch: Branch, build: Build, limit: int) -> list[Mail]:
    """List the mails a build caught, newest first and at most `limit` of them. The worker answers them all at once."""
    if builds.number("limit", limit) < 1:
        raise ValueError("A limit is at least 1")
    _check(branch, build)
    box = _mailbox(transport, project, build)
    if box is None:
        return []
    listed = [_summary(item) for item in _listed(transport, box)]
    # Stable: mails of the same date keep the worker's order.
    newest = sorted(listed, key=lambda mail: (mail.date is not None, mail.date or _UNDATED), reverse=True)
    return newest[:limit]


def mail(transport: Transport, project: str, branch: Branch, build: Build, mail_id: str) -> MailContent:
    """Return one mail a build caught, with its body. Its id is sent only once the worker has listed it."""
    _check(branch, build)
    box = _mailbox(transport, project, build)
    if box is None:
        raise NotFoundError(f"Build {build.id} has caught no mail: it waits for a worker.", operation=_OPERATION)
    for item in _listed(transport, box):
        listed_id = item.identifier("id")
        if _name(listed_id) != mail_id:
            continue
        if _name(listed_id) != str(listed_id):
            msg = f"Build {build.id} caught mail {mail_id!r} under a name that cannot be sent back to the worker."
            raise NotFoundError(msg, operation=_OPERATION)
        return _content(transport, box, _summary(item), listed_id)
    raise NotFoundError(f"Build {build.id} caught no mail {mail_id!r}.", operation=_OPERATION)


def _check(branch: Branch, build: Build) -> None:
    if build.branch_id != branch.id:
        raise ValueError(f"Build {build.id} is not of branch {branch.name}")
    if branch.stage not in _STAGES:
        msg = (
            f"Branch {branch.name} is {branch.stage_name}: "
            "Odoo.sh catches the mails of a development or a staging build only."
        )
        raise NotFoundError(msg, operation=_OPERATION)


def _mailbox(transport: Transport, project: str, build: Build) -> _Mailbox | None:
    worker = builds.worker(transport, build.branch_id, build.id)
    if worker is None:
        return None
    return _Mailbox(worker, projects.access_token(transport, project), build.id)


def _listed(transport: Transport, box: _Mailbox) -> list[Reader]:
    try:
        listed = transport.worker_call(_OPERATION, box.worker, box.path("fetch"), box.token, limit=MAX_MESSAGE)
    except TooLargeError:
        msg = f"The mails build {box.build_id} caught are over {MAX_MESSAGE // 1048576} MiB as the worker lists them, which the library does not read."
        raise OdoucheError(msg, operation=_OPERATION) from None
    return Reader(_OPERATION, listed).items("result")


def _summary(item: Reader) -> Mail:
    date = _header(item, "date")
    return Mail(
        id=_name(item.identifier("id")),
        date=_when(date),
        date_text=date,
        sender=_header(item, "from"),
        recipients=_header(item, "to"),
        subject=_header(item, "subject"),
    )


def _name(listed_id: int | str) -> str:
    """Return the id a mail is named by, as the model holds it."""
    return str(listed_id).encode("utf-8", "replace").decode()


def _header(item: Reader, key: str) -> str:
    """Return a header the worker lists. A mail may lack it, which the worker may say with `false`.

    Half of a surrogate pair, which JSON can hold and no encoder takes, is replaced.
    """
    return (item.optional_text(key) or "").encode("utf-8", "replace").decode()


def _when(text: str) -> datetime | None:
    """Read a date as a mail writes it, or as Odoo.sh writes its own. It is the build's text: it never raises."""
    try:
        moment = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            return datetime.strptime(text, _STAMP).replace(tzinfo=UTC)
        except ValueError:
            return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    try:
        return moment.astimezone(UTC)
    except OverflowError:
        # A date on the last day of the calendar, in a zone behind UTC.
        return None


def _content(transport: Transport, box: _Mailbox, summary: Mail, listed_id: int | str) -> MailContent:
    """Read a mail's body and attachments from its source, the one field of the answer read."""
    try:
        # Sent back as the worker typed it.
        params = {"message_id": listed_id}
        answer = transport.worker_call(
            _OPERATION, box.worker, box.path("message"), box.token, params, limit=MAX_MESSAGE
        )
    except TooLargeError:
        return MailContent(mail=summary, cc="", body="", attachments=(), truncated=True)
    parsed = _mime.parse(Reader(_OPERATION, answer).child("result").text("source"))
    return MailContent(
        mail=summary, cc=parsed.cc, body=parsed.body, attachments=parsed.attachments, truncated=parsed.truncated
    )
