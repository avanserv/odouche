"""The branches request."""

import logging

from odouche._upstream import builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import NotFoundError
from odouche.models import Branch, BranchSummary, Stage, TrackedBuild


_OPERATION = "branches"
_STAGES = {"production": Stage.PRODUCTION, "staging": Stage.STAGING, "dev": Stage.DEVELOPMENT}
NAMES = {stage: name for name, stage in _STAGES.items()}

_logger = logging.getLogger("odouche")


def branches(transport: Transport, project: str) -> list[Branch]:
    """List the branches of the project named `project`, in the order Odoo.sh answers them."""
    technical_name = projects.technical_name(transport, project)
    if technical_name is None:
        raise NotFoundError(f"The session's user can reach no project named {project!r}.", operation=_OPERATION)
    return [branch(row) for row in listed(transport, technical_name)]


def listed(transport: Transport, technical_name: str) -> list[Reader]:
    """Return the readers of the branches of the project Odoo.sh addresses as `technical_name`."""
    path = f"/app/project/{projects.segment(technical_name)}/branches"
    return Reader(_OPERATION, transport.call(_OPERATION, path, retry=True)).items("result")


def branch(row: Reader) -> Branch:
    """Read a branch of the branches answer."""
    return Branch(
        id=row.integer("id"),
        name=row.text("name"),
        stage=stage(row.text("stage")),
        stage_name=row.text("stage"),
    )


def summary(row: Reader) -> BranchSummary:
    """Read a branch of the branches answer with its last build."""
    last = row.optional_pair("last_build_id")
    if last is None:
        return BranchSummary(branch(row), None)
    # As in the builds answer, the status and the result come without their labels.
    outcome = builds.outcome(row.text("last_build_status"), row.optional_text("last_build_result"))
    return BranchSummary(branch(row), TrackedBuild(id=last[0], **outcome))


def stage(name: str) -> Stage:
    """Return the stage Odoo.sh calls `name`."""
    known = _STAGES.get(name)
    if known is None:
        _logger.debug("Unknown branch stage: %r", name)
        return Stage.UNKNOWN
    return known
