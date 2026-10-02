"""The errors the library raises.

An error carries the name of the operation, the HTTP status when there was one and a short
message: never a session value, request headers or a response body. Raise one `from None` wherever
the exception being handled holds the request.
"""

from typing import Any


_ISSUES_URL = "https://github.com/avanserv/odouche/issues"

_NO_KEYRING = (
    "No usable keyring: the session is stored only in Secret Service, macOS Keychain or Windows "
    "Credential Locker. Install a Secret Service provider, or supply the session through the "
    "environment."
)


class OdoucheError(Exception):
    """Base class of every error the library raises."""

    operation: str | None
    status: int | None

    def __init__(self, message: str, *, operation: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.operation = operation
        self.status = status


class NoSessionError(OdoucheError):
    """Raised when there is no session: none was passed, set in the environment or stored.

    The user has to log in.
    """


class SessionExpiredError(OdoucheError):
    """Raised when Odoo.sh rejects the session, or when it has passed the client-side max age.

    The stored session is gone and the user has to log in again.
    """


class NotFoundError(OdoucheError):
    """Raised when the project, branch or build asked for does not exist."""


class PermissionDeniedError(OdoucheError):
    """Raised when the session is valid but is not allowed to do what was asked."""


class UpstreamChangedError(OdoucheError):
    """Raised when an answer from Odoo.sh no longer has the shape the library reads.

    Odoo.sh has no public API, so this is the expected way for the library to break. It is not a
    mistake in the caller's input.
    """

    field: str

    def __init__(self, operation: str, field: str, *, status: int | None = None) -> None:
        super().__init__(
            f"Unexpected answer from Odoo.sh for {operation}, at {field}. Odoo.sh has probably "
            f"changed, which is not a mistake on your side. Please report it at {_ISSUES_URL}",
            operation=operation,
            status=status,
        )
        self.field = field

    # The default rebuilds from `args`, which holds the message.
    def __reduce__(self) -> tuple[Any, ...]:
        return type(self), (self.operation, self.field), vars(self)


class UpstreamUnavailableError(OdoucheError):
    """Raised when Odoo.sh cannot be reached, or answers with a server error."""


class KeyringUnavailableError(OdoucheError):
    """Raised when no accepted keyring backend is available to store the session.

    Nothing was persisted. The message names the two ways out.
    """

    def __init__(self, message: str = _NO_KEYRING, *, operation: str | None = None, status: int | None = None) -> None:
        super().__init__(message, operation=operation, status=status)
