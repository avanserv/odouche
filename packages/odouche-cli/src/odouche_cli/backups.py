"""`osh backups`: the backups of an Odoo.sh project."""

from typing import Annotated

import typer

import odouche
from odouche_cli._client import open_client
from odouche_cli._context import ProjectOption, resolve_project
from odouche_cli._output import Column, Output


app = typer.Typer(
    name="backups",
    help="List the backups of an Odoo.sh project.",
    epilog="Example: osh backups list --branch staging",
    no_args_is_help=True,
)

_HASH_LENGTH = 7
_TAKEN = "%Y-%m-%d %H:%M:%S"
_UNITS = ("B", "KiB", "MiB", "GiB")
_STEP = 1024


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
    columns = [
        Column[odouche.Backup]("Taken (UTC)", lambda backup: backup.taken_at.strftime(_TAKEN)),
        Column[odouche.Backup]("Kind", lambda backup: backup.kind_name),
        Column[odouche.Backup]("Branch", lambda backup: backup.branch_name),
        Column[odouche.Backup]("Build", lambda backup: backup.build_name),
        Column[odouche.Backup]("Commit", lambda backup: backup.commit_hash[:_HASH_LENGTH]),
        Column[odouche.Backup]("Size", lambda backup: "" if backup.size is None else _size(backup.size)),
        Column[odouche.Backup]("Downloadable", lambda backup: "yes" if backup.downloadable else "no"),
    ]
    output.rows(found, columns, empty="No backups.")


def _size(size: int) -> str:
    value = float(size)
    for unit in _UNITS[:-1]:
        # Compared as shown, so 1048575 bytes is 1.0 MiB and not 1024.0 KiB.
        if round(value, 1) < _STEP:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= _STEP
    return f"{value:.1f} {_UNITS[-1]}"
