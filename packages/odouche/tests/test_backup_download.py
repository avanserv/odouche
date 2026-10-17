import copy
import inspect
import json
import logging
from urllib.parse import parse_qsl, urlencode

import httpx2
import pytest

from odouche import (
    Client,
    NotFoundError,
    OutcomeUnknownError,
    ReadOnlyError,
    Secret,
    SessionExpiredError,
    StreamTimeoutError,
    UpstreamChangedError,
    UpstreamUnavailableError,
)
from odouche._upstream import backups


STAGING = 51020
BUILD = 88124
BUILDS = f"/app/branch/{STAGING}/builds"
INFO = "/app/project/acme-shop/get_info"
DUMP = f"/app/build/{BUILD}/dump"
HANDOVER = f"/paas/build/{BUILD}/token"
FILE = f"/paas/build/{BUILD}/download/dump"
WORKER = "https://eupd00.odoo.com"
TAKEN = "2026-10-14 12:48:50"
TOKEN = "t0k3n" * 6
QUERY = {"backup_datetime_utc": TAKEN, "test_dump": "1", "filestore": "1"}
LINK = f"{WORKER}{FILE}?{urlencode(QUERY)}"
CONTENT = b"PK\x03\x04 a zip"


def paths(upstream):
    return [request.url.path for request in upstream.requests]


def notification(number, link=LINK, notif_type="dump"):
    return {
        "id": number,
        "seen": False,
        "create_date": "2026-10-14 15:16:59",
        "notif_type": notif_type,
        "level": "info",
        "name": "Database dump ready",
        "content": "<p>Your database dump is ready. It will be available for 2 hours.</p>",
        "buttons": [{"type": "download", "text": None, "url": link}],
    }


def notifications(upstream):
    return upstream.bodies[INFO]["result"]["notifications"]["4217"]["items"]


def handed_over(location):
    return lambda _: httpx2.Response(302, headers={"Location": location})


def handover(request):
    """Send to the address asked for with a token first, as Odoo.sh does."""
    path, _, query = request.url.params["redirect"].partition("?")
    return httpx2.Response(302, headers={"Location": f"{request.url.params['base_url']}{path}?token={TOKEN}&{query}"})


@pytest.fixture(autouse=True)
def staging(upstream):
    body = copy.deepcopy(upstream.load("builds.json"))
    entry = body["result"][0]
    entry["branch_info"] |= {"id": STAGING, "name": "staging", "stage": "staging"}
    entry["builds"] = [
        entry["builds"][1]
        | {"id": BUILD, "name": "acme-shop-staging-88124", "branch_id": [STAGING, "staging"], "worker_url": WORKER}
    ]
    upstream.bodies[BUILDS] = body
    upstream.bodies[DUMP] = upstream.load("dump.json")
    notifications(upstream).append(notification(9000, link=f"{WORKER}/elsewhere"))
    upstream.bodies[HANDOVER] = handover
    upstream.bodies[FILE] = lambda _: httpx2.Response(200, content=CONTENT)


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


@pytest.fixture
def backup(client):
    return client.backups("acme-shop")[0]


@pytest.fixture
def prepared(client, upstream, backup):
    prepared = client.prepare_download("acme-shop", backup)
    upstream.requests.clear()
    return prepared


@pytest.mark.parametrize(("neutralized", "filestore"), [(True, True), (True, False), (False, True), (False, False)])
def test_prepares_once_on_the_backup_s_build(client, upstream, session, backup, neutralized, filestore):
    upstream.requests.clear()

    prepared = client.prepare_download("acme-shop", backup, neutralized=neutralized, filestore=filestore)

    assert paths(upstream)[-2:] == [INFO, DUMP]
    assert paths(upstream).count(DUMP) == 1
    sent = upstream.requests[-1]
    assert json.loads(sent.content)["params"] == {
        "test_dump": neutralized,
        "filestore": filestore,
        "backup_datetime_utc": TAKEN,
    }
    assert sent.headers["Cookie"] == f"session_id={session}"
    assert prepared.build.id == BUILD
    assert prepared.worker_url == WORKER
    assert prepared.previous == 9000
    flags = {"test_dump": str(int(neutralized)), "filestore": str(int(filestore))}
    assert prepared.link == f"{WORKER}{FILE}?{urlencode(QUERY | flags)}"


