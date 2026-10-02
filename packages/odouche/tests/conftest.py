from datetime import UTC, datetime

import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError, PasswordSetError

from odouche import _session


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, 12, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


def _memory():
    class Memory(KeyringBackend):
        """Keeps entries on the class: the store builds a backend on every use."""

        priority = 1  # pyright: ignore[reportAssignmentType]
        entries = {}
        calls = 0
        failure = None
        refuses_deletion = False
        failing_writes = 0
        write_failure = PasswordSetError

        def _call(self):
            type(self).calls += 1
            if self.failure is not None:
                raise self.failure(f"failed, entry: {self.entries}")

        def get_password(self, service, username):
            self._call()
            return self.entries.get((service, username))

        def set_password(self, service, username, password):
            self._call()
            if self.failing_writes:
                type(self).failing_writes -= 1
                raise self.write_failure(f"failed, entry: {password}")
            # As Credential Locker does with the entry it overwrites.
            if (service, username) in self.entries:
                self.entries[f"{username}@{service}", username] = self.entries[service, username]
            self.entries[service, username] = password

        def delete_password(self, service, username):
            self._call()
            if self.refuses_deletion or (service, username) not in self.entries:
                raise PasswordDeleteError("No such password!")
            del self.entries[service, username]

    return Memory


@pytest.fixture
def backend(monkeypatch):
    backend = _memory()
    monkeypatch.setattr(_session, "_accepted", lambda: backend)
    return backend


@pytest.fixture
def no_backend(monkeypatch):
    class NotViable(_memory()):
        viable = False  # pyright: ignore[reportAssignmentType]

    monkeypatch.setattr(_session, "_accepted", lambda: NotViable)
    return NotViable


@pytest.fixture
def memory():
    return _memory
