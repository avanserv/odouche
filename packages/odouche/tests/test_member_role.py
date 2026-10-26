import inspect
import json
import re
import traceback
from dataclasses import replace

import httpx2
import pytest

from odouche import (
    Client,
    MemberRefusedError,
    MemberRole,
    NotFoundError,
    OutcomeUnknownError,
    PermissionDeniedError,
    ProjectMember,
    ReadOnlyError,
    Secret,
    UpstreamUnavailableError,
)
from odouche._upstream import members


INFO = "/app/project/acme-shop/get_info"
SETTINGS = "/app/project/acme-corp-odoo-addons-4217/get_settings"
SET = "/app/user_access/61002/set_access_level"
SET_OWN = "/app/user_access/61001/set_access_level"
SET_ANY = re.compile(r"/app/user_access/(\d+)/set_access_level")
OCTO = ProjectMember(61001, "octo-dev", "octo-dev", MemberRole.ADMIN, 1000001, pending_login=False)
JANE = ProjectMember(61002, "jane-doe", "jane-doe", MemberRole.TESTER, 1000002, pending_login=False)


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def sent(upstream):
    return [
        json.loads(request.content)["params"] for request in upstream.requests if SET_ANY.fullmatch(request.url.path)
    ]


def users(upstream):
    return upstream.bodies[SETTINGS]["result"]["users"]


def give(upstream, number, access):
    """Set a member's role in the answers, and the caller's own when it is theirs."""
    for user in users(upstream):
        if user["id"] == number:
            user["access_level"] = access

    if number == OCTO.id:
        upstream.bodies[INFO]["result"]["user"]["access"] = access


@pytest.fixture(autouse=True)
def sets(upstream):
    """Answer a role change as Odoo.sh is taken to: the member has the role sent."""

    def answer(request):
        number = int(request.url.path.split("/")[3])
        give(upstream, number, json.loads(request.content)["params"]["access_level"])

        return httpx2.Response(200, json=upstream.load("set_access_level.json"))

    for number in (61001, 61002, 61003):
        upstream.bodies[f"/app/user_access/{number}/set_access_level"] = answer


@pytest.mark.parametrize("member", ["jane-doe", "JANE-DOE", JANE], ids=["login", "case", "member"])
def test_a_member_is_given_a_role_once_on_their_membership(client, upstream, session, member):
    changed = client.set_member_role("acme-shop", member, MemberRole.DEVELOPER)

    assert changed == ProjectMember(61002, "jane-doe", "jane-doe", MemberRole.DEVELOPER, 1000002, pending_login=False)
    assert paths(upstream) == [INFO, SETTINGS, SET, SETTINGS]
    request = upstream.requests[2]
    assert request.method == "POST"
    assert json.loads(request.content)["params"] == {"access_level": "developer"}
    assert request.headers["Cookie"] == f"session_id={session}"


def test_takes_a_project_or_its_name_and_a_role_as_its_value(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert client.set_member_role(project, "jane-doe", "admin").role is MemberRole.ADMIN  # pyright: ignore[reportArgumentType]
    assert sent(upstream) == [{"access_level": "admin"}]


def test_a_member_with_that_role_already_is_returned_and_nothing_is_sent(client, upstream):
    assert client.set_member_role("acme-shop", "jane-doe", MemberRole.TESTER) == JANE
    assert paths(upstream) == [INFO, SETTINGS]


def test_a_member_read_earlier_with_another_role_is_changed_by_the_role_read_now(client, upstream):
    stale = replace(JANE, role=MemberRole.DEVELOPER)
    changed = client.set_member_role("acme-shop", stale, MemberRole.DEVELOPER)

    assert changed.role is MemberRole.DEVELOPER
    assert paths(upstream) == [INFO, SETTINGS, SET, SETTINGS]


def test_a_second_admin_read_earlier_and_gone_now_does_not_let_the_last_one_be_lowered(client, upstream):
    # The caller's read had jane-doe as an admin: the one made in the call has her as a tester.
    with pytest.raises(MemberRefusedError, match="last admin"):
        client.set_member_role("acme-shop", OCTO, MemberRole.TESTER)

    assert paths(upstream) == [INFO, SETTINGS]


@pytest.mark.parametrize("member", ["octo-cat", "", "jane-doe\n", replace(JANE, id=61009)])
def test_a_member_not_listed_is_not_found_and_nothing_is_sent(client, upstream, member):
    with pytest.raises(NotFoundError, match="is not a member of the project") as raised:
        client.set_member_role("acme-shop", member, MemberRole.DEVELOPER)

    assert raised.value.operation == "member role change"
    assert paths(upstream) == [INFO, SETTINGS]


@pytest.mark.parametrize("role", ["owner", "Admin", ""])
def test_a_role_that_is_not_one_is_refused_before_any_request(client, upstream, role):
    with pytest.raises(ValueError, match="MemberRole"):
        client.set_member_role("acme-shop", "jane-doe", role)

    assert upstream.requests == []


@pytest.mark.parametrize("role", [MemberRole.TESTER, MemberRole.DEVELOPER])
def test_the_last_admin_who_has_logged_in_is_not_lowered(client, upstream, role):
    with pytest.raises(MemberRefusedError, match="octo-dev is the last admin of the project") as raised:
        client.set_member_role("acme-shop", "octo-dev", role)

    assert raised.value.operation == "member role change"
    assert paths(upstream) == [INFO, SETTINGS]


def test_an_admin_who_has_not_logged_in_does_not_count(client, upstream):
    give(upstream, 61003, "admin")

    with pytest.raises(MemberRefusedError):
        client.set_member_role("acme-shop", "octo-dev", MemberRole.TESTER)

    assert sent(upstream) == []


def test_an_admin_who_has_not_logged_in_is_lowered_while_another_remains(client, upstream):
    give(upstream, 61003, "admin")

    assert client.set_member_role("acme-shop", "build-bot1", MemberRole.DEVELOPER).role is MemberRole.DEVELOPER


def test_another_admin_is_lowered_and_read_back_from_the_members(client, upstream):
    give(upstream, 61002, "admin")

    assert client.set_member_role("acme-shop", "jane-doe", MemberRole.TESTER) == JANE
    assert paths(upstream) == [INFO, SETTINGS, SET, SETTINGS]


def test_the_caller_lowering_themselves_is_read_back_from_their_info(client, upstream):
    give(upstream, 61002, "admin")

    changed = client.set_member_role("acme-shop", "Octo-Dev", MemberRole.DEVELOPER)

    assert changed == replace(OCTO, role=MemberRole.DEVELOPER)
    assert paths(upstream) == [INFO, SETTINGS, SET_OWN, INFO]


def test_the_caller_whose_info_reads_back_admin_is_unknown(client, upstream):
    give(upstream, 61002, "admin")
    upstream.bodies[SET_OWN] = upstream.load("set_access_level.json")

    with pytest.raises(OutcomeUnknownError, match="their role reads back as admin"):
        client.set_member_role("acme-shop", "octo-dev", MemberRole.TESTER)


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_below_admin_it_is_denied_after_the_info(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="only a project's admins change a member's role") as raised:
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert raised.value.operation == "member role change"
    assert paths(upstream) == [INFO]


def test_a_read_only_client_sends_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)

    with pytest.raises(ReadOnlyError):
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert upstream.requests == []


