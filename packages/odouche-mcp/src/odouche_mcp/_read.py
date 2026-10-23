"""The tools that read projects, branches, a branch's history and settings, builds, and the revision a build runs.

Branch names, commit messages, and author and pusher names are written by third parties. They are returned in
the fields of the library's models only, never in a sentence the server writes.
"""

from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError

import odouche
from odouche_mcp._session import open_client


DEFAULT_LISTED = 50
MAX_LISTED = 200
"""The most projects or branches one call returns."""

DEFAULT_BUILDS = 4
MAX_BUILDS = 20
"""The most builds one call returns."""

DEFAULT_HISTORY = 10
MAX_HISTORY = 100
"""The most events of a branch's history one call returns."""
HISTORY_TIMEOUT = 60
"""The seconds a call has to read the pages of a branch's history."""


@dataclass(frozen=True)
class Projects:
    projects: list[odouche.Project]
    truncated: bool


@dataclass(frozen=True)
class Branches:
    branches: list[odouche.Branch]
    truncated: bool


@dataclass(frozen=True)
class Builds:
    builds: list[odouche.Build]
    truncated: bool


@dataclass(frozen=True)
class History:
    events: list[odouche.Tracking]
    truncated: bool


@dataclass(frozen=True)
class BuildRead:
    build: odouche.Build


@dataclass(frozen=True)
class SettingsRead:
    branch: odouche.Branch
    settings: odouche.BranchSettings


@dataclass(frozen=True)
class RevisionRead:
    revision: odouche.BuildRevision


def list_projects(limit: int = DEFAULT_LISTED) -> Projects:
    """List the Odoo.sh projects the user can reach. Call it first: every other tool takes a project by its name."""
    limit = capped(limit, MAX_LISTED)
    with open_client() as client:
        found = client.projects()
    return Projects(found[:limit], truncated=len(found) > limit)


def list_branches(project: str, limit: int = DEFAULT_LISTED) -> Branches:
    """List the branches of a project, given by its name, with the stage each sits in."""
    limit = capped(limit, MAX_LISTED)
    with open_client() as client:
        found = client.branches(project)
    return Branches(found[:limit], truncated=len(found) > limit)


def list_builds(project: str, branch: str, limit: int = DEFAULT_BUILDS) -> Builds:
    """List the latest builds of a branch of a project, newest first, with their status, result and commit."""
    limit = capped(limit, MAX_BUILDS)
    with open_client() as client:
        # One more than asked for tells whether there are more.
        found = client.builds(find_branch(client, project, branch), limit=limit + 1)
    return Builds(found[:limit], truncated=len(found) > limit)


def list_history(project: str, branch: str, limit: int = DEFAULT_HISTORY) -> History:
    """List the history of a branch of a project, newest first: each push with its commits, each rebuild and each move between stages."""
    limit = capped(limit, MAX_HISTORY)
    with open_client() as client:
        found = client.history(find_branch(client, project, branch), limit=limit + 1, timeout=HISTORY_TIMEOUT)
        events = list(found)
    return History(events[:limit], truncated=len(events) > limit)


def get_build(project: str, branch: str, build_id: int | None = None) -> BuildRead:
    """Read one build of a branch of a project: the build of that number, or the latest one when none is given. Odoo.sh has no settings request for a build: a new build takes its branch's settings, which `get_branch_settings` reads."""
    with open_client() as client:
        return BuildRead(find_build(client, project, branch, build_id))


def get_branch_settings(project: str, branch: str) -> SettingsRead:
    """Read the settings of a branch of a project: what a new commit does, which modules and tests a new build runs, its Odoo version and revision, its operating system and its custom domains."""
    with open_client() as client:
        found = find_branch(client, project, branch)
        return SettingsRead(found, client.branch_settings(found))


def get_build_revision(project: str, branch: str, build_id: int | None = None) -> RevisionRead:
    """Read what a build of a branch of a project runs: its head commit, its Odoo version, and the Odoo revision its branch has selected, with the commit of each Odoo repository. The build of that number, or the latest one. Odoo.sh ties no Odoo revision to a build, so the branch's may not be the build's. Odoo.sh gives no commit for a submodule, so none is returned, and the result says nothing of whether the repository has any."""
    with open_client() as client:
        return RevisionRead(client.build_revision(project, find_build(client, project, branch, build_id)))


def capped(limit: int, cap: int, name: str = "A limit") -> int:
    if limit < 1:
        msg = f"{name} is at least 1."
        raise ToolError(msg)
    return min(limit, cap)


def find_branch(client: odouche.Client, project: str, name: str) -> odouche.Branch:
    for branch in client.branches(project):
        if branch.name == name:
            return branch
    msg = f"Project {project} has no branch {name}."
    raise odouche.NotFoundError(msg)


def find_build(client: odouche.Client, project: str, branch: str, build_id: int | None) -> odouche.Build:
    """Return the build of that number of a branch, or its latest one when none is given."""
    return build_of(client, project, find_branch(client, project, branch), build_id)


def build_of(client: odouche.Client, project: str, branch: odouche.Branch, build_id: int | None) -> odouche.Build:
    """Return the build of that number of a branch found already, or its latest one when none is given."""
    if build_id is not None:
        return client.build(branch, build_id)
    latest = client.latest_build(branch)
    if latest is None:
        msg = f"Branch {branch.name} of {project} has no build."
        raise odouche.NotFoundError(msg)
    return latest
