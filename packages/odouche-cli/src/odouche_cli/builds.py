"""`osh builds`: the builds of a branch of an Odoo.sh project."""

import re
import sys
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

import odouche
from odouche_cli import _terminal
from odouche_cli._client import forget_session_env, open_client
from odouche_cli._context import (
    BranchOption,
    ContextError,
    ProjectOption,
    checkout_branch,
    checkout_head,
    checkout_is_of,
    find_build,
    is_given,
    project_branch,
    resolve_branch,
    result_of,
    result_style,
    stage_of,
    status_of,
    subject,
)
from odouche_cli._errors import (
    EXIT_BUILD_FAILED,
    EXIT_BUILD_NO_RESULT,
    EXIT_BUILD_TIMEOUT,
    EXIT_BUILD_WARNING,
    EXIT_DECLINED,
    EXIT_NO_BROWSER,
)
from odouche_cli._output import Column, Format, Output, strip_control
from odouche_cli._time import ago, elapsed


app = typer.Typer(
    name="builds",
    help="List, show and watch the builds of a branch, start a new one, and open its panels.",
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

# What the tests replace: the clock of the deadline, the wait between two requests and the browser.
_monotonic: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep
_browse: Callable[[str], bool] = webbrowser.open_new_tab

_RESULT_EXITS = {
    odouche.BuildResult.SUCCESS: (0, "succeeded"),
    odouche.BuildResult.WARNING: (EXIT_BUILD_WARNING, "finished with warnings"),
    odouche.BuildResult.FAILED: (EXIT_BUILD_FAILED, "failed"),
}

LimitOption = Annotated[
    int,
    typer.Option(
        "--limit",
        min=1,
        help="The most builds to list. Odoo.sh has only been seen to answer up to 4: older builds are out of reach.",
    ),
]
BuildArgument = Annotated[
    int | None,
    typer.Argument(
        metavar="BUILD_ID",
        min=1,
        help="The build's number, among the branch's latest builds. Default: the latest one.",
    ),
]
WatchedArgument = Annotated[
    int | None,
    typer.Argument(
        metavar="BUILD_ID",
        min=1,
        help="The build's number, among the branch's latest builds. "
        "Default: the build of HEAD when the project and the branch are the checkout's, the latest build otherwise.",
    ),
]


def _hash(value: str | None) -> str | None:
    if value is not None and not _COMMIT.fullmatch(value):
        msg = "A commit is 7 to 64 hexadecimal digits."
        raise typer.BadParameter(msg)
    return value


TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout", min=1, metavar="SECONDS", help="The longest to wait for the build to appear and to finish."
    ),
]
CommitOption = Annotated[
    str | None,
    typer.Option(
        "--commit",
        metavar="SHA",
        callback=_hash,
        help="Wait for a build of this commit, given as the first 7 to 64 digits of its hash. "
        "Default: the git checkout's HEAD, when the project and the branch are the checkout's. "
        "Goes with neither BUILD_ID nor `--no-wait`.",
    ),
]
NoWaitOption = Annotated[
    bool,
    typer.Option("--no-wait", help="Watch the branch's latest build, whatever its commit."),
]
YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Rebuild without asking. Needed when stdin or stderr is not a terminal."),
]
WatchOption = Annotated[
    bool,
    typer.Option("--watch", help="Watch the new build until it finishes, and exit with its result."),
]
WatchTimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        metavar="SECONDS",
        help="The longest to wait for the new build to finish. Goes with `--watch` only.",
    ),
]
PanelArgument = Annotated[
    odouche.Panel,
    typer.Argument(
        metavar="PANEL",
        help="The panel: the branch's monitor, or the shell or the editor on the build's own host.",
    ),
]
OpenOption = Annotated[
    bool,
    typer.Option(
        "--open",
        help="Open the panel in your default browser rather than print its URL. "
        "The browser signs in to Odoo.sh on its own.",
    ),
]


