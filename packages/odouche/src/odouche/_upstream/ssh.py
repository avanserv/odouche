"""The SSH target of a build, which Odoo.sh gives in no payload: the page shows `<id>@<host of url>`."""

from odouche._upstream import builds
from odouche.errors import NotFoundError, UpstreamChangedError
from odouche.models import Build, SshTarget


_OPERATION = "ssh target"


def target(build: Build) -> SshTarget:
    """Return the user and the host of a build, each checked before it becomes an argument of `ssh`."""
    # A negative number would start with a dash.
    if type(build.id) is not int or build.id < 1:
        raise UpstreamChangedError(_OPERATION, "id")

    host = builds.host(build, _OPERATION)

    if host is None:
        raise NotFoundError(f"Build {build.id} has no host to connect to.", operation=_OPERATION)

    return SshTarget(user=str(build.id), host=host)
