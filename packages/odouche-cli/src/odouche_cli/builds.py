"""`osh builds`: the builds of a branch of an Odoo.sh project."""

import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

import odouche
from odouche_cli._client import open_client
from odouche_cli._context import (
    BranchOption,
    ProjectOption,
    checkout_branch,
    checkout_head,
    checkout_is_of,
    find_branch,
    resolve_branch,
    resolve_project,
)
from odouche_cli._errors import EXIT_BUILD_FAILED, EXIT_BUILD_NO_RESULT, EXIT_BUILD_TIMEOUT, EXIT_BUILD_WARNING
from odouche_cli._output import Column, Format, Output, strip_control
from odouche_cli._time import ago, elapsed


app = typer.Typer(
    name="builds",
    help="List, show and watch the builds of a branch.",
    epilog="Example: osh builds show",
    no_args_is_help=True,
)

_DEFAULT_LIMIT = 4

_HASH_LENGTH = 7

_DEFAULT_TIMEOUT = 1800
# How long between two requests for a build of the awaited commit.
_POLL = 3.0
# The longest to wait for a build of the awaited commit to be listed.
_COMMIT_WAIT = 120.0
_COMMIT = re.compile(r"[0-9a-f]{7,64}", re.IGNORECASE)

# What the tests replace: the clock of the deadline and the wait between two requests.
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep

_RESULT_STYLES = {
    odouche.BuildResult.SUCCESS: "green",
    odouche.BuildResult.WARNING: "yellow",
    odouche.BuildResult.FAILED: "red",
}
_RESULT_EXITS = {
    odouche.BuildResult.SUCCESS: (0, "succeeded"),
    odouche.BuildResult.WARNING: (EXIT_BUILD_WARNING, "finished with warnings"),
    odouche.BuildResult.FAILED: (EXIT_BUILD_FAILED, "failed"),
}

LimitOption = Annotated[
    int,
    typer.Option("--limit", min=1, help="The most builds to list. Odoo.sh may answer fewer."),
]
BuildArgument = Annotated[
    int | None,
    typer.Argument(metavar="BUILD_ID", min=1, help="The build's number. Default: the branch's latest build."),
]
WatchedArgument = Annotated[
    int | None,
    typer.Argument(
        metavar="BUILD_ID",
        min=1,
        help="The build's number. Default: the build of HEAD when the project and the branch are the checkout's, "
        "the latest build otherwise.",
    ),
]


def _hash(value: str | None) -> str | None:
    if value is not None and not _COMMIT.fullmatch(value):
        msg = "A commit is 7 to 64 hexadecimal digits."
        raise typer.BadParameter(msg)
    return value


