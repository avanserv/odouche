import inspect
import json
import traceback

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
    UpstreamChangedError,
)
from odouche._upstream import members


INFO = "/app/project/acme-shop/get_info"
SETTINGS = "/app/project/acme-corp-odoo-addons-4217/get_settings"
FIND_USERS = "/app/github/find_users"
ADD = "/app/project/acme-corp-odoo-addons-4217/add_collaborator"
ADDED = ProjectMember(
    id=61004, login="Octo-Cat", name="Octo-Cat", role=MemberRole.DEVELOPER, github_id=1000004, pending_login=True
)


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def sent(upstream, path):
    return [json.loads(request.content)["params"] for request in upstream.requests if request.url.path == path]


def users(upstream):
    return upstream.bodies[SETTINGS]["result"]["users"]


@pytest.fixture(autouse=True)
def adds(upstream):
    """Answer a search with the fixture and an addition as Odoo.sh is taken to: the user is listed with the role sent."""
    upstream.bodies[FIND_USERS] = upstream.load("find_users.json")

    def answer(request):
        body = upstream.load("add_collaborator.json")
        body["result"]["access_level"] = json.loads(request.content)["params"]["access_level"]
        users(upstream).append(body["result"])

        return httpx2.Response(200, json=body)

    upstream.bodies[ADD] = answer


@pytest.mark.parametrize("role", list(MemberRole))
def test_a_github_user_is_added_once_with_the_role_given(client, upstream, session, role):
    added = client.add_member("acme-shop", "octo-cat", role)

    assert added == ProjectMember(61004, "Octo-Cat", "Octo-Cat", role, 1000004, pending_login=True)
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS, ADD, SETTINGS]
    assert sent(upstream, FIND_USERS) == [{"query": "octo-cat"}]
    request = upstream.requests[3]
    assert request.method == "POST"
    assert json.loads(request.content)["params"] == {
        "github_username": "Octo-Cat",
        "access_level": role.value,
        "send_invitation": False,
    }
    assert request.headers["Cookie"] == f"session_id={session}"


def test_the_role_is_developer_unless_given(client, upstream):
    assert client.add_member("acme-shop", "octo-cat") == ADDED


def test_a_role_given_as_its_value_is_taken(client, upstream):
    assert client.add_member("acme-shop", "octo-cat", "tester").role is MemberRole.TESTER  # pyright: ignore[reportArgumentType]


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert client.add_member(project, "octo-cat") == ADDED
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS, ADD, SETTINGS]


@pytest.mark.parametrize("login", ["", "-a", "a-", "a--b", "a" * 40, "a_b", "a b", "a\n", "é", "octo.cat"])
def test_a_login_github_would_refuse_is_refused_before_any_request(client, upstream, login):
    with pytest.raises(ValueError, match="is not a GitHub login"):
        client.add_member("acme-shop", login)

    assert upstream.requests == []


@pytest.mark.parametrize("login", ["a", "a" * 39, "a-b-c", "0ctocat", "OCTO-CAT"])
def test_a_login_github_takes_is_checked_and_nothing_is_asked(client, upstream, login):
    client.check_add_member(login, MemberRole.ADMIN)

    assert upstream.requests == []


@pytest.mark.parametrize("login", [None, 7, b"octo-cat"])
def test_a_login_that_is_not_a_string_is_refused_before_any_request(client, upstream, login):
    with pytest.raises(TypeError, match="login"):
        client.add_member("acme-shop", login)

    assert upstream.requests == []


@pytest.mark.parametrize("role", ["owner", "Admin", ""])
def test_a_role_that_is_not_one_is_refused_before_any_request(client, upstream, role):
    with pytest.raises(ValueError, match="MemberRole"):
        client.add_member("acme-shop", "octo-cat", role)

    assert upstream.requests == []


def test_a_read_only_client_sends_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)

    with pytest.raises(ReadOnlyError):
        client.add_member("acme-shop", "octo-cat")

    assert upstream.requests == []


def test_the_addition_is_marked_as_state_changing():
    assert inspect.unwrap(members.member_addition) is not members.member_addition


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_below_admin_it_is_denied_after_the_info(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="only a project's admins add a member") as raised:
        client.add_member("acme-shop", "octo-cat")

    assert raised.value.operation == "member addition"
    assert paths(upstream) == [INFO]


@pytest.mark.parametrize("login", ["jane-doe", "JANE-DOE", "Jane-Doe"])
def test_a_member_by_login_in_any_case_is_refused_before_the_search(client, upstream, login):
    with pytest.raises(MemberRefusedError, match="jane-doe is already a member, with the role tester") as raised:
        client.add_member("acme-shop", login)

    assert raised.value.operation == "member addition"
    assert paths(upstream) == [INFO, SETTINGS]


def test_a_member_under_a_login_since_renamed_is_refused_before_the_addition(client, upstream):
    users(upstream)[1]["hosting_identifier"] = "1000004"

    with pytest.raises(MemberRefusedError, match="Octo-Cat is already a member, as jane-doe, with the role tester"):
        client.add_member("acme-shop", "octo-cat")

    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS]


