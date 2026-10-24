"""`osh projects`: the Odoo.sh projects the session's user can reach, and one's overview."""

from collections.abc import Callable

import typer

import odouche
from odouche_cli import _size
from odouche_cli._client import open_client
from odouche_cli._context import ProjectOption, resolve_project
from odouche_cli._output import Column, Output


app = typer.Typer(
    name="projects",
    help="List the Odoo.sh projects you can reach, and show one's overview.",
    epilog="Example: osh projects list",
    no_args_is_help=True,
)

_COLUMNS = [
    Column[odouche.Project]("Name", lambda project: project.name),
    Column[odouche.Project]("Repository", lambda project: project.repository),
    Column[odouche.Project]("URL", lambda project: project.url),
]

_ADMINS_ONLY = "admins only"
_SUBSCRIPTION_STYLES = {
    odouche.Subscription.VALID: "green",
    odouche.Subscription.TRIAL: "yellow",
    odouche.Subscription.NON_STANDARD: "yellow",
    odouche.Subscription.EXPIRED: "red",
}


@app.command("list", epilog="Example: osh projects list")
def list_(ctx: typer.Context) -> None:
    """List the projects you can reach, with their repository and address."""
    output: Output = ctx.obj
    with open_client() as client:
        found = client.projects()
    output.rows(found, _COLUMNS, empty="No projects.")


@app.command(epilog="Example: osh projects show --project acme-shop")
def show(ctx: typer.Context, project: ProjectOption = None) -> None:
    """Show a project's overview, one fact per line: its subscription, Odoo version, hosting, production build and branches by stage.

    Storage, workers and staging branches are on the project's Settings page, which Odoo.sh shows to an admin of the project only: anyone else gets `admins only`.
    """
    output: Output = ctx.obj
    with open_client() as client:
        read = client.project_overview(resolve_project(ctx, project, client.projects))
    output.one(read, _OVERVIEW)


def _subscription(read: odouche.ProjectOverview) -> str:
    named = read.subscription_name if read.subscription is odouche.Subscription.UNKNOWN else read.subscription.value
    days = read.trial_days_left
    return named if days is None else f"{named}, {days} day{'' if days == 1 else 's'} left"


def _hosting(value: Callable[[odouche.ProjectHosting], object]) -> Callable[[odouche.ProjectOverview], object]:
    return lambda read: _ADMINS_ONLY if read.hosting is None else value(read.hosting)


def _storage(hosting: odouche.ProjectHosting) -> str:
    shown = f"{_size.size(hosting.storage_used_bytes)} of {_size.size(hosting.storage_quota_bytes)}"
    if not hosting.storage_quota_bytes:
        return shown
    return f"{shown}, {hosting.storage_used_bytes * 100 / hosting.storage_quota_bytes:.0f}%"


def _production(read: odouche.ProjectOverview) -> str:
    build = read.production_build
    return "none" if build is None else f"{build.id} on {build.branch_name}"


def _stages(read: odouche.ProjectOverview) -> str:
    return ", ".join(
        f"{counted.count} {counted.stage_name if counted.stage is odouche.Stage.UNKNOWN else counted.stage.value}"
        for counted in read.stages
    )


_OVERVIEW = [
    Column[odouche.ProjectOverview]("Name", lambda read: read.name),
    Column[odouche.ProjectOverview]("Repository", lambda read: read.repository),
    Column[odouche.ProjectOverview](
        "Subscription", _subscription, lambda read: _SUBSCRIPTION_STYLES.get(read.subscription)
    ),
    Column[odouche.ProjectOverview]("Odoo version", lambda read: read.odoo_version),
    Column[odouche.ProjectOverview]("Region", lambda read: read.region),
    Column[odouche.ProjectOverview]("Storage", _hosting(_storage)),
    Column[odouche.ProjectOverview]("Workers", _hosting(lambda hosting: hosting.workers)),
    Column[odouche.ProjectOverview]("Staging branches", _hosting(lambda hosting: hosting.staging_branches)),
    Column[odouche.ProjectOverview]("Dedicated", lambda read: "yes" if read.dedicated else "no"),
    Column[odouche.ProjectOverview]("Production build", _production),
    Column[odouche.ProjectOverview](
        "Production URL", lambda read: None if read.production_build is None else read.production_build.url
    ),
    Column[odouche.ProjectOverview]("Branches", _stages),
    Column[odouche.ProjectOverview]("Your access", lambda read: read.access_level),
]
