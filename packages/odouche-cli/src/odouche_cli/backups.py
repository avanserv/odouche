"""`osh backups`: the backups of an Odoo.sh project."""

import os
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

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
from odouche_cli._errors import EXIT_DECLINED, EXIT_NOT_WRITTEN
from odouche_cli._output import Column, Output, strip_control


app = typer.Typer(
    name="backups",
    help="List the backups of an Odoo.sh project, take one, and download one.",
    epilog="Example: osh backups list --branch staging",
    no_args_is_help=True,
)

_HASH_LENGTH = 7
_TAKEN = "%Y-%m-%d %H:%M:%S"
_UNITS = ("B", "KiB", "MiB", "GiB")
_STEP = 1024
_DEFAULT_TIMEOUT = 600
_LATEST = "latest"
# `O_BINARY` is Windows' alone, where without it the zip would be written as text.
_CREATE_PRIVATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
_PRIVATE = 0o600


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


BackupArgument = Annotated[
    str | None,
    typer.Argument(
        metavar="[BACKUP]",
        help="The time that names the backup, in UTC, as `osh backups list` shows it, or `latest`: the newest that "
        "can be downloaded. Default: latest.",
    ),
]
OutputOption = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        metavar="PATH",
        dir_okay=False,
        help="The file to write, which must not exist yet. Needed unless `--link` is given.",
    ),
]
LinkOption = Annotated[
    bool,
    typer.Option(
        "--link",
        help="Print the page's link to the prepared file instead of downloading it. It opens only in a browser signed "
        "in to Odoo.sh.",
    ),
]
ExactOption = Annotated[
    bool, typer.Option("--exact", help="The exact database, rather than the neutralized one the page offers first.")
]
NoFilestoreOption = Annotated[bool, typer.Option("--no-filestore", help="Leave the filestore out of the file.")]
NewOption = Annotated[
    bool, typer.Option("--new", help="Take a backup of the branch's latest build first, and download that one.")
]
DownloadYesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Change state without asking. Needed when stdin or stderr is not a terminal."),
]
DownloadTimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        metavar="SECONDS",
        help="The longest to wait for the backup, with `--new`, and for the file, each.",
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


@app.command(epilog="Example: osh backups download --branch staging --output staging.zip")
def download(
    ctx: typer.Context,
    backup: BackupArgument = None,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    output: OutputOption = None,
    link: LinkOption = False,
    exact: ExactOption = False,
    no_filestore: NoFilestoreOption = False,
    new: NewOption = False,
    yes: DownloadYesOption = False,
    timeout: DownloadTimeoutOption = _DEFAULT_TIMEOUT,
) -> None:
    """Change state on Odoo.sh: have it prepare a backup's file, then write it to `--output`, or print its link.

    The file is a zip of the database, neutralized unless `--exact` is given, and of its filestore unless
    `--no-filestore` is. It is customer data: it is written readable by its owner alone, and deleting it is yours to do.
    It asks first, unless `--yes` is given.
    """
    taken = _download_usage(ctx, backup, output, link=link, new=new)
    name = resolve_branch(ctx, branch)
    if not yes and not _terminal.can_ask():
        msg = (
            "Stdin or stderr is not a terminal, so the change cannot be confirmed. "
            "Give --yes to make it without being asked."
        )
        raise ContextError(msg, ctx=ctx)
    neutralized, filestore = not exact, not no_filestore
    with open_client(writes=True) as client:
        project_name, found = project_branch(ctx, client, project, name)
        if new:
            client.check_backup(found)
            latest = client.latest_build(found)
            if latest is None:
                msg = f"Branch {found.name} of {project_name} has no build to back up."
                raise odouche.NotFoundError(msg)
            chosen = ready = None
            described = f"Backup: a new one of build {latest.id}, {latest.name}"
        else:
            chosen = _chosen(client.backups(project_name), found, taken)
            ready = client.find_download(project_name, chosen, neutralized=neutralized, filestore=filestore)
            described = (
                f"Backup: {chosen.taken_at.strftime(_TAKEN)} UTC, {chosen.kind_name}, of build {chosen.build_name}"
            )
        for line in (
            f"Project: {project_name}",
            f"Branch: {found.name} ({stage_of(found)})",
            described,
            f"Database: {'neutralized' if neutralized else 'exact'}, {'with' if filestore else 'without'} the filestore",
            f"To: {output}" if output else "To: the link, printed",
            "Odoo.sh already holds this file: nothing is prepared."
            if ready
            else "Odoo.sh keeps a prepared file for 2 hours."
            + (" It keeps a manual backup for 3 days." if new else ""),
        ):
            typer.echo(strip_control(line), err=True)
        prepared = ready or _prepare(
            client, project_name, found, chosen, yes=yes, timeout=timeout, choices=(neutralized, filestore)
        )
        if output is None:
            typer.echo(strip_control(prepared.link))
            return
        _write(client, prepared, output)
    typer.echo(strip_control(f"Wrote {output}. It holds customer data: delete it once you are done with it."), err=True)


