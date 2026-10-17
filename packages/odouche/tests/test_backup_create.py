import copy
import inspect
import json
from datetime import UTC, datetime

import httpx2
import pytest

from odouche import (
    BackupKind,
    Client,
    NotFoundError,
    OutcomeUnknownError,
    ReadOnlyError,
    Secret,
    Stage,
    StageRefusedError,
    StreamTimeoutError,
)
from odouche._upstream import backups


BRANCH = 51044
BUILDS = "/app/branch/51044/builds"
PROJECTS = "/app/projects"
BRANCHES = "/app/project/acme-corp-odoo-addons-4217/branches"
BACKUPS = "/app/project/acme-corp-odoo-addons-4217/backups"
INFO = "/app/project/acme-shop/get_info"
LATEST = 88240
DUMP = f"/app/build/{LATEST}/dump"
NAME = "acme-shop-feature-invoicing-88240"
EARLIER = "2026-10-14 09:00:00"
TAKEN = "2026-10-14 13:05:41"


def listed(upstream):
    return upstream.bodies[BACKUPS]["result"]


def manual(result, taken):
    result.insert(0, copy.deepcopy(result[0]) | {"name": NAME, "backup_datetime_utc": taken})


def paths(upstream):
    return [request.url.path for request in upstream.requests]


@pytest.fixture(autouse=True)
def staging(upstream):
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = "staging"
    upstream.bodies[DUMP] = upstream.load("dump.json")


@pytest.fixture
def clock(monkeypatch):
    """A clock that moves only when the wait sleeps."""
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(backups, "_monotonic", lambda: now[0])
    monkeypatch.setattr(backups, "_sleep", sleep)
    return slept


def test_sends_the_documented_request_once_on_the_latest_build(client, upstream, session, clock):
    request = client.create_backup("acme-shop", BRANCH, comment="before the upgrade")

    assert request.build.id == LATEST
    assert request.previous is None
    assert paths(upstream) == [BUILDS, PROJECTS, BRANCHES, PROJECTS, BACKUPS, DUMP]
    sent = upstream.requests[-1]
    assert json.loads(sent.content)["params"] == {"backup_only": True, "comment": "before the upgrade"}
    assert sent.headers["Cookie"] == f"session_id={session}"


def test_the_comment_is_empty_by_default(client, upstream):
    client.create_backup("acme-shop", BRANCH)

    assert json.loads(upstream.requests[-1].content)["params"] == {"backup_only": True, "comment": ""}


def test_remembers_the_newest_manual_backup_of_the_build(client, upstream):
    manual(listed(upstream), EARLIER)

    request = client.create_backup("acme-shop", BRANCH)

    assert request.previous == datetime(2026, 10, 14, 9, tzinfo=UTC)


def test_the_creation_is_marked_as_state_changing():
    assert inspect.unwrap(backups.backup) is not backups.backup


def test_a_read_only_client_sends_nothing(upstream, session):
    with pytest.raises(ReadOnlyError) as raised:
        Client(Secret(session), read_only=True).create_backup("acme-shop", BRANCH)

    assert raised.value.operation == "backup"
    assert upstream.requests == []


def test_a_development_branch_is_refused_before_any_request(client, upstream):
    development = client.branches("acme-shop")[1]
    upstream.requests.clear()

    with pytest.raises(StageRefusedError, match="development") as raised:
        client.create_backup("acme-shop", development)

    assert development.stage is Stage.DEVELOPMENT
    assert raised.value.operation == "backup"
    assert upstream.requests == []


@pytest.mark.parametrize("stage", ["dev", "archived"])
def test_a_branch_given_by_number_is_refused_before_the_backup(client, upstream, stage):
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = stage

    with pytest.raises(StageRefusedError):
        client.create_backup("acme-shop", BRANCH)

    assert paths(upstream) == [BUILDS]


def test_a_production_branch_is_backed_up(client, upstream):
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = "production"

    assert client.create_backup("acme-shop", BRANCH).build.id == LATEST


def test_a_check_refuses_the_stage_a_backup_refuses_and_asks_nothing(upstream, session):
    client = Client(Secret(session), read_only=True)
    production, development = client.branches("acme-shop")[:2]
    upstream.requests.clear()

    client.check_backup(production)
    with pytest.raises(StageRefusedError):
        client.check_backup(development)

    assert upstream.requests == []


def test_a_branch_with_no_build_is_not_found(client, upstream):
    upstream.bodies[BUILDS]["result"][0]["builds"].clear()

    with pytest.raises(NotFoundError, match="no build"):
        client.create_backup("acme-shop", BRANCH)

    assert DUMP not in paths(upstream)


