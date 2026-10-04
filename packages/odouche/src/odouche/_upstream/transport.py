"""The one place a request to Odoo.sh is sent, and the session attached to it."""

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.cookiejar import DefaultCookiePolicy
from importlib.metadata import version
from typing import Self, cast

import httpx2

from odouche.errors import (
    NotFoundError,
    OdoucheError,
    PermissionDeniedError,
    SessionExpiredError,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche.secret import Secret


HOST = "www.odoo.sh"

_LOGIN_PATH = "/web/login"
_SESSION_EXPIRED = "odoo.http.SessionExpiredException"
_ACCESS_DENIED = "odoo.exceptions.AccessError"
_UNEXPLAINED = "builtins.Exception"
_SESSION_ALPHABET = re.compile(r"[A-Za-z0-9_-]+")
_TIMEOUT = httpx2.Timeout(connect=10, read=30, write=10, pool=10)
_BACKOFF = (1.0, 2.0)
_TRANSIENT = frozenset({502, 503, 504})
_DENIED = "Odoo.sh does not allow this to the session's user."
_REFUSED: dict[int, tuple[type[OdoucheError], str]] = {
    404: (NotFoundError, "Odoo.sh has nothing at this address."),
    403: (PermissionDeniedError, _DENIED),
}

_logger = logging.getLogger("odouche")


@dataclass(frozen=True, slots=True)
class _Answer:
    """What is kept of one attempt: nothing of the request, and of the response only what is read."""

    status: int | None = None
    location: str | None = None
    body: object = None
    failure: str | None = None

    @property
    def transient(self) -> bool:
        return self.status is None or self.status in _TRANSIENT


def is_unauthenticated(status: int, location: str | None, body: object) -> bool:
    """Tell whether an answer is one of the two Odoo.sh gives to a missing or expired session."""
    if status == httpx2.codes.SEE_OTHER:
        return location is not None and _is_login(location)
    return status == httpx2.codes.OK and _error_name(body) == _SESSION_EXPIRED


def is_sendable(session: Secret) -> bool:
    """Tell whether a value has the alphabet of a session, so that it is a cookie value and no more."""
    return _SESSION_ALPHABET.fullmatch(session.expose_secret()) is not None


def _error_name(body: object) -> object:
    """Return the name of the exception an answer reports, when it reports one."""
    error = cast("dict[str, object]", body).get("error") if isinstance(body, dict) else None
    data = cast("dict[str, object]", error).get("data") if isinstance(error, dict) else None
    return cast("dict[str, object]", data).get("name") if isinstance(data, dict) else None


def _is_login(location: str) -> bool:
    try:
        url = httpx2.URL(f"https://{HOST}/").join(location)
    except httpx2.InvalidURL:
        return False
    return (url.scheme, url.host, url.port, url.path) == ("https", HOST, None, _LOGIN_PATH)


def _url(path: str) -> httpx2.URL:
    url = httpx2.URL(f"https://{HOST}{path}")
    if not path.startswith("/") or path.startswith("//") or url.scheme != "https" or url.host != HOST:
        raise ValueError(f"A request path is absolute and on {HOST}")
    return url


def _unexpected(status: int, body: object) -> str | None:
    """Name the part of an answer that the upstream reference does not describe."""
    if status != httpx2.codes.OK:
        return "Location" if httpx2.codes.is_redirect(status) else "status"
    if not isinstance(body, dict):
        return "body"
    return "error.data.name" if "error" in body else None


def _error(operation: str, answer: _Answer, not_found: str | None) -> OdoucheError | None:
    status = answer.status
    if status is None:
        return UpstreamUnavailableError(f"Odoo.sh could not be reached ({answer.failure}).", operation=operation)
    if httpx2.codes.is_server_error(status) or status == httpx2.codes.TOO_MANY_REQUESTS:
        return UpstreamUnavailableError(f"Odoo.sh answered with status {status}.", operation=operation, status=status)
    if status in _REFUSED:
        cls, message = _REFUSED[status]
        return cls(message, operation=operation, status=status)
    if status == httpx2.codes.OK and _error_name(answer.body) == _ACCESS_DENIED:
        return PermissionDeniedError(_DENIED, operation=operation, status=status)
    if not_found is not None and status == httpx2.codes.OK and _error_name(answer.body) == _UNEXPLAINED:
        return NotFoundError(not_found, operation=operation, status=status)
    field = _unexpected(status, answer.body)
    return UpstreamChangedError(operation, field, status=status) if field else None


class Transport:
    """Sends requests to Odoo.sh with the session, one at a time and to `HOST` only.

    A redirect is never followed. `on_rejected` is called when Odoo.sh rejects the session, before
    `SessionExpiredError` is raised.
    """

    def __init__(
        self,
        session: Secret,
        *,
        on_rejected: Callable[[], None] = lambda: None,
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session
        self._on_rejected = on_rejected
        self._sleep = sleep
        self._lock = threading.Lock()
        self._client = httpx2.Client(
            headers={"User-Agent": f"odouche/{version('odouche')}"},
            timeout=_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )
        # Answers set `session_id` again: keeping it would hold the session as a bare string.
        self._client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connections."""
        self._client.close()

    def call(
        self,
        operation: str,
        path: str,
        params: Mapping[str, object] | None = None,
        *,
        retry: bool = False,
        not_found: str | None = None,
    ) -> dict[str, object]:
        """Send one JSON-RPC request and return the answer, which holds no `error`.

        `retry` repeats a request that failed in transit or on a gateway error. It is for reads
        only: a state-changing request sent twice is done twice.

        `not_found` is the message of the `NotFoundError` raised for the error Odoo.sh gives no
        reason for, which is its answer to a branch that does not exist. Without it that answer
        is an `UpstreamChangedError`.
        """
        url = _url(path)
        with self._lock:
            answer = self._send(url, params)
            for delay in _BACKOFF if retry else ():
                if not answer.transient:
                    break
                self._sleep(delay)
                answer = self._send(url, params)
        if answer.status is not None and is_unauthenticated(answer.status, answer.location, answer.body):
            self._on_rejected()
            raise SessionExpiredError(
                "Odoo.sh rejected the session. Log in again.", operation=operation, status=answer.status
            )
        error = _error(operation, answer, not_found)
        if error is not None:
            raise error
        return cast("dict[str, object]", answer.body)

    def _send(self, url: httpx2.URL, params: Mapping[str, object] | None) -> _Answer:
        """Make one attempt.

        A failure is returned, not raised: the client's exception holds the request, and an error
        raised while it is being handled would carry it as its context.
        """
        started = time.perf_counter()
        try:
            response = self._client.post(
                url,
                json={"jsonrpc": "2.0", "method": "call", "params": dict(params or {}), "id": 1},
                headers={"Cookie": f"session_id={self._session.expose_secret()}"},
            )
        except httpx2.RequestError as error:
            answer = _Answer(failure=type(error).__name__)
        else:
            answer = _Answer(response.status_code, response.headers.get("Location"), _json(response.content))
        elapsed = (time.perf_counter() - started) * 1000
        _logger.debug("POST %s: %s in %.0f ms", url.path, answer.status or answer.failure, elapsed)
        return answer


def _json(content: bytes) -> object:
    try:
        return json.loads(content)
    except ValueError:
        return None
