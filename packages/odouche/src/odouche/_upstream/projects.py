"""The projects request."""

from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.models import Project


PATH = "/app/projects"

_OPERATION = "projects"


def projects(transport: Transport) -> list[Project]:
    """List the projects the session's user can reach. Odoo.sh answers them all at once."""
    return [
        Project(
            id=repo.integer("id"),
            name=repo.text("project_name"),
            repository=f"{repo.text('owner')}/{repo.text('name')}",
            url=repo.text("project_url"),
        )
        for repo in _repos(transport)
    ]


def technical_name(transport: Transport, name: str) -> str | None:
    """Return the name a project's other requests address it by, or `None` when it is not listed."""
    for repo in _repos(transport):
        if repo.text("project_name") == name:
            return repo.text("technical_name")
    return None


def _repos(transport: Transport) -> list[Reader]:
    answer = Reader(_OPERATION, transport.call(_OPERATION, PATH, retry=True))
    return answer.child("result").items("repos")
