"""`osh builds`: the builds of a branch of an Odoo.sh project."""

from datetime import datetime
from typing import Annotated

import typer

import odouche
from odouche_cli._client import open_client
from odouche_cli._context import BranchOption, ProjectOption, find_branch, resolve_branch, resolve_project
from odouche_cli._output import Column, Output
from odouche_cli._time import ago


app = typer.Typer(
    name="builds",
    help="List and show the builds of a branch.",
    epilog="Example: osh builds show",
    no_args_is_help=True,
)

_DEFAULT_LIMIT = 4

_HASH_LENGTH = 7

_RESULT_STYLES = {
    odouche.BuildResult.SUCCESS: "green",
    odouche.BuildResult.WARNING: "yellow",
    odouche.BuildResult.FAILED: "red",
}

LimitOption = Annotated[
    int,
    typer.Option("--limit", min=1, help="The most builds to list. Odoo.sh may answer fewer."),
]
BuildArgument = Annotated[
    int | None,
    typer.Argument(metavar="BUILD_ID", min=1, help="The build's number. Default: the branch's latest build."),
]


@app.command("list", epilog="Example: osh builds list --branch staging")
def list_(
    ctx: typer.Context,
    project: ProjectOption = None,
    branch: BranchOption = None,
    limit: LimitOption = _DEFAULT_LIMIT,
) -> None:
    """List a branch's latest builds, newest first."""
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        _, found = _branch(ctx, client, project, name)
        builds = client.builds(found, limit=limit)
    columns = [
        Column[odouche.Build]("ID", lambda build: build.id),
        Column[odouche.Build]("Status", _status),
        Column[odouche.Build]("Result", _result, _result_style),
        Column[odouche.Build]("Commit", lambda build: build.commit.hash[:_HASH_LENGTH]),
        Column[odouche.Build]("Subject", _subject),
        Column[odouche.Build]("Age", lambda build: _ago(build.started_at)),
    ]
    output.rows(builds, columns, empty="No builds.")


@app.command(epilog="Example: osh builds show 1234")
def show(
    ctx: typer.Context,
    build_id: BuildArgument = None,
    project: ProjectOption = None,
    branch: BranchOption = None,
) -> None:
    """Show one build of a branch: its latest, or the one numbered BUILD_ID."""
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        project_name, found = _branch(ctx, client, project, name)
        build = _build(client, project_name, found, build_id)
    columns = [
        Column[odouche.Build]("ID", lambda build: build.id),
        Column[odouche.Build]("Name", lambda build: build.name),
        Column[odouche.Build]("Branch", lambda build: build.branch_name),
        Column[odouche.Build]("Status", _status),
        Column[odouche.Build]("Result", _result, _result_style),
        Column[odouche.Build]("Info", lambda build: build.status_info),
        Column[odouche.Build]("Started", lambda build: _ago(build.started_at)),
        Column[odouche.Build]("Commit", lambda build: build.commit.hash),
        Column[odouche.Build]("Subject", _subject),
        Column[odouche.Build]("Author", lambda build: build.commit.author),
        Column[odouche.Build]("Committed", lambda build: _ago(build.commit.timestamp)),
        Column[odouche.Build]("URL", lambda build: build.url),
    ]
    output.one(build, columns)


def _branch(ctx: typer.Context, client: odouche.Client, project: str | None, name: str) -> tuple[str, odouche.Branch]:
    """Return the project's name and its branch of that name."""
    project_name = resolve_project(ctx, project, client.projects)
    return project_name, find_branch(client, project_name, name)


def _build(client: odouche.Client, project: str, branch: odouche.Branch, build_id: int | None) -> odouche.Build:
    """Return the branch's build of that number, or its latest."""
    if build_id is not None:
        for build in client.builds(branch):
            if build.id == build_id:
                return build
        msg = f"Build {build_id} is not among the latest builds of branch {branch.name} of {project}."
        raise odouche.NotFoundError(msg)
    latest = client.latest_build(branch)
    if latest is None:
        msg = f"Branch {branch.name} of {project} has no build."
        raise odouche.NotFoundError(msg)
    return latest


def _status(build: odouche.Build) -> str:
    """Return the status's name, and what Odoo.sh calls it when the library does not know it."""
    return build.status_name if build.status is odouche.BuildStatus.UNKNOWN else build.status.value


def _result(build: odouche.Build) -> str | None:
    """Return the result's name, and what Odoo.sh calls it when the library does not know it."""
    if build.result is None or build.result is odouche.BuildResult.UNKNOWN:
        return build.result_name
    return build.result.value


def _result_style(build: odouche.Build) -> str | None:
    return None if build.result is None else _RESULT_STYLES.get(build.result)


def _subject(build: odouche.Build) -> str:
    """Return the first line of the commit message."""
    lines = build.commit.message.strip().splitlines()
    return lines[0] if lines else ""


def _ago(moment: datetime | None) -> str | None:
    return None if moment is None else ago(moment)
