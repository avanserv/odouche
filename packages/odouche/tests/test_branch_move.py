import inspect
import json
import traceback

import httpx2
import pytest

from odouche import (
    Branch,
    Client,
    NotFoundError,
    OutcomeUnknownError,
    PermissionDeniedError,
    ReadOnlyError,
    Secret,
    Stage,
    StageRefusedError,
    UpstreamUnavailableError,
)
from odouche._upstream import branches


BRANCH = 51044
BUILDS = "/app/branch/51044/builds"
SET_STAGE = "/app/branch/51044/set_stage"
DEVELOPMENT = Branch(BRANCH, "feature-invoicing", Stage.DEVELOPMENT, "dev")
STAGING = Branch(BRANCH, "feature-invoicing", Stage.STAGING, "staging")
PRODUCTION = Branch(BRANCH, "feature-invoicing", Stage.PRODUCTION, "production")
REFUSAL = {"jsonrpc": "2.0", "id": None, "error": {"code": 200, "data": {"name": "builtins.Exception"}}}


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def sent(upstream):
    return [json.loads(request.content)["params"] for request in upstream.requests if request.url.path == SET_STAGE]


def in_stage(upstream, stage):
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = stage


@pytest.fixture(autouse=True)
def moves(upstream):
    """Answer a move as Odoo.sh is taken to: the branch is in the stage sent."""

    def answer(request):
        in_stage(upstream, json.loads(request.content)["params"]["stage"])
        return httpx2.Response(200, json=upstream.load("set_stage.json"))

    upstream.bodies[SET_STAGE] = answer


@pytest.mark.parametrize("branch", [BRANCH, DEVELOPMENT], ids=["number", "branch"])
def test_a_development_branch_is_moved_to_staging_once(client, upstream, session, branch):
    moved = client.move_branch(branch, Stage.STAGING)

    assert moved == STAGING
    assert paths(upstream) == [BUILDS, SET_STAGE, BUILDS]
    request = upstream.requests[1]
    assert request.method == "POST"
    assert json.loads(request.content) == {"jsonrpc": "2.0", "method": "call", "params": {"stage": "staging"}, "id": 1}
    assert request.headers["Cookie"] == f"session_id={session}"


@pytest.mark.parametrize("branch", [BRANCH, STAGING], ids=["number", "branch"])
def test_a_staging_branch_is_moved_to_development_once(client, upstream, branch):
    in_stage(upstream, "staging")

    moved = client.move_branch(branch, Stage.DEVELOPMENT)

    assert moved == DEVELOPMENT
    assert paths(upstream) == [BUILDS, SET_STAGE, BUILDS]
    assert sent(upstream) == [{"stage": "dev"}]


def test_a_stage_given_as_its_value_is_taken(client, upstream):
    assert client.move_branch(BRANCH, "staging").stage is Stage.STAGING  # pyright: ignore[reportArgumentType]


def test_a_stage_that_is_not_one_is_refused_before_any_request(client, upstream):
    with pytest.raises(ValueError, match="dev"):
        client.move_branch(BRANCH, "dev")  # pyright: ignore[reportArgumentType]

    assert upstream.requests == []


@pytest.mark.parametrize("branch", [PRODUCTION, DEVELOPMENT])
@pytest.mark.parametrize("to", [Stage.PRODUCTION, "production"])
def test_a_move_to_production_is_refused_before_any_request(client, upstream, branch, to):
    with pytest.raises(StageRefusedError, match="production") as raised:
        client.move_branch(branch, to)

    assert raised.value.operation == "branch stage move"
    assert upstream.requests == []


def test_a_production_branch_given_as_a_branch_is_refused_before_any_request(client, upstream):
    with pytest.raises(StageRefusedError, match="production stage is not moved"):
        client.move_branch(PRODUCTION, Stage.DEVELOPMENT)

    assert upstream.requests == []


@pytest.mark.parametrize("stage", ["production", "archived"])
@pytest.mark.parametrize("to", [Stage.STAGING, Stage.DEVELOPMENT])
def test_a_branch_given_by_number_is_refused_after_one_read(client, upstream, stage, to):
    in_stage(upstream, stage)

    with pytest.raises(StageRefusedError, match="is not moved"):
        client.move_branch(BRANCH, to)

    assert paths(upstream) == [BUILDS]


def test_a_branch_in_an_unknown_stage_is_refused_before_any_request(client, upstream):
    unknown = Branch(BRANCH, "feature-invoicing", Stage.UNKNOWN, "archived")

    with pytest.raises(StageRefusedError, match="unknown stage is not moved"):
        client.move_branch(unknown, Stage.STAGING)
    with pytest.raises(StageRefusedError, match="to the unknown stage"):
        client.move_branch(DEVELOPMENT, Stage.UNKNOWN)

    assert upstream.requests == []


def test_a_stale_branch_now_in_production_is_refused_before_the_move(client, upstream):
    in_stage(upstream, "production")

    with pytest.raises(StageRefusedError, match="production stage"):
        client.move_branch(DEVELOPMENT, Stage.STAGING)

    assert paths(upstream) == [BUILDS]


