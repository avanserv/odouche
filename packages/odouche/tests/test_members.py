import dataclasses

import pytest

from odouche import (
    Client,
    MemberRole,
    NotFoundError,
    PermissionDeniedError,
    ProjectMember,
    Secret,
    UpstreamChangedError,
)


INFO = "/app/project/acme-shop/get_info"
SETTINGS = "/app/project/acme-corp-odoo-addons-4217/get_settings"

MEMBERS = [
    ProjectMember(
        id=61001, login="octo-dev", name="octo-dev", role=MemberRole.ADMIN, github_id=1000001, pending_login=False
    ),
    ProjectMember(
        id=61002, login="jane-doe", name="jane-doe", role=MemberRole.TESTER, github_id=1000002, pending_login=False
    ),
    ProjectMember(
        id=61003,
        login="build-bot1",
        name="build-bot1",
        role=MemberRole.DEVELOPER,
        github_id=1000003,
        pending_login=True,
    ),
]


def users(upstream):
    return upstream.bodies[SETTINGS]["result"]["users"]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def test_lists_the_members_of_a_project_an_admin_reaches_in_the_answer_order(client, upstream):
    assert client.members("acme-shop") == MEMBERS
    assert paths(upstream) == [INFO, SETTINGS]


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert client.members(project) == MEMBERS
    assert paths(upstream) == [INFO, SETTINGS]


def test_a_read_only_client_lists_them(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        assert client.members("acme-shop") == MEMBERS


def test_a_project_with_no_member_listed_gives_none(client, upstream):
    upstream.bodies[SETTINGS]["result"]["users"] = []

    assert client.members("acme-shop") == []


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_below_admin_it_is_denied_without_asking_for_the_settings(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="members to its admins only") as raised:
        client.members("acme-shop")

    assert raised.value.operation == "project members"
    assert paths(upstream) == [INFO]


def test_a_project_the_user_cannot_reach_is_not_found(client, upstream):
    upstream.bodies["/app/project/other/get_info"] = {"error": {"data": {"name": "builtins.Exception"}}}

    with pytest.raises(NotFoundError, match="'other'"):
        client.members("other")


def test_an_unknown_role_names_the_request_and_the_field(client, upstream):
    users(upstream)[1]["access_level"] = "owner"

    with pytest.raises(UpstreamChangedError) as raised:
        client.members("acme-shop")

    assert (raised.value.operation, raised.value.field) == ("project settings", "result.users[1].access_level")
    assert "owner" not in str(raised.value)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda member: member.pop("access_level"), "result.users[1].access_level"),
        (lambda member: member.update(access_level=300), "result.users[1].access_level"),
        (lambda member: member.update(access_level=""), "result.users[1].access_level"),
        (lambda member: member.update(username=""), "result.users[1].username"),
        (lambda member: member.update(username=None), "result.users[1].username"),
        (lambda member: member.update(name=False), "result.users[1].name"),
        (lambda member: member.update(id="61002"), "result.users[1].id"),
        (lambda member: member.update(hosting_identifier="abc"), "result.users[1].hosting_identifier"),
        (lambda member: member.update(hosting_identifier=""), "result.users[1].hosting_identifier"),
        (lambda member: member.update(hosting_identifier="\u0661\u0662"), "result.users[1].hosting_identifier"),
        (lambda member: member.update(hosting_identifier=1000002), "result.users[1].hosting_identifier"),
        (lambda member: member.update(user_id=[9102]), "result.users[1].user_id"),
        (lambda member: member.pop("user_id"), "result.users[1].user_id"),
    ],
)
def test_a_member_that_changed_shape_is_named(client, upstream, change, field):
    change(users(upstream)[1])

    with pytest.raises(UpstreamChangedError) as raised:
        client.members("acme-shop")

    assert raised.value.field == field


@pytest.mark.parametrize(("value", "field"), [({}, "result.users"), ([[]], "result.users[0]"), (None, "result.users")])
def test_members_that_are_no_list_of_objects_are_named(client, upstream, value, field):
    upstream.bodies[SETTINGS]["result"]["users"] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.members("acme-shop")

    assert raised.value.field == field


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (INFO, lambda upstream: upstream.bodies[INFO]["result"]["active_repo"]),
        (SETTINGS, lambda upstream: upstream.bodies[SETTINGS]["result"]["repository"]),
    ],
)
def test_another_project_answered_is_a_changed_shape(client, upstream, path, body):
    body(upstream)["project_name"] = "intranet"

    with pytest.raises(UpstreamChangedError) as raised:
        client.members("acme-shop")

    assert raised.value.field.endswith(".project_name")
    assert paths(upstream)[-1] == path


def test_a_member_keeps_no_field_but_those_of_the_model(client, upstream):
    users(upstream)[1]["email"] = "jane@example.com"
    read = client.members("acme-shop")

    assert read[1] == MEMBERS[1]
    assert "example.com" not in repr(read) + repr([dataclasses.asdict(member) for member in read])
    assert "avatars" not in repr(read)
    assert [field.name for field in dataclasses.fields(ProjectMember)] == [
        "id",
        "login",
        "name",
        "role",
        "github_id",
        "pending_login",
    ]


def test_a_member_is_frozen(client):
    member = client.members("acme-shop")[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        member.role = MemberRole.DEVELOPER  # pyright: ignore[reportAttributeAccessIssue]


def test_a_login_is_carried_as_given(client, upstream):
    users(upstream)[0].update(username="octo\x1b[2J-dev", name="Octo\nDev")

    member = client.members("acme-shop")[0]

    assert (member.login, member.name) == ("octo\x1b[2J-dev", "Octo\nDev")


def test_the_roles_rank_lowest_first():
    assert list(MemberRole) == [MemberRole.DEVELOPER, MemberRole.TESTER, MemberRole.ADMIN]
    assert [role.rank for role in MemberRole] == [0, 1, 2]
    assert [role.value for role in MemberRole] == ["developer", "tester", "admin"]
