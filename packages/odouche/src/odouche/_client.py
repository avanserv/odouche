"""The client: the one object a caller asks Odoo.sh through."""

from collections.abc import Callable
from typing import Self

from odouche._session import SessionStore
from odouche._upstream import projects
from odouche._upstream.transport import Transport
from odouche.models import Project
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