def test_the_preparation_is_marked_as_state_changing():
    assert inspect.unwrap(backups.prepare) is not backups.prepare


def test_a_read_only_client_prepares_nothing(upstream, session, backup):
    upstream.requests.clear()

    with pytest.raises(ReadOnlyError):
        Client(Secret(session), read_only=True).prepare_download("acme-shop", backup)

    assert upstream.requests == []


def test_a_remote_backup_is_refused_before_any_request(client, upstream):
    remote = client.backups("acme-shop")[2]
    upstream.requests.clear()

    with pytest.raises(ValueError, match="remote"):
        client.prepare_download("acme-shop", remote)

    assert upstream.requests == []


def test_a_backup_whose_build_is_gone_is_not_found(client, upstream, backup):
    upstream.bodies[BUILDS]["result"][0]["builds"][0]["name"] = "acme-shop-staging-88200"

    with pytest.raises(NotFoundError, match="no longer among the latest builds"):
        client.prepare_download("acme-shop", backup)

    assert DUMP not in paths(upstream)


def test_a_build_with_no_worker_is_not_found(client, upstream, backup):
    upstream.bodies[BUILDS]["result"][0]["builds"][0]["worker_url"] = False

    with pytest.raises(NotFoundError, match="no worker"):
        client.prepare_download("acme-shop", backup)

    assert DUMP not in paths(upstream)


def test_a_preparation_that_is_not_confirmed_is_sent_once(client, upstream, backup):
    upstream.failures[DUMP] = 503

    with pytest.raises(OutcomeUnknownError):
        client.prepare_download("acme-shop", backup)

    assert paths(upstream).count(DUMP) == 1


def test_a_project_with_no_notifications_yet_starts_from_none(client, upstream, backup):
    del upstream.bodies[INFO]["result"]["notifications"]["4217"]

    assert client.prepare_download("acme-shop", backup).previous == 0


@pytest.fixture
def announces(upstream):
    """Add `notified` to the project's notifications at the `look`-th request for them."""

    def announce(look, *notified):
        body = upstream.bodies[INFO]
        looks = 0

        def answer(_):
            nonlocal looks
            looks += 1
            if looks == look:
                body["result"]["notifications"]["4217"]["items"][:0] = notified
            return httpx2.Response(200, json=body)

        upstream.bodies[INFO] = answer

    return announce


def test_the_wait_ends_on_the_notification_that_links_to_the_file(client, upstream, prepared, clock, announces):
    announces(3, notification(9001))

    assert list(client.wait_for_download("acme-shop", prepared, timeout=60)) == [None, None]
    assert paths(upstream) == [INFO] * 3
    assert clock == [5.0, 5.0]


def test_the_link_matches_whatever_the_order_and_encoding_of_its_query(client, prepared, clock, announces):
    reordered = f"{WORKER}{FILE}?filestore=1&test_dump=1&backup_datetime_utc=2026-10-14%2012%3A48%3A50"
    announces(1, notification(9001, link=reordered))

    assert list(client.wait_for_download("acme-shop", prepared, timeout=60)) == []


@pytest.mark.parametrize(
    "notified",
    [
        notification(9000),
        notification(8999),
        notification(9001, notif_type="info"),
        notification(9001, link=LINK.replace("test_dump=1", "test_dump=0")),
        notification(9001, link=LINK.replace(WORKER, "https://eupd01.odoo.com")),
        notification(9001, link="not a link"),
        notification(9001) | {"buttons": [{"type": "link", "url": LINK}]},
        notification(9001) | {"buttons": [{"type": "download"}]},
    ],
)
def test_the_wait_ignores_any_other_notification(client, upstream, prepared, clock, announces, notified):
    announces(1, notified)

    with pytest.raises(StreamTimeoutError) as raised:
        list(client.wait_for_download("acme-shop", prepared, timeout=12))

    assert raised.value.operation == "download preparation"
    assert clock == [5.0, 5.0, 2.0]


