"""The panels of a build, which the page links to with no request: each URL is built from the build and its branch."""

from urllib.parse import quote

from odouche._upstream import builds
from odouche._upstream.transport import HOST
from odouche.errors import NotFoundError
from odouche.models import Branch, Build, BuildStatus, Panel, Stage


_OPERATION = "panel"
_MONITORED = frozenset({Stage.PRODUCTION, Stage.STAGING})
_ON_BUILD_HOST = {Panel.SHELL: "/odoo-sh/webshell", Panel.EDITOR: "/odoo-sh/editor"}


def url(project: str, branch: Branch, build: Build, panel: Panel) -> str:
    """Return the address of a panel of a build of a branch, gated on the build and the stage as the page is."""
    if build.branch_id != branch.id:
        raise ValueError(f"Build {build.id} is not of branch {branch.name}")
    if panel is Panel.MONITOR and branch.stage not in _MONITORED:
        msg = f"Branch {branch.name} has no monitor: Odoo.sh has one for a staging or a production branch."
        raise NotFoundError(msg, operation=_OPERATION)
    _ready(build)
    if panel is Panel.MONITOR:
        # The page encodes the branch with `encodeURIComponent`. Quoting more, as here, names the
        # same branch and leaves nothing a shell would read in a URL pasted unquoted.
        return f"https://{HOST}/project/{quote(project, safe='')}/branches/{quote(branch.name, safe='')}/monitor"
    host = builds.host(build, _OPERATION)
    if host is None:
        raise NotFoundError(f"Build {build.id} has no host.", operation=_OPERATION)
    return f"https://{host}{_ON_BUILD_HOST[panel]}"


def _ready(build: Build) -> None:
    if build.status is BuildStatus.DONE:
        return
    if build.status is BuildStatus.PROGRESS and build.started_at is None:
        msg = f"Build {build.id} is waiting for a worker: it has no panels yet."
    else:
        msg = f"Build {build.id} is {build.status_name}: Odoo.sh opens a build's panels once it is done."
    raise NotFoundError(msg, operation=_OPERATION)