def test_the_role_change_is_marked_as_state_changing():
    assert inspect.unwrap(members.role_change) is not members.role_change


@pytest.mark.parametrize("failure", [502, 500, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.RemoteProtocolError])
def test_a_role_change_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[SET] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again") as raised:
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert raised.value.operation == "member role change"
    assert not isinstance(raised.value, UpstreamUnavailableError)
    assert paths(upstream) == [INFO, SETTINGS, SET]


@pytest.mark.parametrize("failure", [httpx2.ConnectError, httpx2.ConnectTimeout])
def test_a_role_change_that_did_not_leave_is_not_repeated(client, upstream, failure):
    upstream.failures[SET] = failure

    with pytest.raises(UpstreamUnavailableError):
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert paths(upstream).count(SET) == 1


def test_a_role_change_read_back_with_the_old_role_is_unknown(client, upstream):
    upstream.bodies[SET] = upstream.load("set_access_level.json")

    with pytest.raises(OutcomeUnknownError, match=r"their role reads back as tester\. Look") as raised:
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert raised.value.__context__ is None
    assert paths(upstream) == [INFO, SETTINGS, SET, SETTINGS]


@pytest.mark.parametrize("failure", [503, 403, "unauthenticated.json", "gone"])
def test_a_role_change_whose_member_cannot_be_read_back_is_unknown(client, upstream, failure):
    def answer(_):
        if isinstance(failure, int):
            upstream.failures[SETTINGS] = failure
        elif failure == "gone":
            del users(upstream)[1]
        else:
            upstream.bodies[SETTINGS] = upstream.load(failure)

        return httpx2.Response(200, json=upstream.load("set_access_level.json"))

    upstream.bodies[SET] = answer

    with pytest.raises(OutcomeUnknownError, match="could not be read back") as raised:
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert raised.value.__context__ is None
    assert paths(upstream).count(SET) == 1


def test_an_unknown_outcome_shows_nothing_of_the_request(client, upstream, session):
    upstream.failures[SET] = httpx2.ReadTimeout

    with pytest.raises(OutcomeUnknownError) as raised:
        client.set_member_role("acme-shop", "jane-doe", MemberRole.DEVELOPER)

    assert raised.value.__context__ is None
    assert session not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("member", [None, 61002])
def test_a_member_that_is_neither_a_member_nor_a_login_is_refused(client, upstream, member):
    with pytest.raises(TypeError, match="ProjectMember or a login"):
        client.set_member_role("acme-shop", member, MemberRole.DEVELOPER)

    assert sent(upstream) == []


@pytest.mark.parametrize("read_only", [False, True])
def test_a_check_refuses_what_a_role_change_refuses_and_asks_nothing(upstream, session, read_only):
    client = Client(Secret(session), read_only=read_only)
    listed = Client(Secret(session)).members("acme-shop")
    upstream.requests.clear()

    assert client.check_member_role(listed, "Jane-Doe", MemberRole.ADMIN) == JANE
    assert client.check_member_role(listed, replace(JANE, role=MemberRole.ADMIN), MemberRole.TESTER) == JANE

    with pytest.raises(MemberRefusedError) as checked:
        client.check_member_role(listed, "octo-dev", MemberRole.TESTER)

    assert checked.value.operation == "member role change"

    with pytest.raises(NotFoundError):
        client.check_member_role(listed, "octo-cat", MemberRole.TESTER)

    with pytest.raises(ValueError, match="MemberRole"):
        client.check_member_role(listed, "jane-doe", "owner")  # pyright: ignore[reportArgumentType]

    assert upstream.requests == []