def test_a_branch_of_another_project_is_not_found_before_the_backup(client, upstream):
    upstream.bodies[BRANCHES]["result"] = [
        branch for branch in upstream.bodies[BRANCHES]["result"] if branch["id"] != BRANCH
    ]

    with pytest.raises(NotFoundError, match="no branch numbered 51044"):
        client.create_backup("acme-shop", BRANCH)

    assert DUMP not in paths(upstream)


def test_an_unknown_project_is_not_found_before_the_backup(client, upstream):
    with pytest.raises(NotFoundError):
        client.create_backup("nope", BRANCH)

    assert DUMP not in paths(upstream)


@pytest.mark.parametrize("failure", [503, httpx2.ReadTimeout])
def test_a_backup_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[DUMP] = failure

    with pytest.raises(OutcomeUnknownError, match="Look before trying again"):
        client.create_backup("acme-shop", BRANCH)

    assert paths(upstream).count(DUMP) == 1


@pytest.fixture
def appears(upstream):
    """List the backup asked for from the `look`-th request for the backups on."""

    def appear(look, taken=TAKEN):
        body = upstream.bodies[BACKUPS]
        looks = 0

        def answer(_):
            nonlocal looks
            looks += 1
            if looks == look:
                manual(body["result"], taken)
            return httpx2.Response(200, json=body)

        upstream.bodies[BACKUPS] = answer

    return appear


def test_the_wait_yields_none_between_looks_and_ends_on_the_backup(client, upstream, clock, appears):
    request = client.create_backup("acme-shop", BRANCH)
    appears(3)

    seen = list(client.wait_for_backup("acme-shop", request, timeout=60))

    assert seen[:2] == [None, None]
    backup = seen[2]
    assert backup is not None
    assert backup.kind is BackupKind.MANUAL
    assert backup.build_name == NAME
    assert backup.taken_at == datetime(2026, 10, 14, 13, 5, 41, tzinfo=UTC)
    assert len(seen) == 3
    assert clock == [5.0, 5.0]


def test_the_wait_looks_past_a_backup_listed_before_the_request(client, upstream, clock, appears):
    manual(listed(upstream), EARLIER)
    request = client.create_backup("acme-shop", BRANCH)
    appears(2)

    seen = list(client.wait_for_backup("acme-shop", request, timeout=60))

    assert seen[0] is None
    assert seen[-1] is not None
    assert seen[-1].taken_at == datetime(2026, 10, 14, 13, 5, 41, tzinfo=UTC)


def test_the_wait_ignores_another_build_s_manual_backup(client, upstream, clock):
    request = client.create_backup("acme-shop", BRANCH)

    with pytest.raises(StreamTimeoutError) as raised:
        list(client.wait_for_backup("acme-shop", request, timeout=12))

    assert listed(upstream)[0]["type"] == "manual"
    assert raised.value.operation == "backups"
    assert clock == [5.0, 5.0, 2.0]


def test_a_wait_that_has_not_started_sends_nothing_more(client, upstream, clock):
    request = client.create_backup("acme-shop", BRANCH)
    upstream.requests.clear()

    client.wait_for_backup("acme-shop", request, timeout=60).close()

    assert paths(upstream) == [PROJECTS]


@pytest.mark.parametrize("timeout", [0, -1])
def test_a_wait_needs_a_timeout(client, upstream, clock, timeout):
    request = client.create_backup("acme-shop", BRANCH)
    upstream.requests.clear()

    with pytest.raises(ValueError, match="timeout"):
        client.wait_for_backup("acme-shop", request, timeout=timeout)

    assert upstream.requests == []


def test_the_wait_ends_only_once_odoo_sh_has_finished_the_backup(client, upstream, clock, appears):
    request = client.create_backup("acme-shop", BRANCH)
    appears(1)
    info = upstream.bodies[INFO]
    looks = 0

    def finished_at_the_third_look(_):
        nonlocal looks
        looks += 1
        return httpx2.Response(
            200,
            json=copy.deepcopy(info)
            | {
                "result": info["result"]
                | {"active_repo": info["result"]["active_repo"] | {"dump_in_progress": looks < 3}}
            },
        )

    upstream.bodies[INFO] = finished_at_the_third_look

    seen = list(client.wait_for_backup("acme-shop", request, timeout=60))

    assert seen[:2] == [None, None]
    assert seen[2] is not None
    assert seen[2].build_name == NAME
    assert looks == 3
