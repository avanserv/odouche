"""The client: the one object a caller asks Odoo.sh through."""

from collections.abc import Callable
from typing import Self

from odouche._session import SessionStore
from odouche._upstream import branches, projects
from odouche._upstream.transport import Transport
from odouche.models import Branch, Project
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
        self._transport = _transport(store.load().session, on_rejected=store.discard)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connections."""
        self._transport.close()

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
        name = project.name if isinstance(project, Project) else project
        return branches.branches(self._transport, name)
