"""Where a session lives: the OS keyring between runs, or the environment in memory only."""

import json
import os
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, cast

from odouche.errors import KeyringUnavailableError, NoSessionError, SessionExpiredError
from odouche.secret import Secret


if TYPE_CHECKING:
    from keyring.backend import KeyringBackend


SESSION_ENV = "ODOUCHE_SESSION"
"""The environment variable a session is read from. It wins over the keyring and is never stored."""

KEYRING_SERVICE = "odouche"
"""The service the session is stored under in the OS keyring."""

KEYRING_ENTRY = "session"
"""The name of the keyring entry, which holds the session and the time it was stored."""

MAX_AGE = timedelta(days=30)


class Source(Enum):
    """Where a session came from."""

    ARGUMENT = "argument"
    ENVIRONMENT = "environment"
    KEYRING = "keyring"


@dataclass(frozen=True, slots=True)
class Resolved:
    """A session, where it came from and, when it is the stored one, when it passes the max age."""

    session: Secret
    source: Source
    expires_at: datetime | None = None


def _accepted() -> "type[KeyringBackend]":
    """Name this platform's backend. `keyring.get_keyring()` would also pick a plaintext one."""
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring as Keychain  # noqa: PLC0415

        return Keychain
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring  # noqa: PLC0415

        return WinVaultKeyring
    from keyring.backends.SecretService import Keyring as SecretService  # noqa: PLC0415

    return SecretService


def _use[T](action: "Callable[[KeyringBackend], T]") -> T:
    """Run one action on the accepted backend.

    A failure is raised once its handler has ended: the backend's exception can hold the entry,
    and an error raised while it is being handled would carry it as its context. No caller binds
    the entry to a name either, since a frame's locals travel with its traceback.
    """
    backend = _accepted()
    if not backend.viable:
        raise KeyringUnavailableError
    try:
        return action(backend())
    # Backends let through more than `KeyringError`: D-Bus, pywin32 and decoding errors.
    except Exception as error:  # noqa: BLE001
        failure = type(error).__name__
    raise KeyringUnavailableError(
        f"The keyring could not be used ({failure}). Unlock it, or supply the session through the environment."
    )


def _get(backend: "KeyringBackend") -> tuple[bool, tuple[Secret, datetime] | None]:
    """Return whether there is an entry, and what it holds if it can be read."""
    entry = backend.get_password(KEYRING_SERVICE, KEYRING_ENTRY)
    return entry is not None, _read(entry)


def _delete(backend: "KeyringBackend") -> None:
    from keyring.errors import PasswordDeleteError  # noqa: PLC0415

    try:
        backend.delete_password(KEYRING_SERVICE, KEYRING_ENTRY)
    except PasswordDeleteError:
        # Raised when there is no entry, and on macOS when the deletion is refused.
        if backend.get_password(KEYRING_SERVICE, KEYRING_ENTRY) is not None:
            raise


def _read(entry: str | None) -> tuple[Secret, datetime] | None:
    """Read a stored entry, or nothing if it is not one."""
    try:
        stored = json.loads(entry or "")
    except ValueError:
        return None
    if not isinstance(stored, dict):
        return None
    fields = cast("dict[str, object]", stored)
    session, stored_at = fields.get("session"), fields.get("stored_at")
    if not isinstance(session, str) or not session or type(stored_at) is not int:
        return None
    try:
        return Secret(session), datetime.fromtimestamp(stored_at, UTC)
    except (OverflowError, OSError, ValueError):
        return None


class SessionStore:
    """Resolves the session: the one passed, then the environment, then the keyring.

    Only `save` writes, and only to the keyring. `max_age` can be shortened, not lengthened.
    """

    def __init__(
        self,
        session: Secret | None = None,
        *,
        max_age: timedelta = MAX_AGE,
        environ: Mapping[str, str] = os.environ,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not timedelta(0) < max_age <= MAX_AGE:
            raise ValueError(f"max_age is positive and at most {MAX_AGE.days} days")
        self._session = session
        self._max_age = max_age
        self._environ = environ
        self._clock = clock

    def load(self) -> Resolved:
        """Return the session, without ever updating the time it was stored.

        A stored session past the max age is deleted and raises `SessionExpiredError`.
        """
        given = self._given()
        if given is not None:
            return given
        found, stored = _use(_get)
        if not found:
            raise NoSessionError("Not logged in.")
        if stored is None:
            _use(_delete)
            raise NoSessionError("The stored session could not be read and was deleted. Log in again.")
        session, stored_at = stored
        # A time in the future is a clock that moved or an entry that was edited.
        if not timedelta(0) <= self._clock() - stored_at <= self._max_age:
            _use(_delete)
            raise SessionExpiredError("The stored session passed its max age and was deleted. Log in again.")
        return Resolved(session, Source.KEYRING, stored_at + self._max_age)

    def save(self, session: Secret) -> None:
        """Store the session in the keyring with the current time, replacing the stored one.

        It is stored even when another session is passed or set in the environment.
        """
        stored_at = int(self._clock().timestamp())

        def replace(backend: "KeyringBackend") -> None:
            # Credential Locker keeps the entry it overwrites under a second name.
            _delete(backend)
            backend.set_password(
                KEYRING_SERVICE,
                KEYRING_ENTRY,
                json.dumps({"session": session.expose_secret(), "stored_at": stored_at}),
            )

        _use(replace)

    def discard(self) -> None:
        """Delete the stored session, if that is the one in use. Safe to call twice."""
        if self._given() is None:
            with suppress(KeyringUnavailableError):
                _use(_delete)

    def _given(self) -> Resolved | None:
        if self._session is not None:
            return Resolved(self._session, Source.ARGUMENT)
        value = self._environ.get(SESSION_ENV)
        return Resolved(Secret(value), Source.ENVIRONMENT) if value else None
