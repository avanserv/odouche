"""How a setting's value is shown, the same for a project's and a branch's."""

from enum import StrEnum


def shown(value: object) -> str:
    """Return a setting's value: `yes` or `no`, an enumeration's value, a list joined by commas, and nothing as `none`."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value) or "none"
    return str(value) if value else "none"
