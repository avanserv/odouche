"""The overview of a project: its info, its listing among the projects, its branches and, for an admin, its settings."""

from collections import Counter
from dataclasses import replace

from odouche._upstream import branches, projects
from odouche._upstream.transport import Transport
from odouche.errors import NotFoundError
from odouche.models import BranchSummary, ProjectOverview, Stage, StageCount


def overview(transport: Transport, name: str) -> ProjectOverview:
    """Return the overview of the project named `name`.

    The region comes from the projects request, which answers it to every member; the rest from the
    requests the project's page and its Settings page send.
    """
    info = projects.info(transport, name)
    repo = info.child("active_repo")

    if repo.text("project_name") != name:
        raise repo.changed("project_name")

    technical_name = repo.text("technical_name")
    subscription, subscription_name = projects.subscription(repo)
    # Read whole before the next request, so that a changed shape sends nothing more.
    read = ProjectOverview(
        id=repo.integer("id"),
        name=name,
        repository=f"{repo.text('owner')}/{repo.text('name')}",
        subscription=subscription,
        subscription_name=subscription_name,
        trial_days_left=repo.optional_integer("production_expiration_days_left"),
        odoo_version=repo.text("odoo_branch"),
        region="",
        dedicated=repo.boolean("pays_dedicated"),
        production_build=projects.production_build(repo),
        access_level=info.child("user").text("access"),
        hosting=None,
        stages=(),
        branches=(),
    )
    admin = projects.is_admin(info)
    region = projects.region(transport, name)

    if region is None:
        raise NotFoundError(f"The session's user can reach no project named {name!r}.", operation="projects")

    summaries = tuple(branches.summary(row) for row in branches.listed(transport, technical_name))
    # The page shows the settings to an admin only: what they answer anyone else was never seen.
    hosting = projects.hosting(projects.settings_answer(transport, technical_name)) if admin else None

    return replace(read, region=region, hosting=hosting, stages=_stages(summaries), branches=summaries)


def _stages(summaries: tuple[BranchSummary, ...]) -> tuple[StageCount, ...]:
    counts = Counter(summary.branch.stage_name for summary in summaries)
    known = [StageCount(stage, name, counts.pop(name, 0)) for stage, name in branches.NAMES.items()]

    return (*known, *(StageCount(Stage.UNKNOWN, name, counts[name]) for name in sorted(counts)))