def _prepare(
    client: odouche.Client,
    project: str,
    branch: odouche.Branch,
    chosen: odouche.Backup | None,
    *,
    yes: bool,
    timeout: int,
    choices: tuple[bool, bool],
) -> odouche.PreparedDownload:
    """Ask, then have Odoo.sh prepare the file, of a new backup when none is `chosen`, and wait for it."""
    question = "Take a backup and prepare its file?" if chosen is None else "Prepare the file of this backup?"
    if not yes and not _terminal.confirmed(question):
        typer.echo("Nothing was sent.", err=True)
        raise typer.Exit(EXIT_DECLINED)
    if chosen is None:
        chosen = _new_backup(client, project, branch, timeout)
    neutralized, filestore = choices
    prepared = client.prepare_download(project, chosen, neutralized=neutralized, filestore=filestore)
    typer.echo("Waiting for Odoo.sh to prepare the file.", err=True)
    with closing(client.wait_for_download(project, prepared, timeout=timeout)) as waited:
        for _ in waited:
            pass
    return prepared


def _download_usage(
    ctx: typer.Context, backup: str | None, output: Path | None, *, link: bool, new: bool
) -> datetime | None:
    """Refuse a combination that cannot be downloaded, before anything is asked. Return the time asked for, if any."""
    if output is None and not link:
        msg = "Give --output PATH to write the file to, or --link to print its link: there is no default place."
        raise ContextError(msg, ctx=ctx)
    if output is not None and link:
        msg = "--output and --link do not go together."
        raise ContextError(msg, ctx=ctx)
    if output is not None and (output.exists() or output.is_symlink()):
        msg = f"{output} already exists, and is never written over."
        raise ContextError(strip_control(msg), ctx=ctx)
    if output is not None and not output.parent.is_dir():
        msg = f"{output.parent} is not a directory."
        raise ContextError(strip_control(msg), ctx=ctx)
    # Before Odoo.sh is asked to prepare anything.
    if output is not None and not os.access(output.parent, os.W_OK):
        msg = f"You cannot write to {output.parent}."
        raise ContextError(strip_control(msg), ctx=ctx)
    if new and backup is not None:
        msg = "BACKUP and --new do not go together: --new downloads the backup it takes."
        raise ContextError(msg, ctx=ctx)
    if backup is None or backup == _LATEST:
        return None
    try:
        return datetime.strptime(backup, _TAKEN).replace(tzinfo=UTC)
    except ValueError:
        msg = f"A backup is named by its time, such as '2026-10-14 12:48:50', or {_LATEST!r}."
        raise typer.BadParameter(msg, ctx=ctx, param_hint="BACKUP") from None


def _chosen(listed: list[odouche.Backup], branch: odouche.Branch, taken: datetime | None) -> odouche.Backup:
    """Return the branch's backup taken at `taken`, or its newest that can be downloaded."""
    mine = [backup for backup in listed if backup.branch_name == branch.name]
    if taken is not None:
        mine = [backup for backup in mine if backup.taken_at == taken]
    # A `remote` backup shares its time with the `daily` one it is a copy of.
    downloadable = [backup for backup in mine if backup.downloadable]
    if downloadable:
        return downloadable[0]
    if mine:
        msg = (
            f"Backup {mine[0].taken_at.strftime(_TAKEN)} of branch {branch.name} is {mine[0].kind_name}: "
            "Odoo.sh does not let it be downloaded."
        )
    elif taken is not None:
        msg = (
            f"Branch {branch.name} has no backup taken at {taken.strftime(_TAKEN)} UTC. `osh backups list` lists them."
        )
    else:
        msg = f"Branch {branch.name} has no backup that can be downloaded."
    raise odouche.NotFoundError(strip_control(msg))


def _new_backup(client: odouche.Client, project: str, branch: odouche.Branch, timeout: int) -> odouche.Backup:
    # Sent once: an error is reported, never retried.
    request = client.create_backup(project, branch)
    typer.echo(f"A backup of build {request.build.id} was asked for. Waiting for Odoo.sh to list it.", err=True)
    try:
        with closing(client.wait_for_backup(project, request, timeout=timeout)) as waited:
            return next(listed for listed in waited if listed is not None)
    except odouche.OdoucheError:
        listed = f"osh backups list --branch {branch.name}"
        typer.echo(strip_control(f"The backup may still be coming. Look with `{listed}`."), err=True)
        raise


def _write(client: odouche.Client, prepared: odouche.PreparedDownload, path: Path) -> None:
    """Write the file at `path`, created for its owner alone, and remove what was written when it fails."""
    try:
        descriptor = os.open(path, _CREATE_PRIVATE, _PRIVATE)
    except FileExistsError:
        msg = f"{path} already exists, and is never written over."
        raise ContextError(strip_control(msg)) from None
    except OSError as error:
        msg = f"{path} cannot be created: {error.strerror}."
        raise ContextError(strip_control(msg)) from None
    console = Console(file=sys.stderr, highlight=False)
    written = 0
    try:
        with os.fdopen(descriptor, "wb") as file, client.download(prepared) as body:
            if _terminal.redraws(console):
                with Live(get_renderable=lambda: Text(_written(written, body.size)), console=console, transient=True):
                    for chunk in body.chunks:
                        written += file.write(chunk)
            else:
                for chunk in body.chunks:
                    written += file.write(chunk)
    # An interrupt too: a partial file is never left behind.
    except BaseException as error:
        path.unlink(missing_ok=True)
        if not isinstance(error, OSError):
            raise
        typer.echo(strip_control(f"{path} could not be written: {error.strerror}. Nothing of it is left."), err=True)
        raise typer.Exit(EXIT_NOT_WRITTEN) from None


def _written(written: int, size: int | None) -> str:
    return f"Downloaded {_size(written)}" + ("" if size is None else f" of {_size(size)}")


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
