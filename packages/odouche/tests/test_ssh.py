import dataclasses
import inspect
import ipaddress
import json

import httpx2
import pytest

from odouche import (
    Client,
    NotFoundError,
    OutcomeUnknownError,
    PermissionDeniedError,
    ReadOnlyError,
    Secret,
    SshTarget,
    UpstreamChangedError,
)
from odouche._upstream import allow_ip


BRANCH = 51044
ALLOW = "/app/branch/51044/allow_ip"


@pytest.fixture
def build(client):
    return client.build(BRANCH, 88212)


def test_the_target_is_the_number_of_the_build_at_the_host_of_its_address(client, upstream, build):
    upstream.requests.clear()

    assert client.ssh_target(build) == SshTarget(user="88212", host="acme-shop-feature-invoicing-88212.dev.odoo.com")
    assert upstream.requests == []


@pytest.mark.parametrize(
    "host",
    [
        "acme-shop.odoo.com",
        "acme-shop-staging-88300.dev.odoo.com",
        "acme--shop-9.dev.odoo.com",
        "4217-shop.odoo.com",
        "a.b.c.odoo.com",
    ],
)
def test_a_host_under_odoo_com_is_a_target(client, build, host):
    assert client.ssh_target(dataclasses.replace(build, url=f"https://{host}")).host == host


def test_a_build_with_no_address_has_no_target(client, build):
    with pytest.raises(NotFoundError, match="Build 88212 has no host"):
        client.ssh_target(dataclasses.replace(build, url=None))


@pytest.mark.parametrize(
    "url",
    [
        "https://-oProxyCommand=id.dev.odoo.com",
        "https://-v.odoo.com",
        "https://acme.-v.odoo.com",
        "https://acme-.odoo.com",
        "-oProxyCommand=id",
        "http://acme-shop.odoo.com",
        "https://acme-shop.odoo.com:22",
        "https://acme-shop.odoo.com/",
        "https://acme-shop.odoo.com/x",
        "https://user@acme-shop.odoo.com",
        "https://acme-shop.odoo.com.example.com",
        "https://example.com",
        "https://odoo.com",
        "https://acme..odoo.com",
        "https://acme-shop.odoo.com?x=1",
        "https://acme-shop.odoo.com#x",
        "https://ACME-shop.odoo.com",
        "https://example.com\\.odoo.com",
        "https://acme-shop.odoo.com\n",
        "https://acme shop.odoo.com",
        "acme-shop.odoo.com",
        "",
        7,
    ],
)
def test_an_address_that_is_not_a_host_of_odoo_com_is_a_changed_upstream(client, build, url):
    with pytest.raises(UpstreamChangedError) as raised:
        client.ssh_target(dataclasses.replace(build, url=url))

    assert raised.value.field == "url"


@pytest.mark.parametrize("number", [-88212, 0, True, "88212", "-oProxyCommand=id", 88212.0, None])
def test_a_number_that_is_not_one_is_a_changed_upstream(client, build, number):
    with pytest.raises(UpstreamChangedError) as raised:
        client.ssh_target(dataclasses.replace(build, id=number))

    assert raised.value.field == "id"


@pytest.fixture
def allows(upstream):
    upstream.bodies[ALLOW] = upstream.load("allow_ip.json")


@pytest.mark.usefixtures("allows")
def test_allowing_returns_the_address_odoo_sh_saw_and_names_none(client, upstream):
    assert client.allow_ip(BRANCH) == ipaddress.IPv4Address("203.0.113.7")
    [request] = upstream.requests
    assert request.url.path == ALLOW
    assert json.loads(request.content).get("params", {}) == {}


@pytest.mark.usefixtures("allows")
def test_allowing_takes_a_branch(client, upstream):
    client.allow_ip(next(branch for branch in client.branches("acme-shop") if branch.id == BRANCH))

    assert upstream.requests[-1].url.path == ALLOW


def test_an_ipv6_address_is_one(client, upstream):
    upstream.bodies[ALLOW] = {"jsonrpc": "2.0", "id": 1, "result": "2001:db8::7"}

    assert client.allow_ip(BRANCH) == ipaddress.IPv6Address("2001:db8::7")


def test_allowing_is_marked_as_state_changing():
    assert inspect.unwrap(allow_ip.allow_ip) is not allow_ip.allow_ip


@pytest.mark.usefixtures("allows")
def test_a_read_only_client_allows_nothing_and_sends_nothing(upstream, session):
    with pytest.raises(ReadOnlyError) as raised:
        Client(Secret(session), read_only=True).allow_ip(BRANCH)

    assert raised.value.operation == "allow_ip"
    assert upstream.requests == []


@pytest.mark.parametrize("result", ["", "not an address", "203.0.113.7/24", 7, None, False, ["203.0.113.7"]])
def test_an_answer_that_is_not_an_address_is_a_changed_upstream(client, upstream, result):
    upstream.bodies[ALLOW] = {"jsonrpc": "2.0", "id": 1, "result": result}

    with pytest.raises(UpstreamChangedError) as raised:
        client.allow_ip(BRANCH)

    assert raised.value.field == "result"


@pytest.mark.parametrize("failure", [503, httpx2.ReadTimeout])
def test_an_allowing_that_is_not_confirmed_is_sent_once_and_its_outcome_is_unknown(client, upstream, failure):
    upstream.failures[ALLOW] = failure

    with pytest.raises(OutcomeUnknownError):
        client.allow_ip(BRANCH)

    assert len(upstream.requests) == 1


def test_a_refused_allowing_is_a_denied_permission(client, upstream):
    upstream.bodies[ALLOW] = upstream.load("access_error.json")

    with pytest.raises(PermissionDeniedError):
        client.allow_ip(BRANCH)

    assert len(upstream.requests) == 1
