"""The members of a project, which its Settings page lists to an admin with the role of each, and the requests that
add one and change one's role.
"""

import re
from collections.abc import Sequence
from dataclasses import replace

from odouche._upstream import projects, settings
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import MemberRefusedError, NotFoundError, OdoucheError, OutcomeUnknownError
from odouche.models import MemberRole, ProjectMember


_OPERATION = "project members"
_OPERATION_ADD = "member addition"
_OPERATION_ROLE = "member role change"
_OPERATION_FIND = "GitHub user search"
# The keys of `access_level_map` but its empty one, which the page's select leaves out.
_ROLES = {"developer": MemberRole.DEVELOPER, "tester": MemberRole.TESTER, "admin": MemberRole.ADMIN}
_ROLES_SENT = {role: wire for wire, role in _ROLES.items()}
_DIGITS = re.compile(r"[0-9]+")
# GitHub's rule for a new account. Older logins can break it: the page adds those, the library does not.
_GRANT = (
    "Search a GitHub user in the Collaborators item of the project's Settings page once, which asks GitHub for it, "
    "then try again."
)
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")


def members(transport: Transport, name: str) -> list[ProjectMember]:
    """Return the members of the project named `name`, in the order Odoo.sh answers them."""
    technical = projects.admin(transport, name, _OPERATION, "Odoo.sh shows a project's members to its admins only.")

    return _listed(transport, name, technical)


@state_changing
def member_addition(transport: Transport, name: str, login: str, role: MemberRole) -> ProjectMember:
    """Add the GitHub user `login` to the project named `name` as `role`, once, and return them read back."""
    role = allow_addition(login, role)
    technical = projects.admin(transport, name, _OPERATION_ADD, "Odoo.sh lets only a project's admins add a member.")
    current = _listed(transport, name, technical)
    allow_addition(login, role, current)
    spelled, github_id = _github_user(transport, login)
    renamed = next((member for member in current if member.github_id == github_id), None)

    if renamed is not None:
        msg = f"{spelled} is already a member, as {renamed.login}, with the role {renamed.role.value}."
        raise MemberRefusedError(msg, operation=_OPERATION_ADD)

    # `send_invitation` is what the page sends: its dialog has no control for it.
    params = {"github_username": spelled, "access_level": _ROLES_SENT[role], "send_invitation": False}
    transport.change(_OPERATION_ADD, f"/app/project/{projects.segment(technical)}/add_collaborator", params)

    try:
        after = _listed(transport, name, technical)
    except OdoucheError:
        after = None

    added = next((member for member in after or () if member.github_id == github_id), None)

    if added is None or added.role is not role:
        if after is None:
            found = "the members could not be read back"
        elif added is None:
            found = "they are not listed"
        else:
            found = f"they read back as {added.role.value}"

        # As unknown: an error that reads as a failure invites a second addition.
        raise OutcomeUnknownError(
            f"The addition of {spelled} to {name} as {role.value} was sent, and {found}. Look before trying again.",
            operation=_OPERATION_ADD,
        )

    return added


def allow_addition(login: str, role: MemberRole, current: Sequence[ProjectMember] = ()) -> MemberRole:
    """Return `role` as a role, and raise for an addition that is not sent. Nothing is asked."""
    if type(login) is not str:
        msg = f"A login is a string, not {type(login).__name__}."
        raise TypeError(msg)

    if not _LOGIN.fullmatch(login):
        msg = (
            f"{login!r} is not a GitHub login: 1 to 39 letters, digits and single hyphens, "
            "not starting or ending with a hyphen."
        )
        raise ValueError(msg)

    role = MemberRole(role)
    listed = _by_login(current, login)

    if listed is not None:
        msg = f"{listed.login} is already a member, with the role {listed.role.value}. `members role` changes it."
        raise MemberRefusedError(msg, operation=_OPERATION_ADD)

    return role