@app.command("list", epilog="Example: osh builds list --branch staging")
def list_(
    ctx: typer.Context,
    project: ProjectOption = None,
    branch: BranchOption = None,
    limit: LimitOption = _DEFAULT_LIMIT,
) -> None:
    """List a branch's latest builds, newest first, with their status, result and commit."""
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        _, found = project_branch(ctx, client, project, name)
        builds = client.builds(found, limit=limit)
    columns = [
        Column[odouche.Build]("ID", lambda build: build.id),
        Column[odouche.Build]("Status", status_of),
        Column[odouche.Build]("Result", result_of, result_style),
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
    """Show one build of a branch, with its commit and the address of its database: its latest, or BUILD_ID."""
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        project_name, found = project_branch(ctx, client, project, name)
        build = find_build(client, project_name, found, build_id)
    output.one(build, _build_columns())


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
        project_name, found = project_branch(ctx, client, project, name)
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
            build = find_build(client, project_name, found, build_id)
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


@app.command(epilog="Example: osh builds rebuild --watch")
def rebuild(
    ctx: typer.Context,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    yes: YesOption = False,
    then_watch: WatchOption = False,
    timeout: WatchTimeoutOption = _DEFAULT_TIMEOUT,
) -> None:
    """Change state on Odoo.sh: start a new build of a branch, which replaces its latest one.

    Only a development or a staging branch is rebuilt. It asks first, unless `--yes` is given.
    """
    output: Output = ctx.obj
    if is_given(ctx, "timeout") and not then_watch:
        msg = "--timeout goes with --watch only."
        raise typer.BadParameter(msg, ctx=ctx)
    name = resolve_branch(ctx, branch)
    if not yes and not _terminal.can_ask():
        msg = (
            "Stdin or stderr is not a terminal, so the rebuild cannot be confirmed. "
            "Give --yes to rebuild without being asked."
        )
        raise ContextError(msg, ctx=ctx)
    with open_client(writes=True) as client:
        project_name, found = project_branch(ctx, client, project, name)
        client.check_rebuild(found)
        latest = client.latest_build(found)
        for line in _rebuilt(project_name, found, latest):
            typer.echo(strip_control(line), err=True)
        if not yes and not _terminal.confirmed("Start a new build of this branch?"):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)
        # Sent once: an error is reported, never retried.
        started = client.rebuild(found)
        typer.echo(f"Build {started.id} was started.", err=True)
        if not then_watch:
            output.one(started, _build_columns())
            return
        try:
            code = watch_build(client, output, project_name, started, timeout=timeout)
        except odouche.OdoucheError:
            typer.echo(
                f"Build {started.id} may still be running. Follow it with `osh builds watch {started.id}`.", err=True
            )
            raise
    raise typer.Exit(code)


@app.command("open", epilog="Example: osh builds open shell --open")
def open_(
    ctx: typer.Context,
    panel: PanelArgument,
    build_id: BuildArgument = None,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    then_open: OpenOption = False,
) -> None:
    """Print the URL of a build's monitor, shell or editor: of its latest build, or BUILD_ID.

    The monitor is the branch's, for a staging or a production branch, and takes no BUILD_ID.
    """
    output: Output = ctx.obj
    if panel is odouche.Panel.MONITOR and build_id is not None:
        msg = "The monitor is the branch's: it takes no BUILD_ID."
        raise typer.BadParameter(msg, ctx=ctx)
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        project_name, found = project_branch(ctx, client, project, name)
        build = find_build(client, project_name, found, build_id)
        url = client.panel_url(project_name, found, build, panel)
    if not then_open:
        output.stream([url], str)
        return
    forget_session_env()
    if _browse(url):
        typer.echo(f"Sent the {panel.value} of build {build.id} to your browser.", err=True)
        return
    typer.echo("No browser could be started. Open this URL yourself:", err=True)
    output.stream([url], str)
    raise typer.Exit(EXIT_NO_BROWSER)


def _rebuilt(project: str, branch: odouche.Branch, latest: odouche.Build | None) -> list[str]:
    """Say what a rebuild is about to work on: the project, the branch and its latest build."""
    build = "none"
    if latest is not None:
        build = f"{latest.id}, of commit {latest.commit.hash[:_HASH_LENGTH]} {_subject(latest)}".rstrip()
    return [f"Project: {project}", f"Branch: {branch.name} ({stage_of(branch)})", f"Latest build: {build}"]


def _build_columns() -> list[Column[odouche.Build]]:
    """Return the columns that show one build."""
    return [
        Column[odouche.Build]("ID", lambda build: build.id),
        Column[odouche.Build]("Name", lambda build: build.name),
        Column[odouche.Build]("Branch", lambda build: build.branch_name),
        Column[odouche.Build]("Status", status_of),
        Column[odouche.Build]("Result", result_of, result_style),
        Column[odouche.Build]("Info", lambda build: build.status_info),
        Column[odouche.Build]("Started", lambda build: _ago(build.started_at)),
        Column[odouche.Build]("Commit", lambda build: build.commit.hash),
        Column[odouche.Build]("Subject", _subject),
        Column[odouche.Build]("Author", lambda build: build.commit.author),
        Column[odouche.Build]("Committed", lambda build: _ago(build.commit.timestamp)),
        Column[odouche.Build]("URL", lambda build: build.url),
    ]


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
            elif _terminal.redraws(console):
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
    line = f"Build {build.id}: {status_of(build)}"
    if build.status_info and build.status_info != status_of(build):
        line += f", {build.status_info}"
    if build.started_at is not None and not build.finished:
        line += f" ({elapsed(build.started_at)})"
    return strip_control(line)


def _conclude(build: odouche.Build, *, as_json: bool) -> int:
    """Print the result of a finished build and its address, and return the exit code for it.

    A dropped build has no address left.
    """
    no_result = EXIT_BUILD_NO_RESULT, f"ended without a result ({result_of(build) or status_of(build)})"
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


def _subject(build: odouche.Build) -> str:
    return subject(build.commit.message)


def _ago(moment: datetime | None) -> str | None:
    return None if moment is None else ago(moment)