@pytest.mark.parametrize("timeout", [0, -1])
def test_a_wait_needs_a_timeout(client, upstream, prepared, timeout):
    with pytest.raises(ValueError, match="timeout"):
        client.wait_for_download("acme-shop", prepared, timeout=timeout)

    assert upstream.requests == []


def test_downloads_with_the_token_handed_over_and_without_the_session(client, upstream, session, prepared):
    with client.download(prepared) as file:
        assert file.size == len(CONTENT)
        assert b"".join(file.chunks) == CONTENT

    handover, worker = upstream.requests
    assert handover.url.host == "www.odoo.sh"
    assert handover.url.path == HANDOVER
    assert dict(handover.url.params) == {"redirect": f"{FILE}?{urlencode(QUERY)}", "base_url": WORKER}
    assert handover.headers["Cookie"] == f"session_id={session}"
    assert f"{worker.url.scheme}://{worker.url.host}" == WORKER
    assert worker.url.path == FILE
    assert parse_qsl(worker.url.query.decode()) == [("token", TOKEN), *QUERY.items()]
    assert "Cookie" not in worker.headers
    assert worker.headers["Accept-Encoding"] == "identity"


def test_a_file_of_unknown_size_is_read_whole(client, upstream, prepared):
    upstream.bodies[FILE] = lambda _: httpx2.Response(200, content=iter([CONTENT]))

    with client.download(prepared) as file:
        assert file.size is None
        assert b"".join(file.chunks) == CONTENT


@pytest.mark.parametrize(
    "location",
    [
        f"https://eupd01.odoo.com{FILE}?token={TOKEN}&{urlencode(QUERY)}",
        f"http://eupd00.odoo.com{FILE}?token={TOKEN}&{urlencode(QUERY)}",
        f"{WORKER}:8443{FILE}?token={TOKEN}&{urlencode(QUERY)}",
        f"{WORKER}/paas/build/{BUILD}/download/other?token={TOKEN}&{urlencode(QUERY)}",
        f"{FILE}?token={TOKEN}&{urlencode(QUERY)}",
        f"{WORKER}{FILE}?{urlencode(QUERY)}",
        f"{WORKER}{FILE}?token={TOKEN}&token={TOKEN}&{urlencode(QUERY)}",
        f"{WORKER}{FILE}?token=abc%26x%3D1&{urlencode(QUERY)}",
        f"{WORKER}{FILE}?token={TOKEN}&{urlencode(QUERY)}&next=1",
        f"{WORKER}{FILE}?token={TOKEN}&{urlencode(QUERY | {'test_dump': '0'})}",
    ],
)
def test_a_handover_to_anywhere_but_the_file_is_not_followed(client, upstream, prepared, location):
    upstream.bodies[HANDOVER] = handed_over(location)

    with pytest.raises(UpstreamChangedError) as raised, client.download(prepared):
        pass

    assert raised.value.field == "Location"
    assert TOKEN not in str(raised.value)
    assert paths(upstream) == [HANDOVER]


def test_a_handover_with_no_redirect_is_a_changed_upstream(client, upstream, prepared):
    upstream.bodies[HANDOVER] = lambda _: httpx2.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": True})

    with pytest.raises(UpstreamChangedError), client.download(prepared):
        pass

    assert paths(upstream) == [HANDOVER]


def test_a_rejected_session_at_the_handover_is_a_rejection(client, upstream, prepared):
    upstream.bodies[HANDOVER] = lambda _: httpx2.Response(303, headers={"Location": "/web/login?redirect=x"})

    with pytest.raises(SessionExpiredError), client.download(prepared):
        pass

    assert paths(upstream) == [HANDOVER]


def test_a_file_that_is_not_ready_is_not_found(client, upstream, prepared):
    upstream.bodies[FILE] = lambda _: httpx2.Response(404, text="<title>404 Not Found</title>")

    with pytest.raises(NotFoundError, match="not ready") as raised, client.download(prepared):
        pass

    assert raised.value.operation == "download"
    assert raised.value.__context__ is None


