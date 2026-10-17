"""`osh branches`: the branches of an Odoo.sh project."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

import typer

import odouche
from odouche_cli._client import open_client
from odouche_cli._context import (
    BranchOption,
    ProjectOption,
    checkout_branch,
    project_branch,
    resolve_branch,
    resolve_project,
    result_of,
    result_style,
    stage_of,
    status_of,
    subject,
)
from odouche_cli._output import Column, Format, Output
from odouche_cli._time import ago


app = typer.Typer(
    name="branches",
    help="List the branches of an Odoo.sh project, and a branch's history.",
    epilog="Example: osh branches list --stage staging",
    no_args_is_help=True,
)

_STAGE_ORDER = {odouche.Stage.PRODUCTION: 0, odouche.Stage.STAGING: 1, odouche.Stage.DEVELOPMENT: 2}

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 200
# For the history pages, one request each: ten at most.
_TIMEOUT = 60.0
_HASH_LENGTH = 7
_INDENT = "    "

StageOption = Annotated[
    list[odouche.Stage] | None,
    typer.Option(
        "--stage",
        help="List only the branches in this stage. Can be given more than once. "
        "`unknown` is any stage `osh` does not know.",
    ),
]

LimitOption = Annotated[
    int, typer.Option("--limit", min=1, max=_MAX_LIMIT, help=f"The most events to list, {_MAX_LIMIT} at most.")
]
CommitsOption = Annotated[
    bool,
    typer.Option("--commits", help="Print each commit in full: its whole hash, its address and its whole message."),
]


@app.command("list", epilog="Example: osh branches list --stage staging")
def list_(ctx: typer.Context, project: ProjectOption = None, stage: StageOption = None) -> None:
    """List a project's branches with their stage: production, staging, then development, each sorted by name.

    A stage `osh` does not know is shown as Odoo.sh names it, after the others. In the table, `*` marks the branch checked out, when the project comes from the git checkout.
    """
    output: Output = ctx.obj
    with open_client() as client:
        found = client.branches(resolve_project(ctx, project, client.projects))
    if stage:
        found = [branch for branch in found if branch.stage in stage]
    found.sort(key=lambda branch: (_STAGE_ORDER.get(branch.stage, len(_STAGE_ORDER)), branch.name))
    # A project given by name may not be the checkout's.
    current = checkout_branch() if project is None and output.format is Format.TABLE else None
    columns = [
        Column[odouche.Branch]("", lambda branch: "*" if branch.name == current else ""),
        Column[odouche.Branch]("Name", lambda branch: branch.name),
        Column[odouche.Branch]("Stage", stage_of),
    ]
    output.rows(found, columns, empty="No branches.")


@dataclass(frozen=True, slots=True)
class _Row:
    """One line of the history table: an event's first line, or one more of its commits."""

    tracking: odouche.Tracking
    commit: odouche.PushedCommit | None
    first: bool


@app.command(epilog="Example: osh branches history --branch staging --limit 30")
def history(
    ctx: typer.Context,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    limit: LimitOption = _DEFAULT_LIMIT,
    commits: CommitsOption = False,
) -> None:
    """List a branch's history, newest first: each push with its commits, each rebuild and each move between stages.

    A push lists each commit by its short hash and the first line of its message, and `--commits` prints them in full. The build is the one the event made, as it is now: `osh builds show` has the rest of it.
    """
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        _, found = project_branch(ctx, client, project, name)
        events = list(client.history(found, limit=limit, timeout=_TIMEOUT))
    if output.format is Format.JSON:
        output.rows(events, [], empty="No history.")
    elif commits and events:
        output.lines(_full(events), lambda line: line)
    else:
        columns = [
            Column[_Row]("When", lambda row: ago(row.tracking.created_at) if row.first else None),
            Column[_Row]("Kind", lambda row: _kind(row.tracking) if row.first else None),
            Column[_Row]("Build", lambda row: _build(row, lambda build: build.id)),
            Column[_Row]("Status", lambda row: _build(row, status_of)),
            Column[_Row]("Result", lambda row: _build(row, result_of), lambda row: _build(row, result_style)),
            Column[_Row]("By", lambda row: row.tracking.pusher if row.first else None),
            Column[_Row]("Change", _change),
        ]
        output.rows(_rows(events), columns, empty="No history.")


def _rows(events: list[odouche.Tracking]) -> Iterator[_Row]:
    for tracking in events:
        if not tracking.commits:
            yield _Row(tracking, None, first=True)
        for at, commit in enumerate(tracking.commits):
            yield _Row(tracking, commit, first=at == 0)


def _kind(tracking: odouche.Tracking) -> str:
    """Return the kind's name, and what Odoo.sh calls it when the library does not know it."""
    return tracking.kind_name if tracking.kind is odouche.TrackingKind.UNKNOWN else tracking.kind.value


def _build[T](row: _Row, value: Callable[[odouche.TrackedBuild], T]) -> T | None:
    build = row.tracking.build
    return value(build) if row.first and build is not None else None


def _change(row: _Row) -> str | None:
    if row.commit is not None:
        return f"{row.commit.hash[:_HASH_LENGTH]} {subject(row.commit.message)}".rstrip()
    return _moved(row.tracking)


def _moved(tracking: odouche.Tracking) -> str | None:
    """Say how a branch moved between stages, or `None` for an event that moved it nowhere."""
    source, target = tracking.source_stage, tracking.target_stage
    if target is None:
        return None
    if source is None:
        return f"created in {target.value}"
    return f"{source.value} → {target.value}"


def _full(events: list[odouche.Tracking]) -> Iterator[str]:
    """Return each event on a line of its own, then each of its commits in full, as `git log` does."""
    for at, tracking in enumerate(events):
        if at:
            yield ""
        said = [_kind(tracking), ago(tracking.created_at)]
        if tracking.pusher is not None:
            said.append(f"by {tracking.pusher}")
        if tracking.build is not None:
            outcome = " ".join(filter(None, [status_of(tracking.build), result_of(tracking.build)]))
            said.append(f"build {tracking.build.id} {outcome}")
        moved = _moved(tracking)
        if moved is not None:
            said.append(moved)
        yield ", ".join(said)
        for commit in tracking.commits:
            yield ""
            yield f"{_INDENT}commit {commit.hash}"
            yield f"{_INDENT}{commit.url}"
            yield ""
            yield from (f"{_INDENT * 2}{line}".rstrip() for line in commit.message.strip().splitlines())
