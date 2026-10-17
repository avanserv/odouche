"""The history of a branch: its pushes, rebuilds and moves between stages, a page at a time."""

import logging
import time
from collections.abc import Callable, Generator

from odouche._upstream import branches, builds
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import StreamTimeoutError, UpstreamChangedError
from odouche.models import PushedCommit, TrackedBuild, Tracking, TrackingKind


# The page's own size. That the next page is at this offset is inferred: only offset 0 was seen.
PAGE = 20

_OPERATION = "history"
_KINDS = {kind.value: kind for kind in TrackingKind if kind is not TrackingKind.UNKNOWN}

# What the tests replace: the clock.
_monotonic: Callable[[], float] = time.monotonic

_logger = logging.getLogger("odouche")


def history(transport: Transport, branch_id: int, *, limit: int, timeout: float) -> Generator[Tracking]:
    """Yield the events of a branch, newest first and at most `limit` of them, asking a page when it is reached."""
    builds.number("branch", branch_id)
    if builds.number("limit", limit) < 1:
        raise ValueError("A limit is at least 1")
    if timeout <= 0:
        raise ValueError("A timeout is more than 0")
    return _history(transport, branch_id, limit, _monotonic() + timeout)


def _history(transport: Transport, branch_id: int, limit: int, deadline: float) -> Generator[Tracking]:
    given = 0
    oldest: int | None = None
    while True:
        total, page = _page(transport, branch_id, given, deadline)
        # An event that came after the first page pushes the next ones down: what is read again is skipped.
        older = [tracking for tracking in page if oldest is None or tracking.id < oldest]
        # A page with nothing older, as one whose offset Odoo.sh ignores, would never end.
        if page and not older:
            raise UpstreamChangedError(_OPERATION, "result.trackings")
        for tracking in older:
            yield tracking
            oldest = tracking.id
            given += 1
            if given >= limit:
                return
        if not page or given >= total:
            return


def _page(transport: Transport, branch_id: int, offset: int, deadline: float) -> tuple[int, list[Tracking]]:
    remaining = deadline - _monotonic()
    if remaining <= 0:
        raise StreamTimeoutError(
            f"The history of branch {branch_id} was still being read at the timeout.", operation=_OPERATION
        )
    answer = Reader(
        _OPERATION,
        transport.call(
            _OPERATION,
            f"/app/branch/{branch_id}/history",
            {"offset": offset},
            retry=True,
            not_found=f"The session's user can reach no branch numbered {branch_id}. Odoo.sh gives no reason.",
            within=remaining,
        ),
    )
    result = answer.child("result")
    return result.integer("num_trackings"), [_tracking(tracking) for tracking in result.items("trackings")]


def _tracking(tracking: Reader) -> Tracking:
    kind = tracking.text("tracking_type")
    build = tracking.optional_child("build")
    source = tracking.optional_text("source_stage")
    target = tracking.optional_text("target_stage")
    return Tracking(
        id=tracking.integer("id"),
        kind=_kind(kind),
        kind_name=kind,
        created_at=builds.timestamp(tracking, "create_date", tracking.text("create_date")),
        build=None if build is None else _build(build),
        commits=tuple(
            PushedCommit(
                hash=commit.text("identifier"), message=commit.text("message"), url=commit.text("provider_url")
            )
            for commit in tracking.items("commits")
        ),
        pusher=tracking.optional_text("pusher_name"),
        source_stage=None if source is None else branches.stage(source),
        target_stage=None if target is None else branches.stage(target),
    )


def _build(build: Reader) -> TrackedBuild:
    # Unlike in the builds answer, the status and the result come with their labels.
    return TrackedBuild(id=build.integer("id"), **builds.outcome(build.label("status"), build.optional_label("result")))


def _kind(name: str) -> TrackingKind:
    known = _KINDS.get(name)
    if known is None:
        _logger.debug("Unknown tracking type: %r", name)
        return TrackingKind.UNKNOWN
    return known
