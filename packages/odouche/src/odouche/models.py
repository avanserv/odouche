"""What the library returns: its own models, not the payloads of Odoo.sh."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Project:
    """An Odoo.sh project the session's user can reach."""

    id: int
    """The number Odoo.sh gives the project."""

    name: str
    """The project's name on Odoo.sh, as in the address of its page."""

    repository: str
    """The GitHub repository the project builds, as `owner/name`."""

    url: str
    """The address of the project's page on Odoo.sh."""


class Stage(StrEnum):
    """The stage a branch sits in on Odoo.sh."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"
    """A stage the library does not know. The branch's `stage_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class Branch:
    """A branch of an Odoo.sh project."""

    id: int
    """The number Odoo.sh gives the branch."""

    name: str
    """The git branch."""

    stage: Stage
    """The stage the branch sits in now."""

    stage_name: str
    """What Odoo.sh calls that stage, such as `dev`."""