@pytest.mark.parametrize(("stage", "to"), [("dev", Stage.DEVELOPMENT), ("staging", Stage.STAGING)])
def test_a_branch_already_there_is_refused(client, upstream, stage, to):
    in_stage(upstream, stage)

    with pytest.raises(StageRefusedError, match=f"Branch 51044 is already in {to.value}"):
        client.move_branch(BRANCH, to)

    assert sent(upstream) == []


def test_production_cannot_reach_the_request():
    assert Stage.PRODUCTION not in branches._MOVES
    assert "production" not in branches._MOVES.values()


def test_a_read_only_client_sends_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)

    with pytest.raises(ReadOnlyError):
        client.move_branch(BRANCH, Stage.STAGING)

    assert upstream.requests == []


def test_the_move_is_marked_as_state_changing():
    assert inspect.unwrap(branches.move) is not branches.move


@pytest.mark.parametrize(
    "failure", [502, 500, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.RemoteProtocolError, REFUSAL]
)
def test_a_move_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    if isinstance(failure, dict):
        upstream.bodies[SET_STAGE] = failure
    else:
        upstream.failures[SET_STAGE] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again") as raised:
        client.move_branch(BRANCH, Stage.STAGING)

    assert raised.value.operation == "branch stage move"
    assert not isinstance(raised.value, UpstreamUnavailableError)
    assert paths(upstream) == [BUILDS, SET_STAGE]


@pytest.mark.parametrize("failure", [httpx2.ConnectError, httpx2.ConnectTimeout])
def test_a_move_that_did_not_leave_is_not_repeated(client, upstream, failure):
    upstream.failures[SET_STAGE] = failure

    with pytest.raises(UpstreamUnavailableError):
        client.move_branch(BRANCH, Stage.STAGING)

    assert paths(upstream).count(SET_STAGE) == 1


@pytest.mark.parametrize("refusal", [403, "access_error.json"])
def test_a_refused_move_is_a_refusal_and_not_unknown(client, upstream, refusal):
    if isinstance(refusal, int):
        upstream.failures[SET_STAGE] = refusal
    else:
        upstream.bodies[SET_STAGE] = upstream.load(refusal)

    with pytest.raises(PermissionDeniedError):
        client.move_branch(BRANCH, Stage.STAGING)

    assert paths(upstream) == [BUILDS, SET_STAGE]


def test_a_move_read_back_in_the_old_stage_is_unknown(client, upstream):
    upstream.bodies[SET_STAGE] = upstream.load("set_stage.json")

    with pytest.raises(OutcomeUnknownError, match=r"reads back in development\. Look") as raised:
        client.move_branch(BRANCH, Stage.STAGING)

    assert raised.value.__context__ is None
    assert paths(upstream) == [BUILDS, SET_STAGE, BUILDS]


@pytest.mark.parametrize("builds", [503, 403, {"result": []}, "unauthenticated.json"])
def test_a_move_whose_branch_cannot_be_read_back_is_unknown(client, upstream, builds):
    def answer(_):
        if isinstance(builds, int):
            upstream.failures[BUILDS] = builds
        else:
            upstream.bodies[BUILDS] = upstream.load(builds) if isinstance(builds, str) else builds
        return httpx2.Response(200, json=upstream.load("set_stage.json"))

    upstream.bodies[SET_STAGE] = answer

    with pytest.raises(OutcomeUnknownError, match="could not be read back") as raised:
        client.move_branch(BRANCH, Stage.STAGING)

    assert raised.value.__context__ is None
    assert paths(upstream).count(SET_STAGE) == 1


@pytest.mark.parametrize("branch", ["51044", True, 51044.0, None])
def test_a_branch_that_is_not_a_number_is_refused_before_any_request(client, upstream, branch):
    with pytest.raises(TypeError, match="branch"):
        client.move_branch(branch, Stage.STAGING)

    assert upstream.requests == []


def test_a_branch_the_user_cannot_reach_is_not_found_before_the_move(client, upstream):
    upstream.bodies["/app/branch/1/builds"] = REFUSAL

    with pytest.raises(NotFoundError):
        client.move_branch(1, Stage.STAGING)

    assert paths(upstream) == ["/app/branch/1/builds"]


def test_an_unknown_outcome_shows_nothing_of_the_request(client, upstream, session):
    upstream.failures[SET_STAGE] = httpx2.ReadTimeout

    with pytest.raises(OutcomeUnknownError) as raised:
        client.move_branch(BRANCH, Stage.STAGING)

    assert raised.value.__context__ is None
    assert session not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("read_only", [False, True])
def test_a_check_refuses_what_a_move_refuses_and_asks_nothing(upstream, session, read_only):
    client = Client(Secret(session), read_only=read_only)

    client.check_move(DEVELOPMENT, Stage.STAGING)
    client.check_move(STAGING, "development")  # pyright: ignore[reportArgumentType]
    for branch, to in [(PRODUCTION, Stage.STAGING), (DEVELOPMENT, Stage.PRODUCTION), (STAGING, Stage.STAGING)]:
        with pytest.raises(StageRefusedError) as checked:
            client.check_move(branch, to)
        assert checked.value.operation == "branch stage move"

    assert upstream.requests == []
