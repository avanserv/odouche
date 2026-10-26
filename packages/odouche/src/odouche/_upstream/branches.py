"""The branches request, and the request that moves a branch to another stage."""

import logging

from odouche._upstream import builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import NotFoundError, OdoucheError, OutcomeUnknownError, StageRefusedError
from odouche.models import Branch, BranchSummary, Stage, TrackedBuild


_OPERATION = "branches"
_STAGES = {"production": Stage.PRODUCTION, "staging": Stage.STAGING, "dev": Stage.DEVELOPMENT}
NAMES = {stage: name for name, stage in _STAGES.items()}
_OPERATION_MOVE = "branch stage move"
# The only stages a move leaves or reaches, and the only wire values it sends: production is in neither.
_MOVES = {stage: NAMES[stage] for stage in (Stage.STAGING, Stage.DEVELOPMENT)}
_PRODUCTION_REASON = "changing the production branch changes what customers run, and is done in the Odoo.sh page."

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


@state_changing
def move(transport: Transport, branch_id: int, target: Stage, held: Stage | None = None) -> Branch:
    """Move a branch to `target`, once, and return it read back. `held` is the stage the caller holds, if any."""
    target = Stage(target)

    if held is not None:
        allow_move(branch_id, held, target)

    # The stage that decides is the one read now: the caller's can only refuse earlier.
    allow_move(branch_id, stage(builds.entry(transport, branch_id, 1).child("branch_info").text("stage")), target)
    transport.change(_OPERATION_MOVE, f"/app/branch/{branch_id}/set_stage", {"stage": _MOVES[target]})

    try:
        moved = branch(builds.entry(transport, branch_id, 1).child("branch_info"))
    except OdoucheError:
        moved = None

    if moved is None or moved.stage is not target:
        found = "could not be read back" if moved is None else f"reads back in {moved.stage.value}"
        # As unknown: an error that reads as a failure invites a second move.
        raise OutcomeUnknownError(
            f"The move of branch {branch_id} to {target.value} was sent, and the branch {found}. "
            "Look before trying again.",
            operation=_OPERATION_MOVE,
        )

    return moved


def allow_move(branch_id: int, source: Stage, target: Stage) -> None:
    """Raise `StageRefusedError` for a move that is not sent. Nothing is asked."""
    if source is Stage.PRODUCTION:
        msg = f"A branch in the production stage is not moved: {_PRODUCTION_REASON}"
    elif target is Stage.PRODUCTION:
        msg = f"A branch is not moved to production: {_PRODUCTION_REASON}"
    elif source not in _MOVES:
        msg = f"A branch in the {source.value} stage is not moved: only a development or a staging one is."
    elif target not in _MOVES:
        msg = f"A branch is not moved to the {target.value} stage: only to development or staging."
    elif source is target:
        msg = f"Branch {branch_id} is already in {target.value}."
    else:
        return

    raise StageRefusedError(msg, operation=_OPERATION_MOVE)