@state_changing
def role_change(transport: Transport, name: str, member: ProjectMember | str, role: MemberRole) -> ProjectMember:
    """Give `member` of the project named `name` the role `role`, once, and return them read back."""
    role = MemberRole(role)
    technical, info = projects.admin_info(
        transport, name, _OPERATION_ROLE, "Odoo.sh lets only a project's admins change a member's role."
    )
    caller = info.child("user").text("username")
    current = _listed(transport, name, technical)
    found = find(current, member)

    if not allow_role(current, found, role):
        return found

    transport.change(
        _OPERATION_ROLE, f"/app/user_access/{found.id}/set_access_level", {"access_level": _ROLES_SENT[role]}
    )
    # An admin who lowers their own role can no longer read the members: their info says their role.
    own = found.login.casefold() == caller.casefold()

    try:
        after = _own_role(transport, name, found) if own else find(_listed(transport, name, technical), found)
    except OdoucheError:
        after = None

    if after is None or after.role is not role:
        said = "could not be read back" if after is None else f"reads back as {after.role.value}"
        # As unknown: an error that reads as a failure invites a second change.
        raise OutcomeUnknownError(
            f"The change of {found.login}'s role on {name} to {role.value} was sent, and their role {said}. "
            "Look before trying again.",
            operation=_OPERATION_ROLE,
        )

    return after


def find(current: Sequence[ProjectMember], member: ProjectMember | str) -> ProjectMember:
    """Return the member of `current` that `member` names: a `ProjectMember` by its membership, a login by itself."""
    if isinstance(member, ProjectMember):
        found = next((listed for listed in current if listed.id == member.id), None)
        named = member.login
    else:
        if type(member) is not str:
            msg = f"A member is a ProjectMember or a login, not {type(member).__name__}."
            raise TypeError(msg)

        found, named = _by_login(current, member), member

    if found is None:
        raise NotFoundError(f"{named} is not a member of the project.", operation=_OPERATION_ROLE)

    return found


def allow_role(current: Sequence[ProjectMember], member: ProjectMember, role: MemberRole) -> bool:
    """Tell whether giving `member` the role `role` changes it, and raise for a change that is not sent."""
    role = MemberRole(role)

    if member.role is role:
        return False

    # An invitee who never logs in leaves nobody to administer the project.
    others = [
        listed
        for listed in current
        if listed.role is MemberRole.ADMIN and not listed.pending_login and listed.id != member.id
    ]

    if member.role is MemberRole.ADMIN and not others:
        msg = (
            f"{member.login} is the last admin of the project who has logged in to Odoo.sh. "
            "Give another member the admin role first."
        )
        raise MemberRefusedError(msg, operation=_OPERATION_ROLE)

    return True


def _listed(transport: Transport, name: str, technical: str) -> list[ProjectMember]:
    answer = projects.settings_answer(transport, technical)
    repo = answer.child("repository")

    if repo.text("project_name") != name:
        raise repo.changed("project_name")

    return [_member(item) for item in answer.items("users")]


def _by_login(current: Sequence[ProjectMember], login: str) -> ProjectMember | None:
    # GitHub logins differ by more than case. The exact one first, should two read alike.
    exact = next((member for member in current if member.login == login), None)
    return exact or next((member for member in current if member.login.casefold() == login.casefold()), None)


def _github_user(transport: Transport, login: str) -> tuple[str, int]:
    """Return the login as GitHub spells it and the user's number, by the page's own way from a typed login."""
    body = transport.call(_OPERATION_FIND, "/app/github/find_users", {"query": login}, retry=True, grant=_GRANT)

    for item in Reader(_OPERATION_FIND, body).items("result"):
        spelled, github_id, kind = item.text("login"), item.integer("id"), item.text("type")

        # Checked as a login too: a letter outside ASCII can lower to one inside it. An organisation is
        # found too, and is no member.
        if kind == "User" and _LOGIN.fullmatch(spelled) and spelled.lower() == login.lower():
            return spelled, github_id

    raise NotFoundError(f"GitHub has no user {login} that Odoo.sh finds.", operation=_OPERATION_ADD)


def _own_role(transport: Transport, name: str, member: ProjectMember) -> ProjectMember:
    return replace(member, role=settings.choice(projects.info(transport, name).child("user"), "access", _ROLES))


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
