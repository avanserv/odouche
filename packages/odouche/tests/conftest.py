import json
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError, PasswordSetError

from odouche import SESSION_ENV, Client, Secret, _client, _session
from odouche._upstream.transport import Transport


FIXTURES = Path(__file__).parent / "fixtures"


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


class Upstream:
    """Answers each request with the body of its path, and keeps the requests and the transports it was reached through."""

    def __init__(self):
        self.bodies = {
            "/app/projects": self.load("projects.json"),
            "/app/project/acme-corp-odoo-addons-4217/branches": self.load("branches.json"),
        }
        self.requests = []
        self.transports = []

    @staticmethod
    def load(name):
        return json.loads((FIXTURES / name).read_text())

    def connect(self, session, **options):
        self.transports.append(Transport(session, transport=httpx2.MockTransport(self._answer), **options))
        return self.transports[-1]

    def _answer(self, request):
        self.requests.append(request)
        return httpx2.Response(200, json=self.bodies[request.url.path])


@pytest.fixture
def upstream(monkeypatch):
    upstream = Upstream()
    monkeypatch.setattr(_client, "_transport", upstream.connect)
    monkeypatch.delenv(SESSION_ENV, raising=False)
    yield upstream
    for transport in upstream.transports:
        transport.close()


@pytest.fixture
def session():
    return "s3ss10n-v4lu3"


@pytest.fixture
def client(upstream, session):
    return Client(Secret(session))
