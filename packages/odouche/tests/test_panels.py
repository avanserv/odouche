import dataclasses

import pytest

from odouche import Client, NotFoundError, Panel, Secret, Stage, UpstreamChangedError


PROJECT = "acme-shop"
BRANCH = 51044
BUILDS = "/app/branch/51044/builds"
HOST = "acme-shop-feature-invoicing-88240.dev.odoo.com"
MONITOR = "https://www.odoo.sh/project/acme-shop/branches/feature-invoicing/monitor"


@pytest.fixture
def branch(client):
    return next(branch for branch in client.branches(PROJECT) if branch.id == BRANCH)


@pytest.fixture
def done(client, upstream):
    upstream.bodies[BUILDS] = upstream.load("build_done.json")
    return client.latest_build(BRANCH)


def staged(branch, stage):
    return dataclasses.replace(branch, stage=stage, stage_name=stage.value)


@pytest.mark.parametrize(
    ("panel", "stage", "expected"),
    [
        (Panel.SHELL, Stage.DEVELOPMENT, f"https://{HOST}/odoo-sh/webshell"),
        (Panel.EDITOR, Stage.DEVELOPMENT, f"https://{HOST}/odoo-sh/editor"),
        (Panel.MONITOR, Stage.STAGING, MONITOR),
        (Panel.MONITOR, Stage.PRODUCTION, MONITOR),
    ],
)
def test_each_panel_is_built_from_the_build_and_its_branch_with_no_request(
    client, upstream, session, branch, done, panel, stage, expected
):
    upstream.requests.clear()

    url = client.panel_url(PROJECT, staged(branch, stage), done, panel)

    assert url == expected
    assert session not in url
    assert upstream.requests == []


def test_a_panel_is_given_by_its_name(client, branch, done):
    assert client.panel_url(PROJECT, branch, done, "editor") == f"https://{HOST}/odoo-sh/editor"


def test_an_unknown_panel_is_a_value_error(client, branch, done):
    with pytest.raises(ValueError, match="bogus"):
        client.panel_url(PROJECT, branch, done, "bogus")


@pytest.mark.parametrize("panel", list(Panel))
def test_a_build_waiting_for_a_worker_has_no_panels(client, branch, panel):
    waiting = client.latest_build(BRANCH)
    assert waiting.started_at is None

    with pytest.raises(NotFoundError, match="Build 88240 is waiting for a worker"):
        client.panel_url(PROJECT, staged(branch, Stage.STAGING), waiting, panel)


@pytest.mark.parametrize(
    ("fixture", "number", "status"), [("build_progress.json", 88240, "progress"), ("builds.json", 88212, "dropped")]
)
def test_a_build_that_is_not_done_has_no_panels(client, upstream, branch, fixture, number, status):
    upstream.bodies[BUILDS] = upstream.load(fixture)
    build = client.build(BRANCH, number)

    with pytest.raises(NotFoundError, match=f"Build {number} is {status}: .* once it is done"):
        client.panel_url(PROJECT, branch, build, Panel.SHELL)


@pytest.mark.parametrize("stage", [Stage.DEVELOPMENT, Stage.UNKNOWN])
def test_only_a_staging_or_a_production_branch_has_a_monitor_whatever_its_build(client, branch, stage):
    waiting = client.latest_build(BRANCH)

    with pytest.raises(NotFoundError, match="Branch feature-invoicing has no monitor"):
        client.panel_url(PROJECT, staged(branch, stage), waiting, Panel.MONITOR)


@pytest.mark.parametrize(
    ("name", "segment"), [("feature/x y", "feature%2Fx%20y"), ("19.0", "19.0"), ("fix-'(it)!", "fix-%27%28it%29%21")]
)
def test_the_branch_is_quoted_in_the_monitor(client, branch, done, name, segment):
    renamed = dataclasses.replace(staged(branch, Stage.STAGING), name=name)
    url = client.panel_url(PROJECT, renamed, done, Panel.MONITOR)

    assert url == f"https://www.odoo.sh/project/acme-shop/branches/{segment}/monitor"


def test_the_project_is_quoted_in_the_monitor(client, branch, done):
    url = client.panel_url("a b/c?d", staged(branch, Stage.STAGING), done, Panel.MONITOR)

    assert url == "https://www.odoo.sh/project/a%20b%2Fc%3Fd/branches/feature-invoicing/monitor"


def test_a_build_of_another_branch_is_a_value_error(client, branch, done):
    with pytest.raises(ValueError, match="not of branch"):
        client.panel_url(PROJECT, dataclasses.replace(branch, id=51020), done, Panel.SHELL)


def test_a_build_with_no_address_has_no_shell(client, branch, done):
    with pytest.raises(NotFoundError, match="Build 88240 has no host"):
        client.panel_url(PROJECT, branch, dataclasses.replace(done, url=None), Panel.SHELL)


@pytest.mark.parametrize(
    "url",
    [f"https://{HOST}/?token=x", f"https://{HOST}/x", f"http://{HOST}", f"https://u@{HOST}", f"https://{HOST}#x"],
)
def test_an_address_that_is_not_a_bare_host_is_a_changed_upstream(client, branch, done, url):
    with pytest.raises(UpstreamChangedError) as raised:
        client.panel_url(PROJECT, branch, dataclasses.replace(done, url=url), Panel.EDITOR)

    assert (raised.value.operation, raised.value.field) == ("panel", "url")


def test_a_read_only_client_gives_the_url_too(upstream, session, branch, done):
    read_only = Client(Secret(session), read_only=True)

    assert read_only.panel_url(PROJECT, branch, done, Panel.SHELL) == f"https://{HOST}/odoo-sh/webshell"
