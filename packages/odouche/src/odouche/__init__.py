"""Unofficial Python client for Odoo.sh."""

from importlib.metadata import version

from odouche._client import Client
from odouche._login import LoginStep, login
from odouche._session import KEYRING_ENTRY, KEYRING_SERVICE, SESSION_ENV
from odouche.errors import (
    KeyringUnavailableError,
    LoginError,
    LoginTimeoutError,
    NoSessionError,
    NotFoundError,
    OdoucheError,
    PermissionDeniedError,
    SessionExpiredError,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche.models import Branch, Project, Stage
from odouche.secret import Secret


__all__ = [
    "KEYRING_ENTRY",
    "KEYRING_SERVICE",
    "SESSION_ENV",
    "Branch",
    "Client",
    "KeyringUnavailableError",
    "LoginError",
    "LoginStep",
    "LoginTimeoutError",
    "NoSessionError",
    "NotFoundError",
    "OdoucheError",
    "PermissionDeniedError",
    "Project",
    "Secret",
    "SessionExpiredError",
    "Stage",
    "UpstreamChangedError",
    "UpstreamUnavailableError",
    "__version__",
    "login",
]

__version__ = version("odouche")
