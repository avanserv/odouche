"""The members of a project, which its Settings page lists to an admin with the role of each."""

import re

from odouche._upstream import projects, settings
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.models import MemberRole, ProjectMember


_OPERATION = "project members"
# The keys of `access_level_map` but its empty one, which the page's select leaves out.
_ROLES = {"developer": MemberRole.DEVELOPER, "tester": MemberRole.TESTER, "admin": MemberRole.ADMIN}
_DIGITS = re.compile(r"[0-9]+")


def members(transport: Transport, name: str) -> list[ProjectMember]:
    """Return the members of the project named `name`, in the order Odoo.sh answers them."""
    technical = projects.admin(transport, name, _OPERATION, "Odoo.sh shows a project's members to its admins only.")
    answer = projects.settings_answer(transport, technical)
    repo = answer.child("repository")
    if repo.text("project_name") != name:
        raise repo.changed("project_name")
    return [_member(item) for item in answer.items("users")]


def _member(item: Reader) -> ProjectMember:
    # Only the absence of `user_id` is kept: the pair is Odoo.sh's own user and a name that repeats the login.
    # `avatar_url` and `hosting_user_id` are not read.
    login = item.text("username")
    if not login:
        raise item.changed("username")
    github_id = item.text("hosting_identifier")
    if not _DIGITS.fullmatch(github_id):
        raise item.changed("hosting_identifier")
    return ProjectMember(
        id=item.integer("id"),
        login=login,
        name=item.text("name"),
        # A role is read to be compared and written back: an unknown one is not passed through.
        role=settings.choice(item, "access_level", _ROLES),
        github_id=int(github_id),
        pending_login=item.optional_pair("user_id") is None,
    )
