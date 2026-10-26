"""The revision a build runs: its head commit, and the Odoo revision its branch has selected.

No request ties a build to the Odoo revision it ran, or gives the commit of a submodule.
"""

import re

from odouche._upstream import builds, projects
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import NotFoundError
from odouche.models import Build, BuildRevision, OdooRef, OdooRevision


_OPERATION = "build revision"
_HASH = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_URL = re.compile(r"https://[^\s/]+/\S*")


def revision(transport: Transport, project: str, build: Build) -> BuildRevision:
    """Return what a build of the project named `project` runs.

    Its Odoo version and its branch's selection come from the builds answer. A branch with no
    version of its own follows the project's, which the projects answer gives, as on the page.
    """
    entry = builds.entry(transport, build.branch_id, builds.DEFAULT_LIMIT)
    listed = next((item for item in entry.items("builds") if item.integer("id") == build.id), None)

    if listed is None:
        raise builds.not_listed(build.branch_id, build.id)

    version = listed.text("odoo_branch")
    branch = entry.child("branch_info")
    pinned = branch.optional_integer("odoo_revision_id")

    if pinned is None:
        selected = _latest(
            transport, build.branch_id, branch.optional_text("odoo_branch") or _version(transport, project)
        )
    else:
        selected = _read(transport.call(_OPERATION, f"/app/revision/{pinned}", retry=True), pinned=pinned)

    return BuildRevision(build.id, build.name, build.branch_name, build.commit, version, selected)


def _version(transport: Transport, project: str) -> str:
    version = projects.odoo_version(transport, project)

    if version is None:
        raise NotFoundError(f"The session's user can reach no project named {project!r}.", operation=_OPERATION)

    return version


def _latest(transport: Transport, branch_id: int, version: str) -> OdooRevision | None:
    answer = transport.call(
        _OPERATION,
        f"/app/branch/{branch_id}/revision",
        {"odoo_branch": version},
        retry=True,
        not_found=f"The session's user can reach no branch numbered {branch_id}. Odoo.sh gives no reason.",
    )
    return _read(answer, version=version)


def _read(answer: dict[str, object], *, pinned: int | None = None, version: str | None = None) -> OdooRevision | None:
    """Read a revision, which is `pinned` when it was asked by its number and of `version` when it is the latest."""
    # What a version past its end of life answers is not known: the page does not ask.
    result = Reader(_OPERATION, answer).optional_child("result")

    if result is None:
        return None

    number = result.integer("id")

    if pinned is not None and number != pinned:
        raise result.changed("id")

    named = result.text("branch")

    if version is not None and named != version:
        raise result.changed("branch")

    refs = result.items("refs")

    if not refs:
        raise result.changed("refs")

    return OdooRevision(id=number, version=named, pinned=pinned is not None, refs=tuple(_ref(ref) for ref in refs))


def _ref(ref: Reader) -> OdooRef:
    repository = ref.text("repository")

    if not repository:
        raise ref.changed("repository")

    commit_hash = ref.text("ref")

    if not _HASH.fullmatch(commit_hash):
        raise ref.changed("ref")

    url = ref.text("url")

    if not _URL.fullmatch(url):
        raise ref.changed("url")

    return OdooRef(repository=repository, commit_hash=commit_hash, url=url)