TimeoutOption = Annotated[
    int,
    typer.Option("--timeout", min=1, metavar="SECONDS", help="The longest to wait for the build to finish."),
]
CommitOption = Annotated[
    str | None,
    typer.Option(
        "--commit",
        metavar="SHA",
        callback=_hash,
        help="Wait for a build of this commit, given as 7 to 64 digits of its hash. "
        "Default: the git checkout's HEAD, when the project and the branch are the checkout's.",
    ),
]
NoWaitOption = Annotated[
    bool,
    typer.Option("--no-wait", help="Watch the branch's latest build, whatever its commit."),
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


@app.command(epilog="Example: git push && osh builds watch")
def watch(
    ctx: typer.Context,
    build_id: WatchedArgument = None,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    timeout: TimeoutOption = _DEFAULT_TIMEOUT,
    commit: CommitOption = None,
    no_wait: NoWaitOption = False,
) -> None:
    """Watch a build until it finishes, and exit with its result: the build of HEAD, or BUILD_ID."""
    output: Output = ctx.obj
    if commit is not None and (no_wait or build_id is not None):
        msg = "--commit goes with neither BUILD_ID nor --no-wait."
        raise typer.BadParameter(msg, ctx=ctx)
    name = resolve_branch(ctx, branch)
    deadline = _monotonic() + timeout
    with open_client() as client:
        project_name, found = _branch(ctx, client, project, name)
        awaited = commit
        # A project read from the checkout is the checkout's: only one that was named is asked about.
        if (
            awaited is None
            and not no_wait
            and build_id is None
            and name == checkout_branch()
            and (project is None or checkout_is_of(project_name, client.projects))
        ):
            awaited = checkout_head()
            if awaited is None:
                typer.echo("HEAD could not be read: watching the branch's latest build.", err=True)
        if awaited is None:
            build = _build(client, project_name, found, build_id)
        else:
            build = _await_build(client, found, awaited.lower(), min(deadline, _monotonic() + _COMMIT_WAIT))
            if build is None:
                line = (
                    f"Timed out: branch {found.name} of {project_name} has no build of commit "
                    f"{awaited[:_HASH_LENGTH]}. Push it, or watch the latest build with --no-wait."
                )
                typer.echo(strip_control(line), err=True)
                raise typer.Exit(EXIT_BUILD_TIMEOUT)
        # A build listed by the last request allowed is still watched.
        code = watch_build(client, output, project_name, build, timeout=max(deadline - _monotonic(), _POLL))
    raise typer.Exit(code)


def watch_build(client: odouche.Client, output: Output, project: str, build: odouche.Build, *, timeout: float) -> int:
    """Print a build's changes until it finishes, then its result, and return the exit code for it.

    As JSON each change is an object on stdout and the result goes to stderr. Otherwise the
    changes go to stderr, as one line kept up to date on a terminal, and the result to stdout.
    """
    last = build
    console = Console(file=sys.stderr, highlight=False)

    def changes(watched: Iterator[odouche.Build]) -> Iterator[odouche.Build]:
        nonlocal last
        for change in watched:
            last = change
            yield change

    try:
        with closing(client.watch_build(project, build, timeout=timeout)) as watched:
            if output.format is Format.JSON:
                output.stream(changes(watched), _progress)
            elif _redraws(console):
                with Live(get_renderable=lambda: Text(_progress(last)), console=console, transient=True) as live:
                    for _ in changes(watched):
                        live.refresh()
            else:
                for change in changes(watched):
                    typer.echo(_progress(change), err=True)
    except odouche.StreamTimeoutError:
        typer.echo(f"Timed out: build {build.id} has not finished.", err=True)
        return EXIT_BUILD_TIMEOUT
    return _conclude(last, as_json=output.format is Format.JSON)


def _await_build(client: odouche.Client, branch: odouche.Branch, commit: str, deadline: float) -> odouche.Build | None:
    """Return the branch's build of the commit that hash begins, or `None` when the deadline passes with none."""
    waiting = False
    while True:
        for build in client.builds(branch):
            if build.commit.hash.lower().startswith(commit):
                return build
        if not waiting:
            line = f"Waiting for a build of commit {commit[:_HASH_LENGTH]} on branch {branch.name}."
            typer.echo(strip_control(line), err=True)
            waiting = True
        remaining = deadline - _monotonic()
        if remaining <= 0:
            return None
        _sleep(min(_POLL, remaining))


def _progress(build: odouche.Build) -> str:
    """Say where a build is: its status, what it is doing, and for how long while it runs."""
    line = f"Build {build.id}: {_status(build)}"
    if build.status_info and build.status_info != _status(build):
        line += f", {build.status_info}"
    if build.started_at is not None and not build.finished:
        line += f" ({elapsed(build.started_at)})"
    return strip_control(line)


def _conclude(build: odouche.Build, *, as_json: bool) -> int:
    """Print the result of a finished build and its address, and return the exit code for it.

    A dropped build has no address left.
    """
    no_result = EXIT_BUILD_NO_RESULT, f"ended without a result ({_result(build) or _status(build)})"
    known = None if build.result is None else _RESULT_EXITS.get(build.result)
    code, said = known or no_result
    dropped = build.status is odouche.BuildStatus.DROPPED
    if dropped and known:
        said += ", then was replaced by a newer build"
    line = f"Build {build.id} {said}" + (f": {build.url}" if build.url and not dropped else ".")
    typer.echo(strip_control(line), err=as_json)
    if code == EXIT_BUILD_FAILED:
        typer.echo("Run `osh logs` to see why.", err=True)
    return code


def _stderr_is_terminal() -> bool:
    return sys.stderr.isatty()


def _redraws(console: Console) -> bool:
    """Tell whether a `Live` on that console draws: Rich needs the three, and the environment sets each."""
    return _stderr_is_terminal() and console.is_terminal and not console.is_dumb_terminal and console.is_interactive


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
