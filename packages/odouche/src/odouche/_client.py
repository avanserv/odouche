"""The client: the one object a caller asks Odoo.sh through."""

from collections.abc import Callable, Iterator
from typing import Self

from odouche._session import SessionStore
from odouche._upstream import branches, builds, logs, projects, user
from odouche._upstream.transport import Transport
from odouche.models import Branch, Build, Identity, Log, LogKind, LogLine, Project, SessionInfo
from odouche.secret import Secret


# What the tests replace: the connection to Odoo.sh.
_transport: Callable[..., Transport] = Transport


class Client:
    """Asks Odoo.sh on behalf of one session.

    With no argument the session is the one in the environment, then the one stored by `login`.
    A tool that keeps sessions itself passes its own, which is never stored. Raises
    `NoSessionError` when there is none, `SessionExpiredError` when the stored one has passed its
    max age and `KeyringUnavailableError` when the keyring cannot be read.

    Every call raises `SessionExpiredError` when Odoo.sh rejects the session, after deleting it if
    it is the stored one. Nothing is cached: each call asks Odoo.sh. Use the client as a context
    manager, or call `close`.
    """

    def __init__(self, session: Secret | None = None) -> None:
        store = SessionStore(session)
        resolved = store.load()
        self._session = SessionInfo(resolved.source, resolved.stored_at, resolved.expires_at)
        self._transport = _transport(resolved.session, on_rejected=store.discard)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connections."""
        self._transport.close()

    @property
    def session(self) -> SessionInfo:
        """Where the session came from and when it passes its max age. Odoo.sh is not asked."""
        return self._session

    def identity(self) -> Identity:
        """Return the user the session belongs to, which also tells that Odoo.sh still accepts it."""
        return user.identity(self._transport, self._session)

    def projects(self) -> list[Project]:
        """List the projects the session's user can reach."""
        return projects.projects(self._transport)

    def branches(self, project: Project | str) -> list[Branch]:
        """List the branches of a project, given as a `Project` or by its name.

        They come in the order Odoo.sh answers them, which is not by name or by stage. Raises
        `NotFoundError` when the project is not among those the session's user can reach, whether
        or not it exists, and `PermissionDeniedError` when Odoo.sh lists it but refuses its
        branches. Asks Odoo.sh twice, for the projects and then for the branches.
        """
        return branches.branches(self._transport, _project_name(project))

    def builds(self, branch: Branch | int, *, limit: int = builds.DEFAULT_LIMIT) -> list[Build]:
        """List the latest builds of a branch, given as a `Branch` or by its number, newest first.

        At most `limit` builds are returned, in one request. Odoo.sh may answer fewer than asked
        for: it has only been seen to answer up to four, and older builds are out of reach. Raises
        `NotFoundError` when the branch is not one the session's user can reach.
        """
        return builds.builds(self._transport, _branch_id(branch), limit)

    def build(self, branch: Branch | int, build_id: int) -> Build:
        """Return one build of a branch by its number.

        Odoo.sh has no request for a build by its number, so the build is looked for among the
        branch's latest. Raises `NotFoundError` when it is not there, which an older build is not.
        """
        return builds.build(self._transport, _branch_id(branch), build_id)

    def latest_build(self, branch: Branch | int) -> Build | None:
        """Return the newest build of a branch, or `None` when it has none."""
        latest = builds.builds(self._transport, _branch_id(branch), 1)
        return latest[0] if latest else None

    def logs(self, project: Project | str, build: Build) -> list[Log]:
        """List the logs a build of a project has, which is none while it waits for a worker.

        Raises `NotFoundError` when the build is not among its branch's latest, or the project is
        not one the session's user can reach.
        """
        return logs.logs(self._transport, _project_name(project), build)

    def read_log(
        self, project: Project | str, build: Build, kind: LogKind | str, *, tail: int | None = None
    ) -> Iterator[LogLine]:
        """Yield the lines of one log of a build, given as a `LogKind` or by its name.

        Log content is untrusted: it is whatever a process printed, terminal escape sequences and
        secrets of the instance included, and it is returned unchanged.

        With `tail`, only the last lines are yielded, out of the log's last mebibyte. A line
        longer than 64 KiB is cut. Raises `NotFoundError` when the build has no such log.
        """
        return logs.read(self._transport, _project_name(project), build, kind, tail)

    def follow_log(
        self,
        project: Project | str,
        build: Build,
        kind: LogKind | str,
        *,
        timeout: float,
        tail: int = 0,
        offset: int | None = None,
    ) -> Iterator[LogLine]:
        """Yield the lines of one log of a build as they are written, until the iterator is closed.

        Log content is untrusted, as in `read_log`.

        It starts after the log's last `tail` lines, or at `offset`, which is the `offset` of a
        line read before. Odoo.sh is asked every second. Raises `StreamTimeoutError` after
        `timeout` seconds, `UpstreamUnavailableError` when a failed request is not answered after
        two more tries, and `NotFoundError` when the build has no such log.
        """
        return logs.follow(
            self._transport, _project_name(project), build, kind, timeout=timeout, tail=tail, offset=offset
        )


def _project_name(project: Project | str) -> str:
    return project.name if isinstance(project, Project) else project


def _branch_id(branch: Branch | int) -> int:
    return branch.id if isinstance(branch, Branch) else branch
