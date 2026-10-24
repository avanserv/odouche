import dataclasses
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from odouche import (
    AuditEntry,
    AuditKind,
    Client,
    NotFoundError,
    OdoucheError,
    PermissionDeniedError,
    Secret,
    Stage,
    StreamTimeoutError,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche._upstream import audit


INFO = "/app/project/acme-shop/get_info"
AUDIT = "/app/project/acme-corp-odoo-addons-4217/audit_logs"
TOKEN = "t0k3n-0f-th3-pr0j3ct"
CODE = "M999999999999999"
KINDS = [
    ("Allow IP", AuditKind.ALLOW_IP),
    ("Connect as user", AuditKind.CONNECT_AS_USER),
    ("Download database", AuditKind.DOWNLOAD_DATABASE),
    ("Manage collaborators", AuditKind.MANAGE_COLLABORATORS),
    ("Open Editor", AuditKind.OPEN_EDITOR),
    ("Open Shell", AuditKind.OPEN_SHELL),
    ("Open Webmail", AuditKind.OPEN_WEBMAIL),
    ("Open database logs", AuditKind.OPEN_DATABASE_LOGS),
    ("Change branch stage", AuditKind.CHANGE_BRANCH_STAGE),
    ("Add domain name", AuditKind.ADD_DOMAIN_NAME),
    ("Manage settings", AuditKind.MANAGE_SETTINGS),
]


def entries(upstream):
    return upstream.bodies[AUDIT]["result"]


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def row(at, action="Open Shell", **fields):
    """An invented entry, `at` seconds after a fixed moment."""
    moment = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=at)
    return {
        "date": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "stage": "dev",
        "user": "octo-dev",
        "message": "",
        "successful": True,
    } | fields


def test_yields_the_entries_newest_first_with_each_field(client, upstream):
    read = list(client.audit_log("acme-shop", timeout=10))

    assert [entry.kind for entry in read] == [
        AuditKind.MANAGE_COLLABORATORS,
        AuditKind.OPEN_SHELL,
        AuditKind.ALLOW_IP,
        AuditKind.DOWNLOAD_DATABASE,
        AuditKind.OPEN_WEBMAIL,
        AuditKind.OPEN_DATABASE_LOGS,
    ]
    assert read[0] == AuditEntry(
        logged_at=datetime(2026, 10, 23, 20, 21, 27, tzinfo=UTC),
        author="octo-dev",
        kind=AuditKind.MANAGE_COLLABORATORS,
        kind_name="Manage collaborators",
        stage=None,
        details="Change access rights of user `jane-doe` from `tester` to `developer`",
        succeeded=True,
    )
    assert [entry.stage for entry in read] == [
        None,
        Stage.PRODUCTION,
        None,
        Stage.PRODUCTION,
        Stage.STAGING,
        Stage.STAGING,
    ]
    assert paths(upstream) == [INFO, AUDIT]


def test_a_development_branch_s_stage_is_read(client, upstream):
    entries(upstream)[0]["stage"] = "dev"

    assert next(client.audit_log("acme-shop", timeout=10)).stage is Stage.DEVELOPMENT


@pytest.mark.parametrize(("action", "kind"), KINDS)
def test_reads_each_action_the_page_names(client, upstream, action, kind):
    entries(upstream)[0]["action"] = action

    read = next(client.audit_log("acme-shop", timeout=10))

    assert (read.kind, read.kind_name) == (kind, action)


def test_an_unknown_action_is_unknown_and_keeps_its_name_cut(client, upstream, caplog):
    entries(upstream)[1]["action"] = "Restore backup"
    entries(upstream)[2]["action"] = "x" * 1000

    with caplog.at_level(logging.DEBUG, logger="odouche"):
        read = list(client.audit_log("acme-shop", timeout=10))

    assert (read[1].kind, read[1].kind_name) == (AuditKind.UNKNOWN, "Restore backup")
    assert (read[2].kind, read[2].kind_name) == (AuditKind.UNKNOWN, "x" * 64)
    assert len(read) == 6
    assert "Restore backup" in caplog.text
    assert "x" * 65 not in caplog.text


