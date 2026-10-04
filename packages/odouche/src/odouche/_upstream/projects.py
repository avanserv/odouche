"""The projects request."""

from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.models import Project


PATH = "/app/projects"

_OPERATION = "projects"


def projects(transport: Transport) -> list[Project]:
    """List the projects the session's user can reach. Odoo.sh answers them all at once."""
    answer = Reader(_OPERATION, transport.call(_OPERATION, PATH, retry=True))
    return [
        Project(
            id=repo.integer("id"),
            name=repo.text("project_name"),
            repository=f"{repo.text('owner')}/{repo.text('name')}",
            url=repo.text("project_url"),
        )
        for repo in answer.child("result").items("repos")
    ]