@pytest.mark.parametrize("found", [[], "near miss"])
def test_a_user_the_search_does_not_find_exactly_is_not_found_and_nothing_is_added(client, upstream, found):
    if found == "near miss":
        upstream.bodies[FIND_USERS]["result"] = upstream.bodies[FIND_USERS]["result"][:1]
    else:
        upstream.bodies[FIND_USERS]["result"] = found

    with pytest.raises(NotFoundError, match=r"GitHub has no user octo-cat that Odoo\.sh finds") as raised:
        client.add_member("acme-shop", "octo-cat")

    assert raised.value.operation == "member addition"
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS]


def test_a_found_login_outside_ascii_that_lowers_to_the_one_given_is_not_taken(client, upstream):
    upstream.bodies[FIND_USERS]["result"] = [{"login": "\N{KELVIN SIGN}ate", "id": 1000006, "type": "User"}]

    with pytest.raises(NotFoundError):
        client.add_member("acme-shop", "kate")

    assert sent(upstream, ADD) == []


def test_an_organisation_found_exactly_is_not_found_and_nothing_is_added(client, upstream):
    with pytest.raises(NotFoundError, match=r"GitHub has no user octo-org that Odoo\.sh finds"):
        client.add_member("acme-shop", "octo-org")

    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS]


@pytest.mark.parametrize("field", ["id", "type"])
def test_a_search_answer_of_another_shape_is_a_changed_shape_and_nothing_is_added(client, upstream, field):
    del upstream.bodies[FIND_USERS]["result"][0][field]

    with pytest.raises(UpstreamChangedError, match=rf"GitHub user search, at result\[0\]\.{field}"):
        client.add_member("acme-shop", "octo-cat")

    assert sent(upstream, ADD) == []


def test_a_grant_without_the_scope_is_denied_with_where_to_grant_it(client, upstream):
    upstream.bodies[FIND_USERS] = upstream.load("insufficient_scope.json")

    with pytest.raises(
        PermissionDeniedError,
        match=r"^Odoo\.sh's grant on GitHub does not cover this\. Search a GitHub user in the "
        "Collaborators item of the project's Settings page",
    ) as raised:
        client.add_member("acme-shop", "octo-cat")

    assert "http" not in str(raised.value)
    assert "github.com" not in "".join(traceback.format_exception(raised.value))
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS]


@pytest.mark.parametrize("failure", [502, 500, httpx2.ReadTimeout, httpx2.RemoteProtocolError])
def test_an_addition_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[ADD] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again") as raised:
        client.add_member("acme-shop", "octo-cat")

    assert raised.value.operation == "member addition"
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS, ADD]


def test_an_addition_the_members_do_not_list_is_unknown(client, upstream):
    upstream.bodies[ADD] = upstream.load("add_collaborator.json")

    with pytest.raises(OutcomeUnknownError, match=r"they are not listed\. Look") as raised:
        client.add_member("acme-shop", "octo-cat")

    assert raised.value.__context__ is None
    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS, ADD, SETTINGS]


def test_an_addition_read_back_with_another_role_is_unknown(client, upstream):
    def answer(_):
        users(upstream).append(upstream.load("add_collaborator.json")["result"])
        return httpx2.Response(200, json=upstream.load("add_collaborator.json"))

    upstream.bodies[ADD] = answer

    with pytest.raises(OutcomeUnknownError, match="as admin was sent, and they read back as developer"):
        client.add_member("acme-shop", "octo-cat", MemberRole.ADMIN)


@pytest.mark.parametrize("failure", [503, 403, "unauthenticated.json"])
def test_an_addition_whose_members_cannot_be_read_back_is_unknown(client, upstream, failure):
    def answer(_):
        if isinstance(failure, int):
            upstream.failures[SETTINGS] = failure
        else:
            upstream.bodies[SETTINGS] = upstream.load(failure)

        return httpx2.Response(200, json=upstream.load("add_collaborator.json"))

    upstream.bodies[ADD] = answer

    with pytest.raises(OutcomeUnknownError, match="the members could not be read back") as raised:
        client.add_member("acme-shop", "octo-cat")

    assert raised.value.__context__ is None
    assert paths(upstream).count(ADD) == 1


def test_a_refused_addition_is_a_refusal_and_not_unknown(client, upstream):
    upstream.bodies[ADD] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError):
        client.add_member("acme-shop", "octo-cat")

    assert paths(upstream) == [INFO, SETTINGS, FIND_USERS, ADD]


@pytest.mark.parametrize("read_only", [False, True])
def test_a_check_refuses_what_an_addition_refuses_and_asks_nothing(upstream, session, read_only):
    client = Client(Secret(session), read_only=read_only)
    listed = Client(Secret(session)).members("acme-shop")
    upstream.requests.clear()
    client.check_add_member("octo-cat", MemberRole.TESTER)
    Client.check_add_member("octo-cat", MemberRole.TESTER, listed)

    with pytest.raises(MemberRefusedError, match="already a member"):
        client.check_add_member("Octo-Dev", MemberRole.TESTER, listed)

    with pytest.raises(ValueError, match="not a GitHub login"):
        Client.check_add_member("octo--cat", MemberRole.TESTER)

    with pytest.raises(ValueError, match="MemberRole"):
        client.check_add_member("octo-cat", "owner")  # pyright: ignore[reportArgumentType]

    assert upstream.requests == []
