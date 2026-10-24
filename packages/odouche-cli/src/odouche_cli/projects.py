"""`osh projects`: the Odoo.sh projects the session's user can reach, one's overview and its checks."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

import typer

import odouche
from odouche_cli import _size
from odouche_cli._client import open_client
from odouche_cli._context import ProjectOption, resolve_project, result_of, status_of
from odouche_cli._errors import EXIT_CHECK_FAILED, EXIT_CHECK_WARNED
from odouche_cli._output import Column, Output


app = typer.Typer(
    name="projects",
    help="List the Odoo.sh projects you can reach, show one's overview, and check it.",
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

StorageMarginOption = Annotated[
    int,
    typer.Option(
        "--storage-margin",
        min=0,
        max=100,
        metavar="PERCENT",
        help="Warn when the storage used is within this share of the quota. 0 never warns, 100 warns on any use.",
    ),
]


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


class Verdict(StrEnum):
    """The result of one check of `osh projects check`."""

    PASSED = "pass"
    WARNED = "warn"
    FAILED = "fail"
    SKIPPED = "skip"
    """The check could not be made. It does not count in the exit code."""


@dataclass(frozen=True, slots=True)
class Check:
    """One check of a project: what it looked at, its result, and the fact it was judged on."""

    name: str
    """What scripts match on, so renaming one is a breaking change."""
    result: Verdict
    fact: str


_VERDICT_STYLES = {Verdict.PASSED: "green", Verdict.WARNED: "yellow", Verdict.FAILED: "red"}

_CHECK_COLUMNS = [
    Column[Check]("Check", lambda check: check.name),
    Column[Check]("Result", lambda check: check.result.value, lambda check: _VERDICT_STYLES.get(check.result)),
    Column[Check]("Fact", lambda check: check.fact),
]


@app.command(epilog="Example: osh projects check --project acme-shop")
def check(ctx: typer.Context, project: ProjectOption = None, storage_margin: StorageMarginOption = 10) -> None:
    """Check a project's subscription, production build, storage and branches, and exit 30 when one fails, 31 when one warns.

    Each check is a row: its name, `pass`, `warn`, `fail` or `skip`, and the fact it was judged on. Storage is on the project's Settings page, which Odoo.sh shows to an admin of the project only: anyone else gets `skip`, which does not count in the exit code.
    """
    output: Output = ctx.obj
    with open_client() as client:
        read = client.project_overview(resolve_project(ctx, project, client.projects))
    checks = _checks(read, margin=storage_margin)
    output.rows(checks, _CHECK_COLUMNS, empty="")
    code = _exit_code(checks)
    if code:
        raise typer.Exit(code)


def _checks(read: odouche.ProjectOverview, *, margin: int) -> tuple[Check, ...]:
    return (
        _check_subscription(read),
        _check_production(read),
        _check_storage(read, margin),
        _check_branches(read),
    )


def _exit_code(checks: Iterable[Check]) -> int:
    worst = _worst(check.result for check in checks)
    return {Verdict.FAILED: EXIT_CHECK_FAILED, Verdict.WARNED: EXIT_CHECK_WARNED}.get(worst, 0)


def _worst(verdicts: Iterable[Verdict]) -> Verdict:
    found = set(verdicts)
    return next((verdict for verdict in (Verdict.FAILED, Verdict.WARNED) if verdict in found), Verdict.PASSED)


def _check_subscription(read: odouche.ProjectOverview) -> Check:
    # The project's page calls any state it does not know an invalid subscription.
    if read.subscription in {odouche.Subscription.EXPIRED, odouche.Subscription.UNKNOWN}:
        result = Verdict.FAILED
    elif read.subscription is odouche.Subscription.VALID and read.trial_days_left is None:
        result = Verdict.PASSED
    else:
        result = Verdict.WARNED
    return Check("subscription", result, _subscription(read))


def _check_production(read: odouche.ProjectOverview) -> Check:
    judged = [_last_build(summary) for summary in read.branches if summary.branch.stage is odouche.Stage.PRODUCTION]
    if not judged:
        return Check("production", Verdict.WARNED, "no production branch")
    return Check("production", _worst(result for result, _ in judged), "; ".join(fact for _, fact in judged))


_SAID = {
    odouche.BuildResult.SUCCESS: (Verdict.PASSED, "succeeded"),
    odouche.BuildResult.WARNING: (Verdict.WARNED, "finished with warnings"),
    odouche.BuildResult.FAILED: (Verdict.FAILED, "failed"),
}
_RUNNING = frozenset({odouche.BuildStatus.PROGRESS, odouche.BuildStatus.UPDATING})


def _last_build(summary: odouche.BranchSummary) -> tuple[Verdict, str]:
    """Judge a branch's last build by its result, so a build dropped for a newer one counts as it ended."""
    build = summary.last_build
    if build is None:
        return Verdict.WARNED, f"{summary.branch.name} has no build"
    if build.result is None and build.status in _RUNNING:
        result, said = Verdict.WARNED, f"has no result yet ({status_of(build)})"
    elif build.result is None:
        result, said = Verdict.WARNED, f"ended without a result ({status_of(build)})"
    else:
        result, said = _SAID.get(build.result) or (Verdict.WARNED, f"ended {result_of(build)}")
    return result, f"build {build.id} on {summary.branch.name} {said}"


def _check_storage(read: odouche.ProjectOverview, margin: int) -> Check:
    hosting = read.hosting
    if hosting is None:
        return Check("storage", Verdict.SKIPPED, _ADMINS_ONLY)
    used, quota = hosting.storage_used_bytes, hosting.storage_quota_bytes
    if not quota:
        result = Verdict.SKIPPED
    elif used >= quota:
        result = Verdict.FAILED
    # In integers, so no rounding moves the boundary.
    elif used * 100 > quota * (100 - margin):
        result = Verdict.WARNED
    else:
        result = Verdict.PASSED
    return Check("storage", result, _storage(hosting))


def _check_branches(read: odouche.ProjectOverview) -> Check:
    # An unknown result could be a failure Odoo.sh renamed, so it warns rather than passing as none failed.
    flagged = [
        _last_build(summary)
        for summary in read.branches
        if summary.last_build is not None
        and summary.last_build.result in {odouche.BuildResult.FAILED, odouche.BuildResult.UNKNOWN}
    ]
    if flagged:
        return Check("branches", _worst(result for result, _ in flagged), ", ".join(fact for _, fact in flagged))
    count = len(read.branches)
    return Check("branches", Verdict.PASSED, f"{count} branch{'' if count == 1 else 'es'}, none failed")


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
