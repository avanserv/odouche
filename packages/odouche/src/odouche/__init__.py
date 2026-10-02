"""Unofficial Python client for Odoo.sh."""

from importlib.metadata import version

from odouche._session import KEYRING_ENTRY, KEYRING_SERVICE, SESSION_ENV
from odouche.errors import (
    KeyringUnavailableError,
    NoSessionError,
    NotFoundError,
    OdoucheError,
    PermissionDeniedError,
    SessionExpiredError,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche.secret import Secret


__all__ = [
    "KEYRING_ENTRY",
    "KEYRING_SERVICE",
    "SESSION_ENV",
    "KeyringUnavailableError",
    "NoSessionError",
    "NotFoundError",
    "OdoucheError",
    "PermissionDeniedError",
    "Secret",
    "SessionExpiredError",
    "UpstreamChangedError",
    "UpstreamUnavailableError",
    "__version__",
]

__version__ = version("odouche")
