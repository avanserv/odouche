"""`osh backups`: the backups of an Odoo.sh project."""

from contextlib import closing
from typing import Annotated

import typer

import odouche
from odouche_cli import _terminal
from odouche_cli._client import open_client
from odouche_cli._context import (
    BranchOption,
    ContextError,
    ProjectOption,
    is_given,
    project_branch,
    resolve_branch,
    resolve_project,
    stage_of,
)
from odouche_cli._errors import EXIT_DECLINED
from odouche_cli._output import Column, Output, strip_control


app = typer.Typer(
    name="backups",
    help="List the backups of an Odoo.sh project, and take one.",
    epilog="Example: osh backups list --branch staging",
    no_args_is_help=True,
)

_HASH_LENGTH = 7
_TAKEN = "%Y-%m-%d %H:%M:%S"
_UNITS = ("B", "KiB", "MiB", "GiB")
_STEP = 1024
_DEFAULT_TIMEOUT = 600


def _branch(value: str | None) -> str | None:
    if value == "":
        msg = "A branch is not empty."
        raise typer.BadParameter(msg)
    return value


# Not the checkout's branch by default: the daily backups are production's.
BranchFilter = Annotated[
    str | None,
    typer.Option(
        "--branch", callback=_branch, help="List only the backups taken on this branch. Default: every branch."
    ),
]


CommentOption = Annotated[
    str | None, typer.Option("--comment", help="The comment Odoo.sh keeps with the backup, as the page's dialog asks.")
]
YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Take the backup without asking. Needed when stdin or stderr is not a terminal."),
]
WaitOption = Annotated[
    bool,
    typer.Option("--wait", help="Wait until Odoo.sh lists the backup, which takes about a minute, and show it."),
]
WaitTimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        metavar="SECONDS",
        help="The longest to wait for the backup to be listed. Goes with `--wait` only.",
    ),
]


@app.command("list", epilog="Example: osh backups list --branch staging")
def list_(ctx: typer.Context, project: ProjectOption = None, branch: BranchFilter = None) -> None:
    """List a project's backups on every branch, newest first, with the time that names each one, in UTC.

    Odoo.sh keeps a daily backup off-site as well, under the same time: that copy is `remote`, and cannot be downloaded.
    """
    output: Output = ctx.obj
    with open_client() as client:
        found = client.backups(resolve_project(ctx, project, client.projects))
    if branch is not None:
        found = [backup for backup in found if backup.branch_name == branch]
    output.rows(found, _columns(), empty="No backups.")


@app.command(epilog="Example: osh backups create --branch staging --wait")
def create(
    ctx: typer.Context,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    comment: CommentOption = None,
    yes: YesOption = False,
    wait: WaitOption = False,
    timeout: WaitTimeoutOption = _DEFAULT_TIMEOUT,
) -> None:
    """Change state on Odoo.sh: take a manual backup of a branch's latest build, which Odoo.sh keeps for 3 days.

    Only a staging or a production branch is backed up. It asks first, unless `--yes` is given.
    """
    output: Output = ctx.obj
    if is_given(ctx, "timeout") and not wait:
        msg = "--timeout goes with --wait only."
        raise typer.BadParameter(msg, ctx=ctx)
    name = resolve_branch(ctx, branch)
    if not yes and not _terminal.can_ask():
        msg = (
            "Stdin or stderr is not a terminal, so the backup cannot be confirmed. "
            "Give --yes to take it without being asked."
        )
        raise ContextError(msg, ctx=ctx)
    with open_client(writes=True) as client:
        project_name, found = project_branch(ctx, client, project, name)
        client.check_backup(found)
        latest = client.latest_build(found)
        if latest is None:
            msg = f"Branch {found.name} of {project_name} has no build to back up."
            raise odouche.NotFoundError(msg)
        for line in (
            f"Project: {project_name}",
            f"Branch: {found.name} ({stage_of(found)})",
            f"Latest build: {latest.id}, {latest.name}",
            "Odoo.sh keeps a manual backup for 3 days.",
        ):
            typer.echo(strip_control(line), err=True)
        if not yes and not _terminal.confirmed("Take a backup of this build?"):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)
        # Sent once: an error is reported, never retried.
        request = client.create_backup(project_name, found, comment=comment or "")
        typer.echo(f"A backup of build {request.build.id} was asked for.", err=True)
        listed = f"osh backups list --branch {found.name}"
        if not wait:
            typer.echo(strip_control(f"Odoo.sh lists it about a minute later: `{listed}`."), err=True)
            return
        typer.echo("Waiting for Odoo.sh to list it.", err=True)
        try:
            with closing(client.wait_for_backup(project_name, request, timeout=timeout)) as waited:
                backup = next(listed_now for listed_now in waited if listed_now is not None)
        except odouche.OdoucheError:
            typer.echo(strip_control(f"The backup may still be coming. Look with `{listed}`."), err=True)
            raise
    output.one(backup, _columns())


def _columns() -> list[Column[odouche.Backup]]:
    return [
        Column[odouche.Backup]("Taken (UTC)", lambda backup: backup.taken_at.strftime(_TAKEN)),
        Column[odouche.Backup]("Kind", lambda backup: backup.kind_name),
        Column[odouche.Backup]("Branch", lambda backup: backup.branch_name),
        Column[odouche.Backup]("Build", lambda backup: backup.build_name),
        Column[odouche.Backup]("Commit", lambda backup: backup.commit_hash[:_HASH_LENGTH]),
        Column[odouche.Backup]("Size", lambda backup: "" if backup.size is None else _size(backup.size)),
        Column[odouche.Backup]("Downloadable", lambda backup: "yes" if backup.downloadable else "no"),
    ]


def _size(size: int) -> str:
    value = float(size)
    for unit in _UNITS[:-1]:
        # Compared as shown, so 1048575 bytes is 1.0 MiB and not 1024.0 KiB.
        if round(value, 1) < _STEP:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= _STEP
    return f"{value:.1f} {_UNITS[-1]}"