def test_an_answer_out_of_order_is_yielded_newest_first(client, upstream):
    upstream.bodies[AUDIT]["result"] = [
        row(10, user="a"),
        row(30, user="b"),
        row(20, user="c"),
        row(30, user="d"),
    ]

    read = list(client.audit_log("acme-shop", timeout=10))

    # Entries of the same second keep the answer's order.
    assert [entry.author for entry in read] == ["b", "d", "c", "a"]


def test_nothing_is_asked_before_the_first_entry_is_read(client, upstream):
    read = client.audit_log("acme-shop", timeout=10)

    assert upstream.requests == []
    next(read)
    assert paths(upstream) == [INFO, AUDIT]


@pytest.mark.parametrize("how", ["whole", "limit", "closed"])
def test_the_log_is_asked_once_however_it_is_read(client, upstream, how):
    if how == "whole":
        list(client.audit_log("acme-shop", timeout=10))
    elif how == "limit":
        list(client.audit_log("acme-shop", limit=2, timeout=10))
    else:
        read = client.audit_log("acme-shop", timeout=10)
        next(read)
        read.close()

    assert paths(upstream) == [INFO, AUDIT]


def test_a_long_log_yields_the_limit_newest_from_one_request(client, upstream):
    upstream.bodies[AUDIT]["result"] = [row(at) for at in range(200)]

    read = list(client.audit_log("acme-shop", limit=10, timeout=10))

    assert len(read) == 10
    assert read[0].logged_at == datetime(2026, 10, 1, 0, 3, 19, tzinfo=UTC)
    assert paths(upstream) == [INFO, AUDIT]


def test_an_entry_past_the_limit_is_not_read(client, upstream):
    upstream.bodies[AUDIT]["result"] = [row(2), row(1, user=None)]

    assert [entry.author for entry in client.audit_log("acme-shop", limit=1, timeout=10)] == ["octo-dev"]


def test_takes_a_project_or_its_name(client, upstream):
    project = client.projects()[0]
    upstream.requests.clear()

    assert len(list(client.audit_log(project, timeout=10))) == 6
    assert paths(upstream) == [INFO, AUDIT]


def test_a_read_only_client_reads_it(upstream, session):
    with Client(Secret(session), read_only=True) as client:
        assert len(list(client.audit_log("acme-shop", timeout=10))) == 6


@pytest.mark.parametrize(
    ("limit", "timeout", "error"),
    [(0, 10, ValueError), (-1, 10, ValueError), (True, 10, TypeError), (1, 0, ValueError), (1, -1, ValueError)],
)
def test_a_limit_or_timeout_out_of_range_is_refused_before_any_request(client, upstream, limit, timeout, error):
    with pytest.raises(error):
        client.audit_log("acme-shop", limit=limit, timeout=timeout)

    assert upstream.requests == []


@pytest.mark.parametrize("access", ["developer", "tester"])
def test_below_admin_it_is_denied_without_asking_for_the_log(client, upstream, access):
    upstream.bodies[INFO]["result"]["user"]["access"] = access

    with pytest.raises(PermissionDeniedError, match="admins only") as raised:
        list(client.audit_log("acme-shop", timeout=10))

    assert raised.value.operation == "audit log"
    assert paths(upstream) == [INFO]


def test_a_refused_log_is_denied(client, upstream):
    upstream.bodies[AUDIT] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError):
        list(client.audit_log("acme-shop", timeout=10))