def test_the_caller_s_own_not_found_is_not_rewritten(client, prepared):
    with pytest.raises(NotFoundError, match="the caller's"), client.download(prepared):
        raise NotFoundError("the caller's")


def test_a_cut_connection_fails_the_read(client, upstream, prepared):
    def cut():
        yield CONTENT
        raise httpx2.ReadError(f"failed at token={TOKEN}")

    upstream.bodies[FILE] = lambda _: httpx2.Response(200, content=cut())

    with client.download(prepared) as file, pytest.raises(UpstreamUnavailableError) as raised:
        list(file.chunks)

    assert raised.value.__context__ is None
    assert TOKEN not in str(raised.value)


def test_a_file_shorter_than_it_said_fails_the_read(client, upstream, prepared):
    upstream.bodies[FILE] = lambda _: httpx2.Response(200, headers={"Content-Length": "100"}, content=iter([CONTENT]))

    with client.download(prepared) as file, pytest.raises(UpstreamUnavailableError, match="ended after"):
        list(file.chunks)


def test_a_size_that_is_not_a_number_is_a_changed_upstream(client, upstream, prepared):
    upstream.bodies[FILE] = lambda _: httpx2.Response(200, headers={"Content-Length": "-1"}, content=iter([CONTENT]))

    with pytest.raises(UpstreamChangedError) as raised, client.download(prepared):
        pass

    assert raised.value.field == "Content-Length"


def test_the_token_is_logged_nowhere(client, upstream, prepared, caplog):
    with caplog.at_level(logging.DEBUG), client.download(prepared) as file:
        b"".join(file.chunks)

    assert caplog.records
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in repr(record.args)
    assert TOKEN not in repr(prepared)


def test_finds_a_file_odoo_sh_already_holds_without_preparing_it(upstream, session, backup):
    notifications(upstream).append(notification(9001))
    upstream.requests.clear()

    found = Client(Secret(session), read_only=True).find_download("acme-shop", backup)

    assert found is not None
    assert found.link == LINK
    assert found.build.id == BUILD
    assert found.previous == 9001
    assert DUMP not in paths(upstream)
    assert paths(upstream)[-2:] == [HANDOVER, FILE]


def test_the_newest_notification_of_the_file_is_the_one_found(client, upstream, backup):
    notifications(upstream).extend([notification(9003), notification(9002)])

    found = client.find_download("acme-shop", backup)

    assert found is not None
    assert found.previous == 9003


@pytest.mark.parametrize(
    "notified",
    [
        notification(9001, link=f"{WORKER}/elsewhere"),
        notification(9001, link=LINK.replace("test_dump=1", "test_dump=0")),
        notification(9001, notif_type="info"),
    ],
)
def test_no_notification_of_the_file_is_nothing_found(client, upstream, backup, notified):
    notifications(upstream).append(notified)
    upstream.requests.clear()

    assert client.find_download("acme-shop", backup) is None
    assert HANDOVER not in paths(upstream)


def test_the_file_is_found_with_the_choices_asked(client, upstream, backup):
    notifications(upstream).append(notification(9001, link=LINK.replace("filestore=1", "filestore=0")))

    assert client.find_download("acme-shop", backup) is None
    assert client.find_download("acme-shop", backup, filestore=False) is not None


def test_a_file_odoo_sh_no_longer_holds_is_nothing_found(client, upstream, backup):
    notifications(upstream).append(notification(9001))
    upstream.bodies[FILE] = lambda _: httpx2.Response(404, text="<title>404 Not Found</title>")

    assert client.find_download("acme-shop", backup) is None
    assert DUMP not in paths(upstream)


def test_a_remote_backup_is_never_looked_for(client, upstream):
    remote = client.backups("acme-shop")[2]
    upstream.requests.clear()

    with pytest.raises(ValueError, match="remote"):
        client.find_download("acme-shop", remote)

    assert upstream.requests == []
