"""`osh branches`: the branches of an Odoo.sh project."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

import typer

import odouche
from odouche_cli import _settings, _terminal
from odouche_cli._client import open_client
from odouche_cli._context import (
    BranchOption,
    BuildOption,
    ProjectOption,
    checkout_branch,
    find_build,
    project_branch,
    resolve_branch,
    resolve_project,
    result_of,
    result_style,
    stage_of,
    status_of,
    subject,
)
from odouche_cli._errors import EXIT_DECLINED
from odouche_cli._output import Column, Format, Output, strip_control
from odouche_cli._settings import quoted, shown
from odouche_cli._time import ago


app = typer.Typer(
    name="branches",
    help="List the branches of an Odoo.sh project, a branch's history, show and change its settings, and the "
    "revision a build runs.",
    epilog="Example: osh branches list --stage staging",
    no_args_is_help=True,
)
settings_app = typer.Typer(
    name="settings",
    help="Show a branch's settings, or change them.",
    epilog="Example: osh branches settings show --branch staging",
    no_args_is_help=True,
)
app.add_typer(settings_app)

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
SettingsArgument = Annotated[
    list[str],
    typer.Argument(
        metavar="NAME=VALUE...",
        show_default=False,
        help="A setting and its new value, named as `osh branches settings show --format json` prints them.",
    ),
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


_SETTINGS = [
    Column[odouche.BranchSettings]("On new commit", lambda read: read.push_behavior.value),
    Column[odouche.BranchSettings]("Project defaults", lambda read: shown(read.project_defaults)),
    Column[odouche.BranchSettings]("Install", lambda read: shown(read.module_install)),
    Column[odouche.BranchSettings]("Modules", lambda read: shown(read.modules)),
    Column[odouche.BranchSettings]("Tests", lambda read: shown(read.tests)),
    Column[odouche.BranchSettings]("Test tags", lambda read: shown(read.test_tags)),
    Column[odouche.BranchSettings]("Demo data", lambda read: shown(read.demo_data)),
    Column[odouche.BranchSettings]("AI agent", lambda read: shown(read.ai_agent)),
    Column[odouche.BranchSettings]("Odoo version", lambda read: read.odoo_version or "the project's"),
    Column[odouche.BranchSettings](
        "Revision id", lambda read: "latest" if read.odoo_revision_id is None else read.odoo_revision_id
    ),
    Column[odouche.BranchSettings]("OS", lambda read: read.machine),
    Column[odouche.BranchSettings]("Recommended OS", lambda read: read.recommended_machine),
    Column[odouche.BranchSettings]("OS on next commit", lambda read: read.next_machine),
    Column[odouche.BranchSettings]("Domains", lambda read: ", ".join(read.domains)),
    Column[odouche.BranchSettings]("DNS target", lambda read: read.dns_target),
]


@settings_app.command(epilog="Example: osh branches settings show --branch staging")
def show(ctx: typer.Context, project: ProjectOption = None, branch: BranchOption = None) -> None:
    """Show a branch's settings, one per line, as its Settings tab has them.

    The new build options, from `Project defaults` to `AI agent`, apply to a development branch only, and not while it uses the project's defaults.
    """
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        _, found = project_branch(ctx, client, project, name)
        read = client.branch_settings(found)
    output.one(read, _SETTINGS)


@settings_app.command("set", epilog="Example: osh branches settings set --branch feature-x ai_agent=opencode")
def set_(
    ctx: typer.Context,
    settings: SettingsArgument,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    yes: _settings.YesOption = False,
) -> None:
    """Change state on Odoo.sh: change a branch's settings, sending only those given.

    The others keep their value. NAME is one of push_behavior, project_defaults, module_install, modules, tests, test_tags, demo_data and ai_agent. A choice takes a value `show --format json` prints, a yes or no takes `yes` or `no`, `modules` takes names separated by commas, and `test_tags=` clears the tags. Only a development branch has new build options, and while the project's defaults apply they are changed with `project_defaults=no` too. What a new commit does is not changed on a production branch. It asks first, unless `--yes` is given.
    """
    output: Output = ctx.obj
    change = _settings.built(ctx, lambda: odouche.SettingsChange(**_settings.given(ctx, settings, _READS)))  # pyright: ignore[reportArgumentType]
    name = resolve_branch(ctx, branch)
    _settings.can_ask(ctx, yes=yes)
    with open_client(writes=True) as client:
        project_name, found = project_branch(ctx, client, project, name)
        current = client.branch_settings(found)
        narrowed = _settings.checked(ctx, lambda: client.check_settings_change(found, current, change))
        for line in _changing(project_name, found, current, change, narrowed):
            _settings.say(line)
        if narrowed is None:
            typer.echo("Nothing was sent: every setting already has that value.", err=True)
            output.one(current, _SETTINGS)
            return
        if not yes and not _terminal.confirmed("Change these settings of this branch?"):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)
        # Sent once: an error is reported, never retried.
        outcome = _settings.checked(ctx, lambda: client.change_branch_settings(found, narrowed))
        typer.echo("The settings were changed.", err=True)
        _settings.say_moved(outcome)
    output.one(outcome.after, _SETTINGS)


# How a setting given on the command line is read, by its name in `BranchSettings`.
_READS: dict[str, _settings.Read] = {
    "push_behavior": _settings.choice(odouche.PushBehavior),
    "project_defaults": _settings.flag,
    "module_install": _settings.choice(odouche.ModuleInstall),
    "modules": _settings.names,
    "tests": _settings.choice(odouche.BuildTests),
    "test_tags": _settings.text,
    "demo_data": _settings.flag,
    "ai_agent": _settings.choice(odouche.AiAgent),
}


def _changing(
    project: str,
    branch: odouche.Branch,
    current: odouche.BranchSettings,
    change: odouche.SettingsChange,
    narrowed: odouche.SettingsChange | None,
) -> list[str]:
    """Say what a change is about to work on: the project, the branch, and each setting from its value to the new one.

    A setting is already at its value when the library leaves it out of what it sends.
    """
    sent = {} if narrowed is None else narrowed.given()
    lines = [f"Project: {project}", f"Branch: {branch.name} ({stage_of(branch)})"]
    for name, value in change.given().items():
        before, after = quoted(getattr(current, name)), quoted(value)
        lines.append(f"{name}: {before} → {after}" if name in sent else f"{name} is already {after}.")
    return lines


_REVISION = [
    Column[odouche.BuildRevision]("Build", lambda read: read.build_id),
    Column[odouche.BuildRevision]("Name", lambda read: read.build_name),
    Column[odouche.BuildRevision]("Branch", lambda read: read.branch_name),
    Column[odouche.BuildRevision]("Commit", lambda read: read.commit.hash),
    Column[odouche.BuildRevision]("Subject", lambda read: subject(read.commit.message)),
    Column[odouche.BuildRevision]("Author", lambda read: read.commit.author),
    Column[odouche.BuildRevision]("Committed", lambda read: ago(read.commit.timestamp)),
    Column[odouche.BuildRevision]("Commit URL", lambda read: read.commit.url),
    Column[odouche.BuildRevision]("Odoo version", lambda read: read.odoo_version),
    Column[odouche.BuildRevision]("Branch's Odoo revision", lambda read: _selection(read.branch_odoo_revision)),
]


@app.command(epilog="Example: osh branches revision --branch staging")
def revision(
    ctx: typer.Context, project: ProjectOption = None, branch: BranchOption = None, *, build_id: BuildOption = None
) -> None:
    """Show what a build of a branch runs: its head commit, its Odoo version, and the Odoo revision the branch has selected. The latest build, or `--build`.

    Odoo.sh ties no Odoo revision to a build: the branch's is the one it has selected now, which the build may not run. Odoo.sh gives no commit for a submodule, and a line on stderr says so.
    """
    output: Output = ctx.obj
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        project_name, found = project_branch(ctx, client, project, name)
        read = client.build_revision(project_name, find_build(client, project_name, found, build_id))
    output.one(read, _revision_columns(read))
    typer.echo("Submodule commits are not available: Odoo.sh does not give them.", err=True)


def _revision_columns(read: odouche.BuildRevision) -> list[Column[odouche.BuildRevision]]:
    refs = () if read.branch_odoo_revision is None else read.branch_odoo_revision.refs
    return [*_REVISION, *map(_ref_column, refs)]


def _ref_column(ref: odouche.OdooRef) -> Column[odouche.BuildRevision]:
    # The repository's name is Odoo.sh's, and `Output.one` prints a header as it is.
    return Column[odouche.BuildRevision](strip_control(f"Branch's {ref.repository}"), lambda _: ref.commit_hash)


def _selection(selected: odouche.OdooRevision | None) -> str:
    if selected is None:
        return "none"
    if selected.pinned:
        return f"{selected.id}, pinned, {selected.version}"
    return f"{selected.id}, latest of {selected.version}"


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