@pytest.fixture
def now(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(audit, "_monotonic", lambda: now[0])
    return now


def slowed(upstream, path, now, seconds, failure=None):
    """Answer `path` as before, or with `failure`, once the clock has moved `seconds` on."""
    body = upstream.bodies[path]

    def answer(request):
        now[0] += seconds
        if failure is not None:
            raise failure("timed out", request=request)
        return httpx2.Response(200, json=body)

    upstream.bodies[path] = answer


def test_a_deadline_passed_during_the_info_sends_nothing_more(client, upstream, now):
    slowed(upstream, INFO, now, 6)

    with pytest.raises(StreamTimeoutError, match="'acme-shop'") as raised:
        list(client.audit_log("acme-shop", timeout=5))

    assert raised.value.operation == "audit log"
    assert paths(upstream) == [INFO]


def test_a_request_the_deadline_cut_short_is_the_timeout_not_a_short_log(client, upstream, now):
    slowed(upstream, AUDIT, now, 6, httpx2.ReadTimeout)

    with pytest.raises(StreamTimeoutError):
        list(client.audit_log("acme-shop", timeout=5))


def test_a_failed_request_within_the_deadline_is_the_failure(client, upstream, now):
    slowed(upstream, AUDIT, now, 0, httpx2.ReadTimeout)

    with pytest.raises(UpstreamUnavailableError, match="ReadTimeout"):
        list(client.audit_log("acme-shop", timeout=5))


def test_each_request_has_what_the_deadline_leaves(upstream, session, now, monkeypatch):
    transport = upstream.connect(Secret(session))
    call = transport.call
    left = []

    def bounded(*args, **options):
        left.append(options["within"])
        now[0] += 2
        return call(*args, **options)

    monkeypatch.setattr(transport, "call", bounded)

    list(audit.audit_log(transport, "acme-shop", limit=10, timeout=5))

    assert left == [5, 3]


def test_an_answer_still_arriving_at_the_deadline_is_the_timeout(client, upstream):
    def trickle():
        yield b'{"result": ['
        for _ in range(400):
            time.sleep(0.05)
            yield b" "
        yield b"]}"

    upstream.bodies[AUDIT] = lambda _: httpx2.Response(200, content=trickle())
    started = time.monotonic()

    with pytest.raises(StreamTimeoutError):
        list(client.audit_log("acme-shop", timeout=1))

    # Wide: a slow runner under coverage still ends far before the 20 seconds of the answer.
    assert time.monotonic() - started < 10


def test_an_answer_over_the_cap_is_not_read(client, upstream):
    over = b'{"result": [' + b" " * audit.MAX_ANSWER + b"]}"
    upstream.bodies[AUDIT] = lambda _: httpx2.Response(200, content=over)

    with pytest.raises(OdoucheError, match="over 16 MiB") as raised:
        list(client.audit_log("acme-shop", timeout=10))

    assert type(raised.value) is OdoucheError
    assert raised.value.operation == "audit log"
    assert raised.value.__suppress_context__


def test_a_project_the_user_cannot_reach_is_not_found(client, upstream):
    upstream.bodies["/app/project/other/get_info"] = {"error": {"data": {"name": "builtins.Exception"}}}

    with pytest.raises(NotFoundError, match="'other'"):
        list(client.audit_log("other", timeout=10))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date", "23/10/2026"),
        ("date", None),
        ("action", False),
        ("stage", False),
        ("user", None),
        ("message", False),
        ("successful", "yes"),
    ],
)
def test_names_the_field_of_an_entry_that_changed_shape(client, upstream, field, value):
    entries(upstream)[1][field] = value

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.audit_log("acme-shop", timeout=10))

    assert (raised.value.operation, raised.value.field) == ("audit log", f"result[1].{field}")


@pytest.mark.parametrize("body", [{}, {"result": {}}, {"result": [1]}])
def test_names_the_part_of_the_answer_that_changed_shape(client, upstream, body):
    upstream.bodies[AUDIT] = body

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.audit_log("acme-shop", timeout=10))

    assert raised.value.field.startswith("result")


def test_no_token_or_code_of_the_info_reaches_an_entry_or_the_log(client, upstream, caplog):
    result = upstream.bodies[INFO]["result"]
    result["access_token"] = TOKEN
    result["active_repo"]["subscription_code"] = CODE

    with caplog.at_level(logging.DEBUG):
        read = list(client.audit_log("acme-shop", timeout=10))

    shown = repr(read) + json.dumps([dataclasses.asdict(entry) for entry in read], default=str) + caplog.text
    assert TOKEN not in shown
    assert CODE not in shown


def test_the_name_odoo_sh_gives_cannot_change_the_address(client, upstream):
    upstream.bodies[INFO]["result"]["active_repo"]["technical_name"] = "../branch/1/rebuild?x="
    upstream.bodies["/app/project/../branch/1/rebuild?x=/audit_logs"] = upstream.bodies[AUDIT]

    list(client.audit_log("acme-shop", timeout=10))

    assert upstream.requests[1].url.raw_path == b"/app/project/%2E%2E%2Fbranch%2F1%2Frebuild%3Fx%3D/audit_logs"


def test_an_entry_is_frozen(client):
    read = next(client.audit_log("acme-shop", timeout=10))

    with pytest.raises(dataclasses.FrozenInstanceError):
        read.author = "other"  # pyright: ignore[reportAttributeAccessIssue]
