"""Unofficial Python client for Odoo.sh."""

from importlib.metadata import version

from odouche.secret import Secret


__all__ = ["Secret", "__version__"]

__version__ = version("odouche")
